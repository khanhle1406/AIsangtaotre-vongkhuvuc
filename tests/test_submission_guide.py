"""Exercise the judge's six arguments without contacting a paid provider."""

import csv
import hashlib
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

import openpyxl
import pytest

from benchmarks.package_submission import package
from run import validate_artifact_paths, write_submission
from src.llm_agent import DEFAULT_MODEL, normalize_base_url

ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = "submission-test-placeholder"


@pytest.fixture
def judge_input(tmp_path: Path) -> tuple[Path, Path, list[dict[str, Any]]]:
    input_dir = tmp_path / "input" / "xlsx_files"
    input_dir.mkdir(parents=True)
    workbook = openpyxl.Workbook()
    workbook.active.append(["Item", "Units"])
    workbook.active.append(["Lamp", 47])
    workbook.save(input_dir / "new workbook.xlsx")
    workbook.close()
    queries = [
        {
            "id": key,
            "file_name": "new workbook.xlsx",
            "query": "How many units? Answer only the integer.",
        }
        for key in ["câu-α", 42]
    ]
    path = input_dir.parent / "queries.json"
    path.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
    return input_dir, path, queries


@pytest.fixture
def api() -> Iterator[tuple[str, list[dict[str, Any]], dict[str, int]]]:
    calls: list[dict[str, Any]] = []
    status = {"post": 200}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def reply(self, body: dict[str, Any], code: int = 200) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            calls.append({"path": self.path, "method": "GET"})
            self.reply(
                {
                    "data": {
                        "id": DEFAULT_MODEL,
                        "endpoints": [
                            {
                                "pricing": {
                                    "prompt": "0.0000002",
                                    "completion": "0.0000008",
                                }
                            }
                        ],
                    }
                }
            )

        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(
                {
                    "path": self.path,
                    "method": "POST",
                    "payload": payload,
                    "authorization": self.headers.get("Authorization"),
                }
            )
            if status["post"] != 200:
                self.reply({"error": {"code": "unauthorized"}}, status["post"])
                return
            program = {
                "code": "result=num(sheets[0], 'B2')",
                "format": {"kind": "integer"},
            }
            self.reply(
                {
                    "model": DEFAULT_MODEL,
                    "choices": [
                        {
                            "message": {"content": json.dumps(program)},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"total_tokens": 50, "cost": 0},
                }
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api/v1/", calls, status
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def invoke(
    input_dir: Path, queries: Path, output: Path, base: str, legacy: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "run.py"),
            "--input-dir" if legacy else "--xlsx-dir",
            str(input_dir),
            "--queries",
            str(queries),
            "--output",
            str(output),
            "--api-key" if legacy else "--openrouter-key",
            TEST_KEY,
            "--model" if legacy else "--openrouter-model",
            DEFAULT_MODEL,
            "--openrouter-base-url",
            base,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_judge_arguments_real_http_worker_csv_and_readonly_input(
    judge_input: tuple[Path, Path, list[dict[str, Any]]],
    api: tuple[str, list[dict[str, Any]], dict[str, int]],
    tmp_path: Path,
    legacy: bool,
) -> None:
    input_dir, queries_path, queries = judge_input
    base, calls, _ = api
    originals = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in input_dir.parent.rglob("*")
        if path.is_file()
    }
    output = tmp_path / "output" / "submission.csv"
    result = invoke(input_dir, queries_path, output, base, legacy)
    assert result.returncode == 0, result.stderr
    with output.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == ["id", "answer"]
        assert list(reader) == [
            {"id": str(query["id"]), "answer": "47"} for query in queries
        ]
    assert set(output.parent.iterdir()) == {output}
    assert originals == {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in input_dir.parent.rglob("*")
        if path.is_file()
    }
    assert TEST_KEY not in result.stdout + result.stderr + output.read_text()
    assert calls[0]["path"] == f"/api/v1/models/{DEFAULT_MODEL}/endpoints"
    posts = [call for call in calls if call["method"] == "POST"]
    assert len(posts) == 2
    assert all(
        call["path"] == "/api/v1/chat/completions"
        and call["payload"]["model"] == DEFAULT_MODEL
        and call["authorization"] == f"Bearer {TEST_KEY}"
        for call in posts
    )


def test_failed_api_does_not_report_success(
    judge_input: tuple[Path, Path, list[dict[str, Any]]],
    api: tuple[str, list[dict[str, Any]], dict[str, int]],
    tmp_path: Path,
) -> None:
    input_dir, queries_path, _ = judge_input
    base, _, status = api
    status["post"] = 401
    result = invoke(input_dir, queries_path, tmp_path / "output.csv", base)
    assert result.returncode == 1
    assert TEST_KEY not in result.stdout + result.stderr


def test_failed_output_write_does_not_report_success(
    judge_input: tuple[Path, Path, list[dict[str, Any]]],
    api: tuple[str, list[dict[str, Any]], dict[str, int]],
    tmp_path: Path,
) -> None:
    input_dir, queries_path, _ = judge_input
    base, calls, _ = api
    output = tmp_path / "directory.csv"
    output.mkdir()
    result = invoke(input_dir, queries_path, output, base)
    assert result.returncode == 1 and not calls
    assert output.is_dir()


@pytest.mark.parametrize(
    "kind", ["inside", "query", "temporary", "symlink", "hardlink", "trace"]
)
def test_input_artifacts_are_rejected_before_writes(
    judge_input: tuple[Path, Path, list[dict[str, Any]]],
    tmp_path: Path,
    kind: str,
) -> None:
    input_dir, queries_path, queries = judge_input
    output, trace = tmp_path / "answer.csv", None
    if kind == "inside":
        output = input_dir / "new" / "answer.csv"
    elif kind == "query":
        output = queries_path
    elif kind == "temporary":
        queries_path = output.with_name(output.name + ".tmp")
        queries_path.write_text("input query data")
    elif kind == "symlink":
        output.symlink_to(input_dir / "new workbook.xlsx")
    elif kind == "hardlink":
        os.link(queries_path, output)
    else:
        trace = input_dir.parent / "symlinked-input" / "trace.jsonl"
        trace.parent.symlink_to(input_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="input data"):
        validate_artifact_paths(input_dir, queries_path, queries, output, trace, True)


def test_utf8_csv_preserves_names_and_punctuation(tmp_path: Path) -> None:
    output = tmp_path / "submission.csv"
    answer = 'Công ty Ánh Dương, "Inc."'
    write_submission(output, [{"id": "câu-1"}], {"câu-1": answer})
    with output.open(encoding="utf-8", newline="") as stream:
        assert list(csv.DictReader(stream)) == [{"id": "câu-1", "answer": answer}]


@pytest.mark.parametrize(
    "base",
    [
        "file:///tmp/api",
        "https://secret@api.test/v1",
        "https://api.test/v1?key=secret",
        "https://api.test/v1#fragment",
    ],
)
def test_invalid_api_base_is_rejected_without_echoing_secrets(base: str) -> None:
    with pytest.raises(ValueError, match="API base URL") as error:
        normalize_base_url(base)
    assert "secret" not in str(error.value)


def test_submission_zip_contains_root_dockerfile_and_no_secrets(tmp_path: Path) -> None:
    destination = tmp_path / "Tên Đội.zip"
    secret = uuid4().hex
    with patch(
        "benchmarks.package_submission.dotenv_values",
        return_value={"API_KEY": secret},
    ):
        package(destination, team_name="Tên Đội")
    with ZipFile(destination) as archive:
        names = archive.namelist()
        assert "Dockerfile" in names and ".dockerignore" in names
        assert archive.testzip() is None
        assert not any(
            part in {".env", ".venv", "__pycache__", "data", "reports", "notebooks"}
            for name in names
            for part in Path(name).parts
        )
        assert all(secret.encode() not in archive.read(name) for name in names)
        dockerfile = archive.read("Dockerfile").decode()
        assert 'ENTRYPOINT ["python", "run.py"]' in dockerfile
        assert "linux/amd64" in dockerfile and "pip install" in dockerfile
    assert destination.stat().st_size <= 100_000_000


@pytest.mark.parametrize("team", ["../outside", "a/b", "a\\b", "", "..", " team "])
def test_package_rejects_invalid_team_names(tmp_path: Path, team: str) -> None:
    with pytest.raises(ValueError, match="Team name"):
        package(tmp_path / "team.zip", team_name=team)


def test_package_rejects_filename_different_from_team(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="match the team"):
        package(tmp_path / "wrong.zip", team_name="Registered Team")


def test_package_secret_rejection_preserves_existing_zip(tmp_path: Path) -> None:
    destination = tmp_path / "team.zip"
    destination.write_bytes(b"previous validated archive")
    source_text = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
    with (
        patch(
            "benchmarks.package_submission.dotenv_values",
            return_value={"API_KEY": source_text},
        ),
        pytest.raises(ValueError, match="credential"),
    ):
        package(destination, team_name="team")
    assert destination.read_bytes() == b"previous validated archive"
