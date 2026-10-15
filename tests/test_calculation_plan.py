"""Independent arithmetic oracles and source-preserving compiler transformations."""

import datetime as dt
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from openpyxl.utils import get_column_letter

from benchmarks.gateway import BatchLimits
from benchmarks.packed import CalculationPlanAgent, namespace_books
from benchmarks.plan_agent import schema_view
from src.calculation_plan import compile_plan
from src.excel_parser import CellData, SheetData, WorkbookData
from src.executor import execute_program
from src.llm_agent import Program


def run_plan(plan: dict[str, Any], book: WorkbookData, query: str = "") -> Any:
    program = Program.model_validate_json(compile_plan(plan, book.wire(), query))
    result = execute_program(program.code, book.wire())
    assert result.success, result.error
    return result


@pytest.mark.parametrize("offset", [0, 300])
@pytest.mark.parametrize("columns", [(1, 2, 3), (7, 12, 9)])
def test_rank_reads_only_selected_metric_after_relocation_and_column_permutation(
    offset: int, columns: tuple[int, int, int]
) -> None:
    label, measure, other = map(get_column_letter, columns)
    sheet = "Renamed data"
    cells = {
        f"{label}{offset + 1}": CellData("Entity", "string"),
        f"{measure}{offset + 1}": CellData("Nominal change", "string"),
        f"{other}{offset + 1}": CellData("Adjusted change", "string"),
    }
    values = [("ACME Inc.", -27, 9), ("Cedar", 14, 900), ("Birch", 2, 4)]
    for row, (name, target, noise) in enumerate(values, start=offset + 2):
        cells[f"{label}{row}"] = CellData(name, "string")
        cells[f"{measure}{row}"] = CellData(target, "number")
        cells[f"{other}{row}"] = CellData(noise, "number")
    book = WorkbookData({sheet: SheetData(sheet, cells=cells)})
    scan = {
        "op": "scan",
        "sheet": sheet,
        "rows": [offset + 2, offset + 4],
        "sort": {"op": "abs", "args": [{"col": measure}]},
        "descending": True,
        "take": [0, 1],
        "value": {"col": label, "kind": "text"},
    }
    plan = {"expr": {"op": "first", "args": [scan]}}
    result = run_plan(
        plan, book, 'Which entity has the largest absolute "Nominal change"?'
    )
    assert result.result == max(values, key=lambda row: abs(row[1]))[0]
    assert not any(address.startswith(sheet + "!" + other) for address in result.reads)
    wrong = json.loads(json.dumps(plan))
    wrong["expr"]["args"][0]["sort"]["args"][0]["col"] = other
    with pytest.raises(ValueError, match="contradicts quoted header"):
        compile_plan(
            wrong,
            book.wire(),
            'Which entity has the largest absolute "Nominal change"?',
        )


def test_compiled_date_rank_and_post_selection_aggregate() -> None:
    sheet = "Dates"
    values = [
        ("Birch", dt.datetime(2000, 1, 1), dt.datetime(2025, 1, 1), 41),
        ("Cedar", dt.datetime(2001, 1, 1), dt.datetime(2023, 1, 1), 83),
        ("Elm", dt.datetime(2002, 1, 1), dt.datetime(2028, 1, 1), 56),
    ]
    cells = {}
    for row, (name, birth, event, score) in enumerate(values, 2):
        for col, value, kind in [
            ("A", name, "string"),
            ("B", birth, "datetime"),
            ("C", event, "datetime"),
            ("D", score, "number"),
        ]:
            cells[f"{col}{row}"] = CellData(value, kind)
    book = WorkbookData({sheet: SheetData(sheet, cells=cells)})
    scan = {
        "op": "scan",
        "sheet": sheet,
        "rows": [2, 4],
        "sort": {
            "op": "days",
            "args": [
                {
                    "op": "sub",
                    "args": [
                        {"col": "C", "kind": "date"},
                        {"col": "B", "kind": "date"},
                    ],
                }
            ],
        },
        "take": [0, 2],
        "value": {"col": "D"},
    }
    result = run_plan({"expr": {"op": "max", "args": [scan]}}, book)
    expected = max(
        row[3] for row in sorted(values, key=lambda row: row[2] - row[1])[:2]
    )
    assert result.result == expected
    assert "Dates!D4" not in result.reads  # projected values read only AFTER rank/take


