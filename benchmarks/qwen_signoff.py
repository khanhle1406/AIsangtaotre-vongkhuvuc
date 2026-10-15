"""Bounded official-model acceptance gate; development Gemini scores cannot promote defaults."""

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from evaluate import read_answers
from run import run_queries, validate_queries
from src.llm_agent import DEFAULT_MODEL, LLMAgent, QueryState

from .budget import workspace_budget
from .compare import score, source_hash
from .gateway import atomic_json
from .gateway_runner import HELPER_CONTRACT


class CandidateAgent(LLMAgent):
    def __init__(
        self,
        *,
        helper_contract: bool = False,
        precision_profile: str | None = None,
        **kwargs: Any,
    ) -> None:
        if precision_profile is not None:
            if precision_profile not in {"robust", "lean"}:
                raise ValueError("Unknown precision profile")
            kwargs.update(iterator_helpers=True, compact_prompt=True)
        super().__init__(**kwargs)
        self.helper_instructions = HELPER_CONTRACT if helper_contract else ""
        if precision_profile is not None:
            from .precision import ACCURACY_CONTRACT, LEAN_SYSTEM

            self.helper_instructions = ACCURACY_CONTRACT
            if precision_profile == "lean":
                self.system_prompt = LEAN_SYSTEM
        self.system_prompt += self.helper_instructions

    def _request(self, messages: list[dict[str, str]], state: QueryState) -> str:
        if self.helper_instructions:
            messages = [dict(message) for message in messages]
            messages[-1]["content"] += "\n" + self.helper_instructions
        return super()._request(messages, state)


def acceptance_verdict(stages: dict[str, Any], names: list[str]) -> dict[str, Any]:
    """Compare complete official-model runs in contest order, after per-set safety gates."""
    ranks = {}
    complete = True
    for label in ("baseline", "candidate"):
        reports = [stages[label + "_" + name] for name in names]
        count = sum(report["score"]["total"] for report in reports)
        complete = (
            complete
            and count > 0
            and all(
                not report.get("fatal_error")
                and not report["metrics"]["failures"]
                and report["metrics"]["answered"] == report["score"]["total"]
                for report in reports
            )
        )
        ranks[label] = (
            -sum(report["score"]["correct"] for report in reports),
            sum(report["metrics"]["elapsed_seconds"] for report in reports)
            / max(1, count),
            sum(report["metrics"]["tokens"] for report in reports) / max(1, count),
        )
    non_regression = all(
        stages["candidate_" + name]["score"]["correct"]
        >= stages["baseline_" + name]["score"]["correct"]
        for name in names
    )
    public = stages.get("candidate_public")
    public_perfect = (
        public is None or public["score"]["correct"] == public["score"]["total"]
    )
    return {
        "ranks": ranks,
        "complete": complete,
        "non_regression": non_regression,
        "promotion_eligible": complete
        and non_regression
        and public_perfect
        and ranks["candidate"] < ranks["baseline"],
    }


