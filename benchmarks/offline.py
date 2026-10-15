"""Paired defect regressions and prompt measurements; never a live LLM score."""

import importlib
import json
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

from evaluate import read_answers
from src import executor, llm_agent, verification
from src.excel_parser import CellData, SheetData, WorkbookData, load_workbook_data
from src.postprocessor import AnswerFormat, format_answer

from .compare import source_hash


@dataclass
class Case:
    name: str
    workbook: WorkbookData
    query: str
    code: str
    expected: float | str


def make_sheet(
    name: str, values: dict[str, Any], merges: list[str] | None = None
) -> SheetData:
    sheet = SheetData(name, merges=merges or [])
    for address, value in values.items():
        formula = value if isinstance(value, str) and value.startswith("=") else None
        sheet.cells[address] = CellData(
            None if formula else value,
            "uncached_formula"
            if formula
            else "string"
            if isinstance(value, str)
            else "number",
            formula=formula,
        )
    return sheet


def defect_cases(seed: int = 66139) -> list[Case]:
    """Independent arithmetic oracles; cases target known defects, not private accuracy."""
    rng = random.Random(seed)
    cases = []
    a, b, c, d = (rng.randrange(10, 90) for _ in range(4))
    base = {
        "A1": "Metric",
        "B1": "North",
        "D1": "South",
        "B2": "Level A",
        "C2": "Level B",
        "D2": "Level A",
        "E2": "Level B",
        "A3": "Rate",
        "B3": a,
        "C3": b,
        "D3": c + 500,
        "E3": d + 500,
    }
    sheet = make_sheet("Groups", base, ["B1:C1", "D1:E1"])
    cases.append(
        Case(
            "named_header_branch",
            WorkbookData({"Groups": sheet}),
            "Average Rate across all levels for North.",
            "result=sum(values('Groups','B3:C3'))/2",
            (a + b) / 2,
        )
    )
    base = {
        **base,
        "G1": "Separate report",
        "G2": "Metric",
        "H2": "Sample size",
        "G3": "Rate",
        "H3": rng.randrange(1000, 9000),
    }
    sheet = make_sheet("Groups", base, ["B1:C1", "D1:E1"])
    cases.append(
        Case(
            "adjacent_table_same_metric",
            WorkbookData({"Groups": sheet}),
            "Average Rate across all levels for North in the primary report.",
            "result=sum(values('Groups','B3:C3'))/2",
            (a + b) / 2,
        )
    )
    for label in ("Record ID", "Sample size", "Weight", "Denominator"):
        sheet = make_sheet(
            "Measures",
            {
                "A1": "Metric",
                "B1": "Level A",
                "C1": "Level B",
                "D1": label,
                "A2": "Rate",
                "B2": a,
                "C2": b,
                "D2": rng.randrange(1000, 9000),
            },
        )
        cases.append(
            Case(
                f"exclude_{label.lower().replace(' ', '_')}",
                WorkbookData({"Measures": sheet}),
                "Average Rate across all levels.",
                "result=sum(values('Measures','B2:C2'))/2",
                (a + b) / 2,
            )
        )
    sheet = make_sheet(
        "Fiscal",
        {
            "A1": "Metric",
            "B1": "FY 2024",
            "D1": "FY 2025",
            "B2": "Level A",
            "C2": "Level B",
            "D2": "Level A",
            "E2": "Level B",
            "A3": "Rate",
            "B3": c,
            "C3": d,
            "D3": a,
            "E3": b,
        },
        ["B1:C1", "D1:E1"],
    )
    cases.append(
        Case(
            "year_inside_header_label",
            WorkbookData({"Fiscal": sheet}),
            "Average Rate across all levels in 2025.",
            "result=num('Fiscal','D3')",
            (a + b) / 2,
        )
    )
    for formula, expected, name in [
        ("=SUM('Input data'!A1:A2,B2)", a + b + c, "cross_sheet_aggregate"),
        ("='Input data'!$A$1+B2", a + c, "cross_sheet_absolute_reference"),
        ("=SUM(B2,4,6)", c + 10, "multi_argument_sum"),
        ("=AVERAGE(B2,4,6)", (c + 10) / 3, "multi_argument_average"),
    ]:
        book = WorkbookData(
            {
                "Report": make_sheet("Report", {"B2": c, "B3": formula}),
                "Input data": make_sheet("Input data", {"A1": a, "A2": b}),
            }
        )
        cases.append(
            Case(
                name,
                book,
                "Return the computed value.",
                "result=cell('Report','B3')",
                expected,
            )
        )
    book = WorkbookData({"S": make_sheet("S", {"A1": a, "A2": "=A1+100"})})
    cases.append(
        Case(
            "extrema_includes_uncached_formula",
            book,
            "Return the maximum cell address.",
            "result=argmax('S','A1:A2')",
            "A2",
        )
    )
    for name, code, expected in [
        ("control_lookup", "result=num('S','A1')", a),
        ("control_sum", "result=sum(values('S','A1:A2'))", a + b),
        ("control_difference", "result=num('S','A1')-num('S','A2')", a - b),
        ("control_cached_max", "result=argmax('S','A1:A2')", "A1" if a >= b else "A2"),
    ]:
        cases.append(
            Case(
                name,
                WorkbookData({"S": make_sheet("S", {"A1": a, "A2": b})}),
                "Return the computed value.",
                code,
                expected,
            )
        )
    return cases