def test_compiled_filter_group_sum_and_literal_restrictions() -> None:
    book = WorkbookData(
        {
            "Moved": SheetData(
                "Moved",
                cells={
                    "A301": CellData("open", "string"),
                    "B301": CellData(13, "number"),
                    "A302": CellData("closed", "string"),
                    "B302": CellData(900, "number"),
                    "A303": CellData("open", "string"),
                    "B303": CellData(-4, "number"),
                },
            )
        }
    )
    plan = {
        "expr": {
            "op": "sum",
            "args": [
                {
                    "op": "scan",
                    "sheet": "Moved",
                    "rows": [301, 303],
                    "where": {
                        "op": "eq",
                        "args": [{"col": "A", "kind": "text"}, {"const": "open"}],
                    },
                    "value": {"col": "B"},
                }
            ],
        }
    }
    actual = run_plan(plan, book, 'Sum the measure for "open" records.')
    assert actual.result == 9 and "Moved!B302" not in actual.reads
    with pytest.raises(ValueError, match="must depend"):
        compile_plan({"expr": {"const": "Copied answer"}}, book.wire(), "")
    with pytest.raises(ValueError, match="stated in the question"):
        compile_plan(
            {
                "expr": {
                    "op": "mul",
                    "args": [{"cell": ["Moved", "B301"]}, {"const": 5000}],
                }
            },
            book.wire(),
            "",
        )


@pytest.mark.parametrize(
    "expr",
    [
        {"col": "B"},
        {"cell": ["Foreign", "B2"]},
        {"cell": ["Moved", "XFE1"]},
        {"cell": ["Moved", "B0"]},
        {"cell": ["Moved", "B2"], "code": "result=42"},
        {"op": "sum", "args": []},
        {"op": "invented", "args": [{"const": 1}]},
    ],
)
def test_invalid_or_foreign_plan_does_not_compile(expr: dict[str, Any]) -> None:
    with pytest.raises((ValueError, TypeError)):
        compile_plan({"expr": expr}, {"Moved": {"cells": {}}}, "")


def test_missing_formula_cache_is_never_zero_and_merged_numeric_not_duplicated() -> (
    None
):
    book = WorkbookData(
        {
            "Moved": SheetData(
                "Moved",
                cells={
                    "C301": CellData(23, "number"),
                    "D301": CellData(
                        None, "uncached_formula", formula="=UNSUPPORTED(C301)"
                    ),
                },
                merges=["C301:C302"],
            )
        }
    )
    for address in ["C302", "D301"]:
        program = Program.model_validate_json(
            compile_plan({"expr": {"cell": ["Moved", address]}}, book.wire(), "")
        )
        result = execute_program(program.code, book.wire())
        assert not result.success


def test_header_citation_checked_against_original_table() -> None:
    book = WorkbookData(
        {
            "Moved": SheetData(
                "Moved",
                cells={
                    "B1": CellData("Measure", "string"),
                    "A2": CellData("Entity", "string"),
                    "B2": CellData(17, "number"),
                },
            )
        }
    )
    assert (
        run_plan(
            {"expr": {"cell": ["Moved", "B2"], "header": ["Measure"]}}, book
        ).result
        == 17
    )
    with pytest.raises(ValueError, match="Header path disagrees"):
        compile_plan(
            {"expr": {"cell": ["Moved", "B2"], "header": ["Different"]}},
            book.wire(),
            "",
        )


def test_schema_view_keeps_metadata_and_discloses_full_backend() -> None:
    book = WorkbookData(
        {
            "Moved": SheetData(
                "Moved",
                cells={
                    "F301": CellData("Measure (%)", "string"),
                    "G302": CellData(-91824.25, "number", number_format="0.00%"),
                    "F302": CellData("ACME Inc.", "string"),
                    "H302": CellData(None, "uncached_formula", formula="=G302*2"),
                },
                merges=["F301:G301"],
                hidden_rows=[302],
            )
        }
    )
    before = book.wire()
    view = schema_view(book)
    assert "-91824.25" not in view
    for text in [
        "G302",
        "0.00%",
        "ACME Inc.",
        "F301:G301",
        "=G302*2",
        '"hidden_rows":[302]',
        "not blanks/zero",
    ]:
        assert text in view
    assert "ALL stored cells follow" not in view
    assert book.wire() == before
    assert execute_program("result=num('Moved','G302')", before).result == -91824.25