def signoff(root: Path) -> dict[str, Any]:
    lock = json.loads((root / "candidate_lock.json").read_text())
    if lock["source_sha256"] != source_hash():
        raise ValueError("Competition source changed after candidate lock")
    if (
        lock.get("helper_sha256")
        and lock["helper_sha256"]
        != hashlib.sha256(HELPER_CONTRACT.encode()).hexdigest()
    ):
        raise ValueError("Candidate helper changed after lock")
    if lock.get("precision_profile"):
        from .precision import ACCURACY_CONTRACT

        if (
            lock["accuracy_contract_sha256"]
            != hashlib.sha256(ACCURACY_CONTRACT.encode()).hexdigest()
        ):
            raise ValueError("Precision task contract changed after lock")
    destination = root / "qwen_signoff.json"
    if destination.exists():
        raise ValueError("Preserve the existing Qwen acceptance evidence")
    report: dict[str, Any] = {
        "model": DEFAULT_MODEL,
        "provider": "openrouter",
        "limit_usd": 0.05,
        "new_generations": 0,
        "promoted": False,
    }
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        report.update(status="blocked_credentials")
        atomic_json(destination, report)
        return report
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/credits",
        headers={"Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            credit = json.load(response)["data"]
        balance = float(credit["total_credits"]) - float(credit["total_usage"])
        report["credit_preflight"] = {
            "total_credits": credit["total_credits"],
            "total_usage": credit["total_usage"],
            "available_usd": balance,
        }
        if balance <= 0:
            report.update(
                status="blocked_credit",
                reason="Account balance cannot fund paid Qwen requests; no inference sent",
            )
            atomic_json(destination, report)
            return report
    except (urllib.error.URLError, ValueError, KeyError) as error:
        report.update(status="blocked_credit_preflight", error=type(error).__name__)
        atomic_json(destination, report)
        return report
    stages = {}
    synthetic = root / "synthetic"
    if not synthetic.exists():
        synthetic = Path("reports/optimization/gemini_gateway/synthetic")
    held_candidates = [
        root / "sealed_holdout",
        root.parent / "sealed_holdout",
        Path("reports/optimization/frozen_holdout"),
    ]
    held = [
        path
        for path in held_candidates
        if (path / "manifest.json").exists()
        and (
            not lock.get("holdout_manifest_sha256")
            or hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()
            == lock["holdout_manifest_sha256"]
        )
    ]
    if not held:
        raise ValueError("The locked holdout manifest cannot be located")
    held_root = held[0]
    report["holdout_path"] = str(held_root)
    datasets = [
        (
            "public",
            Path("data/xlsx_files"),
            Path("data/queries.json"),
            Path("data/sample_submission.csv"),
        ),
        (
            "synthetic",
            synthetic / "xlsx_files",
            synthetic / "queries.json",
            synthetic / "answers.csv",
        ),
        (
            "holdout",
            held_root / "xlsx_files",
            held_root / "queries.json",
            held_root / "references.csv",
        ),
    ]
    # Acceptance only; never tune from this run or launch another paid sweep.
    with workspace_budget().stage(
        str(root.resolve()) + ":qwen-signoff", 0.05
    ) as ledger:
        deadline = time.monotonic() + 1800
        for name, files, queries_path, refs in datasets:
            for label in ("baseline", "candidate"):
                is_candidate = label == "candidate"
                client = CandidateAgent(
                    ledger=ledger,
                    deadline=deadline,
                    compact_prompt=is_candidate and lock.get("profile") in {"B", "C"},
                    helper_contract=is_candidate and lock.get("profile") == "C",
                    precision_profile=lock.get("precision_profile")
                    if is_candidate
                    else None,
                    max_tokens=lock["max_tokens"] if is_candidate else 2048,
                )
                output = root / f"qwen_{label}_{name}.csv"
                queries = validate_queries(queries_path, files)
                metrics = run_queries(files, queries, output, client, 2)
                stages[label + "_" + name] = {
                    "metrics": metrics,
                    "score": score(
                        output, read_answers(refs), {str(q["id"]) for q in queries}
                    ),
                    "fatal_error": client.fatal_error,
                }
                report["new_generations"] += sum(
                    1
                    for line in output.with_suffix(".trace.jsonl")
                    .read_text()
                    .splitlines()
                    if json.loads(line).get("requests", 0)
                )
                report["stages"] = stages
                if client.fatal_error:
                    report.update(status="blocked_api", error=client.fatal_error)
                    atomic_json(destination, report)
                    return report
                atomic_json(destination, report)
    report["status"] = "evaluated"
    report.update(acceptance_verdict(stages, [name for name, *_ in datasets]))
    # Promotion is kept explicit; the CLI default remains the verified configuration.
    atomic_json(destination, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    print(json.dumps(signoff(parser.parse_args().root), indent=2))