def baseline_modules(
    snapshot: Path,
) -> tuple[ModuleType, ModuleType, ModuleType, ModuleType]:
    package = ModuleType("optimization_baseline")
    package.__path__ = [str(snapshot / "src")]
    sys.modules[package.__name__] = package
    return tuple(
        importlib.import_module(f"{package.__name__}.{name}")
        for name in ("executor", "verification", "llm_agent", "excel_parser")
    )


def run_cases(
    cases: list[Case], engine: ModuleType, checks: ModuleType
) -> dict[str, Any]:
    rows = []
    for case in cases:
        wire = case.workbook.wire()
        execution = engine.execute_program(case.code, wire)
        if execution.success:
            correction = checks.complete_mean_contract(wire, execution, case.query)
            if correction is not None:
                execution = engine.execute_program(correction, wire)
        rows.append(
            {
                "name": case.name,
                "correct": execution.success and execution.result == case.expected,
                "result": execution.result,
                "expected": case.expected,
                "error": execution.error,
            }
        )
    return {
        "correct": sum(row["correct"] for row in rows),
        "total": len(rows),
        "cases": rows,
    }


def replay_public() -> dict[str, Any]:
    queries = json.loads(Path("data/queries.json").read_text())
    references = read_answers("data/sample_submission.csv")
    recorded = {
        f"p4_q{int(row['id'].rsplit('-', 1)[1]):03d}": row
        for line in Path("reports/relocated.trace.jsonl").read_text().splitlines()
        if (row := json.loads(line))
    }
    rows = []
    for query in queries:
        wire = load_workbook_data(Path("data/xlsx_files") / query["file_name"]).wire()
        attempt = next(
            item
            for item in reversed(recorded[query["id"]]["attempts"])
            if not item.get("error")
        )
        result = executor.execute_program(
            attempt["code"],
            wire,
            result_variable=attempt.get("result_variable", "result"),
        )
        correction = (
            verification.complete_mean_contract(wire, result, query["query"])
            or verification.complete_total_contract(wire, result, query["query"])
            if result.success
            else None
        )
        if correction:
            result = executor.execute_program(correction, wire)
        contradictions = []
        if result.success:
            contradictions = (
                llm_agent.selection_errors(wire, result.reads, query["query"])
                + verification.row_scope_errors(wire, result.reads, query["query"])
                + verification.aggregation_overlap_errors(
                    wire, result.reads, query["query"]
                )
                + verification.age_sort_errors(wire, result, query["query"])
                + verification.label_errors(result, query["query"])
                + verification.entity_label_errors(wire, result, query["query"])
            )
        answer = (
            format_answer(
                result.result,
                query["query"],
                AnswerFormat.model_validate(attempt.get("format", {})),
            )
            if result.success
            else ""
        )
        rows.append(
            {
                "id": query["id"],
                "correct": answer == references[str(query["id"])]
                and not contradictions,
                "answer": answer,
                "error": result.error,
                "contradictions": contradictions,
                "review_signals": verification.scope_risks(wire, result, query["query"])
                if result.success
                else [],
            }
        )
    return {
        "correct": sum(row["correct"] for row in rows),
        "total": len(rows),
        "cases": rows,
        "method": "Replay previously generated programs; no fresh LLM inference",
    }


