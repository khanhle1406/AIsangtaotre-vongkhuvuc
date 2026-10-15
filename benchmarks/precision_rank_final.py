"""Finish within the SAME validation quota; freeze before any sealed answer is scored."""

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from evaluate import read_answers
from run import validate_queries
from src.excel_parser import load_workbook_data
from src.llm_agent import LLMAgent

from .budget import workspace_budget
from .compare import source_hash
from .gateway import BatchLimits, atomic_json
from .gateway_runner import run_stage
from .precision import ACCURACY_CONTRACT, LEAN_SYSTEM


def replay_known(root: Path) -> dict[str, Any]:
    prior = Path("reports/optimization/gemini_gateway")
    synthetic = prior / "synthetic"
    records = json.loads((root / "final/synthetic/checkpoint.json").read_text())[
        "records"
    ]
    queries = validate_queries(synthetic / "queries.json", synthetic / "xlsx_files")
    gold = read_answers(synthetic / "answers.csv")
    results = []
    for q in queries:
        record = records[q["id"]]
        selected = next(a for a in reversed(record["attempts"]) if a.get("code"))
        program = {
            key: selected[key]
            for key in ("code", "result_variable", "format", "selection", "assumptions")
            if key in selected
        }
        agent = LLMAgent("replay-placeholder", pricing=(0, 0), iterator_helpers=True)
        with patch.object(agent, "_request", return_value=json.dumps(program)):
            result = agent.solve_workbook(
                load_workbook_data(synthetic / "xlsx_files" / q["file_name"]),
                q["query"],
            )
        results.append(
            {
                "id": q["id"],
                "correct": result.answer == gold[q["id"]],
                "answer": result.answer,
                "error": result.error,
            }
        )
    return {
        "kind": "full-pipeline stored-program replay; zero LLM calls",
        "correct": sum(r["correct"] for r in results),
        "total": len(results),
        "source_sha256": source_hash(),
        "rows": results,
    }


def execute(root: Path = Path("reports/optimization/precision_v2")) -> dict[str, Any]:
    out = root / "final_rank"
    out.mkdir(exist_ok=True)
    limits = BatchLimits(root / "validation_batch.json")
    prior = Path("reports/optimization/gemini_gateway")
    old = Path("reports/optimization/frozen_holdout")
    hold = root / "sealed_holdout"
    if (hold / "evaluated.json").exists():
        raise ValueError("Independent holdout already consumed")
    summary: dict[str, Any] = {
        "source_sha256": source_hash(),
        "precision_profile": "robust",
        "stages": {},
        "promoted": False,
    }
    summary["synthetic_replay"] = replay_known(root)
    atomic_json(out / "summary.json", summary)
    with workspace_budget().stage(
        str(out.resolve()) + f":rank-final:{time.time_ns()}", 0.001
    ) as ledger:

        def stage(
            label: str,
            files: Path,
            qpath: Path,
            refs: Path,
            precision: str | None = "robust",
        ) -> dict[str, Any]:
            result = run_stage(
                out / label,
                files,
                validate_queries(qpath, files),
                refs,
                "C" if precision is None else "B",
                limits,
                thinking="minimal" if precision is None else "low",
                iterator_helpers=True,
                precision_profile=precision,
                cost_ledger=ledger,
            )
            summary["stages"][label] = result
            atomic_json(out / "summary.json", summary)
            return result

        for name, files, queries, refs in [
            (
                "public",
                Path("data/xlsx_files"),
                Path("data/queries.json"),
                Path("data/sample_submission.csv"),
            ),
            (
                "known_validation",
                old / "xlsx_files",
                old / "queries.json",
                old / "references.csv",
            ),
            (
                "metamorphic",
                prior / "metamorphic/xlsx_files",
                prior / "metamorphic/queries.json",
                prior / "metamorphic/references.csv",
            ),
            (
                "public_repeat",
                Path("data/xlsx_files"),
                Path("data/queries.json"),
                Path("data/sample_submission.csv"),
            ),
        ]:
            stage(name, files, queries, refs)
        perfect = (
            all(
                r["generation_complete"]
                and r["score"]["correct"] == r["score"]["total"]
                for r in summary["stages"].values()
            )
            and summary["synthetic_replay"]["correct"] == 24
        )
        summary["known_gates_all_perfect"] = perfect
        if not perfect:
            summary["status"] = "known gate failed; no holdout evaluation"
            summary["batch"] = limits.update()
            atomic_json(out / "summary.json", summary)
            return summary
        lock = {
            "precision_profile": "robust",
            "thinking": "low",
            "max_tokens": 2048,
            "iterator_helpers": True,
            "source_sha256": source_hash(),
            "accuracy_contract_sha256": hashlib.sha256(
                ACCURACY_CONTRACT.encode()
            ).hexdigest(),
            "lean_system_sha256": hashlib.sha256(LEAN_SYSTEM.encode()).hexdigest(),
            "transport_sha256": hashlib.sha256(
                Path(__file__).with_name("gateway.py").read_bytes()
            ).hexdigest(),
            "holdout_manifest_sha256": hashlib.sha256(
                (hold / "manifest.json").read_bytes()
            ).hexdigest(),
        }
        atomic_json(out / "candidate_lock.json", lock)
        atomic_json(hold / "evaluated.json", lock)
        summary["candidate"] = lock
        # Candidate first: do not consume the remaining allowance on a baseline
        # and accidentally leave the independent candidate evaluation unfinished.
        stage(
            "candidate_fresh_holdout",
            hold / "xlsx_files",
            hold / "queries.json",
            hold / "references.csv",
        )
        remaining = limits.update()["attempt_limit"] - limits.update()["attempts"]
        if remaining >= 24:
            stage(
                "baseline_fresh_holdout",
                hold / "xlsx_files",
                hold / "queries.json",
                hold / "references.csv",
                None,
            )
        else:
            summary["baseline_fresh_holdout"] = (
                "not evaluated: insufficient shared allowance"
            )
        summary["batch"] = limits.update()
        summary["status"] = "fixed quota complete; Qwen confirmation required"
    atomic_json(out / "summary.json", summary)
    return summary


if __name__ == "__main__":
    execute()
