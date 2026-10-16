"""Conservative program-intent checks; never use a reference answer or repair a value."""

import ast
import itertools
import re
from typing import Any

from openpyxl.utils import coordinate_to_tuple, get_column_letter

from .executor import ISO_DATE, ExecutionResult
from .postprocessor import query_format
from .verification import canonical_label, cell_region


def temporal_comparison_errors(
    execution: ExecutionResult, query: str, code: str
) -> list[str]:
    """Reject mixed datetime string representations that compare separators before time."""
    if not any(
        entry["kind"] == "datetime" for entry in execution.reads.values()
    ) or re.search(
        r"lexicograph|alphabetic|string (?:order|compar)", query, re.IGNORECASE
    ):
        return []
    assigned = bindings(code)
    for comparison in ast.walk(ast.parse(code)):
        if not isinstance(comparison, ast.Compare):
            continue
        operands = [comparison.left, *comparison.comparators]
        for left, right in itertools.pairwise(operands):
            left, right = resolve(left, assigned), resolve(right, assigned)
            for text, literal in ((left, right), (right, left)):
                if (
                    isinstance(text, ast.Call)
                    and isinstance(text.func, ast.Name)
                    and text.func.id == "str"
                    and text.args
                    and not isinstance(text.args[0], ast.Constant)
                    and isinstance(literal, ast.Constant)
                    and isinstance(literal.value, str)
                    and "T" in literal.value
                    and ISO_DATE.fullmatch(literal.value)
                ):
                    return [
                        "Temporal comparison mismatch: str(datetime) uses a SPACE, but the compared ISO timestamp uses T. Lexical order can misclassify times on the cutoff day. Compare typed datetime values against a parsed datetime cutoff, or normalize both timestamps to the same ISO representation; do not compare str(datetime) to a T-separated literal."
                    ]
    return []


def bindings(code: str) -> dict[str, ast.AST]:
    """Resolve only simple top-level bindings; uncertain control flow remains unchecked."""
    result = {}
    for statement in ast.parse(code).body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            result[statement.target.id] = statement.value
        elif isinstance(statement, (ast.For, ast.While, ast.If, ast.Try, ast.With)):
            for child in ast.walk(statement):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    result.pop(child.id, None)
    return result


def resolve(node: ast.AST, assigned: dict[str, ast.AST]) -> ast.AST:
    seen = set()
    while isinstance(node, ast.Name) and node.id in assigned and node.id not in seen:
        seen.add(node.id)
        node = assigned[node.id]
    return node


def scale_conversion_errors(
    workbook: dict[str, Any],
    execution: ExecutionResult,
    query: str,
    code: str,
    result_variable: str,
) -> list[str]:
    """Flag unrequested literal scaling of uniformly declared thousand/million values."""
    values = (
        execution.result if isinstance(execution.result, list) else [execution.result]
    )
    explicit_numeric = any(isinstance(value, str) for value in values) and query_format(
        query
    ).kind in {"integer", "decimal"}
    if not values or not all(
        type(value) in {int, float} or explicit_numeric and isinstance(value, str)
        for value in values
    ):
        return []
    if re.search(
        r"\b(?:percent(?:age)?s?|ratio|rate)\b|\bactual\s+(?:USD|EUR|dollars?|amounts?|counts?|units?)\b|\b(?:base|unscaled|individual) units\b|\b(?:in|to|as)\s+(?:USD|EUR|dollars?|euros?|units?|persons?|people|workers?)\b|\b1,?000(?:,?000)?\b",
        query,
        re.IGNORECASE,
    ):
        return []
    observed = []
    for key, entry in execution.reads.items():
        if entry["kind"] != "number":
            continue
        name, address = key.rsplit("!", 1)
        sheet = workbook.get(name, {})
        region = cell_region(sheet, *coordinate_to_tuple(address))
        if not region or not region.get("headers"):
            return []
        text = " ".join(
            str(value) for path in region["headers"].values() for value in path
        )
        scales = {
            factor
            for word, factor in [("thousands?", 1000), ("millions?", 1000000)]
            if re.search(rf"\b{word}\b", text, re.IGNORECASE)
        }
        if len(scales) != 1:
            return []
        observed.append(next(iter(scales)))
    if not observed or len(set(observed)) != 1:
        return []
    unit_query = re.sub(
        r"\b(?:without|no)\s+thousands?\s+separators?\b", "", query, flags=re.IGNORECASE
    )
    requested_scales = {
        factor
        for word, factor in [("thousands?", 1000), ("millions?", 1000000)]
        if re.search(rf"\b{word}\b", unit_query, re.IGNORECASE)
    }
    if requested_scales and requested_scales != {observed[0]}:
        return []  # An explicitly different scale may legitimately require conversion.
    assigned = bindings(code)
    if result_variable not in assigned:
        return []
    pending = [assigned[result_variable]]
    seen = set()
    while pending:
        node = pending.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, ast.BinOp):
            operands = (
                [node.left, node.right]
                if isinstance(node.op, ast.Mult)
                else [node.right]
                if isinstance(node.op, ast.Div)
                else []
            )
            if any(
                isinstance(value, ast.Constant)
                and type(value.value) in {int, float}
                and value.value in {1000, 1000000}
                for value in (resolve(operand, assigned) for operand in operands)
            ):
                return [
                    "Unrequested unit conversion: source values have a declared thousand/million scale. Keep that displayed scale; integer/no-units formatting does not request multiplication or division by 1000."
                ]
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in assigned
        ):
            pending.append(assigned[node.id])
        pending.extend(ast.iter_child_nodes(node))
    return []


