"""Small recorded capability probe; never infer unsupported thinking from catalog size."""

import argparse
import json
import time
from pathlib import Path
from typing import Any

from src.llm_agent import QueryState

from .gateway import BatchLimits, GatewayAgent, atomic_json, gateway_settings


def probe(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    limits = BatchLimits(root / "batch.json")
    attempts: list[dict[str, Any]] = []
    for thinking in ("low", None):
        agent = GatewayAgent(
            **gateway_settings(), batch_limits=limits, thinking=thinking, max_tokens=256
        )
        state = QueryState(time.monotonic() + 60, 0.09)
        start = time.monotonic()
        try:
            content = agent._request(
                [
                    {
                        "role": "user",
                        "content": "Return one JSON object with key ok and boolean value true.",
                    }
                ],
                state,
            ).strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            ok = json.loads(content) == {"ok": True}
            expected = agent.model.removeprefix("ag/")
            if any(
                call.get("response_model") not in {agent.model, expected}
                for call in state.calls
                if not call.get("error")
            ):
                raise ValueError("Unexpected response model; no substitute accepted")
            report = {
                "ok": ok,
                "thinking": thinking,
                "elapsed_seconds": time.monotonic() - start,
                "calls": state.calls,
                "previous_attempts": attempts,
                "cost_basis": "free according to user; provider cost may be absent",
                "thinking_support": "request accepted; gateway application of thinking is not independently observable",
            }
            atomic_json(root / "probe.json", report)
            return report
        except (ValueError, TypeError, TimeoutError) as error:
            attempts.append({"error": str(error), "calls": state.calls})
            # Exactly one basic-payload retry, only for a rejected low payload.
            if thinking is None or not any(
                c.get("error") in {"HTTP 400", "HTTP 422"} for c in state.calls
            ):
                break
    report = {"ok": False, "attempts": attempts}
    atomic_json(root / "probe.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    print(json.dumps(probe(parser.parse_args().root), indent=2))
