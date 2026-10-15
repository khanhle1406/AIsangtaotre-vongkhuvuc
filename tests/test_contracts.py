"""Task contracts use source structure and arithmetic intent, never sample answers."""

import datetime as dt
import json
from pathlib import Path

import openpyxl
import pytest

from src.contracts import (
    extremum_evidence_errors,
    header_count_errors,
    scale_conversion_errors,
    signed_comparison_errors,
)
from src.excel_parser import load_workbook_data
from src.executor import execute_program
from src.verification import scope_risks


def test_named_comparison_requires_both_actual_numeric_header_columns(
    tmp_path: Path,
) -> None:
    from src.verification import column_scope_errors

    book = openpyxl.Workbook()
    sheet = book.active
    for row, values in enumerate(
        [["Group", "Manufacturing", "Construction", "Other"], ["Young", 37, 61, 89]],
        407,
    ):
        for column, value in enumerate(values, 4):
            sheet.cell(row, column, value)
    path = tmp_path / "permuted.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    question = "For Young, what is the sum of Construction and Manufacturing?"
    wrong = execute_program("result=num('Sheet','F408')+num('Sheet','G408')", wire)
    right = execute_program("result=num('Sheet','E408')+num('Sheet','F408')", wire)
    assert column_scope_errors(wire, wrong, question)
    assert not column_scope_errors(wire, right, question)


def test_cross_sheet_difference_rank_requests_independent_semantic_review(
    tmp_path: Path,
) -> None:
    book = openpyxl.Workbook()
    charges = book.active
    charges.title = "Charges"
    charges.append(["Item", "Charge"])
    charges.append(["Rotor", 57])
    settled = book.create_sheet("Settlements")
    settled.append(["Item", "Paid"])
    settled.append(["Rotor", 13])
    path = tmp_path / "balances.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    code = (
        "owed=num('Charges','B2')-num('Settlements','B2'); result=cell('Charges','A2')"
    )
    execution = execute_program(code, wire)
    risks = scope_risks(
        wire, execution, "Which item has largest remaining balance?", code
    )
    assert any("subtraction direction" in risk for risk in risks)
    assert not scope_risks(wire, execution, "What is the Rotor name?", code)
    assert not scope_risks(
        wire,
        execution,
        "Each step adds Charge and subtracts Paid. Which item has largest remaining balance?",
        code,
    )


def test_flat_matrix_aggregate_can_finish_after_two_runtime_repairs(
    tmp_path: Path,
) -> None:
    from unittest.mock import patch

    from src.llm_agent import LLMAgent

    book = openpyxl.Workbook()
    sheet = book.active
    for row, values in enumerate(
        [
            ["Actual", "Predicted", "Count"],
            ["North", "North", 17],
            ["North", "East", 3],
            ["East", "North", 5],
            ["East", "East", 13],
        ],
        402,
    ):
        for col, value in enumerate(values, 6):
            sheet.cell(row, col, value)
    path = tmp_path / "counts.xlsx"
    book.save(path)
    book.close()
    body = "tp=sum(x[2] for x in data if x[0]=='North' and x[1]=='North')\nfp=sum(x[2] for x in data if x[0]!='North' and x[1]=='North')\nfn=sum(x[2] for x in data if x[0]=='North' and x[1]!='North')\nresult=100*2*tp/(2*tp+fp+fn)"
    programs = [
        {"code": code, "format": {"kind": "decimal", "decimals": 2}}
        for code in [
            "result =",
            "data=values('Sheet','F403:H406')\n" + body,
            "data=cells('Sheet','F403:H406')\n" + body,
        ]
    ]
    client = LLMAgent(api_key="test-placeholder", pricing=(0, 0))
    with patch.object(
        client, "_request", side_effect=[json.dumps(p) for p in programs]
    ) as call:
        result = client.solve_workbook(
            load_workbook_data(path),
            "Calculate North F1 = 2*TP/(2*TP+FP+FN), expressed as percent to two decimal places.",
        )
    assert call.call_count == 3 and result.error is None
    assert result.answer == f"{100 * 34 / (34 + 3 + 5):.2f}"


