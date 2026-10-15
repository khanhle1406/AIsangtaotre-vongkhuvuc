"""Labelled deterministic validation of stored programs; never counted as new generation."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from evaluate import read_answers
from run import validate_queries
from src.excel_parser import load_workbook_data
from src.llm_agent import LLMAgent

from .compare import source_hash
from .gateway import atomic_json


def replay(root: Path = Path("reports/optimization/precision_v2")) -> dict[str, Any]:
    proof = root / "frozen_proof"
    prior = Path("reports/optimization/gemini_gateway")
    old = Path("reports/optimization/frozen_holdout")
    sets = [
        (
            "public",
            Path("data/xlsx_files"),
            Path("data/queries.json"),
            Path("data/sample_submission.csv"),
            proof / "public/checkpoint.json",
        ),
        (
            "known_validation",
            old / "xlsx_files",
            old / "queries.json",
            old / "references.csv",
            proof / "known_validation/checkpoint.json",
        ),
        (
            "synthetic",
            prior / "synthetic/xlsx_files",
            prior / "synthetic/queries.json",
            prior / "synthetic/answers.csv",
            root / "final/synthetic/checkpoint.json",
        ),
        (
            "metamorphic",
            prior / "metamorphic/xlsx_files",
            prior / "metamorphic/queries.json",
            prior / "metamorphic/references.csv",
            proof / "metamorphic/checkpoint.json",
        ),
        (
            "public_mutation",
            root / "public_mutation_complete/xlsx_files",
            root / "public_mutation_complete/queries.json",
            root / "public_mutation_complete/references.csv",
            proof / "public_mutation/checkpoint.json",
        ),
        (
            "consumed_holdout_validation",
            root / "sealed_holdout/xlsx_files",
            root / "sealed_holdout/queries.json",
            root / "sealed_holdout/references.csv",
            proof / "candidate_fresh_holdout/checkpoint.json",
        ),
    ]
    report: dict[str, Any] = {
        "kind": "full pipeline replay of stored generated programs, NOT fresh LLM generation",
        "source_sha256": source_hash(),
        "new_llm_requests": 0,
        "sets": {},
    }
    for name, files, queries_path, refs, trace in sets:
        records = json.loads(trace.read_text())["records"]
        gold = read_answers(refs)
        results = []
        for question in validate_queries(queries_path, files):
            record = records[str(question["id"])]
            selected = next(
                attempt
                for attempt in reversed(record["attempts"])
                if attempt.get("code")
            )
            program = {
                key: selected[key]
                for key in [
                    "code",
                    "result_variable",
                    "format",
                    "assumptions",
                    "selection",
                ]
                if key in selected
            }
            agent = LLMAgent(
                "replay-placeholder", pricing=(0, 0), iterator_helpers=True
            )
            with patch.object(agent, "_request", return_value=json.dumps(program)):
                result = agent.solve_workbook(
                    load_workbook_data(files / question["file_name"]), question["query"]
                )
            results.append(
                {
                    "id": question["id"],
                    "answer": result.answer,
                    "correct": result.answer == gold[str(question["id"])],
                    "error": result.error,
                }
            )
        report["sets"][name] = {
            "correct": sum(r["correct"] for r in results),
            "total": len(results),
            "rows": results,
        }
        print(name, report["sets"][name]["correct"], len(results), flush=True)
    atomic_json(root / "post_holdout_replay.json", report)
    return report


if __name__ == "__main__":
    replay()