def test_expression_envelope_ownership_repair_budget_and_unchanged_python_fallback(
    tmp_path: Path,
) -> None:
    agent = CalculationPlanAgent(
        api_key="test-placeholder",
        gateway_url="https://gateway.invalid/v1",
        gateway_model="ag/gemini-3-flash",
        batch_limits=BatchLimits(tmp_path / "batch.json"),
    )
    source = WorkbookData(
        {"Data": SheetData("Data", cells={"B2": CellData(17, "number")})}
    )
    book = namespace_books({"left.xlsx": source, "right.xlsx": source})
    questions = [
        {"id": "renamed-a", "file_name": "left.xlsx", "query": "Read the value."},
        {"id": "renamed-b", "file_name": "right.xlsx", "query": "Read the value."},
    ]
    response = json.dumps(
        {
            "plans": {
                "q0": {"expr": {"cell": ["W0::Data", "B2"]}},
                "q1": {"expr": {"cell": ["W0::Data", "B2"]}},
            }
        }
    )
    programs = agent.parse_programs(response, book, questions)
    assert Program.model_validate_json(programs[0]).code
    assert "foreign" in json.loads(programs[1])["planning_error"]
    for malformed in [
        '{"plans":{"q0":{},"q0":{}}}',
        '{"plans":{"q0":{}}}',
        '{"plans":{"q1":{},"q0":{}},"extra":true}',
    ]:
        with pytest.raises(ValueError):
            agent.parse_programs(malformed, book, questions)
    messages = agent.planning_messages(book, questions, "unused full view")
    assert '"plans"' in messages[0]["content"]
    assert "code STRING" not in messages[0]["content"]
    assert '"allowed_sheets": ["W0::Data"]' in messages[1]["content"]
    output = io_response({"plans": {"q0": {"defer": True}}})
    repair = io_response(
        {"code": "result=num('W0::Data','B2')", "format": {"kind": "integer"}}
    )
    with patch(
        "benchmarks.gateway.GatewayAgent._open_request", side_effect=[output, repair]
    ) as request:
        records, event = agent.solve_group(book, questions[:1])
    assert records[0]["answer"] == "17" and len(records[0]["calls"]) == 2
    assert len(event["calls"]) == 1 and request.call_count == 2
    assert records[0]["calls"][0]["shared_questions"] == 1


