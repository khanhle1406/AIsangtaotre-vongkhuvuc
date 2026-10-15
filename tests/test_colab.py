"""Exercise the real loopback protocol and checkpoints without GPU/paid APIs."""

import ast
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

import openpyxl
import pytest

from benchmarks.colab_bootstrap import child_environment
from benchmarks.colab_bundle import notebook
from benchmarks.colab_io import atomic_json, export_results
from benchmarks.colab_local import (
    LOCAL_MODEL,
    LocalDevelopmentAgent,
    local_json,
    loopback_url,
)
from benchmarks.colab_runner import choose_profile, read_checkpoint, run_stage
from benchmarks.colab_server import SessionControl, handler_for
from benchmarks.providers import provider_transport
from src.excel_parser import CellData, SheetData, WorkbookData
from src.llm_agent import DEFAULT_MODEL, QueryState


class FakeEngine:
    def __init__(self, control: SessionControl) -> None:
        self.control = control
        self.payloads: list[dict[str, Any]] = []

    def token_ids(self, messages: list[dict[str, str]]) -> list[int]:
        return [1] * (sum(len(message["content"]) for message in messages) // 12 + 10)

    def generate(self, body: dict[str, Any], warmup: bool = False) -> dict[str, Any]:
        self.control.reserve(warmup)
        self.payloads.append(body)
        if "reasoning" in body:
            raise ValueError("Non-thinking transport must not send reasoning")
        self.control.history.append(
            {"generation": self.control.generations, "elapsed_seconds": 0.01}
        )
        self.control.save()
        return {
            "model": LOCAL_MODEL,
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "code": "result=num('S','B2')",
                                "format": {"kind": "integer"},
                            }
                        )
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"cost": 0, "total_tokens": 20},
        }


@pytest.fixture
def local_server(tmp_path: Path) -> Iterator[tuple[str, FakeEngine]]:
    control = SessionControl(tmp_path / "state", time.time())
    engine = FakeEngine(control)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(engine, control))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", engine
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8000/v1",
        "http://localhost:8000/v1",
        "http://example.com:8000/v1",
        "http://user:pass@127.0.0.1:8000/v1",
        "http://127.0.0.1:8000/v1?redirect=external",
    ],
)
def test_local_transport_refuses_non_loopback_or_credential_urls(url: str) -> None:
    with pytest.raises(ValueError, match="127.0.0.1"):
        loopback_url(url)


def test_local_control_does_not_follow_redirects() -> None:
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", "https://example.invalid/never-contact")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            local_json(f"http://127.0.0.1:{server.server_port}/v1", "/models")
        assert error.value.code == 302
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_local_provider_does_not_lookup_prices_or_use_a_real_api_key(
    local_server: tuple[str, FakeEngine],
) -> None:
    base, engine = local_server
    with provider_transport("colab-local", object(), local_base_url=base) as transport:
        client = transport["client_class"](**transport["client_kwargs"])
        assert client.api_key == "local-development-placeholder"
        assert client.reasoning_tokens == 0 and client.request_timeout_seconds == 120
        assert client.pricing == (0, 0) and DEFAULT_MODEL == "qwen/qwen3.7-flash"
        state = QueryState(time.monotonic() + 60, 0.09)
        client._request([{"role": "user", "content": "Return a program"}], state)
    assert len(engine.payloads) == 1 and "reasoning" not in engine.payloads[0]
    assert state.cost == 0


def test_context_projection_keeps_the_entire_backend(
    local_server: tuple[str, FakeEngine],
) -> None:
    base, _ = local_server
    client = LocalDevelopmentAgent(local_base_url=base)
    client.local_context = 2500
    workbook = WorkbookData(
        {
            "S": SheetData(
                "S",
                cells={
                    "A301": CellData(777, "number"),
                    "B1": CellData("Current value", "string"),
                },
            )
        }
    )
    client.local_workbook = workbook.wire()
    client.local_query = "Current value?"
    fitted = client.fit_context(
        [
            {"role": "system", "content": "Generate JSON"},
            {
                "role": "user",
                "content": "WORKBOOK DATA:\n"
                + "x" * 50000
                + "\n\nQUESTION:\nCurrent value?",
            },
        ]
    )
    assert "EXPANDABLE WORKBOOK VIEW" in fitted[1]["content"]
    assert client.local_workbook["S"]["cells"]["A301"]["value"] == 777
    assert client.token_count(fitted) + client.max_tokens <= client.local_context


def test_local_context_without_workbook_is_never_silently_truncated(
    local_server: tuple[str, FakeEngine],
) -> None:
    base, engine = local_server
    client = LocalDevelopmentAgent(local_base_url=base)
    client.local_context = 2100
    with pytest.raises(ValueError, match="overflow"):
        client._request(
            [{"role": "user", "content": "x" * 10000}],
            QueryState(time.monotonic() + 60, 0.09),
        )
    assert not engine.payloads


