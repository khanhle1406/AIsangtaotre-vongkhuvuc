"""One bounded, frozen Gemini qualification and an optional once-only independent proof."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from run import validate_queries

from .batched import run_batched_stage
from .budget import workspace_budget
from .gateway import BatchLimits, atomic_json
from .gateway_runner import run_stage
from .qwen_batch_signoff import source_manifest
from .structured_batch import StructuredBatchedAgent


def qualify(
    root: Path,
    heldout: Path,
    *,
    independent: bool = True,
    thinking: str = "low",
    concurrency: int = 4,
    extended_regression: bool = False,
) -> dict[str, Any]:
    """Preserve every result; do not open holdout inference until all prerequisites pass."""
    if root.exists():
        raise ValueError("Preserve existing qualification evidence")
    if thinking not in {"minimal", "low", "medium", "high"} or concurrency not in {
        1,
        2,
        4,
        8,
    }:
        raise ValueError("Invalid development qualification configuration")
    manifest = heldout / "manifest.json"
    for name, expected in json.loads(manifest.read_text())["hashes"].items():
        path = heldout / name
        if (
            not path.resolve().is_relative_to(heldout.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("Frozen holdout dataset has changed")
    receipt = heldout / "evaluated.json"
    if receipt.exists() and independent:
        raise ValueError("This independent holdout has already been consumed")
    datasets = {
        "baseline_public": (Path("data"), "sample_submission.csv"),
        **{f"public_{i}": (Path("data"), "sample_submission.csv") for i in range(1, 4)},
        "regression_60": (
            Path("reports/optimization/efficiency_v3/sealed_holdout"),
            "references.csv",
        ),
        "regression_32": (
            Path("reports/optimization/efficiency_v4/sealed_challenge"),
            "references.csv",
        ),
        "known_18": (Path("reports/optimization/frozen_holdout"), "references.csv"),
        "synthetic_24": (
            Path("reports/optimization/gemini_gateway/synthetic"),
            "answers.csv",
        ),
    }
    extensions = {}
    if extended_regression:
        for label, folder, count in [
            ("structural_18", "structural_v1_holdout", 18),
            ("generalization_18", "generalization_v1_holdout", 18),
            ("transfer_24", "efficiency_v5_holdout", 24),
            ("compositional_18", "compositional_v1_holdout", 18),
        ]:
            dataset = Path("reports/optimization") / folder
            extensions[label] = {"folder": str(dataset), "count": count}
            datasets[label] = (dataset, "references.csv")
    for folder, reference in [*datasets.values(), (heldout, "references.csv")]:
        if not (folder / reference).is_file():
            raise ValueError(f"Missing evaluation reference: {folder / reference}")
    root.mkdir(parents=True)
    lock = {
        "modules": source_manifest(),
        "scope": "Fixed qualification then once-only unseen comparison; no tuning on holdout"
        if independent
        else "Known datasets and consumed validation: regression only, no independent holdout claim",
        "independent_validation": independent,
        "public_repetitions": 3,
        "configuration": {"thinking": thinking, "concurrency": concurrency},
        "regression_extensions": extensions,
        "validation_dataset": str(heldout),
        "validation_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    atomic_json(root / "source_lock.json", lock)
    for path in [*map(Path, lock["modules"]), Path(__file__)]:
        target = (
            root / "evaluated_source" / path.relative_to(Path.cwd())
            if path.is_absolute()
            else root / "evaluated_source" / path
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    limits = BatchLimits(root / "batch.json")
    result: dict[str, Any] = {
        "source_lock": lock,
        "stages": {},
        "btc_private_verified": False,
        "qwen_confirmed": False,
    }

    def stage(
        label: str, folder: Path, reference_name: str, baseline: bool = False
    ) -> dict[str, Any]:
        if lock["modules"] != source_manifest():
            raise ValueError("Candidate source changed during live evaluation")
        queries = validate_queries(folder / "queries.json", folder / "xlsx_files")
        reference = folder / reference_name
        destination = root / label
        with workspace_budget().stage(str(destination.resolve()), 0.001) as ledger:
            if baseline:
                report = run_stage(
                    destination,
                    folder / "xlsx_files",
                    queries,
                    reference,
                    "B",
                    limits,
                    cost_ledger=ledger,
                    iterator_helpers=True,
                    precision_profile="robust",
                )
            else:
                report = run_batched_stage(
                    destination,
                    folder / "xlsx_files",
                    queries,
                    reference,
                    limits,
                    ledger,
                    agent_class=StructuredBatchedAgent,
                    thinking=thinking,
                    concurrency=concurrency,
                )
        if lock["modules"] != source_manifest():
            raise ValueError("Candidate source changed during live evaluation")
        result["stages"][label] = report
        atomic_json(root / "summary.json", result)
        print(
            json.dumps(
                {
                    "stage": label,
                    "score": report["score"],
                    "seconds": report["wall_seconds"],
                    "tokens": report["provider_tokens_known"],
                }
            ),
            flush=True,
        )
        return report

    for label, (folder, reference) in datasets.items():
        stage(label, folder, reference, baseline=label == "baseline_public")
    qualified = all(
        report["complete"] and report["score"]["correct"] == report["score"]["total"]
        for name, report in result["stages"].items()
        if name != "baseline_public"
    )
    if qualified and independent:
        atomic_json(receipt, lock)
        baseline = stage(
            "heldout_proof/baseline", heldout, "references.csv", baseline=True
        )
        candidate = stage("heldout_proof/candidate", heldout, "references.csv")
        result["holdout_status"] = "consumed once; future runs are regression only"
        result["comparison"] = {
            "complete": baseline["complete"] and candidate["complete"],
            "correct_gain": candidate["score"]["correct"]
            - baseline["score"]["correct"],
            "wall_reduction": 1 - candidate["wall_seconds"] / baseline["wall_seconds"],
            "token_reduction": 1
            - candidate["provider_tokens_known"] / baseline["provider_tokens_known"]
            if baseline["provider_tokens_known"]
            else None,
            "usage_complete": baseline["usage_missing_attempts"]
            == candidate["usage_missing_attempts"]
            == 0,
        }
    elif independent:
        result["holdout_status"] = "not evaluated; failed qualification"
    else:
        stage("consumed_validation", heldout, "references.csv")
        result["holdout_status"] = (
            "No independent evaluation; consumed validation is regression only"
        )
    atomic_json(root / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--thinking", choices=["minimal", "low", "medium", "high"], default="low"
    )
    parser.add_argument("--concurrency", type=int, choices=[1, 2, 4, 8], default=4)
    parser.add_argument(
        "--extended-regression",
        action="store_true",
        help="Require every previously consumed challenge family before opening new holdout",
    )
    parser.add_argument(
        "--regression-only",
        action="store_true",
        help="Evaluate consumed data without touching its independent-test receipt",
    )
    parser.add_argument(
        "--heldout",
        type=Path,
        default=Path("reports/optimization/efficiency_v5_holdout"),
    )
    arguments = parser.parse_args()
    qualify(
        arguments.root,
        arguments.heldout,
        independent=not arguments.regression_only,
        thinking=arguments.thinking,
        concurrency=arguments.concurrency,
        extended_regression=arguments.extended_regression,
    )
