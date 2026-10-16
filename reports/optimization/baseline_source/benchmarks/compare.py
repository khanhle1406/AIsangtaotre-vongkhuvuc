"""Budgeted configuration comparison; select using tuning, evaluate holdout once."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from evaluate import read_answers
from run import run_queries, validate_queries
from src.llm_agent import BudgetLedger, LLMAgent, get_pricing

from .fixtures import generate_fixtures


def source_hash() -> str:
    digest = hashlib.sha256()
    base = Path(__file__).resolve().parents[1]
    for path in [base / "run.py", *sorted((base / "src").glob("*.py"))]:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def score(output: Path, references: dict[str, str]) -> dict[str, Any]:
    predictions = read_answers(output)
    expected = {key: references[key] for key in predictions}
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
    prior = sum(
        json.loads(path.read_text())["cost_usd"]
        for path in Path("reports").rglob("*.metrics.json")
    )
    total = BudgetLedger(0.5, spent=prior)
    pricing = get_pricing("qwen/qwen3.7-flash")
    references = read_answers(references_path)
    all_queries = validate_queries(queries_path, input_dir)
    if {str(item["id"]) for item in all_queries} != references.keys():
        raise ValueError("Reference IDs do not match queries")
    if tuning_path is None and Path("reports/tuning/queries.json").is_file():
        tuning_path = Path("reports/tuning/queries.json")
    if tuning_path is not None:
        tune = validate_queries(tuning_path, input_dir)
    else:
        files = sorted(
            {item["file_name"] for item in all_queries},
            key=lambda name: hashlib.sha256(name.encode()).hexdigest(),
        )
        held = set(files[: max(1, len(files) // 5)]) if len(files) > 1 else set()
        tune = [item for item in all_queries if item["file_name"] not in held]
    (root / "tuning_queries.json").write_text(
        json.dumps(tune, ensure_ascii=False, indent=2), encoding="utf8"
    )
    candidates = []
    before = total.spent
    digest = source_hash()
    for label, reasoning, output_tokens in [("low", 256, 2048), ("high", 1024, 4096)]:
        stage = BudgetLedger(
            min(0.125, 0.25 - (total.spent - before), 0.5 - total.spent)
        )
        client = LLMAgent(
            ledger=stage,
            pricing=pricing,
            reasoning_tokens=reasoning,
            max_tokens=output_tokens,
            deadline=time.monotonic() + 600,
        )
        output = root / f"{label}.csv"
        metrics = run_queries(input_dir, tune, output, client)
        total.spent += stage.spent
        candidates.append(
            {"label": label, **score(output, references), "metrics": metrics}
        )
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
    # Configuration is frozen before either unseen synthetic or reserved public workbook evaluation.
    client = LLMAgent(
        ledger=BudgetLedger(min(0.10, 0.5 - total.spent)),
        pricing=pricing,
        reasoning_tokens=chosen_metrics["reasoning_tokens"],
        max_tokens=chosen_metrics["max_tokens"],
        deadline=time.monotonic() + 600,
    )
    public_output = root / "public.csv"
    public_metrics = run_queries(input_dir, all_queries, public_output, client)
    total.spent += client.ledger.spent
    fixtures, answers = generate_fixtures(root / "holdout", seed=seed)
    client = LLMAgent(
        ledger=BudgetLedger(min(0.10, 0.5 - total.spent)),
        pricing=pricing,
        reasoning_tokens=chosen_metrics["reasoning_tokens"],
        max_tokens=chosen_metrics["max_tokens"],
        deadline=time.monotonic() + 600,
    )
    hold_output = root / "holdout.csv"
    hold_metrics = run_queries(
        fixtures.parent / "xlsx_files",
        validate_queries(fixtures, fixtures.parent / "xlsx_files"),
        hold_output,
        client,
    )
    total.spent += client.ledger.spent
    report = {
        "source_sha256": digest,
        "initial_exploratory_cost_usd": prior,
        "candidates": candidates,
        "selected": chosen["label"],
        "public": {
            "score": score(public_output, references),
            "metrics": public_metrics,
        },
        "synthetic_holdout": {
            "score": score(hold_output, read_answers(answers)),
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