def test_generation_limit_persists_across_server_restart(tmp_path: Path) -> None:
    started = time.time()
    state = SessionControl(tmp_path, started)
    state.generations = 99
    state.reserve()
    loaded = SessionControl(tmp_path, started)
    with pytest.raises(TimeoutError, match="100-generation"):
        loaded.reserve()
    with pytest.raises(ValueError, match="another session"):
        SessionControl(tmp_path, started + 1)


def test_only_one_context_fallback_is_allowed_during_warmup(tmp_path: Path) -> None:
    state = SessionControl(tmp_path, time.time())
    assert state.oom(warmup=True) and state.context_length == 16384
    assert not state.oom(warmup=True) and state.fatal_error
    with pytest.raises(RuntimeError, match="OOM"):
        state.reserve()


def test_no_context_change_after_benchmark_has_started(tmp_path: Path) -> None:
    state = SessionControl(tmp_path, time.time())
    assert not state.oom(warmup=False)
    assert state.context_length == 24576 and state.fatal_error


def test_session_deadlines_include_setup_and_inference(tmp_path: Path) -> None:
    state = SessionControl(tmp_path, time.time() - 601)
    with pytest.raises(TimeoutError):
        state.reserve(warmup=True)
    state = SessionControl(tmp_path / "second", time.time() - 2521)
    with pytest.raises(TimeoutError):
        state.reserve()


def test_checkpoint_rejects_changed_inputs_or_configuration(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    atomic_json(path, {"fingerprint": "old", "records": {}})
    with pytest.raises(ValueError, match="mismatch"):
        read_checkpoint(path, "new")


def test_selection_is_exact_match_then_time_then_tokens() -> None:
    def report(
        correct: int, elapsed: float, tokens: int, complete: bool = True
    ) -> dict[str, Any]:
        return {
            "complete": complete,
            "score": {"correct": correct},
            "elapsed_seconds": elapsed,
            "tokens": tokens,
        }

    assert (
        choose_profile(
            {"A": report(8, 10, 90), "B": report(7, 1, 1), "C": report(8, 9, 100)}
        )
        == "C"
    )
    assert choose_profile({"A": report(8, 10, 90), "B": report(8, 10, 100)}) == "A"
    assert choose_profile({"A": report(8, 1, 1, False)}) is None


def test_real_solver_stage_resumes_without_regenerating_and_rejects_data_changes(
    tmp_path: Path, local_server: tuple[str, FakeEngine]
) -> None:
    base, engine = local_server
    dataset = tmp_path / "dataset"
    (dataset / "xlsx_files").mkdir(parents=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    ws.append(["Item", "Value"])
    ws.append(["Current", 37])
    wb.save(dataset / "xlsx_files/book.xlsx")
    wb.close()
    (dataset / "queries.json").write_text(
        json.dumps(
            [
                {
                    "id": "new-name",
                    "file_name": "book.xlsx",
                    "query": "What is the Current value? Answer with only the integer.",
                }
            ]
        )
    )
    (dataset / "references.csv").write_text("id,answer\nnew-name,37\n")
    session = tmp_path / "session"
    first = run_stage("public_A", "A", dataset, base, session)
    assert first["complete"] and first["score"]["correct"] == 1
    assert first["cost_usd"] == 0 and len(engine.payloads) == 1
    assert run_stage("public_A", "A", dataset, base, session) == first
    assert len(engine.payloads) == 1
    (dataset / "queries.json").write_text(
        json.dumps(
            [{"id": "changed", "file_name": "book.xlsx", "query": "Changed question"}]
        )
    )
    with pytest.raises(ValueError, match="mismatch"):
        run_stage("public_A", "A", dataset, base, session)
    assert len(engine.payloads) == 1


def test_notebook_cells_compile_and_do_not_contain_credentials() -> None:
    nb = notebook()
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]))
            assert cell["outputs"] == []
    assert "OPENROUTER_API_KEY" not in json.dumps(nb)


def test_child_environment_and_export_exclude_secret_files(tmp_path: Path) -> None:
    with patch.dict(
        "os.environ",
        {"OPENROUTER_API_KEY": "test-placeholder", "PATH": "/usr/bin"},
        clear=True,
    ):
        environment = child_environment()
    assert "OPENROUTER_API_KEY" not in environment and environment["PATH"] == "/usr/bin"
    (tmp_path / ".env").write_text("must-not-export")
    atomic_json(tmp_path / "job.json", {"status": "completed"})
    from zipfile import ZipFile

    with ZipFile(export_results(tmp_path)) as archive:
        assert archive.namelist() == ["job.json"]
