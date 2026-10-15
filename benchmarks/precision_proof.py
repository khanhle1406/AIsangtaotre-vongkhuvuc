"""Last bounded proof run: no resampling, no tuning after sealed evaluation."""

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
from .precision_rank_final import replay_known


def execute(root: Path = Path("reports/optimization/precision_v2")) -> dict[str, Any]:
    out = root / "frozen_proof"
    out.mkdir(exist_ok=True)
    limits = BatchLimits(out / "batch.json", attempts=180)
    hold = root / "sealed_holdout"
    old = Path("reports/optimization/frozen_holdout")
    prior = Path("reports/optimization/gemini_gateway")
    if (hold / "evaluated.json").exists():
        raise ValueError("Independent evaluation is already consumed")
    summary: dict[str, Any] = {
        "source_sha256": source_hash(),
        "profile": "robust",
        "stages": {},
        "promoted": False,
        "scope": "one final fixed run; maximum 180 attempts, 2M tokens and 30 minutes; no loop after holdout",
    }
    summary["synthetic_replay"] = replay_known(root)
    atomic_json(out / "summary.json", summary)
    with workspace_budget().stage(
        str(out.resolve()) + f":proof:{time.time_ns()}", 0.001
    ) as ledger:

        def stage(
            label: str, files: Path, qpath: Path, refs: Path, baseline: bool = False
        ) -> dict[str, Any]:
            result = run_stage(
                out / label,
                files,
                validate_queries(qpath, files),
                refs,
                "C" if baseline else "B",
                limits,
                thinking="minimal" if baseline else "low",
                iterator_helpers=True,
                precision_profile=None if baseline else "robust",
                cost_ledger=ledger,
            )
            summary["stages"][label] = result
            atomic_json(out / "summary.json", summary)
            return result

        for name, files, qpath, refs in [
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
            (
                "public_mutation",
                root / "public_mutation_complete/xlsx_files",
                root / "public_mutation_complete/queries.json",
                root / "public_mutation_complete/references.csv",
            ),
        ]:
            stage(name, files, qpath, refs)
        summary["pre_holdout_scores"] = {
            n: r["score"] for n, r in summary["stages"].items()
        }
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
        stage(
            "candidate_fresh_holdout",
            hold / "xlsx_files",
            hold / "queries.json",
            hold / "references.csv",
        )
        if limits.update()["attempt_limit"] - limits.update()["attempts"] >= 24:
            stage(
                "baseline_fresh_holdout",
                hold / "xlsx_files",
                hold / "queries.json",
                hold / "references.csv",
                True,
            )
        else:
            summary["baseline_fresh_holdout"] = (
                "not evaluated; insufficient request allowance"
            )
        summary["batch"] = limits.update()
        summary["status"] = "fixed proof run complete; no additional holdout tuning"
    atomic_json(out / "summary.json", summary)
    return summary


if __name__ == "__main__":
    execute()
