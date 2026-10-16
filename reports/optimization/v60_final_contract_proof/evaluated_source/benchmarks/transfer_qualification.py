"""One bounded, frozen Gemini qualification and an optional once-only independent proof."""

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

from run import validate_queries

from .batched import run_batched_stage
from .budget import workspace_budget
from .gateway import BatchLimits, atomic_json
from .gateway_runner import run_stage
from .packed import PLANNING_PROFILES, planning_agent
from .qwen_batch_signoff import source_manifest


def batch_stop_reason(allowance: dict[str, Any]) -> str | None:
    """Report exhaustion before loading another dataset or creating empty predictions."""
    if allowance["fatal_error"]:
        return str(allowance["fatal_error"])
    if time.time() >= allowance["deadline_unix"]:
        return "Batch deadline exhausted"
    if allowance["attempts"] >= allowance["attempt_limit"]:
        return "Batch HTTP attempt allowance exhausted"
    if allowance["token_upper"] >= allowance["token_limit"]:
        return "Batch token allowance exhausted"
    return None


def qualify(
    root: Path,
    heldout: Path,
    *,
    independent: bool = True,
    thinking: str = "low",
    concurrency: int = 4,
    extended_regression: bool = False,
    review_candidate: bool = False,
    deduplicate_headers: bool = False,
    boundary_contract: bool = False,
    planning_profile: str = "same-book",
) -> dict[str, Any]:
    """Preserve every result; do not open holdout inference until all prerequisites pass."""
    if root.exists():
        raise ValueError("Preserve existing qualification evidence")
    agent_class = planning_agent(planning_profile)
    if thinking not in {"minimal", "low", "medium", "high"} or concurrency not in {
        1,
        2,
        4,
        8,
    }:
        raise ValueError("Invalid development qualification configuration")
    manifest = heldout / "manifest.json"
    manifest_data = json.loads(manifest.read_text())
    for name, expected in manifest_data["hashes"].items():
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
    expected_counts = {
        "baseline_public": 20,
        **{f"public_{i}": 20 for i in range(1, 4)},
        "regression_60": 60,
        "regression_32": 32,
        "known_18": 18,
        "synthetic_24": 24,
    }
    if extended_regression:
        for label, folder, count in [
            ("decision_18", "decision_v1_holdout", 18),
            ("structural_18", "structural_v1_holdout", 18),
            ("generalization_18", "generalization_v1_holdout", 18),
            ("transfer_24", "efficiency_v5_holdout", 24),
            ("compositional_18", "compositional_v1_holdout", 18),
            ("robustness_24", "robustness_v1_holdout", 24),
        ]:
            dataset = Path("reports/optimization") / folder
            if not independent and dataset.resolve() == heldout.resolve():
                continue  # The consumed-validation stage covers this dataset once.
            extensions[label] = {"folder": str(dataset), "count": count}
            datasets[label] = (dataset, "references.csv")
            expected_counts[label] = count
    for folder, reference in [*datasets.values(), (heldout, "references.csv")]:
        if not (folder / reference).is_file():
            raise ValueError(f"Missing evaluation reference: {folder / reference}")
    new_families = set(manifest_data.get("families", []))
    if independent and new_families:
        known_families = {
            q["family"]
            for folder, _ in datasets.values()
            for q in json.loads((folder / "queries.json").read_text())
            if q.get("family")
        }
        if new_families & known_families:
            raise ValueError("Independent holdout families overlap regression families")
    root.mkdir(parents=True)
    lock = {
        "modules": source_manifest(),
        "scope": "Fixed qualification then once-only unseen comparison; no tuning on holdout"
        if independent
        else "Known datasets and consumed validation: regression only, no independent holdout claim",
        "independent_validation": independent,
        "public_repetitions": 3,
        "configuration": {
            "thinking": thinking,
            "temperature": agent_class.default_temperature,
            "concurrency": concurrency,
            "review_candidate": review_candidate,
            "deduplicate_headers": deduplicate_headers,
            "boundary_contract": boundary_contract,
            "planning_profile": planning_profile,
            "group_size": agent_class.maximum_group_size,
            "planning_max_tokens": agent_class.planning_max_tokens or 2048,
            "agent_class": agent_class.__name__,
        },
        "regression_extensions": extensions,
        "expected_case_counts": expected_counts,
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
        "unassessed": {},
        "btc_private_verified": False,
        "qwen_confirmed": False,
    }

    def stage(
        label: str, folder: Path, reference_name: str, baseline: bool = False
    ) -> dict[str, Any] | None:
        reason = result.get("stopped") or batch_stop_reason(limits.update())
        if reason:
            result["unassessed"][label] = reason
            atomic_json(root / "summary.json", result)
            return None
        if lock["modules"] != source_manifest():
            raise ValueError("Candidate source changed during live evaluation")
        queries = validate_queries(folder / "queries.json", folder / "xlsx_files")
        expected_count = expected_counts.get(label, manifest_data.get("queries"))
        if type(expected_count) is int and len(queries) != expected_count:
            raise ValueError(
                "Dataset count does not match the frozen qualification scope"
            )
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
                    agent_class=agent_class,
                    group_size=agent_class.maximum_group_size,
                    thinking=thinking,
                    concurrency=concurrency,
                    review_candidate=review_candidate,
                    deduplicate_headers=deduplicate_headers,
                    boundary_contract=boundary_contract,
                )
        if lock["modules"] != source_manifest():
            raise ValueError("Candidate source changed during live evaluation")
        result["stages"][label] = report
        reason = batch_stop_reason(limits.update())
        if reason or any(
            "Gateway batch request/token allowance exhausted" in str(error)
            for error in report.get("errors", {}).values()
        ):
            result["stopped"] = (
                reason or "Insufficient remaining request/token allowance"
            )
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
    qualified = (
        not result.get("stopped")
        and set(datasets) <= result["stages"].keys()
        and all(
            report["complete"]
            and report["score"]["correct"] == report["score"]["total"]
            for name, report in result["stages"].items()
            if name != "baseline_public"
        )
    )
    if qualified and independent:
        remaining = limits.update()
        count = len(validate_queries(heldout / "queries.json", heldout / "xlsx_files"))
        if (
            remaining["attempt_limit"] - remaining["attempts"]
            < count + (count + 3) // 4
        ):
            result["unassessed"]["heldout_proof"] = (
                "Insufficient allowance even for the minimum baseline/candidate requests"
            )
            result["holdout_status"] = "not evaluated; insufficient batch allowance"
            atomic_json(root / "summary.json", result)
            return result
        atomic_json(receipt, lock)
        baseline = stage(
            "heldout_proof/baseline", heldout, "references.csv", baseline=True
        )
        candidate = stage("heldout_proof/candidate", heldout, "references.csv")
        if baseline is None or candidate is None:
            result["holdout_status"] = (
                "Consumed receipt preserved; comparison incomplete due batch allowance"
            )
            atomic_json(root / "summary.json", result)
            return result
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
        "--review-candidate",
        action="store_true",
        help="Audit unverified executable code during semantic review; keep default unchanged",
    )
    parser.add_argument("--deduplicate-headers", action="store_true")
    parser.add_argument("--boundary-contract", action="store_true")
    parser.add_argument(
        "--planning-profile", choices=list(PLANNING_PROFILES), default="same-book"
    )
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
        review_candidate=arguments.review_candidate,
        deduplicate_headers=arguments.deduplicate_headers,
        boundary_contract=arguments.boundary_contract,
        planning_profile=arguments.planning_profile,
    )