def header_count_errors(
    workbook: dict[str, Any],
    execution: ExecutionResult,
    query: str,
    code: str,
    result_variable: str,
) -> list[str]:
    """Check direct row counts from string-only type filters against header evidence."""
    if not re.search(
        r"\bhow many\b.*\b(?:records|rows|observations)\b", query, re.IGNORECASE
    ) or re.search(
        r"\b(?:including|include|count)\b[^.?!]{0,20}\bheaders?\b", query, re.IGNORECASE
    ):
        return []
    assigned = bindings(code)
    if result_variable not in assigned:
        return []
    node = resolve(assigned[result_variable], assigned)
    while (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"int", "float", "round"}
        and node.args
    ):
        node = resolve(node.args[0], assigned)
    if (
        not isinstance(node, ast.Call)
        or not isinstance(node.func, ast.Name)
        or node.func.id != "len"
        or len(node.args) != 1
    ):
        return []
    call = resolve(node.args[0], assigned)
    if (
        not isinstance(call, ast.Call)
        or not isinstance(call.func, ast.Name)
        or call.func.id != "data_rows"
        or len(call.args) < 2
    ):
        return []
    try:
        name = ast.literal_eval(resolve(call.args[0], assigned))
        columns = ast.literal_eval(resolve(call.args[1], assigned))
        kind = (
            ast.literal_eval(call.args[2])
            if len(call.args) > 2
            else next(
                (
                    ast.literal_eval(kw.value)
                    for kw in call.keywords
                    if kw.arg == "kind"
                ),
                "number",
            )
        )
    except (ValueError, TypeError):
        return []
    required = dict.fromkeys(columns, kind) if isinstance(columns, list) else columns
    if (
        not isinstance(name, str)
        or name not in workbook
        or not isinstance(required, dict)
        or not required
        or any(value != "string" for value in required.values())
    ):
        return []
    sheet = workbook[name]
    if not any(
        entry["kind"] in {"number", "datetime"} for entry in sheet["cells"].values()
    ):
        return []  # All-text tables need explicit schema interpretation, not type inference.
    by_row: dict[int, list[tuple[str, dict[str, Any]]]] = {}
    for address, entry in sheet["cells"].items():
        if entry["value"] not in (None, ""):
            by_row.setdefault(coordinate_to_tuple(address)[0], []).append(
                (address, entry)
            )
    rows = set(by_row)
    candidates = [
        row
        for row in rows
        if all(
            sheet["cells"].get(column.upper() + str(row), {}).get("kind") == "string"
            for column in required
        )
    ]
    if execution.result != len(candidates):
        return []
    for row in candidates:
        cells = by_row[row]
        if len(cells) < 2 or any(entry["kind"] != "string" for _, entry in cells):
            continue
        matching = 0
        for address, entry in cells:
            region = cell_region(sheet, *coordinate_to_tuple(address))
            path = (
                (region or {})
                .get("headers", {})
                .get(get_column_letter(coordinate_to_tuple(address)[1]), [])
            )
            if (
                path
                and canonical_label(entry["value"]).casefold()
                == canonical_label(path[-1]).casefold()
            ):
                matching += 1
        if matching >= 2:
            return [
                f"Record count includes probable header row {name!r}!{row}; a string-only data_rows filter also matches headings. Verify/exclude the header or include the appropriate typed date/measure columns without dropping valid missing-value records."
            ]
    return []


def signed_comparison_errors(query: str, code: str) -> list[str]:
    """An explicit signed minimum must not use absolute magnitude as its criterion."""
    if not re.search(
        r"\b(?:smallest|lowest|minimum)\b[^.?!]{0,35}\bsigned\s+(?:change|difference|delta)\b",
        query,
        re.IGNORECASE,
    ) or re.search(
        r"\b(?:absolute|magnitude|distance|closest)\b", query, re.IGNORECASE
    ):
        return []
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name)
            and node.func.id == "abs"
            and node.args
            and not isinstance(node.args[0], ast.Constant)
            and not (
                isinstance(node.args[0], ast.BinOp)
                and isinstance(node.args[0].op, ast.Sub)
            )
        ):
            return [
                "Signed minimum requested, but abs() transforms a candidate change into magnitude. Compare raw signed changes and the stated tie order."
            ]
    return []


def extremum_evidence_errors(
    workbook: dict[str, Any], execution: ExecutionResult, query: str, code: str
) -> list[str]:
    """A numeric ranking cannot be justified by looking up only its guessed label."""
    if (
        not workbook
        or not isinstance(execution.result, str)
        or not re.search(
            r"\b(?:which|who)\b.*\b(?:highest|largest|lowest|smallest|most|least)\b",
            query,
            re.IGNORECASE,
        )
    ):
        return []
    if not re.search(
        r"\b(?:percent(?:age)?|score|value|amount|count|hours?|units?|workers?|population|quantity|revenue|cost|sales|profit)\b",
        query,
        re.IGNORECASE,
    ) or re.search(
        r"\b(?:alphabetical|lexicograph\w*|characters?|length)\b", query, re.IGNORECASE
    ):
        return []
    if any(
        entry["kind"] in {"number", "datetime"}
        or (
            entry["kind"] == "string"
            and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", str(entry["value"]).strip())
        )
        for entry in execution.reads.values()
    ):
        return []
    tree = ast.parse(code)
    if any(
        isinstance(node, ast.Name) and node.id in {"len", "sum", "Counter", "ord"}
        for node in ast.walk(tree)
    ) or any(
        isinstance(node, ast.Attribute) and node.attr == "Counter"
        for node in ast.walk(tree)
    ):
        return []  # Counts/lengths can legitimately be derived from string records.
    return [
        "Numeric extremum has no measure evidence: reading only a guessed name/category does not establish highest/lowest. Read and compare the relevant measure candidates, then return the corresponding whole identity label."
    ]