def prompt_bytes(
    client_module: ModuleType, parser_module: ModuleType, compact: bool = False
) -> dict[str, Any]:
    queries = json.loads(Path("data/queries.json").read_text())
    cache = {}
    rows = []
    for query in queries:
        name = query["file_name"]
        if name not in cache:
            cache[name] = parser_module.load_workbook_data(
                Path("data/xlsx_files") / name
            )
        kwargs = {"compact_prompt": compact} if client_module is llm_agent else {}
        client = client_module.LLMAgent(
            "offline-placeholder", pricing=(1e-7, 1e-7), **kwargs
        )
        captured = []

        def capture(
            messages: list[dict[str, str]],
            _state: Any,
            collected: list[dict[str, str]] = captured,
        ) -> str:
            collected.extend(messages)
            raise client_module.BudgetExceeded("Offline measurement; no request")

        with patch.object(client, "_request", side_effect=capture):
            client.solve_workbook(cache[name], query["query"])
        rows.append(
            {
                "id": query["id"],
                "utf8_bytes": sum(
                    len(message["content"].encode()) for message in captured
                ),
            }
        )
    return {
        "total_utf8_bytes": sum(row["utf8_bytes"] for row in rows),
        "questions": rows,
        "note": "Exact prompt text bytes, NOT tokenizer counts or API latency",
    }


def main() -> None:
    root = Path("reports/optimization")
    old_engine, old_checks, old_client, old_parser = baseline_modules(
        root / "baseline_source"
    )
    cases = defect_cases()
    report = {
        "source_sha256": source_hash(),
        "paid_llm_calls": 0,
        "targeted_regressions_before": run_cases(cases, old_engine, old_checks),
        "targeted_regressions_after": run_cases(cases, executor, verification),
        "public_replay": replay_public(),
        "prompt_before": prompt_bytes(old_client, old_parser),
        "prompt_after_default": prompt_bytes(
            llm_agent, sys.modules[load_workbook_data.__module__]
        ),
        "prompt_after_compact_candidate": prompt_bytes(
            llm_agent, sys.modules[load_workbook_data.__module__], True
        ),
    }
    timings: dict[str, list[float]] = {"before": [], "after": []}
    for iteration in range(5):
        for label in ("before", "after") if iteration % 2 == 0 else ("after", "before"):
            started = time.perf_counter()
            for path in sorted(Path("data/xlsx_files").glob("*.xlsx")):
                if label == "before":
                    workbook = old_parser.load_workbook_data(path)
                    workbook.wire()
                    workbook.to_text()
                else:
                    workbook = load_workbook_data(path)
                    wire = workbook.wire()
                    workbook.to_text(metadata=wire)
            timings[label].append(time.perf_counter() - started)
    report["local_parse_and_render"] = {
        label: {"median_seconds": statistics.median(values), "samples_seconds": values}
        for label, values in timings.items()
    }
    (root / "offline.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                key: {k: v for k, v in value.items() if k not in {"cases", "questions"}}
                if isinstance(value, dict)
                else value
                for key, value in report.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
