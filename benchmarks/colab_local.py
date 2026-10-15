"""Development-only loopback client; imports no GPU libraries in the solver."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from src.context import project_workbook
from src.excel_parser import WorkbookData
from src.llm_agent import LLMAgent, QueryState, SolveResult

LOCAL_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
LOCAL_REVISION = "cdbee75f17c01a7cc42f958dc650907174af0554"
HELPER_CONTRACT = """
HELPER RETURN CONTRACTS (same workbook semantics as above):
cell(sheet,address): one scalar, including strings and typed dates.
cells(sheet,range): a 2D list, even for one cell; values(sheet,range): a flat list.
num(sheet,address): one numeric measure; do not apply it to a header or label.
Find rows from their full labels and section/header paths, not adjacency guesses.
data_rows(sheet, {'A':'string','B':'number'}) supports mixed column types.
Assign the final scalar/list to result; declare matching format and result_variable.
For a single text cell use result=cell('Example','C7').
For a numeric range use result=sum(values('Example','D8:D10')).
These are API shape examples, not workbook coordinates to copy.
"""


def loopback_url(base: str) -> str:
    """Reject proxies, credentials, remote hosts, queries and endpoint overrides."""
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
        or parsed.port is None
    ):
        raise ValueError("Local transport requires http://127.0.0.1:<port>/v1")
    return base.rstrip("/")


def local_opener() -> urllib.request.OpenerDirector:
    # Ignore HTTP_PROXY/HTTPS_PROXY even on Colab. No redirects to external hosts.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def local_json(
    base: str, endpoint: str, payload: dict[str, Any] | None = None, timeout: float = 10
) -> dict[str, Any]:
    base = loopback_url(base)
    if endpoint not in {"/models", "/tokenize", "/warmup"}:
        raise ValueError("Unknown local control endpoint")
    request = urllib.request.Request(
        base + endpoint,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with local_opener().open(request, timeout=timeout) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise TypeError("Invalid local control response")
    return data


class LocalDevelopmentAgent(LLMAgent):
    """Use the unchanged grounded solver with a non-thinking local transport."""

    def __init__(self, *, local_base_url: str, **kwargs: Any) -> None:
        self.local_base_url = loopback_url(local_base_url)
        metadata = local_json(self.local_base_url, "/models")
        self.local_metadata = metadata["local"]
        if (
            self.local_metadata["model"] != LOCAL_MODEL
            or self.local_metadata["revision"] != LOCAL_REVISION
        ):
            raise ValueError("Unexpected local model/revision; no substitute allowed")
        self.local_context = int(self.local_metadata["context_length"])
        if self.local_context not in {16384, 24576}:
            raise ValueError("Unsupported T4 context profile")
        kwargs.update(
            api_key="local-development-placeholder",
            model=LOCAL_MODEL,
            pricing=(0.0, 0.0),
            reasoning_tokens=0,
            request_timeout_seconds=120,
        )
        super().__init__(**kwargs)
        self.local_workbook: dict[str, Any] = {}
        self.local_query = ""

    def _request_url(self) -> str:
        return self.local_base_url + "/chat/completions"

    def _open_request(self, request: urllib.request.Request, timeout: float) -> Any:
        return local_opener().open(request, timeout=timeout)

    def token_count(self, messages: list[dict[str, str]]) -> int:
        result = local_json(self.local_base_url, "/tokenize", {"messages": messages})
        count = result.get("tokens")
        if type(count) is not int or count < 0:
            raise ValueError("Invalid local tokenizer count")
        return count

    def fit_context(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        fitted = [dict(message) for message in messages]
        if self.token_count(fitted) + self.max_tokens <= self.local_context:
            return fitted
        if not self.local_workbook:
            raise ValueError("Local context overflow; no expandable workbook")
        for byte_budget in (80000, 40000, 20000, 10000, 5000):
            view = project_workbook(self.local_workbook, self.local_query, byte_budget)
            # Preserve instructions appended by the solver after QUESTION.
            original = fitted[1]["content"]
            marker = "\n\nQUESTION:\n"
            if marker not in original:
                raise ValueError("Cannot replace an unknown workbook message")
            question = original.split(marker, 1)[1]
            fitted[1]["content"] = "WORKBOOK DATA:\n" + view + marker + question
            if self.token_count(fitted) + self.max_tokens <= self.local_context:
                return fitted
        raise ValueError(
            "Local context overflow including inspection; request narrower regions"
        )

    def solve_workbook(
        self, workbook: WorkbookData, query: str, max_retries: int = 2
    ) -> SolveResult:
        self.local_workbook, self.local_query = workbook.wire(), query
        return super().solve_workbook(workbook, query, max_retries)

    def _request(self, messages: list[dict[str, str]], state: QueryState) -> str:
        return super()._request(self.fit_context(messages), state)

    def _before_request(self, payload: dict[str, Any], state: QueryState) -> None:
        metadata = local_json(self.local_base_url, "/models")["local"]
        if metadata.get("fatal_error"):
            self.fatal_error = "Local model unavailable: " + metadata["fatal_error"]
            raise TimeoutError(self.fatal_error)
        if metadata["context_length"] != self.local_context:
            raise ValueError("Context profile changed; restart the comparison")
        payload.pop("reasoning", None)
        payload["timeout_seconds"] = min(115, state.deadline - time.monotonic() - 2)
