"""Compare full versus lean system instructions while retaining the full task contract."""

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from run import validate_queries

from .batched import run_batched_stage
from .budget import workspace_budget
from .gateway import BatchLimits, atomic_json
from .qwen_batch_signoff import source_manifest
from .structured_batch import StructuredBatchedAgent
from .transfer_qualification import batch_stop_reason


class LeanStructuredAgent(StructuredBatchedAgent):
    """Change system verbosity only; keep accuracy, runtime and output contracts."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(lean_system=True, **kwargs)


def compare(root: Path) -> dict[str, Any]:
    """Alternate policy order across consumed families; never promote from screening."""
    if root.exists():
        raise ValueError("Preserve prior prompt comparison")
    root.mkdir(parents=True)
    source = source_manifest()
    result: dict[str, Any] = {
        "modules": source,
        "independent_validation": False,
        "promoted": False,
        "stages": {},
        "unassessed": {},
    }
    for name in [*source, "benchmarks/prompt_ablation.py"]:
        target = root / "evaluated_source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(name, target)
    atomic_json(root / "summary.json", result)
    limits = BatchLimits(root / "batch.json")
    datasets = [
        ("public", Path("data"), "sample_submission.csv"),
        *[
            (label, Path("reports/optimization") / folder, "references.csv")
            for label, folder in [
                ("decision", "decision_v1_holdout"),
                ("structural", "structural_v1_holdout"),
                ("generalization", "generalization_v1_holdout"),
                ("compositional", "compositional_v1_holdout"),
            ]
        ],
    ]
    stopped = None
    for index, (label, folder, reference) in enumerate(datasets):
        arms = [("full", StructuredBatchedAgent), ("lean", LeanStructuredAgent)]
        if index % 2:
            arms.reverse()
        for arm, agent_class in arms:
            key = arm + "/" + label
            reason = stopped or batch_stop_reason(limits.update())
            if reason:
                result["unassessed"][key] = reason
                atomic_json(root / "summary.json", result)
                continue
            if source != source_manifest():
                raise ValueError("Source changed during prompt comparison")
            output = root / arm / label
            queries = validate_queries(folder / "queries.json", folder / "xlsx_files")
            with workspace_budget().stage(str(output.resolve()), 0.001) as ledger:
                report = run_batched_stage(
                    output,
                    folder / "xlsx_files",
                    queries,
                    folder / reference,
                    limits,
                    ledger,
                    agent_class=agent_class,
                    review_candidate=True,
                )
            if source != source_manifest():
                raise ValueError("Source changed during prompt comparison")
            result["stages"][key] = report
            stopped = batch_stop_reason(limits.update()) or report.get("fatal_error")
            if any(
                "Gateway batch request/token allowance exhausted" in str(error)
                for error in report.get("errors", {}).values()
            ):
                stopped = "Insufficient remaining request/token allowance"
            atomic_json(root / "summary.json", result)
            print(json.dumps({"stage": key, "score": report["score"]}), flush=True)
    if not result["unassessed"]:
        result["comparison"] = {}
        for arm in ["full", "lean"]:
            reports = [result["stages"][arm + "/" + label] for label, _, _ in datasets]
            result["comparison"][arm] = {
                "correct": sum(r["score"]["correct"] for r in reports),
                "total": sum(r["score"]["total"] for r in reports),
                "seconds": sum(r["wall_seconds"] for r in reports),
                "tokens_known": sum(r["provider_tokens_known"] for r in reports),
                "usage_missing": sum(r["usage_missing_attempts"] for r in reports),
            }
    atomic_json(root / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    compare(parser.parse_args().root)