def test_row_count_is_grounded_in_structure_but_unused_probe_cannot_ground_literal(
    tmp_path: Path,
) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    for row, values in enumerate([["Key", "Value"], ["A", 37], ["B", 61]], 307):
        for col, value in enumerate(values, 4):
            sheet.cell(row, col, value)
    path = tmp_path / "shifted_rows.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    count = execute_program("result=len([r for r in rows('Sheet') if r>307])", wire)
    assert count.success and count.result == 2
    assert count.reads and all(
        entry["kind"] == "type_probe" for entry in count.reads.values()
    )
    guessed = execute_program("unused=rows('Sheet'); result=2", wire)
    assert not guessed.success and "depend" in guessed.error


def test_typed_date_compared_as_space_string_to_iso_t_cutoff_is_rejected(
    tmp_path: Path,
) -> None:
    from src.contracts import temporal_comparison_errors

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Event"])
    sheet.append([dt.datetime(2029, 5, 1, 8)])
    sheet.append([dt.datetime(2029, 4, 30, 23)])
    path = tmp_path / "times.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    wrong = "r=data_rows('Sheet',{'A':'datetime'}); result=sum(1 for i in r if str(cell('Sheet','A'+str(i)))<'2029-05-01T00:00:00')"
    execution = execute_program(wrong, wire)
    query = "How many events occur strictly before 2029-05-01 00:00?"
    assert execution.result == 2 and temporal_comparison_errors(execution, query, wrong)
    assert not temporal_comparison_errors(
        execution, "Compare the timestamp strings lexicographically.", wrong
    )
    correct = "r=data_rows('Sheet',{'A':'datetime'}); result=sum(1 for i in r if cell('Sheet','A'+str(i))<datetime.datetime(2029,5,1))"
    checked = execute_program(correct, wire)
    assert checked.result == 1 and not temporal_comparison_errors(
        checked, query, correct
    )


def test_unused_source_elimination_preserves_result_and_complete_audit(
    tmp_path: Path,
) -> None:
    from unittest.mock import patch

    from src.llm_agent import LLMAgent

    book = openpyxl.Workbook()
    sheet = book.active
    for row, values in enumerate([["Name", "Units"], ["One", 37], ["Two", 61]], 307):
        for column, value in enumerate(values, 4):
            sheet.cell(row, column, value)
    path = tmp_path / "outside_evidence.xlsx"
    book.save(path)
    book.close()
    workbook = load_workbook_data(path)
    client = LLMAgent(api_key="test-placeholder", pricing=(0, 0))
    code = "unused=values('Sheet','E309:E309')[0]; answer=num('Sheet','E308')"
    program = {
        "code": code,
        "result_variable": "answer",
        "selection": [{"sheet": "Sheet", "range": "E308"}],
        "format": {"kind": "integer"},
    }
    with patch.object(client, "_request", return_value=json.dumps(program)) as call:
        result = client.solve_workbook(
            workbook, "What is Units for One? Answer only the integer."
        )
    assert call.call_count == 1 and result.answer == "37" and result.error is None
    assert "Sheet!E309" in result.attempts[0]["reads"]
    assert result.attempts[1]["contract_kind"] == "unused-source-elimination"
    assert "Sheet!E309" not in result.attempts[1]["reads"]
    bad = {"code": "unused=num('Sheet','D308'); result=num('Sheet','E308')"}
    with patch.object(
        client,
        "_request",
        side_effect=[
            json.dumps(bad),
            json.dumps({"code": "result=num('Sheet','E308')"}),
        ],
    ) as call:
        corrected = client.solve_workbook(
            workbook, "What is Units for One? Answer only the integer."
        )
    assert call.call_count == 2 and corrected.answer == "37"
    assert corrected.attempts[0]["error"]


def test_source_simplification_keeps_mutations_shadowed_helpers_and_closures() -> None:
    from src.executor import without_unused_source_reads

    for code in (
        "items=[1,2]; unused=items.pop(); result=len(items)",
        "x=cell('S','A1')\ndef f():\n    return x\nresult=f()",
        "def cell(s,a):\n    items.append(a)\nitems=[]\nunused=cell('S','A1')\nresult=len(items)",
    ):
        assert without_unused_source_reads(code) == code


