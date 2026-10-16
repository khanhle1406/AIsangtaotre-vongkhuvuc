"""Screen medium effort only on application-triggered verification, never initial plans."""

import json
import time
import urllib.error
from pathlib import Path
from typing import Any, ClassVar

from src.llm_agent import QueryState

from .budget import workspace_budget
from .gateway import BatchLimits, GatewayAgent, atomic_json, gateway_settings
from .structured_batch import StructuredBatchedAgent


class MediumReviewAgent(StructuredBatchedAgent):
    """Keep initial low and third-attempt high; raise only a low verification call."""

    verification_thinking: ClassVar[str] = "medium"

    def _thinking_for_request(self, state: QueryState) -> str | None:
        effort = super()._thinking_for_request(state)
        if state.verification and effort in {"minimal", "low"}:
            return self.verification_thinking
        return effort


def probe(
    root: Path, limits: BatchLimits, *, thinking: str = "medium", max_tokens: int = 256
) -> dict[str, Any]:
    """Check requested effort/output acceptance within the experiment's allowance."""
    state = QueryState(time.monotonic() + 60, 0.09)
    report: dict[str, Any] = {
        "ok": False,
        "thinking_support": "requested effort only; internal implementation unverified",
        "requested_thinking": thinking,
        "requested_max_tokens": max_tokens,
    }
    with workspace_budget().stage(str((root / "probe").resolve()), 0.001) as ledger:
        agent = GatewayAgent(
            **gateway_settings(),
            thinking=thinking,
            batch_limits=limits,
            ledger=ledger,
            max_tokens=max_tokens,
        )
        try:
            content = agent._request(
                [{"role": "user", "content": 'Return exactly {"ok":true} as JSON.'}],
                state,
            ).strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            report["ok"] = (
                json.loads(content) == {"ok": True}
                and not agent.fatal_error
                and all(
                    call.get("response_model")
                    in {agent.model, agent.model.removeprefix("ag/")}
                    for call in state.calls
                    if not call.get("error")
                )
            )
        except (ValueError, TypeError, TimeoutError, urllib.error.URLError) as error:
            report["error"] = f"{type(error).__name__}: {error}"
    report["calls"] = state.calls
    atomic_json(root / "probe.json", report)
    return report
