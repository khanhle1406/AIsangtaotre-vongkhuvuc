"""Regression tests for dataset isolation, scope evidence and formula semantics."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from benchmarks.budget import DevelopmentBudget
from benchmarks.compare import score, tuning_queries
from src.excel_parser import CellData, SheetData, WorkbookData
from src.executor import execute_program
from src.llm_agent import BudgetExceeded, LLMAgent
from src.verification import (
    complete_mean_contract,
    evidence_errors,
    mean_scope_cells,
    row_scope_errors,
)


def scope_book(extra: str = "Population") -> WorkbookData:
    sheet = SheetData("Metrics")
    for address, value in {
        "A1": "Metric",
        "B1": "North",
        "D1": "South",
        "B2": "Level A",
        "C2": "Level B",
        "D2": "Level A",
        "E2": "Level B",
        "A3": "Rate",
        "B3": 10,
        "C3": 30,
        "D3": 500,
        "E3": 900,
        "H1": "Other report",
        "G2": "Metric",
        "H2": extra,
        "G3": "Rate",
        "H3": 10000,
    }.items():
        sheet.cells[address] = CellData(
            value, "string" if isinstance(value, str) else "number"
        )
    sheet.merges = ["B1:C1", "D1:E1"]
    return WorkbookData({sheet.name: sheet})


def test_benchmark_rejects_missing_extra_and_empty_predictions(tmp_path: Path) -> None:
    output = tmp_path / "out.csv"
    output.write_text("id,answer\na,1\n")
    assert score(output, {"a": "1", "b": "2"}, {"a"})["correct"] == 1
    with pytest.raises(ValueError, match="IDs"):
        score(output, {"a": "1", "b": "2"}, {"a", "b"})
    with pytest.raises(ValueError, match="IDs"):
        score(output, {"a": "1", "b": "2"}, {"b"})
    output.write_text("id,answer\n")
    with pytest.raises(ValueError):
        score(output, {}, set())


def test_tuning_cannot_load_another_dataset(tmp_path: Path) -> None:
    current = [{"id": "a", "file_name": "a.xlsx", "query": "Current?"}]
    path = tmp_path / "tuning.json"
    path.write_text(json.dumps([{**current[0], "query": "Old dataset?"}]))
    with pytest.raises(ValueError, match="current dataset"):
        tuning_queries(current, tmp_path, path)
    assert tuning_queries(current, tmp_path, None) == current


def test_persistent_budget_counts_interrupted_and_failed_runs(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    budget = DevelopmentBudget(path, initial_spent=0.2)
    with pytest.raises(RuntimeError), budget.stage("failed", 0.1) as ledger:
        # Reservation is persisted before a request can start.
        assert DevelopmentBudget(path, 0.2).remaining == pytest.approx(0.2)
        ledger.reserve(0.02)
        ledger.settle(0.02, 0.01)
        raise RuntimeError("interrupted experiment")
    assert budget.remaining == pytest.approx(0.29)
    with pytest.raises(BudgetExceeded), budget.stage("too-large", 0.3):
        pytest.fail("Must not enter a stage without sufficient budget")


def test_table_regions_keep_separate_headers_and_original_data() -> None:
    book = scope_book()
    wire = book.wire()["Metrics"]
    assert [table["range"] for table in wire["tables"]] == ["A1:E3", "G1:H3"]
    assert wire["tables"][0]["headers"]["B"] == ["North", "Level A"]
    assert wire["tables"][1]["headers"]["H"] == ["Other report", "Population"]
    for compact in (False, True):
        text = book.to_text(compact=compact)
        assert ("H3=" if compact else "H3<") in text and "10000" in text


def test_mean_stays_in_requested_branch_and_table() -> None:
    book = scope_book()
    sheet = book.wire()["Metrics"]
    # The duplicated metric label across separate tables is ambiguous: no rewrite.
    query = "Average Rate across all levels for North."
    assert mean_scope_cells(sheet, 3, query) is None
    del book.sheets["Metrics"].cells["G3"]
    sheet = book.wire()["Metrics"]
    assert mean_scope_cells(sheet, 3, query) == ["B3", "C3"]
    wire = book.wire()
    partial = execute_program("result=num('Metrics','B3')", wire)
    code = complete_mean_contract(wire, partial, query)
    assert code is not None
    assert execute_program(code, wire).result == 20
    full = execute_program("result=sum(values('Metrics','B3:C3'))/2", wire)
    assert complete_mean_contract(wire, full, query) is None
    assert not row_scope_errors(wire, full.reads, query)


@pytest.mark.parametrize("extra", ["Record ID", "Sample size", "Weight", "Denominator"])
def test_mean_never_adds_identity_or_weight_columns(extra: str) -> None:
    book = WorkbookData(
        {
            "S": SheetData(
                "S",
                cells={
                    "A1": CellData("Metric", "string"),
                    "B1": CellData("Level A", "string"),
                    "C1": CellData("Level B", "string"),
                    "D1": CellData(extra, "string"),
                    "A2": CellData("Rate", "string"),
                    "B2": CellData(1, "number"),
                    "C2": CellData(3, "number"),
                    "D2": CellData(1000, "number"),
                },
            )
        }
    )
    wire = book.wire()
    program = execute_program("result=sum(values('S','B2:C2'))/2", wire)
    assert (
        complete_mean_contract(wire, program, "Average Rate across all levels.") is None
    )
    assert not row_scope_errors(wire, program.reads, "Average Rate across all levels.")


def test_evidence_cannot_claim_cells_outside_actual_input() -> None:
    wire = scope_book().wire()
    execution = execute_program("result=num('Metrics','B3')", wire)
    assert not evidence_errors(
        wire, execution.reads, [{"sheet": "Metrics", "range": "A1:C3"}]
    )
    for selection in [
        {"sheet": "Missing", "range": "B3"},
        {"sheet": "Metrics", "range": "C3"},
        {"sheet": "Metrics", "range": "C3:B1"},
    ]:
        assert evidence_errors(wire, execution.reads, [selection])


def test_application_review_is_independent_of_model_flag() -> None:
    client = LLMAgent("unit-test-placeholder", pricing=(2e-7, 8e-7))
    program = json.dumps({"code": "result=sum(values('Metrics','B3:C3'))/2"})
    with patch.object(client, "_request", side_effect=[program, program]) as request:
        result = client.solve_workbook(
            scope_book(), "Average Rate across all levels for North."
        )
    assert result.answer == "20"
    assert request.call_count == 2
    second = request.call_args_list[1].args[0]
    assert all(message["role"] != "assistant" for message in second)
    assert "verification_triggers" in result.attempts[0]


@pytest.mark.parametrize(
    "text,expected",
    [("1,234.5", 1234.5), ("(1,234)", -1234), ("-.5", -0.5), ("1e3", 1000)],
)
def test_numeric_text_is_parsed_without_guessing(text: str, expected: float) -> None:
    book = WorkbookData({"S": SheetData("S", cells={"A1": CellData(text, "string")})})
    assert execute_program("result=num('S','A1')", book.wire()).result == expected


@pytest.mark.parametrize("text", ["1,2", "1.2.3", "1,23,456", "123,45"])
def test_ambiguous_numeric_text_is_rejected(text: str) -> None:
    book = WorkbookData({"S": SheetData("S", cells={"A1": CellData(text, "string")})})
    execution = execute_program("result=num('S','A1')", book.wire())
    assert not execution.success and "Ambiguous numeric" in execution.error


def test_cross_sheet_formula_multi_argument_aggregate_and_extrema() -> None:
    book = WorkbookData(
        {
            "Report": SheetData(
                "Report",
                cells={
                    "B2": CellData(3, "number"),
                    "B3": CellData(
                        None,
                        "uncached_formula",
                        formula="=SUM('Input data'!$A$1:$A$2,B2)",
                    ),
                },
            ),
            "Input data": SheetData(
                "Input data",
                cells={"A1": CellData(4, "number"), "A2": CellData(8, "number")},
            ),
        }
    )
    wire = book.wire()
    result = execute_program("result=cell('Report','B3')", wire)
    assert result.success and result.result == 15
    assert "Input data!A1" in result.reads
    assert execute_program("result=argmax('Report','B2:B3')", wire).result == "B3"
    book.sheets["Report"].cells["B3"].formula = "=VLOOKUP(B2,B2:B3,1)"
    assert not execute_program("result=argmax('Report','B2:B3')", book.wire()).success


def test_single_measure_tables_have_header_hints() -> None:
    book = WorkbookData(
        {
            "S": SheetData(
                "S",
                cells={
                    "A1": CellData("Name", "string"),
                    "B1": CellData("Value", "string"),
                    "A2": CellData("Alpha", "string"),
                    "B2": CellData(5, "number"),
                },
            )
        }
    )
    assert book.header_paths("S")["B"] == ["Value"]


def test_multiple_year_headers_and_year_sized_data_are_distinct() -> None:
    sheet = SheetData(
        "S",
        cells={
            "A1": CellData("Metric", "string"),
            "B1": CellData(2024, "number"),
            "C1": CellData(2025, "number"),
            "B2": CellData("North", "string"),
            "C2": CellData("South", "string"),
            "A3": CellData("Count", "string"),
            "B3": CellData(2000, "number"),
            "C3": CellData(2020, "number"),
        },
    )
    assert WorkbookData({"S": sheet}).header_paths("S")["C"] == ["2025", "South"]


def test_formula_quoted_sheet_name_cycles_and_excel_errors() -> None:
    report = SheetData(
        "Report",
        cells={
            "A1": CellData(None, "uncached_formula", formula="='O''Brien'!A1+2"),
            "A2": CellData(3, "number"),
        },
    )
    inputs = SheetData("O'Brien", cells={"A1": CellData(7, "number")})
    book = WorkbookData({"Report": report, "O'Brien": inputs})
    assert execute_program("result=cell('Report','A1')", book.wire()).result == 9
    inputs.cells["A1"] = CellData(None, "uncached_formula", formula="=Report!A1")
    assert (
        "Circular formula"
        in execute_program("result=cell('Report','A1')", book.wire()).error
    )
    report.cells["A1"] = CellData("#VALUE!", "error")
    assert (
        "Excel error"
        in execute_program("result=argmax('Report','A1:A2')", book.wire()).error
    )


def test_adaptive_reasoning_is_local_to_repair_not_other_queries() -> None:
    client = LLMAgent(
        "unit-test-placeholder", pricing=(2e-7, 8e-7), adaptive_reasoning=True
    )
    book = WorkbookData({"S": SheetData("S", cells={"A1": CellData(5, "number")})})
    seen = []

    def respond(_messages: list[dict[str, str]], state: object) -> str:
        from src.llm_agent import QueryState

        assert isinstance(state, QueryState)
        seen.append((state.reasoning_tokens, state.max_tokens))
        return "{}" if len(seen) == 1 else json.dumps({"code": "result=num('S','A1')"})

    with patch.object(client, "_request", side_effect=respond):
        assert client.solve_workbook(book, "Return the value.").answer == "5"
        assert client.solve_workbook(book, "Return the value.").answer == "5"
    assert seen == [(None, None), (1024, 4096), (None, None)]
    assert client.reasoning_tokens == 256 and client.max_tokens == 2048


def test_development_budget_serializes_experiments(tmp_path: Path) -> None:
    budget = DevelopmentBudget(tmp_path / "budget.json", 0)
    with (
        budget.stage("one", 0.1),
        pytest.raises(BlockingIOError),
        budget.stage("two", 0.1),
    ):
        pytest.fail("Concurrent experiments must not mutate a shared reservation")


def test_family_variants_cannot_straddle_tuning_and_holdout(tmp_path: Path) -> None:
    queries = [
        {"id": "one", "file_name": "one.xlsx", "query": "Value?", "family": "invoices"},
        {"id": "two", "file_name": "two.xlsx", "query": "Value?", "family": "invoices"},
        {
            "id": "three",
            "file_name": "three.xlsx",
            "query": "Value?",
            "family": "survey",
        },
    ]
    selected = tuning_queries(queries, tmp_path, None)
    ids = {row["id"] for row in selected}
    assert ("one" in ids) == ("two" in ids)
    path = tmp_path / "tuning.json"
    path.write_text(json.dumps([queries[0]]))
    with pytest.raises(ValueError, match="straddle"):
        tuning_queries(queries, tmp_path, path)


def test_entity_validation_ignores_unread_sheets() -> None:
    from src.verification import entity_label_errors

    def company(name: str, label: str) -> SheetData:
        return SheetData(
            name,
            cells={
                "A1": CellData("Company", "string"),
                "B1": CellData("Sales", "string"),
                "A2": CellData(label, "string"),
                "B2": CellData(7, "number"),
            },
        )

    book = WorkbookData(
        {"Current": company("Current", "Acme Inc."), "Old": company("Old", "Other Co.")}
    )
    wire = book.wire()
    execution = execute_program(
        "x=num('Current','B2')\nresult=label('Current','A2') if x>0 else ''", wire
    )
    assert not entity_label_errors(
        wire, execution, "Which sold most? Answer with only the company name."
    )


def test_totals_in_adjacent_table_do_not_label_other_table_rows() -> None:
    from src.verification import aggregation_overlap_errors, complete_total_contract

    sheet = SheetData(
        "S",
        cells={
            "A1": CellData("Region", "string"),
            "B1": CellData("Workers", "string"),
            "A2": CellData("Total", "string"),
            "B2": CellData(100, "number"),
            "A3": CellData("East", "string"),
            "B3": CellData(30, "number"),
            "D1": CellData("Region", "string"),
            "E1": CellData("Workers", "string"),
            "D2": CellData("North", "string"),
            "E2": CellData(20, "number"),
            "D3": CellData("South", "string"),
            "E3": CellData(40, "number"),
        },
    )
    wire = WorkbookData({"S": sheet}).wire()
    result = execute_program("result=sum(values('S','E2:E3'))", wire)
    query = "Calculate total workers across all regions in the right table."
    assert result.result == 60
    assert not aggregation_overlap_errors(wire, result.reads, query)
    assert complete_total_contract(wire, result, query) is None


def test_compact_prompt_preserves_native_types_and_semantic_formats() -> None:
    import datetime as dt

    book = WorkbookData(
        {
            "S": SheetData(
                "S",
                cells={
                    "A1": CellData("123", "string"),
                    "A2": CellData(123, "number"),
                    "A3": CellData(False, "boolean"),
                    "A4": CellData(
                        dt.datetime(2025, 1, 1), "datetime", number_format="yyyy-mm-dd"
                    ),
                    "A5": CellData(0.25, "number", number_format="0%"),
                    "A201": CellData(0, "number"),
                },
            )
        }
    )
    text = book.to_text(compact=True)
    assert 'A1="123"' in text and "A2=123" in text and "A3=false" in text
    assert 'A4<d;format=yyyy-mm-dd>="2025-01-01T00:00:00"' in text
    assert "A5<n;format=0%>=0.25" in text and "A201=0" in text


def test_large_workbook_uses_expandable_view_and_real_backend() -> None:
    book = WorkbookData(
        {
            "S": SheetData(
                "S",
                cells={
                    **{
                        f"A{row}": CellData("Long note " * 600, "string")
                        for row in range(1, 201)
                    },
                    "A201": CellData("Target", "string"),
                    "B201": CellData(42, "number"),
                },
            )
        }
    )
    client = LLMAgent("unit-test-placeholder", pricing=(2e-7, 8e-7))
    outputs = [
        json.dumps(
            {
                "code": "result=0",
                "request_regions": [{"sheet": "S", "range": "A201:B201"}],
            }
        ),
        json.dumps({"code": "result=num('S','B201')"}),
    ]
    with patch.object(client, "_request", side_effect=outputs) as request:
        result = client.solve_workbook(book, "Return the integer value for Target.")
    assert result.answer == "42" and request.call_count == 2
    initial = request.call_args_list[0].args[0][1]["content"]
    assert (
        "EXPANDABLE WORKBOOK VIEW" in initial
        and "omitted from this VIEW only" in initial
    )
    assert "context_request" in result.attempts[0]
    assert "B201" in result.attempts[0]["view"]


def test_region_inspection_rejects_excess_instead_of_partial_data() -> None:
    from src.context import inspect_regions

    wire = scope_book().wire()
    assert "B3" in inspect_regions(wire, [{"sheet": "Metrics", "range": "B3:C3"}])
    with pytest.raises(ValueError, match="no partial region"):
        inspect_regions(wire, [{"sheet": "Metrics", "range": "A1:H3"}], max_bytes=200)
    with pytest.raises(ValueError):
        inspect_regions(wire, [{"sheet": "Missing", "range": "A1"}])


def test_explicit_overall_section_keeps_unqualified_lookup_fast() -> None:
    from src.verification import scope_risks

    sheet = SheetData(
        "S",
        cells={
            "A1": CellData("Metric", "string"),
            "B1": CellData("Value", "string"),
            "A2": CellData("Total", "string"),
            "A3": CellData("Rate", "string"),
            "B3": CellData(7, "number"),
            "A4": CellData("North", "string"),
            "A5": CellData("Rate", "string"),
            "B5": CellData(9, "number"),
        },
    )
    wire = WorkbookData({"S": sheet}).wire()
    selected = execute_program("result=num('S','B3')", wire)
    assert not scope_risks(wire, selected, "Return Rate.")
    assert scope_risks(wire, selected, "Return Rate for North.")


def test_typed_row_selection_accepts_mixed_identity_and_measure() -> None:
    sheet = SheetData(
        "S",
        cells={
            "A1": CellData("Name", "string"),
            "B1": CellData("Change", "string"),
            "A2": CellData("North", "string"),
            "B2": CellData(3, "number"),
            "A3": CellData("South", "string"),
            "B3": CellData(-9, "number"),
            "A4": CellData("Footnote", "string"),
        },
    )
    wire = WorkbookData({"S": sheet}).wire()
    result = execute_program(
        "r=data_rows('S',{'A':'string','B':'number'})\nresult=sum(num('S','B'+str(i)) for i in r)",
        wire,
    )
    assert result.success and result.result == -6
    result = execute_program("result=argmax('S','B2:B4',absolute=True)", wire)
    assert result.success and result.result == "B3"


def test_explicit_guard_raise_is_supported_without_exception_swallowing() -> None:
    wire = WorkbookData(
        {"S": SheetData("S", cells={"A1": CellData(5, "number")})}
    ).wire()
    valid = "x=num('S','A1')\nif x<0:\n raise ValueError('Negative input')\nresult=x"
    assert execute_program(valid, wire).result == 5
    invalid = valid.replace("x<0", "x>0")
    result = execute_program(invalid, wire)
    assert not result.success and "Negative input" in result.error
    result = execute_program("raise RuntimeError('Explicit failure')", wire)
    assert not result.success and "Explicit failure" in result.error
