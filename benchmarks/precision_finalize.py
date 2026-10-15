"""One fixed finalization batch after known-validation fixes, before sealed evaluation."""

import hashlib
import time
from pathlib import Path
from typing import Any

from run import validate_queries

from .budget import workspace_budget
from .compare import source_hash
from .gateway import BatchLimits, atomic_json
from .gateway_runner import run_stage
from .precision import ACCURACY_CONTRACT, LEAN_SYSTEM


def execute(root: Path = Path("reports/optimization/precision_v2")) -> dict[str, Any]:
    out = root / "final"
    out.mkdir(exist_ok=True)
    limits = BatchLimits(root / "validation_batch.json")
    prior = Path("reports/optimization/gemini_gateway")
    old = Path("reports/optimization/frozen_holdout")
    hold = root / "sealed_holdout"
    if (hold / "evaluated.json").exists():
        raise ValueError("Sealed holdout already evaluated; no retuning permitted")
    summary: dict[str, Any] = {
        "source_sha256": source_hash(),
        "precision_profile": "robust",
        "stages": {},
        "promoted": False,
        "selection_reason": "Both v2 profiles public 20/20; robust failed optional format metadata, lean failed actual helper usage. Normalize metadata and retain full system semantics.",
    }
    with workspace_budget().stage(
        str(out.resolve()) + f":final:{time.time_ns()}", 0.001
    ) as ledger:

        def stage(
            label: str,
            files: Path,
            qpath: Path,
            refs: Path,
            precision: str | None = "robust",
        ) -> dict[str, Any]:
            queries = validate_queries(qpath, files)
            result = run_stage(
                out / label,
                files,
                queries,
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

        jobs = [
            (
                "public",
                Path("data/xlsx_files"),
                Path("data/queries.json"),
                Path("data/sample_submission.csv"),
            ),
            (
                "synthetic",
                prior / "synthetic/xlsx_files",
                prior / "synthetic/queries.json",
                prior / "synthetic/answers.csv",
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
        ]
        for name, files, queries, refs in jobs:
            stage(name, files, queries, refs)
        complete = all(
            r["generation_complete"] and r["score"]["correct"] == r["score"]["total"]
            for r in summary["stages"].values()
        )
        summary["known_gates_all_perfect"] = complete
        if not complete:
            summary["status"] = (
                "known validation not perfect; sealed holdout remains unconsumed"
            )
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
        stage(
            "baseline_fresh_holdout",
            hold / "xlsx_files",
            hold / "queries.json",
            hold / "references.csv",
            None,
        )
        stage(
            "candidate_fresh_holdout",
            hold / "xlsx_files",
            hold / "queries.json",
            hold / "references.csv",
        )
        summary["candidate"] = lock
        summary["batch"] = limits.update()
        summary["status"] = "finite finalization complete; Qwen signoff required"
    atomic_json(out / "summary.json", summary)
    return summary


if __name__ == "__main__":
    execute()
