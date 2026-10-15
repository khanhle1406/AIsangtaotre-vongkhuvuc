"""Finite precision tuning, stability and a sealed once-only generalization gate."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from run import validate_queries

from .budget import workspace_budget
from .compare import source_hash
from .gateway import BatchLimits, atomic_json
from .gateway_runner import run_stage
from .precision import ACCURACY_CONTRACT, LEAN_SYSTEM


def execute(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    tuning_limits = BatchLimits(root / "tuning_batch.json")
    hold = root / "sealed_holdout"
    if not (hold / "manifest.json").exists():
        raise ValueError("Seal the independent families before tuning begins")
    prior = Path("reports/optimization/gemini_gateway")
    tuning = json.loads((prior / "tuning_manifest.json").read_text())["queries"]
    synthetic = prior / "synthetic"
    public = validate_queries(Path("data/queries.json"), Path("data/xlsx_files"))
    old = Path("reports/optimization/frozen_holdout")
    summary: dict[str, Any] = {
        "source_sha256": source_hash(),
        "stages": {},
        "holdout_presealed": True,
        "promoted": False,
    }
    with workspace_budget().stage(
        str(root.resolve()) + f":precision:{time.time_ns()}", 0.001
    ) as ledger:

        def stage(
            label: str,
            files: Path,
            queries: list[dict[str, Any]],
            refs: Path,
            profile: str,
            limits: BatchLimits,
        ) -> dict[str, Any]:
            result = run_stage(
                root / label,
                files,
                queries,
                refs,
                "B",
                limits,
                thinking="low",
                iterator_helpers=True,
                precision_profile=profile,
                cost_ledger=ledger,
            )
            summary["stages"][label] = result
            atomic_json(root / "summary.json", summary)
            return result

        screens = {}
        for profile in ["robust", "lean"]:
            screens[profile] = stage(
                profile + "_screen",
                synthetic / "xlsx_files",
                tuning,
                synthetic / "answers.csv",
                profile,
                tuning_limits,
            )
        public_reports = {}
        for profile in ["robust", "lean"]:
            public_reports[profile] = stage(
                profile + "_public",
                Path("data/xlsx_files"),
                public,
                Path("data/sample_submission.csv"),
                profile,
                tuning_limits,
            )
        eligible = [
            p
            for p in screens
            if screens[p]["generation_complete"]
            and public_reports[p]["generation_complete"]
            and screens[p]["score"]["correct"] == len(tuning)
            and public_reports[p]["score"]["correct"] == len(public)
        ]
        if not eligible:
            summary["status"] = "no_candidate_meets_public_and_tuning_gates"
            atomic_json(root / "summary.json", summary)
            return summary
        winner = min(
            eligible,
            key=lambda p: (screens[p]["mean_query_seconds"], screens[p]["tokens"], p),
        )
        # Known validation is allowed to reject a prompt before any new holdout evaluation.
        sq = validate_queries(synthetic / "queries.json", synthetic / "xlsx_files")
        vq = validate_queries(old / "queries.json", old / "xlsx_files")
        validation = {}
        for profile in eligible:
            validation[profile] = [
                stage(
                    profile + "_synthetic",
                    synthetic / "xlsx_files",
                    sq,
                    synthetic / "answers.csv",
                    profile,
                    tuning_limits,
                ),
                stage(
                    profile + "_known_validation",
                    old / "xlsx_files",
                    vq,
                    old / "references.csv",
                    profile,
                    tuning_limits,
                ),
            ]
        winner = min(
            eligible,
            key=lambda p: (
                -sum(r["score"]["correct"] for r in validation[p]),
                sum(r["mean_query_seconds"] for r in validation[p]),
                sum(r["tokens"] for r in validation[p]),
                p,
            ),
        )
        mutation = prior / "metamorphic"
        mq = validate_queries(mutation / "queries.json", mutation / "xlsx_files")
        stage(
            winner + "_metamorphic",
            mutation / "xlsx_files",
            mq,
            mutation / "references.csv",
            winner,
            tuning_limits,
        )
        # A repeat is an operational stability test, not a new independent dataset.
        stage(
            winner + "_public_repeat",
            Path("data/xlsx_files"),
            public,
            Path("data/sample_submission.csv"),
            winner,
            tuning_limits,
        )
        selected = {
            "precision_profile": winner,
            "thinking": "low",
            "max_tokens": 2048,
            "iterator_helpers": True,
            "source_sha256": source_hash(),
            "accuracy_contract_sha256": hashlib.sha256(
                ACCURACY_CONTRACT.encode()
            ).hexdigest(),
            "lean_system_sha256": hashlib.sha256(LEAN_SYSTEM.encode()).hexdigest(),
            "holdout_manifest_sha256": hashlib.sha256(
                (hold / "manifest.json").read_bytes()
            ).hexdigest(),
        }
        lock = root / "candidate_lock.json"
        if lock.exists() and json.loads(lock.read_text()) != selected:
            raise ValueError("Candidate already locked; never retune from holdout")
        atomic_json(lock, selected)
        summary["candidate"] = selected
        summary["tuning_batch"] = tuning_limits.update()
        atomic_json(root / "summary.json", summary)
        limits = BatchLimits(root / "validation_batch.json")
        receipt = hold / "evaluated.json"
        if receipt.exists() and json.loads(receipt.read_text()) != selected:
            raise ValueError("Holdout already consumed by another candidate")
        atomic_json(receipt, selected)
        queries = validate_queries(hold / "queries.json", hold / "xlsx_files")
        # C uses the same current executor: this comparison isolates the task contract.
        baseline = run_stage(
            root / "baseline_fresh_holdout",
            hold / "xlsx_files",
            queries,
            hold / "references.csv",
            "C",
            limits,
            thinking="minimal",
            iterator_helpers=True,
            cost_ledger=ledger,
        )
        summary["stages"]["baseline_fresh_holdout"] = baseline
        atomic_json(root / "summary.json", summary)
        stage(
            winner + "_fresh_holdout",
            hold / "xlsx_files",
            queries,
            hold / "references.csv",
            winner,
            limits,
        )
        summary["validation_batch"] = limits.update()
    summary["status"] = "fixed_experiment_complete; Qwen confirmation still required"
    atomic_json(root / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path("reports/optimization/precision_v2")
    )
    execute(parser.parse_args().root)
