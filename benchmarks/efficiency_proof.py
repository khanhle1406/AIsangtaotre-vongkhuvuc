"""Lock a qualified candidate and compare once on the sealed sixty-question oracle."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from run import validate_queries

from .batched import run_batched_stage
from .budget import workspace_budget
from .compare import source_hash
from .gateway import BatchLimits, atomic_json
from .gateway_runner import run_stage


def proof(root: Path = Path("reports/optimization/efficiency_v3")) -> dict[str, Any]:
    prerequisites = {}
    for label in ("final_public", "final_known", "final_synthetic"):
        report = json.loads((root / label / "report.json").read_text())
        if (
            not report["complete"]
            or report["score"]["correct"] != report["score"]["total"]
        ):
            raise ValueError(
                f"Candidate not qualified on {label}; sealed test remains unused"
            )
        prerequisites[label] = report["fingerprint"]
    held = root / "sealed_holdout"
    manifest = json.loads((held / "manifest.json").read_text())
    for name, expected in manifest["hashes"].items():
        if hashlib.sha256((held / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Sealed data/oracle changed")
    source_files = [
        Path("run.py"),
        *sorted(Path("src").glob("*.py")),
        *[
            Path("benchmarks") / name
            for name in (
                "batched.py",
                "efficient.py",
                "precision.py",
                "gateway.py",
                "gateway_runner.py",
            )
        ],
    ]
    lock = {
        "source_sha256": source_hash(),
        "modules": {
            p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source_files
        },
        "holdout_sha256": hashlib.sha256(
            (held / "manifest.json").read_bytes()
        ).hexdigest(),
        "prerequisites": prerequisites,
        "configuration": {
            "strategy": "live-workbook-plan",
            "group_size": 4,
            "concurrency": 4,
            "thinking": "low",
            "max_tokens": 2048,
        },
    }
    out = root / "sealed_proof"
    out.mkdir(exist_ok=True)
    receipt = held / "evaluated.json"
    if receipt.exists():
        if json.loads(receipt.read_text()) != lock:
            raise ValueError(
                "Consumed holdout cannot evaluate a changed candidate as independent"
            )
    else:
        atomic_json(out / "candidate_lock.json", lock)
        for path in source_files:
            target = out / "evaluated_source" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        atomic_json(receipt, lock)
    limits = BatchLimits(out / "batch.json")
    files = held / "xlsx_files"
    queries = validate_queries(held / "queries.json", files)
    results: dict[str, Any] = {
        "lock": lock,
        "stages": {},
        "private_btc_guaranteed": False,
        "qwen_confirmed": False,
    }
    for label in ("baseline", "candidate"):
        stage_root = out / label
        if (stage_root / "report.json").exists():
            report = json.loads((stage_root / "report.json").read_text())
            if report["complete"]:
                results["stages"][label] = report
                continue
        with workspace_budget().stage(str(stage_root.resolve()), 0.001) as ledger:
            if label == "baseline":
                report = run_stage(
                    stage_root,
                    files,
                    queries,
                    held / "references.csv",
                    "B",
                    limits,
                    cost_ledger=ledger,
                    iterator_helpers=True,
                    precision_profile="robust",
                )
            else:
                report = run_batched_stage(
                    stage_root, files, queries, held / "references.csv", limits, ledger
                )
        results["stages"][label] = report
        atomic_json(out / "summary.json", results)
    a, b = (results["stages"][name] for name in ("baseline", "candidate"))
    results["comparison"] = {
        "both_complete": a["complete"] and b["complete"],
        "correct_gain": b["score"]["correct"] - a["score"]["correct"],
        "wall_reduction": 1 - b["wall_seconds"] / a["wall_seconds"],
        "token_reduction_known": 1
        - b["provider_tokens_known"] / a["provider_tokens_known"]
        if a["provider_tokens_known"]
        else None,
        "usage_complete": a["usage_missing_attempts"]
        == b["usage_missing_attempts"]
        == 0,
        "heldout_consumed_after_this_evaluation": True,
    }
    atomic_json(out / "summary.json", results)
    return results


if __name__ == "__main__":
    print(json.dumps(proof()["comparison"], indent=2))