def io_response(content: dict[str, Any]) -> Any:
    import io

    response = io.BytesIO(
        json.dumps(
            {
                "model": "ag/gemini-3-flash",
                "choices": [
                    {
                        "message": {"content": json.dumps(content)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 30,
                    "total_tokens": 130,
                },
            }
        ).encode()
    )

    response.headers = {"Content-Type": "application/json"}
    return response


def test_limits_are_checked_before_worker_execution() -> None:
    from src.executor import MAX_ITEMS

    base = {
        "op": "scan",
        "sheet": "Moved",
        "rows": [1, MAX_ITEMS + 1],
        "value": {"col": "B"},
    }
    with pytest.raises(ValueError, match="bounded inclusive"):
        compile_plan({"expr": base}, {"Moved": {"cells": {}}}, "")
    nested: dict[str, Any] = {"cell": ["Moved", "B2"]}
    for _ in range(18):
        nested = {"op": "abs", "args": [nested]}
    with pytest.raises(ValueError, match="complexity"):
        compile_plan({"expr": nested}, {"Moved": {"cells": {}}}, "")


def test_compound_derived_metric_not_rejected_as_a_reported_header() -> None:
    book = WorkbookData(
        {
            "Moved": SheetData(
                "Moved",
                cells={
                    "A1": CellData("Entity", "string"),
                    "B1": CellData("Net amount", "string"),
                    "C1": CellData("Gross", "string"),
                    "D1": CellData("Expense", "string"),
                    "A2": CellData("Cedar", "string"),
                    "B2": CellData(6, "number"),
                    "C2": CellData(15, "number"),
                    "D2": CellData(9, "number"),
                },
            )
        }
    )
    scan = {
        "op": "scan",
        "sheet": "Moved",
        "rows": [2, 2],
        "sort": {"op": "sub", "args": [{"col": "C"}, {"col": "D"}]},
        "value": {"col": "A", "kind": "text"},
    }
    assert run_plan(
        {"expr": scan}, book, 'Rank by "Net amount", calculated as gross minus expense.'
    ).result == ["Cedar"]


def test_multisheet_capability_routing_uses_existing_python_contract(
    tmp_path: Path,
) -> None:
    agent = CalculationPlanAgent(
        api_key="test-placeholder",
        gateway_url="https://gateway.invalid/v1",
        gateway_model="ag/gemini-3-flash",
        batch_limits=BatchLimits(tmp_path / "batch.json"),
    )
    source = WorkbookData(
        {
            "Left": SheetData("Left", cells={"B2": CellData(7, "number")}),
            "Right": SheetData("Right", cells={"B2": CellData(11, "number")}),
        }
    )
    book = namespace_books({"renamed.xlsx": source})
    questions = [
        {"id": "arbitrary", "file_name": "renamed.xlsx", "query": "Sum both measures."}
    ]
    messages = agent.planning_messages(book, questions, "full original view")
    assert (
        '"programs"' in messages[1]["content"]
        and "full original view" in messages[1]["content"]
    )
    response = io_response(
        {
            "programs": {
                "q0": {
                    "code": "result=num('W0::Left','B2')+num('W0::Right','B2')",
                    "format": {"kind": "integer"},
                }
            }
        }
    )
    with patch(
        "benchmarks.gateway.GatewayAgent._open_request", return_value=response
    ) as request:
        records, _ = agent.solve_group(book, questions)
    assert records[0]["answer"] == "18" and request.call_count == 1


@pytest.mark.parametrize("kind", ["integer", "text"])
def test_rank_cannot_be_replaced_by_a_guessed_output_cell(kind: str) -> None:
    book = WorkbookData(
        {
            "New": SheetData(
                "New",
                cells={"A2": CellData("Cedar", "string"), "B2": CellData(17, "number")},
            )
        }
    )
    with pytest.raises(ValueError, match="guessed output cell"):
        compile_plan(
            {
                "expr": {
                    "cell": ["New", "B2" if kind == "integer" else "A2"],
                    "kind": "number" if kind == "integer" else "text",
                },
                "format": {"kind": kind},
            },
            book.wire(),
            "What did the second-highest entity receive?",
        )
    # Direct published-field lookups remain available without a guessed rank.
    assert (
        run_plan(
            {"expr": {"cell": ["New", "B2"]}}, book, "What is the value for Cedar?"
        ).result
        == 17
    )


def test_age_group_rank_needs_both_date_fields_in_sort_not_just_a_max_score(
    tmp_path: Path,
) -> None:
    sheet = SheetData(
        "New",
        cells={
            "A1": CellData("Entity", "string"),
            "B1": CellData("Birth date", "string"),
            "C1": CellData("Admission date", "string"),
            "D1": CellData("Score", "string"),
            "A2": CellData("Cedar", "string"),
            "B2": CellData(dt.datetime(2001, 1, 1), "datetime"),
            "C2": CellData(dt.datetime(2025, 1, 1), "datetime"),
            "D2": CellData(71, "number"),
        },
    )
    book = WorkbookData({"New": sheet})
    agent = CalculationPlanAgent(
        api_key="test-placeholder",
        gateway_url="https://gateway.invalid/v1",
        gateway_model="ag/gemini-3-flash",
        batch_limits=BatchLimits(tmp_path / "batch.json"),
    )
    owned = namespace_books({"new.xlsx": book})
    messages = agent.planning_messages(
        owned,
        [
            {
                "id": "arbitrary",
                "file_name": "new.xlsx",
                "query": "Who is youngest at admission?",
            }
        ],
        "ignored original view",
    )
    assert "QUESTION DATE INTERPRETATION" in messages[1]["content"]
    assert "'B','C'" in messages[1]["content"]
    scan = {
        "op": "scan",
        "sheet": "New",
        "rows": [2, 2],
        "sort": {"col": "B", "kind": "date"},
        "value": {"col": "D"},
    }
    with pytest.raises(ValueError, match="birth AND reference"):
        compile_plan(
            {"expr": {"op": "max", "args": [scan]}},
            book.wire(),
            "Among the youngest people, what is the maximum score?",
        )
    scan["sort"] = {
        "op": "days",
        "args": [
            {
                "op": "sub",
                "args": [{"col": "C", "kind": "date"}, {"col": "B", "kind": "date"}],
            }
        ],
    }
    assert (
        run_plan(
            {"expr": {"op": "max", "args": [scan]}},
            book,
            "Among the youngest people, what is the maximum score?",
        ).result
        == 71
    )


def test_complete_numeric_ranges_preserve_row_major_shape_and_original_cells() -> None:
    book = WorkbookData(
        {
            "New": SheetData(
                "New",
                cells={
                    "C301": CellData(9, "number"),
                    "D301": CellData(-4, "number"),
                    "C302": CellData(18, "number"),
                    "D302": CellData(1, "number"),
                },
            )
        }
    )
    plan = {"expr": {"op": "mean", "args": [{"range": ["New", "C301:D302"]}]}}
    result = run_plan(plan, book)
    assert result.result == 6 and set(result.reads) == {
        "New!C301",
        "New!D301",
        "New!C302",
        "New!D302",
    }
    assert run_plan({"expr": {"range": ["New", "C301"]}}, book).result == [9]
    for area in ["D302:C301", "A1:XFD1048576", "A1:XFE1", "B0:B5"]:
        with pytest.raises(ValueError):
            compile_plan({"expr": {"range": ["New", area]}}, book.wire(), "")