def test_typed_row_filter_accepts_validated_inclusive_bounds(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    for row in (4, 310, 311, 420):
        sheet.cell(row, 5, "Group")
        sheet.cell(row, 6, row * 3)
    path = tmp_path / "bounded.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    for bounds in ("310,311", "start_row=310,end_row=311"):
        execution = execute_program(
            f"result=data_rows('Sheet',{{'E':'string','F':'number'}},{bounds})", wire
        )
        assert execution.result == [310, 311] and execution.error is None
        assert "Sheet!F420" not in execution.reads
    for bounds in ("311,310", "0,311", "310,True", "310,1048577"):
        execution = execute_program(
            f"result=data_rows('Sheet',{{'F':'number'}},{bounds})", wire
        )
        assert "bounds" in execution.error


def test_iso_age_ranking_uses_each_reference_and_intraday_precision(
    tmp_path: Path,
) -> None:
    from src.verification import age_reference_columns, age_sort_errors

    book = openpyxl.Workbook()
    sheet = book.active
    rows = [
        ["Name", "Birth date", "Admission date", "Audit date"],
        ["A", "2000-01-01T12:00:00", "2020-01-01T18:00:00", "2021-01-01"],
        ["B", "2000-01-01T00:00:00", "2020-01-01T12:00:00", "2020-01-01"],
    ]
    for row, values in enumerate(rows, 309):
        for col, value in enumerate(values, 4):
            sheet.cell(row, col, value)
    path = tmp_path / "ISO.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    question = "Who is oldest at admission?"
    assert age_reference_columns(wire["Sheet"], question) == ("E", "F")
    correct = execute_program(
        "r=age_order('Sheet','E','F',descending=True); result=cell('Sheet','D'+str(r[0]))",
        wire,
    )
    assert correct.result == "B" and not age_sort_errors(wire, correct, question)
    wrong = execute_program(
        "r=age_order('Sheet','E','F'); result=cell('Sheet','D'+str(r[0]))", wire
    )
    assert age_sort_errors(wire, wrong, question)
    assert age_reference_columns(wire["Sheet"], "Who is oldest at audit?") == ("E", "G")
    from src.verification import date_field_errors

    wrong_date = execute_program("result=cell('Sheet','F310')", wire)
    right_date = execute_program("result=cell('Sheet','G310')", wire)
    assert date_field_errors(
        wire, wrong_date, "What is A audit date? Answer only the ISO date."
    )
    assert not date_field_errors(
        wire, right_date, "What is A audit date? Answer only the ISO date."
    )
    assert not date_field_errors(
        wire, wrong_date, "What is A admission date? Answer only the ISO date."
    )


def test_ambiguous_date_text_requires_explicit_format(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Birth", "Reference"])
    sheet.append(["04/03/2000", "05/03/2020"])
    path = tmp_path / "locale.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    ambiguous = execute_program("result=age_order('Sheet','A','B')", wire)
    assert "date_format" in ambiguous.error
    explicit = execute_program(
        "result=age_order('Sheet','A','B',date_format='%d/%m/%Y')", wire
    )
    assert explicit.result == [2] and explicit.error is None
    days = execute_program(
        "result=age_days('Sheet','A2','B2',date_format='%d/%m/%Y')", wire
    )
    assert days.result == (dt.datetime(2020, 3, 5) - dt.datetime(2000, 3, 4)).days


@pytest.mark.parametrize(
    "offset,unit,factor", [(0, "thousands", 1000), (309, "millions", 1000000)]
)
def test_unrequested_scaling_is_detected_but_explicit_conversion_is_allowed(
    tmp_path: Path, offset: int, unit: str, factor: int
) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Unfamiliar scope"
    sheet.cell(offset + 1, 4, f"Amounts in {unit} of USD")
    for i, row in enumerate(
        [["Group", "Amount"], ["North", 47], ["South", 19]], offset + 2
    ):
        for col, value in enumerate(row, 4):
            sheet.cell(i, col, value)
    path = tmp_path / "new.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    code = f"scale={factor}; amount=num('Unfamiliar scope','E{offset + 3}'); result=amount*scale"
    result = execute_program(code, wire)
    question = "What is the Amount for North? Answer only the integer without units."
    assert scale_conversion_errors(wire, result, question, code, "result")
    assert scale_conversion_errors(
        wire, result, f"What is North Amount in {unit}?", code, "result"
    )
    assert scale_conversion_errors(
        wire,
        result,
        "What is North Amount? Format without thousands separators or units.",
        code,
        "result",
    )
    assert not scale_conversion_errors(
        wire, result, "Report the North Amount in actual USD.", code, "result"
    )
    assert not scale_conversion_errors(
        wire,
        result,
        f"Multiply the displayed North Amount by {factor}.",
        code,
        "result",
    )
    untouched = f"unused=2*{factor}; result=num('Unfamiliar scope','E{offset + 3}')"
    assert not scale_conversion_errors(
        wire, execute_program(untouched, wire), question, untouched, "result"
    )
    dynamic = f"scale={factor}\nfor r in [1]:\n    scale=num('Unfamiliar scope','E{offset + 4}')\nresult=num('Unfamiliar scope','E{offset + 3}')*scale"
    assert not scale_conversion_errors(
        wire, execute_program(dynamic, wire), question, dynamic, "result"
    )


def test_string_filter_header_count_is_reviewed_without_dropping_blank_records(
    tmp_path: Path,
) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Events"
    rows = [
        ["Identifier", "Date", "Value"],
        ["A", dt.datetime(2029, 2, 1), None],
        ["B", dt.datetime(2029, 2, 2), 83],
    ]
    for i, row in enumerate(rows, 311):
        for col, value in enumerate(row, 4):
            sheet.cell(i, col, value)
    path = tmp_path / "shifted.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    wrong = "r=data_rows('Events',{'D':'string'}); result=len(r)"
    result = execute_program(wrong, wire)
    query = "How many event records are in the table? Answer only the integer."
    assert result.result == 3 and header_count_errors(
        wire, result, query, wrong, "result"
    )
    assert not header_count_errors(
        wire, result, "How many rows, including headers?", wrong, "result"
    )
    right = "r=data_rows('Events',{'D':'string','E':'datetime'}); result=len(r)"
    checked = execute_program(right, wire)
    assert checked.result == 2 and not header_count_errors(
        wire, checked, query, right, "result"
    )


def test_signed_minimum_and_floating_tie_tolerance_are_distinct() -> None:
    query = "On which date was the smallest signed change? Break ties by earliest date."
    assert signed_comparison_errors(
        query, "if abs(change) < abs(best):\n    result=change"
    )
    assert not signed_comparison_errors(
        query, "if change < best or abs(change-best) < 1e-9:\n    result=change"
    )
    assert not signed_comparison_errors(
        "Find the smallest absolute change.", "if abs(change)<best:\n    result=change"
    )
    assert signed_comparison_errors(
        query,
        "candidates.append((abs(change), change, date))\ncandidates.sort(key=lambda x:x[0])",
    )


def test_explicit_row_dimensions_resolve_only_the_correct_year_and_region(
    tmp_path: Path,
) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Audited decisions"
    for i, row in enumerate(
        [
            ["Year", "Region", "Metric", "Value"],
            [2028, "East", "Approved", 71],
            [2028, "West", "Approved", 29],
            [2029, "East", "Approved", 113],
            [2029, "West", "Approved", 46],
        ],
        301,
    ):
        for col, value in enumerate(row, 4):
            sheet.cell(i, col, value)
    path = tmp_path / "unseen.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    query = "What is Approved Value for East in 2029?"
    correct = execute_program("result=num('Audited decisions','G304')", wire)
    incorrect = execute_program("result=num('Audited decisions','G302')", wire)
    assert not scope_risks(wire, correct, query)
    assert scope_risks(wire, incorrect, query)
    assert scope_risks(
        wire, incorrect, query, "result=sum([num('Audited decisions','G302')])"
    )


def test_flat_ledger_aggregation_is_not_mistaken_for_repeated_sections(
    tmp_path: Path,
) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    rows = [
        ["Date", "Region", "SKU", "Units"],
        [dt.datetime(2029, 2, 1), "South", "K1", 13],
        [dt.datetime(2029, 2, 3), "South", "K2", 27],
        [dt.datetime(2029, 3, 2), "West", "K3", 52],
    ]
    for row, values in enumerate(rows, 303):
        for col, value in enumerate(values, 4):
            sheet.cell(row, col, value)
    path = tmp_path / "ledger.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    execution = execute_program(
        "r=data_rows('Sheet',{'D':'datetime','E':'string','G':'number'}); result=sum(num('Sheet','G'+str(i)) for i in r if cell('Sheet','E'+str(i)) in ['South','West'] and cell('Sheet','D'+str(i))<datetime.datetime(2029,3,1))",
        wire,
    )
    assert execution.result == 40
    assert not scope_risks(
        wire, execution, "What is the total Units for South and West before 2029-03-01?"
    )


def test_root_batch_metadata_cannot_drop_a_review_request(tmp_path: Path) -> None:
    import io

    from benchmarks.gateway import BatchLimits
    from benchmarks.structured_batch import StructuredBatchedAgent

    class Response(io.BytesIO):
        def __init__(self, data: bytes) -> None:
            super().__init__(data)
            self.headers = {"Content-Type": "application/json"}

    agent = StructuredBatchedAgent(
        api_key="test-placeholder",
        gateway_url="https://gateway.invalid/v1",
        gateway_model="ag/gemini-3-flash",
        batch_limits=BatchLimits(tmp_path / "batch.json"),
    )
    agent.structured_state.structured_expected = ["q0"]
    item = {"code": "result=num('S','B2')", "assumptions": ["local"]}
    body = {
        "programs": {"q0": item},
        "assumptions": ["shared"],
        "needs_verification": True,
    }
    raw = {
        "choices": [{"message": {"content": json.dumps(body)}, "finish_reason": "stop"}]
    }
    parsed = agent._read_response(Response(json.dumps(raw).encode()))
    program = json.loads(parsed["choices"][0]["message"]["content"])["programs"][0]
    assert program["needs_verification"] and program["assumptions"] == [
        "local",
        "shared",
    ]
    body["unsupported_answer"] = "42"
    raw["choices"][0]["message"]["content"] = json.dumps(body)
    parsed = agent._read_response(Response(json.dumps(raw).encode()))
    assert "unsupported_answer" in json.loads(
        parsed["choices"][0]["message"]["content"]
    )


def test_nonexistent_columns_cannot_turn_into_a_zero_count(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Shifted source"
    sheet.cell(307, 4, "Identifier")
    sheet.cell(307, 5, "Score")
    sheet.cell(308, 4, "One")
    path = tmp_path / "empty scores.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    invalid = execute_program(
        "result=len(data_rows('Shifted source',{'A':'string','B':'number'}))", wire
    )
    assert not invalid.success and "no stored cells" in invalid.error
    genuinely_empty = execute_program(
        "result=len(data_rows('Shifted source',{'E':'number'}))", wire
    )
    assert genuinely_empty.success and genuinely_empty.result == 0


@pytest.mark.parametrize("offset_hours", [None, 7])
def test_timestamp_is_portable_for_naive_and_aware_input(
    offset_hours: int | None,
) -> None:
    from src.excel_parser import CellData, SheetData, WorkbookData

    timezone = (
        None if offset_hours is None else dt.timezone(dt.timedelta(hours=offset_hours))
    )
    value = dt.datetime(2029, 8, 13, 15, 30, tzinfo=timezone)
    wire = WorkbookData(
        {"Times": SheetData("Times", cells={"D308": CellData(value, "datetime")})}
    ).wire()
    result = execute_program("result=cell('Times','D308').timestamp()", wire)
    assert result.success
    assert result.result == pytest.approx(
        value.replace(tzinfo=timezone or dt.UTC).timestamp()
    )


def test_only_entity_scope_requests_review_of_unfiltered_reads(tmp_path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "New ledger"
    sheet.append(["Entity", "Amount"])
    sheet.append(["Birch", 61])
    sheet.append(["Cedar", 9])
    path = tmp_path / "scope.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    question = "For Birch only, what is Amount? Answer only the integer."
    broad = execute_program("result=sum(values('New ledger','B2:B3'))", wire)
    precise = execute_program("result=num('New ledger','B2')", wire)
    assert any(
        "explicitly restricted" in risk for risk in scope_risks(wire, broad, question)
    )
    assert not scope_risks(wire, precise, question)


def test_bounded_combinations_supports_calculation_without_unbounded_pools() -> None:
    from src.excel_parser import CellData, SheetData, WorkbookData

    wire = WorkbookData(
        {
            "Values": SheetData(
                "Values",
                cells={
                    "D301": CellData(17, "number"),
                    "D302": CellData(29, "number"),
                    "D303": CellData(8, "number"),
                },
            )
        }
    ).wire()
    code = "import itertools\nv=values('Values','D301:D303')\nresult=max(sum(pair) for pair in itertools.combinations(v,2))"
    result = execute_program(code, wire)
    assert result.success and result.result == 46
    too_large = execute_program(
        "import itertools\nresult=list(itertools.combinations(range(1000),5))"
    )
    assert not too_large.success and "item budget" in too_large.error
    assert not execute_program("import itertools\nresult=itertools.__dict__").success


def test_across_all_compares_complete_sibling_columns_only_when_unambiguous(
    tmp_path: Path,
) -> None:
    import copy

    from src.verification import all_category_column_errors

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Relocated matrix"
    sheet["D301"] = "Metric"
    sheet["E301"] = "2028"
    sheet.merge_cells("E301:G301")
    for address, value in {
        "E302": "Amber",
        "F302": "Birch",
        "G302": "Copper",
        "D303": "Earlier",
        "E303": 2,
        "F303": 3,
        "G303": 4,
        "D304": "Later",
        "E304": 5,
        "F304": 7,
        "G304": 8,
    }.items():
        sheet[address] = value
    path = tmp_path / "changed.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    question = "How much greater is Later than Earlier across all categories?"
    partial = execute_program(
        "result=sum(values('Relocated matrix','F304:G304'))-sum(values('Relocated matrix','F303:G303'))",
        wire,
    )
    errors = all_category_column_errors(wire, partial.reads, question)
    assert len(errors) == 2 and any("E303" in error for error in errors)
    complete = execute_program(
        "result=sum(values('Relocated matrix','E304:G304'))-sum(values('Relocated matrix','E303:G303'))",
        wire,
    )
    assert complete.success and complete.result == 11
    assert all_category_column_errors(wire, complete.reads, question) == []
    for narrowed in [question + " Excluding Amber.", question + " For Birch only."]:
        assert all_category_column_errors(wire, partial.reads, narrowed) == []
    # A published parent or competing ancestry prevents inferring a partition.
    for replacement in [["2028", "Total"], ["Other measure", "Amber"]]:
        ambiguous = copy.deepcopy(wire)
        for table in ambiguous["Relocated matrix"]["tables"]:
            if "E" in table["headers"]:
                table["headers"]["E"] = replacement
        assert all_category_column_errors(ambiguous, partial.reads, question) == []
    measures = copy.deepcopy(wire)
    for table in measures["Relocated matrix"]["tables"]:
        if "E" in table["headers"]:
            table["headers"]["E"] = ["2028", "Published workers"]
            table["headers"]["F"] = ["2028", "Completion rate"]
            table["headers"]["G"] = ["2028", "Balance"]
    assert (
        all_category_column_errors(
            measures, partial.reads, "How many workers across all departments?"
        )
        == []
    )
    assert (
        all_category_column_errors(
            wire, partial.reads, question + " Use the published total."
        )
        == []
    )
    mixed = copy.deepcopy(wire)
    mixed["Relocated matrix"]["cells"]["F303"]["number_format"] = "0.0%"
    assert all(
        "E303" not in error
        for error in all_category_column_errors(mixed, partial.reads, question)
    )


def test_named_header_parent_requires_evidence_inside_that_branch(
    tmp_path: Path,
) -> None:
    import copy

    from src.verification import column_scope_errors

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Relocated branches"
    sheet["D401"] = "Metric"
    sheet["E401"] = "2031"
    sheet.merge_cells("E401:H401")
    for address, value in {
        "E402": "Overall",
        "F402": "Channel North",
        "H402": "Channel South",
        "F403": "Total",
        "G403": "Active only",
        "D404": "Units",
        "E404": 999,
        "F404": 30,
        "G404": 20,
        "H404": 50,
    }.items():
        sheet[address] = value
    sheet.merge_cells("F402:G402")
    path = tmp_path / "branches.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    question = "Compare Channel North and Channel South; answer as two integers."
    wrong = execute_program(
        "result=[num('Relocated branches','E404'),num('Relocated branches','H404')]",
        wire,
    )
    errors = column_scope_errors(wire, wrong, question)
    assert errors and "Channel North" in errors[0] and "F" in errors[0]
    right = execute_program(
        "result=[num('Relocated branches','F404'),num('Relocated branches','H404')]",
        wire,
    )
    assert column_scope_errors(wire, right, question) == []
    ambiguous = copy.deepcopy(wire)
    for table in ambiguous["Relocated branches"]["tables"]:
        if "F" in table["headers"]:
            table["headers"]["F"] = ["2031", "Older", "Channel North"]
            table["headers"]["G"] = ["2031", "Newer", "Channel North"]
    assert column_scope_errors(ambiguous, wrong, question) == []


def test_standard_filter_match_groups_and_datetime_feedback_are_safe() -> None:
    from src.excel_parser import CellData, SheetData, WorkbookData

    wire = WorkbookData(
        {"Moved": SheetData("Moved", cells={"K407": CellData("Code-318", "string")})}
    ).wire()
    filtered = execute_program(
        "s=cell('Moved','K407'); result=''.join(filter(str.isdigit,s))", wire
    )
    assert filtered.success and filtered.result == "318"
    matched = execute_program(
        "import re\ns=cell('Moved','K407'); result=re.search(r'([A-Za-z]+)-(\\d+)',s).groups()",
        wire,
    )
    assert matched.success and matched.result == ["Code", "318"]
    mapped = execute_program(
        "s=cell('Moved','K407'); result=sum(map(int,filter(str.isdigit,s)))", wire
    )
    assert mapped.success and mapped.result == 12
    wrong = execute_program("result=datetime(2031,5,7)")
    assert not wrong.success and "datetime.datetime" in wrong.error
    assert execute_program("result=datetime.datetime(2031,5,7).day").result == 7
    for unsafe in [
        "result=str.__dict__",
        "import re\nresult=re.search('x','x').__class__",
        "import re\nresult=re.search('x','x').re",
    ]:
        assert not execute_program(unsafe).success


def test_flat_loop_accumulation_is_not_misread_as_duplicate_sections(
    tmp_path: Path,
) -> None:
    from src.verification import scope_risks

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "State movements"
    for row, values in enumerate(
        [
            ["Origin", "Destination", "Rate"],
            ["Up", "Up", 0.75],
            ["Up", "Down", 0.25],
            ["Down", "Up", 0.5],
            ["Down", "Down", 0.5],
        ],
        309,
    ):
        for col, value in enumerate(values, 7):
            sheet.cell(row, col, value)
    path = tmp_path / "transitions.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    code = """data=cells('State movements','G310:I313')
transitions={(r[0],r[1]):r[2] for r in data}
prob={'Up':1.0,'Down':0.0}
for step in range(2):
    updated={'Up':0.0,'Down':0.0}
    for source in prob:
        for target in prob:
            updated[target]+=prob[source]*transitions[(source,target)]
    prob=updated
result=prob['Up']"""
    execution = execute_program(code, wire)
    assert execution.success and execution.result == 0.6875
    question = "Starting in Up, what is the probability of Up after two steps?"
    assert scope_risks(wire, execution, question, code) == []
    lookup = execute_program("result=num('State movements','I310')", wire)
    assert scope_risks(
        wire, lookup, "What is the Rate for Up?", "result=num('State movements','I310')"
    )


def test_cells_rows_cannot_silently_compare_equal_to_scalar() -> None:
    from src.excel_parser import CellData, SheetData, WorkbookData

    wire = WorkbookData(
        {
            "Status": SheetData(
                "Status",
                cells={
                    "H311": CellData("Active", "string"),
                    "H312": CellData("Closed", "string"),
                },
            )
        }
    ).wire()
    for compare in ["row == 'Active'", "'Active' != row"]:
        result = execute_program(
            f"row=cells('Status','H311')[0]; result={compare}", wire
        )
        assert not result.success and "2D list" in result.error
    correct = execute_program(
        "result=sum(1 for r in [311,312] if cell('Status','H'+str(r))=='Active')", wire
    )
    assert correct.success and correct.result == 1
    structured = execute_program(
        "row=cells('Status','H311')[0]; row.append('extra'); result=[row==['Active','extra'], cells('Status','H312')==[['Closed']], values('Status','H311')=='Active']",
        wire,
    )
    assert structured.success and structured.result == [True, True, False]


def test_permutations_and_set_operations_remain_bounded() -> None:
    from src.excel_parser import CellData, SheetData, WorkbookData
    from src.executor import bounded_permutations

    wire = WorkbookData(
        {
            "Moved": SheetData(
                "Moved",
                cells={
                    "G401": CellData(17, "number"),
                    "G402": CellData(29, "number"),
                    "G403": CellData(8, "number"),
                },
            )
        }
    ).wire()
    result = execute_program(
        "from itertools import permutations\nv=values('Moved','G401:G403')\nresult=max(10*a+b for a,b in permutations(v,2))",
        wire,
    )
    assert result.success and result.result == 307
    result = execute_program(
        "a=frozenset(values('Moved','G401:G402')); b=set(values('Moved','G402:G403')); result=[sorted(a|b),sorted(a&b),sorted(a^b)]",
        wire,
    )
    assert result.success and result.result == [[8, 17, 29], [29], [8, 17]]
    assert list(bounded_permutations([1, 2])) == [(1, 2), (2, 1)]
    assert list(bounded_permutations([1, 2], 3)) == []
    assert list(bounded_permutations([], 0)) == [()]
    for count in (-1, 1.5, True):
        with pytest.raises((ValueError, TypeError)):
            bounded_permutations([1, 2], count)
    with pytest.raises(MemoryError, match="item budget"):
        bounded_permutations(range(1000), 1000)
    assert not execute_program("result=2**4097 | 1").success
    assert not execute_program("def f():\n    yield 1\nresult=list(f())").success


def test_extremum_requires_measure_and_returns_identity_instead_of_measure(
    tmp_path: Path,
) -> None:
    from src.verification import label_errors

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Buckets"
    sheet.append(["Duration category", "Share"])
    sheet.append(["Short", 17])
    sheet.append(["Long", 63])
    numeric = book.create_sheet("Numeric labels")
    numeric.append(["Category", "Share"])
    numeric.append([1, 21])
    numeric.append([2, 48])
    path = tmp_path / "buckets.xlsx"
    book.save(path)
    book.close()
    wire = load_workbook_data(path).wire()
    query = "Which duration category had the highest share percentage? Answer with only the duration category."
    guessed = "result=cell('Buckets','A2')"
    assert extremum_evidence_errors(
        wire, execute_program(guessed, wire), query, guessed
    )
    wrong = execute_program("result=label('Buckets',argmax('Buckets','B2:B3'))", wire)
    assert wrong.success and label_errors(wrong, query, wire)
    correct = "best=argmax('Buckets','B2:B3'); result=cell('Buckets','A'+best[1:])"
    checked = execute_program(correct, wire)
    assert checked.result == "Long" and not label_errors(checked, query, wire)
    assert not extremum_evidence_errors(wire, checked, query, correct)
    numeric_answer = execute_program("result=cell('Numeric labels','A3')", wire)
    assert not label_errors(
        numeric_answer,
        "Which category has highest Share? Answer with only the category.",
        wire,
    )
