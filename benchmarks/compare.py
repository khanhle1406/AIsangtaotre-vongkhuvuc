"""Budgeted configuration comparison; select using tuning, evaluate holdout once."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from evaluate import read_answers
from run import run_queries, validate_queries, write_submission
from src.llm_agent import BudgetLedger, LLMAgent, get_pricing

from .budget import workspace_budget
from .fixtures import generate_fixtures


def source_hash() -> str:
    digest = hashlib.sha256()
    base = Path(__file__).resolve().parents[1]
    for path in [base / "run.py", *sorted((base / "src").glob("*.py"))]:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def score(
    output: Path, references: dict[str, str], expected_ids: set[str]
) -> dict[str, Any]:
    predictions = read_answers(output)
    if predictions.keys() != expected_ids:
        raise ValueError("Prediction IDs do not match this experiment's queries")
    if not expected_ids or not expected_ids <= references.keys():
        raise ValueError("Missing reference answers or empty experiment")
    expected = {key: references[key] for key in expected_ids}
    correct = sum(predictions[key] == answer for key, answer in expected.items())
    return {
        "correct": correct,
        "total": len(expected),
        "errors": {
            key: {"prediction": predictions[key], "reference": answer}
            for key, answer in expected.items()
            if predictions[key] != answer
        },
    }


def tuning_queries(
    all_queries: list[dict[str, Any]], input_dir: Path, tuning_path: Path | None
) -> list[dict[str, Any]]:
    family_by_file: dict[str, str] = {}
    for item in all_queries:
        family = item.get("family", item["file_name"])
        if not isinstance(family, str) or not family:
            raise ValueError("Benchmark family must be a nonempty string")
        if family_by_file.setdefault(item["file_name"], family) != family:
            raise ValueError(
                "One workbook cannot belong to different benchmark families"
            )
    if tuning_path is not None:
        tune = validate_queries(tuning_path, input_dir)
        known = {str(item["id"]): item for item in all_queries}
        if not tune or any(known.get(str(item["id"])) != item for item in tune):
            raise ValueError("Tuning queries must belong to the current dataset")
        selected_families = {family_by_file[item["file_name"]] for item in tune}
        if {str(item["id"]) for item in tune} != {
            str(item["id"])
            for item in all_queries
            if family_by_file[item["file_name"]] in selected_families
        }:
            raise ValueError("A workbook/family cannot straddle tuning and holdout")
        return tune
    files = sorted(
        set(family_by_file.values()),
        key=lambda name: hashlib.sha256(name.encode()).hexdigest(),
    )
    held = set(files[: max(1, len(files) // 5)]) if len(files) > 1 else set()
    return [
        item for item in all_queries if family_by_file[item["file_name"]] not in held
    ]


def compare(
    root: Path,
    seed: int,
    input_dir: Path = Path("data/xlsx_files"),
    queries_path: Path = Path("data/queries.json"),
    references_path: Path = Path("data/sample_submission.csv"),
    tuning_path: Path | None = None,
) -> None:
    if root.exists():
        raise ValueError(
            "Preserve prior benchmark evidence: use a new output directory"
        )
    root.mkdir(parents=True)
    budget = workspace_budget()
    prior = 0.5 - budget.remaining
    total = BudgetLedger(0.5, spent=prior)
    pricing = get_pricing("qwen/qwen3.7-flash")
    references = read_answers(references_path)
    all_queries = validate_queries(queries_path, input_dir)
    if {str(item["id"]) for item in all_queries} != references.keys():
        raise ValueError("Reference IDs do not match queries")
    tune = tuning_queries(all_queries, input_dir, tuning_path)
    (root / "tuning_queries.json").write_text(
        json.dumps(tune, ensure_ascii=False, indent=2), encoding="utf8"
    )
    candidates = []
    before = total.spent
    digest = source_hash()
    for label, reasoning, output_tokens in [("low", 256, 2048), ("high", 1024, 4096)]:
        output = root / f"{label}.csv"
        with budget.stage(
            str(output.resolve()),
            min(0.05, 0.10 - (total.spent - before), budget.remaining),
        ) as stage:
            client = LLMAgent(
                ledger=stage,
                pricing=pricing,
                reasoning_tokens=reasoning,
                max_tokens=output_tokens,
                deadline=time.monotonic() + 600,
            )
            metrics = run_queries(input_dir, tune, output, client)
        total.spent += stage.spent
        candidates.append(
            {
                "label": label,
                **score(output, references, {str(q["id"]) for q in tune}),
                "metrics": metrics,
            }
        )
        if client.fatal_error:
            raise RuntimeError(client.fatal_error)
    chosen = min(
        candidates,
        key=lambda item: (
            -item["correct"],
            item["metrics"]["elapsed_seconds"],
            item["metrics"]["tokens"],
        ),
    )
    chosen_metrics = chosen["metrics"]
    (root / "selection.json").write_text(
        json.dumps(
            {
                "source_sha256": digest,
                "candidates": candidates,
                "selected": chosen["label"],
            },
            indent=2,
        )
    )
    # Configuration is frozen before evaluation; regenerated known families are
    # validation, not an unbiased estimate of private-test accuracy.
    public_output = root / "public.csv"
    with budget.stage(
        str(public_output.resolve()), min(0.045, budget.remaining)
    ) as stage:
        client = LLMAgent(
            ledger=stage,
            pricing=pricing,
            reasoning_tokens=chosen_metrics["reasoning_tokens"],
            max_tokens=chosen_metrics["max_tokens"],
            deadline=time.monotonic() + 600,
        )
        public_metrics = run_queries(input_dir, all_queries, public_output, client)
    total.spent += client.ledger.spent
    if client.fatal_error:
        raise RuntimeError(client.fatal_error)
    tuning_ids = {str(item["id"]) for item in tune}
    held_queries = [item for item in all_queries if str(item["id"]) not in tuning_ids]
    held_score = None
    if held_queries:
        held_output = root / "reserved_public.csv"
        write_submission(held_output, held_queries, read_answers(public_output))
        held_score = score(
            held_output, references, {str(item["id"]) for item in held_queries}
        )
    fixtures, answers = generate_fixtures(root / "holdout", seed=seed)
    hold_output = root / "holdout.csv"
    hold_queries = validate_queries(fixtures, fixtures.parent / "xlsx_files")
    with budget.stage(
        str(hold_output.resolve()), min(0.045, budget.remaining)
    ) as stage:
        client = LLMAgent(
            ledger=stage,
            pricing=pricing,
            reasoning_tokens=chosen_metrics["reasoning_tokens"],
            max_tokens=chosen_metrics["max_tokens"],
            deadline=time.monotonic() + 600,
        )
        hold_metrics = run_queries(
            fixtures.parent / "xlsx_files", hold_queries, hold_output, client
        )
    total.spent += client.ledger.spent
    report = {
        "source_sha256": digest,
        "initial_exploratory_cost_usd": prior,
        "candidates": candidates,
        "selected": chosen["label"],
        "public": {
            "score": score(
                public_output, references, {str(q["id"]) for q in all_queries}
            ),
            "metrics": public_metrics,
        },
        "reserved_public_workbooks": held_score,
        "evaluation_note": "Full public includes tuning; reserved_public excludes tuning families. Generated synthetic families have informed earlier debugging; fresh values are validation, not an unbiased private estimate.",
        "synthetic_holdout": {
            "score": score(
                hold_output, read_answers(answers), {str(q["id"]) for q in hold_queries}
            ),
            "metrics": hold_metrics,
        },
        "total_development_cost_upper_usd": total.spent,
        "budget_usd": total.limit,
    }
    (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=Path("reports/controlled"))
    parser.add_argument("--seed", type=int, default=8117)
    parser.add_argument("--input-dir", type=Path, default=Path("data/xlsx_files"))
    parser.add_argument("--queries", type=Path, default=Path("data/queries.json"))
    parser.add_argument(
        "--references", type=Path, default=Path("data/sample_submission.csv")
    )
    parser.add_argument("--tuning-queries", type=Path, default=None)
    args = parser.parse_args()
    compare(
        args.report_dir,
        args.seed,
        args.input_dir,
        args.queries,
        args.references,
        args.tuning_queries,
    )
