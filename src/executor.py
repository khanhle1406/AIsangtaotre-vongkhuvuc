"""A bounded Python AST interpreter. Generated programs never use exec/eval."""

import ast
import collections
import datetime
import itertools
import json
import math
import operator
import os
import re
import statistics
import string
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psutil

MAX_ITEMS = 200_000
MAX_STEPS = 1_000_000
MAX_OUTPUT_BYTES = 4 * 1024**2
ISO_DATE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?"
)


def stored_datetime(value: Any, date_format: str | None = None) -> datetime.datetime:
    """Parse typed dates or unambiguous ISO text; other formats require consent in code."""
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        value = value.strip()
        if date_format is not None:
            return datetime.datetime.strptime(value, date_format)
        if ISO_DATE.fullmatch(value):
            return datetime.datetime.fromisoformat(value)
    raise ValueError(
        "Expected an Excel datetime or ISO date text; provide date_format for other observed formats"
    )


def column_letter(index: int) -> str:
    """Convert a one-based Excel column index without importing a workbook library."""
    if type(index) is not int or not 1 <= index <= 16384:
        raise ValueError("Excel column index must be an integer from 1 to 16384")
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = string.ascii_uppercase[remainder] + result
    return result


def bounded_combinations(
    values: Iterable[Any], count: int
) -> Iterator[tuple[Any, ...]]:
    """Provide a pure standard operation without admitting unbounded output pools."""
    if type(count) is not int:
        raise TypeError("Combination size must be an integer")
    if count < 0:
        raise ValueError("Combination size must be nonnegative")
    pool = tuple(itertools.islice(values, MAX_ITEMS + 1))
    if len(pool) > MAX_ITEMS or math.comb(len(pool), count) > MAX_ITEMS:
        raise MemoryError("Combinations exceed the worker item budget")
    return itertools.combinations(pool, count)


def bounded_permutations(
    values: Iterable[Any], count: int | None = None
) -> Iterator[tuple[Any, ...]]:
    """Expose standard permutations only when both input and output fit the cap."""
    if count is not None and type(count) is not int:
        raise TypeError("Permutation size must be an integer")
    if count is not None and count < 0:
        raise ValueError("Permutation size must be nonnegative")
    pool = tuple(itertools.islice(values, MAX_ITEMS + 1))
    size = len(pool) if count is None else count
    if len(pool) > MAX_ITEMS:
        raise MemoryError("Permutations exceed the worker item budget")
    # Stop multiplication at the cap rather than constructing a huge factorial.
    cardinality = 0 if size > len(pool) else 1
    if cardinality:
        for factor in range(len(pool), len(pool) - size, -1):
            cardinality *= factor
            if cardinality > MAX_ITEMS:
                raise MemoryError("Permutations exceed the worker item budget")
    return itertools.permutations(pool, size)


def bounded_left_shift(value: int, count: int) -> int:
    """Allow ordinary bit masks without allocating integers beyond the worker cap."""
    if not isinstance(value, int) or not isinstance(count, int):
        raise TypeError("Bit shifts require integers")
    if count < 0:
        raise ValueError("negative shift count")
    if count > 4096 or value.bit_length() + count > 4096:
        raise MemoryError("Left shift exceeds integer bit limit")
    return value << count


BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.BitOr: operator.or_,
    ast.BitAnd: operator.and_,
    ast.BitXor: operator.xor,
    ast.LShift: bounded_left_shift,
    ast.RShift: operator.rshift,
}
COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
MODULES = {
    "itertools": SimpleNamespace(
        combinations=bounded_combinations, permutations=bounded_permutations
    ),
    "string": SimpleNamespace(
        ascii_uppercase=string.ascii_uppercase,
        ascii_lowercase=string.ascii_lowercase,
        digits=string.digits,
    ),
    "math": SimpleNamespace(
        **{
            name: getattr(math, name)
            for name in (
                "ceil",
                "floor",
                "sqrt",
                "fabs",
                "isfinite",
                "isclose",
                "fsum",
                "pi",
            )
        }
    ),
    "statistics": SimpleNamespace(mean=statistics.mean, median=statistics.median),
    "datetime": SimpleNamespace(
        datetime=datetime.datetime, date=datetime.date, timedelta=datetime.timedelta
    ),
    "re": SimpleNamespace(
        search=re.search,
        match=re.match,
        fullmatch=re.fullmatch,
        sub=re.sub,
        split=re.split,
        findall=re.findall,
        IGNORECASE=re.IGNORECASE,
    ),
    "collections": SimpleNamespace(
        Counter=collections.Counter, defaultdict=collections.defaultdict
    ),
}
METHODS = {
    str: {
        "strip",
        "lstrip",
        "rstrip",
        "lower",
        "upper",
        "casefold",
        "replace",
        "split",
        "rsplit",
        "startswith",
        "endswith",
        "join",
        "isdigit",
        "find",
        "index",
    },
    list: {
        "append",
        "extend",
        "insert",
        "index",
        "count",
        "sort",
        "reverse",
        "pop",
        "copy",
    },
    tuple: {"index", "count"},
    dict: {"get", "items", "keys", "values", "setdefault", "copy"},
    set: {
        "add",
        "union",
        "intersection",
        "difference",
        "update",
        "issubset",
        "issuperset",
        "isdisjoint",
    },
    re.Match: {"group", "groups", "start", "end", "span"},
    datetime.datetime: {"date", "isoformat", "strftime", "year", "month", "day"},
    datetime.date: {"isoformat", "strftime", "year", "month", "day"},
    datetime.timedelta: {"days", "seconds", "total_seconds"},
    float: {"is_integer"},
}
BUILTINS = {
    "column_letter": column_letter,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "RuntimeError": RuntimeError,
    "chr": chr,
    "ord": ord,
    "abs": abs,
    "sum": sum,
    "min": min,
    "max": max,
    "len": len,
    "sorted": sorted,
    "round": round,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "tuple": tuple,
    "dict": dict,
    "set": set,
    "frozenset": frozenset,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "filter": filter,
    "map": map,
    "any": any,
    "all": all,
    "isinstance": isinstance,
    "reversed": reversed,
}
ALLOWED_NODES = (
    ast.Module,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Expr,
    ast.If,
    ast.For,
    ast.While,
    ast.FunctionDef,
    ast.Return,
    ast.Raise,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.Import,
    ast.ImportFrom,
    ast.alias,
    ast.Constant,
    ast.Name,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Subscript,
    ast.Slice,
    ast.Call,
    ast.keyword,
    ast.Attribute,
    ast.IfExp,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.Lambda,
    ast.arguments,
    ast.arg,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Starred,
    ast.Load,
    ast.Store,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.BitOr,
    ast.BitAnd,
    ast.BitXor,
    ast.LShift,
    ast.RShift,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
)


def extract_python_code(text: str) -> str:
    """Extract executable Python code from LLM response, including fenced blocks."""
    matches = re.findall(r"```(?:python)?\s*(.*?)(?:```|$)", text, re.DOTALL)
    return matches[0].strip() if matches else text.strip()


def normalise_program(code: str) -> str:
    """Unwrap fences and accept a final, explicitly named result_* declaration."""
    code = extract_python_code(code)
    tree = ast.parse(code)
    if tree.body and isinstance(tree.body[-1], ast.Assign):
        final = tree.body[-1]
        if (
            len(final.targets) == 1
            and isinstance(final.targets[0], ast.Name)
            and final.targets[0].id.startswith("result_")
        ):
            code += f"\nresult={final.targets[0].id}"
    return code


def without_unused_source_reads(code: str, result_variable: str = "result") -> str:
    """Propose a smaller source declaration; caller must first execute original code."""
    tree = ast.parse(code)
    loaded = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    stored = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    } | {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    helpers = {"cell", "num", "values", "cells", "label"} - stored
    pure = helpers | ({"str", "int", "float"} - stored)
    protected = {result_variable, "result", "answer", "ans", "final_answer"}

    def removable(node: ast.stmt) -> bool:
        if (
            not isinstance(node, ast.Assign)
            or len(node.targets) != 1
            or not isinstance(node.targets[0], ast.Name)
            or node.targets[0].id in loaded | protected
        ):
            return False
        if not isinstance(node.value, (ast.Call, ast.Subscript)):
            return False
        children = list(ast.walk(node.value))
        if any(
            isinstance(
                child,
                (
                    ast.NamedExpr,
                    ast.Lambda,
                    ast.comprehension,
                    ast.Yield,
                    ast.YieldFrom,
                ),
            )
            for child in children
        ):
            return False
        calls = [child for child in children if isinstance(child, ast.Call)]
        return (
            bool(calls)
            and any(
                isinstance(call.func, ast.Name) and call.func.id in helpers
                for call in calls
            )
            and all(
                isinstance(call.func, ast.Name) and call.func.id in pure
                for call in calls
            )
        )

    retained = [node for node in tree.body if not removable(node)]
    if len(retained) == len(tree.body):
        return code
    tree.body = retained
    return ast.unparse(tree)


def _coordinate(address: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Za-z]+)([1-9]\d*)", address.replace("$", ""))
    if not match:
        raise ValueError(f"Invalid cell address: {address}")
    col = 0
    for char in match[1].upper():
        col = col * 26 + ord(char) - 64
    row = int(match[2])
    if row > 1_048_576 or col > 16_384:
        raise ValueError("Cell address outside Excel bounds")
    return row, col


def _address(row: int, col: int) -> str:
    if not 1 <= row <= 1_048_576 or not 1 <= col <= 16_384:
        raise ValueError("Cell address outside Excel bounds")
    chars = ""
    while col:
        col, digit = divmod(col - 1, 26)
        chars = chr(65 + digit) + chars
    return f"{chars}{row}"


class CellArray(list[Any]):
    """Preserve cells() shape provenance without changing normal list operations."""


@dataclass
class WorkbookAccess:
    data: dict[str, Any]
    reads: dict[str, dict[str, Any]] = field(default_factory=dict)
    resolving: set[str] = field(default_factory=set)
    sorter: Callable[..., list[Any]] = field(default=sorted, repr=False)

    def cell(self, sheet: str, address: str) -> Any:
        address = address.replace("$", "").upper()
        _coordinate(address)
        entry = self.data[sheet]["cells"].get(address)
        key = f"{sheet}!{address}"
        self.reads[key] = entry or {"value": None, "kind": "blank"}
        if entry is None:
            return None
        if entry["kind"] == "uncached_formula":
            if key in self.resolving:
                raise ValueError(f"Circular formula at {key}")
            self.resolving.add(key)
            try:
                return self.formula(sheet, entry["formula"])
            finally:
                self.resolving.remove(key)
        if entry["kind"] == "error":
            raise ValueError(f"Excel error at {key}: {entry['value']}")
        if entry["kind"] == "datetime":
            return datetime.datetime.fromisoformat(entry["value"])
        if entry["kind"] == "time":
            return datetime.time.fromisoformat(entry["value"])
        return entry["value"]

    def values(self, sheet: str, area: str) -> list[Any]:
        first, last = area.split(":") if ":" in area else (area, area)
        top, left = _coordinate(first)
        bottom, right = _coordinate(last)
        if (
            bottom < top
            or right < left
            or (bottom - top + 1) * (right - left + 1) > MAX_ITEMS
        ):
            raise ValueError("Invalid or excessive cell range")
        return [
            self.cell(sheet, _address(row, col))
            for row in range(top, bottom + 1)
            for col in range(left, right + 1)
        ]

    def cells(self, sheet: str, area: str) -> list[list[Any]]:
        first, last = area.split(":") if ":" in area else (area, area)
        top, left = _coordinate(first)
        bottom, right = _coordinate(last)
        values = self.values(sheet, area)
        width = right - left + 1
        return CellArray(
            [
                CellArray(values[index : index + width])
                for index in range(0, (bottom - top + 1) * width, width)
            ]
        )

    def age_days(
        self, sheet: str, birth: str, reference: str, date_format: str | None = None
    ) -> int:
        dob = stored_datetime(self.cell(sheet, birth), date_format)
        event = stored_datetime(self.cell(sheet, reference), date_format)
        return (event - dob).days

    def num(self, sheet: str, address: str) -> int | float | list[int | float]:
        if ":" in address:
            first, last = address.split(":")
            top, left = _coordinate(first)
            bottom, right = _coordinate(last)
            if (
                bottom < top
                or right < left
                or (bottom - top + 1) * (right - left + 1) > MAX_ITEMS
            ):
                raise ValueError("Invalid or excessive numeric range")
            return [
                self.num(sheet, _address(row, col))
                for row in range(top, bottom + 1)
                for col in range(left, right + 1)
            ]
        value = self.cell(sheet, address)
        if isinstance(value, bool) or value is None:
            raise ValueError(f"Not a numeric measure: {sheet}!{address}")
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("(") and value.endswith(")"):
                value = "-" + value[1:-1]
            if not re.fullmatch(
                r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?",
                value,
            ):
                raise ValueError(
                    f"Ambiguous numeric text at {sheet}!{address}: {value!r}. Use data_rows with the observed numeric columns to exclude headers before calling num; do not coerce a header to zero."
                )
            value = float(value.replace(",", ""))
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Not a finite number: {sheet}!{address}")
        return value

    def label(self, sheet: str, address: str) -> Any:
        """Resolve a merged text label without duplicating numeric measures."""
        if re.fullmatch(r"[A-Za-z]+", address):
            column = address.upper()
            path = self.data[sheet].get("headers", {}).get(column)
            if not path:
                raise ValueError("No verified header path for requested column")
            leaf = path[-1]
            for candidate, entry in self.data[sheet]["cells"].items():
                value = " ".join(
                    re.sub(
                        r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])", "", str(entry["value"])
                    ).split()
                )
                if value != leaf:
                    continue
                _, col = _coordinate(candidate)
                if col == _coordinate(column + "1")[1]:
                    self.cell(sheet, candidate)
                    return leaf
                for area in self.data[sheet]["merges"]:
                    first, last = area.split(":")
                    if (
                        first == candidate
                        and _coordinate(first)[1]
                        <= _coordinate(column + "1")[1]
                        <= _coordinate(last)[1]
                    ):
                        self.cell(sheet, candidate)
                        return leaf
            raise ValueError(
                "Header hint has no source cell; request an explicit address"
            )
        value = self.cell(sheet, address)
        if value is not None:
            return value
        row, col = _coordinate(address)
        for area in self.data[sheet]["merges"]:
            first, last = area.split(":")
            top, left = _coordinate(first)
            bottom, right = _coordinate(last)
            if top <= row <= bottom and left <= col <= right:
                source = self.cell(sheet, first)
                if isinstance(source, str):
                    return source
        return None

    def rows(self, sheet: str) -> list[int]:
        anchors: dict[int, str] = {}
        for address in self.data[sheet]["cells"]:
            anchors.setdefault(_coordinate(address)[0], address)
        for address in anchors.values():
            entry = self.data[sheet]["cells"][address]
            self.reads.setdefault(
                f"{sheet}!{address}",
                {
                    "kind": "type_probe",
                    "stored_kind": entry["kind"],
                    "value": None,
                    "operation": "row-presence",
                },
            )
        return sorted(anchors)

    def data_rows(
        self,
        sheet: str,
        columns: list[str] | dict[str, str],
        kind: str | int = "number",
        end_row: int | None = None,
        *,
        start_row: int | None = None,
    ) -> list[int]:
        """Select rows by explicit stored types; titles/footnotes cannot masquerade as data."""
        if type(kind) is int:
            if not isinstance(columns, dict) or start_row is not None:
                raise ValueError(
                    "Positional row bounds require a typed column dictionary; otherwise use start_row/end_row keywords"
                )
            start_row, kind = kind, "number"
        first = 1 if start_row is None else start_row
        last = 1_048_576 if end_row is None else end_row
        if (
            type(first) is not int
            or type(last) is not int
            or not 1 <= first <= last <= 1_048_576
        ):
            raise ValueError("data_rows bounds must be ordered Excel row indices")
        required = (
            dict.fromkeys(columns, kind) if isinstance(columns, list) else columns
        )
        if not required or any(
            value not in {"number", "datetime", "string", "boolean"}
            for value in required.values()
        ):
            raise ValueError("data_rows needs explicit columns and a supported kind")
        candidates = []
        date_mismatches = []
        if self.data[sheet]["cells"]:
            present = {_coordinate(address)[1] for address in self.data[sheet]["cells"]}
            for column in required:
                if _coordinate(column.upper() + "1")[1] not in present:
                    raise ValueError(
                        f"data_rows column {column!r} has no stored cells in {sheet!r}; use actual workbook columns instead of treating an invalid selection as zero"
                    )
        for row in self.rows(sheet):
            if not first <= row <= last:
                continue
            kinds = []
            for column in required:
                address = column.upper() + str(row)
                _coordinate(address)
                entry = self.data[sheet]["cells"].get(address, {})
                stored = entry.get("kind", "blank")
                self.reads.setdefault(
                    f"{sheet}!{address}",
                    {"kind": "type_probe", "stored_kind": stored, "value": None},
                )
                if stored == "uncached_formula":
                    value = self.cell(sheet, address)
                    stored = (
                        "number"
                        if isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        else "string"
                        if isinstance(value, str)
                        else "datetime"
                        if isinstance(value, datetime.datetime)
                        else "blank"
                    )
                kinds.append(stored)
            if all(
                stored == expected
                for stored, expected in zip(kinds, required.values(), strict=True)
            ):
                candidates.append(row)
            elif all(
                stored == expected or (stored == "datetime" and expected == "string")
                for stored, expected in zip(kinds, required.values(), strict=True)
            ):
                date_mismatches.append(row)
        if not candidates and date_mismatches:
            raise TypeError(
                "data_rows matched no rows because typed datetime cells were requested as string; "
                "use kind 'datetime' for date columns, or inspect types explicitly to count string-only records"
            )
        return candidates

    def age_order(
        self,
        sheet: str,
        birth: str,
        reference: str,
        descending: bool = False,
        date_format: str | None = None,
    ) -> list[int]:
        """Order elapsed ages using each row's own date; preserve intraday precision."""
        ages = {}
        for row in self.rows(sheet):
            addresses = [column.upper() + str(row) for column in (birth, reference)]
            entries = [
                self.data[sheet]["cells"].get(address, {}) for address in addresses
            ]
            raw = [entry.get("value") for entry in entries]
            for address, entry in zip(addresses, entries, strict=True):
                self.reads.setdefault(
                    f"{sheet}!{address}",
                    {
                        "kind": "type_probe",
                        "stored_kind": entry.get("kind", "blank"),
                        "value": None,
                    },
                )
            if any(value is None for value in raw):
                continue
            # Inspect genuine date-like records, not title/header strings or unrelated tables.
            date_like = [
                entry.get("kind") == "datetime"
                or isinstance(value, str)
                and bool(re.search(r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}", value))
                for entry, value in zip(entries, raw, strict=True)
            ]
            if not any(date_like) and date_format is None:
                continue
            if (
                date_format is not None
                and not any(date_like)
                and not any(re.search(r"\d", str(value)) for value in raw)
            ):
                continue
            dob, event = [
                stored_datetime(self.cell(sheet, address), date_format)
                for address in addresses
            ]
            ages[row] = (event - dob).total_seconds() / 86400
        return self.sorter(
            list(ages),
            key=lambda row: ages[row],
            reverse=descending,
        )

    def category_rows(
        self, sheet: str, label_column: str, measure_column: str
    ) -> list[int]:
        """Rank labelled numeric categories without treating the grand total as one."""
        return [
            row
            for row in self.data_rows(
                sheet, {label_column: "string", measure_column: "number"}
            )
            if not re.match(
                r"^\s*(?:Total|All)\b",
                self.cell(sheet, label_column + str(row)),
                re.IGNORECASE,
            )
        ]

    def latest_rows(
        self,
        sheet: str,
        key_column: str,
        time_column: str,
        *,
        date_format: str | None = None,
        ties: str = "error",
        start_row: int | None = None,
        end_row: int | None = None,
    ) -> list[int]:
        """Select maximum timestamp per typed entity key, retaining original row indices."""
        if ties not in {"error", "first", "last"}:
            raise ValueError("latest_rows ties must be error, first or last")
        first = 1 if start_row is None else start_row
        last = 1_048_576 if end_row is None else end_row
        if (
            type(first) is not int
            or type(last) is not int
            or not 1 <= first <= last <= 1_048_576
        ):
            raise ValueError("latest_rows bounds must be ordered Excel row indices")
        columns = [key_column.upper(), time_column.upper()]
        if any(not re.fullmatch(r"[A-Z]+", column) for column in columns):
            raise ValueError(
                "latest_rows requires original column letters, not addresses"
            )
        data = self.data[sheet]
        present = {_coordinate(address)[1] for address in data["cells"]}
        if any(_coordinate(column + "1")[1] not in present for column in columns):
            raise ValueError("latest_rows requires existing workbook columns")
        selected: dict[tuple[str, Any], tuple[datetime.datetime, int]] = {}
        dated_rows: list[int] = []
        missing_rows: list[int] = []
        header_rows: list[int] = []
        ambiguous: set[tuple[str, Any]] = set()
        captions = {
            " ".join(str(value).split()).casefold()
            for value in data.get("headers", {}).get(columns[1], [])
        }
        for row in self.rows(sheet):
            if not first <= row <= last:
                continue
            key_address, time_address = [column + str(row) for column in columns]
            key_entry = data["cells"].get(key_address, {})
            time_entry = data["cells"].get(time_address, {})
            if (
                key_entry.get("value") is None
                and time_entry.get("value") is None
                and time_entry.get("kind") != "uncached_formula"
            ):
                continue
            value = (
                self.cell(sheet, time_address)
                if time_entry.get("kind") == "uncached_formula"
                else time_entry.get("value")
            )
            if value is None:
                missing_rows.append(row)
                continue
            if (
                time_entry.get("kind") == "string"
                and " ".join(str(value).split()).casefold() in captions
            ):
                header_rows.append(row)
                continue
            timestamp = stored_datetime(self.cell(sheet, time_address), date_format)
            key = self.label(sheet, key_address)
            if key is None:
                raise ValueError("A dated record has no entity key")
            kind = (
                "number"
                if isinstance(key, (int, float)) and not isinstance(key, bool)
                else type(key).__name__
            )
            identity = (kind, key)
            dated_rows.append(row)
            prior = selected.get(identity)
            if prior is None or timestamp > prior[0]:
                selected[identity] = (timestamp, row)
                ambiguous.discard(identity)
            elif timestamp == prior[0]:
                if ties == "error":
                    ambiguous.add(identity)
                if ties == "last":
                    selected[identity] = (timestamp, row)
        if ambiguous:
            raise ValueError("Equal latest timestamps require an explicit tie policy")
        first_dated = min(dated_rows, default=last)
        lower = (
            first
            if start_row is not None
            else max(
                (row for row in header_rows if row < first_dated), default=first - 1
            )
            + 1
        )
        upper = (
            last
            if end_row is not None
            else max([*dated_rows, *missing_rows], default=last)
        )
        if any(lower <= row <= upper for row in missing_rows):
            raise ValueError(
                "A keyed record inside the dated table has no timestamp; latest selection is undefined"
            )
        return sorted(row for _, row in selected.values())

    def argmax(
        self, sheet: str, area: str, minimum: bool = False, absolute: bool = False
    ) -> str:
        first, last = area.split(":") if ":" in area else (area, area)
        top, left = _coordinate(first)
        bottom, right = _coordinate(last)
        if (
            bottom < top
            or right < left
            or (bottom - top + 1) * (right - left + 1) > MAX_ITEMS
        ):
            raise ValueError("Invalid or excessive extrema range")
        candidates = []
        for row in range(top, bottom + 1):
            for col in range(left, right + 1):
                address = _address(row, col)
                entry = self.data[sheet]["cells"].get(address, {})
                if entry.get("kind") in {"uncached_formula", "error"}:
                    # A missing/unsupported cache or Excel error must not silently
                    # disappear from an extrema calculation.
                    value = self.cell(sheet, address)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        candidates.append(address)
                elif entry.get("kind") == "number":
                    candidates.append(address)
        if not candidates:
            raise ValueError("No numeric cells in extrema range")
        return (min if minimum else max)(
            candidates,
            key=lambda address: (
                abs(self.num(sheet, address)) if absolute else self.num(sheet, address)
            ),
        )

    def find_rows(self, sheet: str, column: str, label: str) -> list[int]:
        def canonical(value: Any) -> str:
            return " ".join(
                re.sub(r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])", "", str(value)).split()
            ).casefold()

        target = canonical(label)
        matches = []
        for address, entry in self.data[sheet]["cells"].items():
            row, col = _coordinate(address)
            if col != _coordinate(column.upper() + "1")[1] or entry["kind"] != "string":
                continue
            value = canonical(entry["value"])
            if value == target or value.startswith((target + " ", target + "(")):
                self.reads.setdefault(
                    f"{sheet}!{address}",
                    {
                        "kind": "lookup_probe",
                        "value": entry["value"],
                        "stored_kind": "string",
                    },
                )
                matches.append(row)
        return sorted(matches)

    def formula(self, sheet: str, formula: str) -> Any:
        """Evaluate arithmetic, references and common range aggregates; no guesses."""
        token = re.compile(
            r'(?P<string>"(?:[^"]|"")*")'
            r"|(?P<ref>(?:(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?\$?[A-Z]+\$?[1-9]\d*(?::\$?[A-Z]+\$?[1-9]\d*)?)(?!\w)"
            r"|(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
            r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<operator>[+*/(),-])"
        )
        source = formula.lstrip("=").strip()
        parts = []
        position = 0
        while position < len(source):
            if source[position].isspace():
                position += 1
                continue
            match = token.match(source, position)
            if match is None:
                raise ValueError("Unsupported uncached Excel formula syntax")
            text = match[0]
            if match.lastgroup == "ref":
                target, address = text.rsplit("!", 1) if "!" in text else (sheet, text)
                if target.startswith("'"):
                    target = target[1:-1].replace("''", "'")
                if "!" in text:
                    # Planner namespaces relocate explicit sheet references only;
                    # unqualified references already refer to the current sheet.
                    target = (
                        self.data[sheet]
                        .get("formula_sheet_aliases", {})
                        .get(target, target)
                    )
                address = address.replace("$", "")
                helper = "values" if ":" in address else "cell"
                text = f"{helper}({target!r}, {address!r})"
            elif match.lastgroup == "string":
                text = json.dumps(text[1:-1].replace('""', '"'))
            parts.append(text)
            position = match.end()
        expression = "".join(parts)

        def numbers(*items: Any) -> list[int | float]:
            result = []
            for item in items:
                for value in item if isinstance(item, list) else [item]:
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        result.append(value)
                    if len(result) > MAX_ITEMS:
                        raise ValueError("Excessive formula aggregate")
            return result

        env = {
            "cell": self.cell,
            "values": self.values,
            "SUM": lambda *items: sum(numbers(*items)),
            "AVERAGE": lambda *items: statistics.mean(numbers(*items)),
            "MIN": lambda *items: min(numbers(*items), default=0),
            "MAX": lambda *items: max(numbers(*items), default=0),
            "COUNT": lambda *items: len(numbers(*items)),
        }
        return Interpreter(env).evaluate(ast.parse(expression, mode="eval").body, env)


class FlowSignal(Exception):
    def __init__(self, action: str, value: Any = None) -> None:
        self.action, self.value = action, value


class AuditedList(list[Any]):
    def __init__(self, values: list[Any], record: dict[str, Any]) -> None:
        super().__init__(values)
        self.record = record

    def __getitem__(self, index: Any) -> Any:
        if isinstance(index, int):
            self.record["selected"].append(index if index >= 0 else len(self) + index)
        elif isinstance(index, slice):
            self.record["selected"].append(list(range(len(self)))[index])
        return super().__getitem__(index)


class Interpreter:
    def __init__(self, helpers: dict[str, Any], iterator_helpers: bool = False) -> None:
        self.env = {**BUILTINS, **MODULES, **helpers}
        self.iterator_helpers = iterator_helpers
        if iterator_helpers:
            self.env.update(next=next, iter=iter)
        self.steps = 0
        self.sorts: list[dict[str, Any]] = []
        self.sort_targets: dict[int, dict[str, Any]] = {}
        self.env["sorted"] = self.sorted_values

    def sorted_values(
        self, values: Any, key: Any = None, reverse: bool = False
    ) -> AuditedList:
        sequence = self.bounded(list(values))
        keys = [key(value) if key is not None else value for value in sequence]
        indices = sorted(
            range(len(sequence)), key=lambda index: keys[index], reverse=reverse
        )
        simple = [
            value[0] if isinstance(value, (tuple, list)) and value else value
            for value in keys
        ]
        record = {
            "keys": simple
            if all(
                isinstance(value, (int, float, str, datetime.datetime))
                for value in simple
            )
            else [],
            "reverse": reverse,
            "selected": [],
        }
        self.sorts.append(record)
        return AuditedList([sequence[index] for index in indices], record)

    def sort_in_place(
        self, sequence: list[Any], key: Any = None, reverse: bool = False
    ) -> None:
        ordered = self.sorted_values(sequence, key, reverse)
        sequence[:] = ordered
        self.sort_targets[id(sequence)] = ordered.record

    def tick(self) -> None:
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise TimeoutError("AST instruction limit exceeded")

    def insert_value(self, sequence: list[Any], index: int, value: Any) -> None:
        """Retain standard list insertion semantics within the worker item cap."""
        if len(sequence) >= MAX_ITEMS:
            raise MemoryError("List insertion exceeds item limit")
        sequence.insert(index, value)

    def update_set(self, target: set[Any], *sources: Iterable[Any]) -> None:
        """Consume ordinary iterable updates with both step and cardinality limits."""
        for source in sources:
            for value in source:
                self.tick()
                if len(target) >= MAX_ITEMS and value not in target:
                    raise MemoryError("Set update exceeds item limit")
                target.add(value)

    def set_relation(self, left: set[Any], relation: str, right: Iterable[Any]) -> bool:
        """Bound temporary sets made by the standard iterable relation methods."""
        other: set[Any] = set()
        self.update_set(other, right)
        return {
            "issubset": set.issubset,
            "issuperset": set.issuperset,
            "isdisjoint": set.isdisjoint,
        }[relation](left, other)

    def bounded(self, value: Any) -> Any:
        if (
            isinstance(value, (str, bytes, list, tuple, dict, set, frozenset, range))
            and len(value) > MAX_ITEMS
        ):
            raise MemoryError("Generated value exceeds item limit")
        if isinstance(value, int) and value.bit_length() > 4096:
            raise MemoryError("Generated integer exceeds bit limit")
        return value

    def bind(
        self,
        node: ast.AST,
        value: Any,
        env: dict[str, Any],
        origin: ast.AST | None = None,
    ) -> None:
        if isinstance(node, ast.Name):
            env[node.id] = self.bounded(value)
        elif isinstance(node, (ast.Tuple, ast.List)):
            if value is None or isinstance(
                value, (int, float, datetime.date, datetime.timedelta)
            ):
                source = (
                    f" from {ast.unparse(origin)[:180]}" if origin is not None else ""
                )
                raise TypeError(
                    f"Cannot unpack scalar {type(value).__name__} into {ast.unparse(node)[:180]} "
                    f"at line {getattr(node, 'lineno', '?')}{source}. "
                    "values() returns FLAT scalars even for a multi-column range. "
                    "When row tuples are required, replace that values(sheet,range) call with cells(sheet,range). "
                    "Keep values() for a flat vector; cell()/num() also return scalars."
                )
            values = list(value)
            if len(values) != len(node.elts):
                raise ValueError(
                    f"Unpacking length mismatch into {ast.unparse(node)[:180]} at line {getattr(node, 'lineno', '?')}: "
                    f"expected {len(node.elts)} items, got {len(values)}. "
                    "values() yields flat scalars; unpacking a string splits characters. Use cells() for row tuples, "
                    "or explicit string parsing if the question actually requests characters."
                )
            for target, item in zip(node.elts, values, strict=True):
                self.bind(target, item, env)
        elif isinstance(node, ast.Subscript):
            target = self.evaluate(node.value, env)
            target[self.evaluate(node.slice, env)] = value
        else:
            raise TypeError("Unsupported assignment target")

    def function(self, node: ast.FunctionDef | ast.Lambda, env: dict[str, Any]) -> Any:
        if (
            node.args.vararg
            or node.args.kwarg
            or node.args.kwonlyargs
            or node.args.posonlyargs
        ):
            raise ValueError("Use simple function parameters")
        names = [arg.arg for arg in node.args.args]
        defaults = [self.evaluate(value, env) for value in node.args.defaults]

        def call(*args: Any, **kwargs: Any) -> Any:
            local = dict(env)
            if len(args) > len(names) or set(kwargs) - set(names):
                raise TypeError("Invalid function arguments")
            local.update(
                dict(zip(names[-len(defaults) :], defaults, strict=True))
                if defaults
                else {}
            )
            local.update(zip(names, args, strict=False))
            local.update(kwargs)
            if any(name not in local for name in names):
                raise TypeError("Missing function arguments")
            if isinstance(node, ast.Lambda):
                return self.evaluate(node.body, local)
            try:
                self.block(node.body, local)
            except FlowSignal as signal:
                if signal.action == "return":
                    return signal.value
                raise
            return None

        return call

    def evaluate(self, node: ast.AST, env: dict[str, Any]) -> Any:
        self.tick()
        if isinstance(node, ast.Constant):
            return self.bounded(node.value)
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise NameError(f"Unknown name: {node.id}")
            return env[node.id]
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values = [self.evaluate(item, env) for item in node.elts]
            return (
                values
                if isinstance(node, ast.List)
                else tuple(values)
                if isinstance(node, ast.Tuple)
                else set(values)
            )
        if isinstance(node, ast.Dict):
            return {
                self.evaluate(k, env): self.evaluate(v, env)
                for k, v in zip(node.keys, node.values, strict=True)
            }
        if isinstance(node, ast.BinOp):
            left, right = self.evaluate(node.left, env), self.evaluate(node.right, env)
            if isinstance(node.op, ast.Mult):
                sequence, count = (
                    (left, right) if isinstance(right, int) else (right, left)
                )
                if (
                    isinstance(sequence, (str, list, tuple))
                    and isinstance(count, int)
                    and len(sequence) * count > MAX_ITEMS
                ):
                    raise MemoryError("Sequence multiplication exceeds limit")
            if isinstance(node.op, ast.Pow) and abs(right) > 4096:
                raise MemoryError("Exponent exceeds limit")
            return self.bounded(BINARY[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp):
            value = self.evaluate(node.operand, env)
            return {
                ast.Not: operator.not_,
                ast.USub: operator.neg,
                ast.UAdd: operator.pos,
            }[type(node.op)](value)
        if isinstance(node, ast.BoolOp):
            value = None
            for part in node.values:
                value = self.evaluate(part, env)
                if (isinstance(node.op, ast.And) and not value) or (
                    isinstance(node.op, ast.Or) and value
                ):
                    break
            return value
        if isinstance(node, ast.Compare):
            left = self.evaluate(node.left, env)
            for operation, part in zip(node.ops, node.comparators, strict=True):
                right = self.evaluate(part, env)
                if isinstance(operation, (ast.Eq, ast.NotEq)) and any(
                    isinstance(typed, datetime.date)
                    and isinstance(text, str)
                    and ISO_DATE.fullmatch(text.strip())
                    for typed, text in ((left, right), (right, left))
                ):
                    raise TypeError(
                        "Typed date compared with ISO text: this cannot match in Python. "
                        "Parse only the string literal with datetime.datetime.fromisoformat(), "
                        "or normalize both sides with isoformat(). Workbook datetime cells are "
                        "already typed: do not parse them again."
                    )
                if isinstance(operation, (ast.In, ast.NotIn)) and (
                    isinstance(left, CellArray)
                    and isinstance(right, (list, tuple))
                    and right
                    and all(isinstance(item, (str, int, float)) for item in right)
                    or isinstance(right, CellArray)
                    and any(isinstance(item, CellArray) for item in right)
                    and isinstance(left, (str, int, float))
                ):
                    raise TypeError(
                        "cells() returns a 2D list: scalar membership must use cell(), values(), "
                        "or cells(...)[row][column]; compare rows only with other rows."
                    )
                if isinstance(operation, (ast.Eq, ast.NotEq)) and (
                    isinstance(left, CellArray)
                    and isinstance(
                        right, (str, int, float, datetime.date, datetime.timedelta)
                    )
                    or isinstance(right, CellArray)
                    and isinstance(
                        left, (str, int, float, datetime.date, datetime.timedelta)
                    )
                ):
                    raise TypeError(
                        "cells() returns a 2D list: comparing its row/list to a scalar silently discards matches. "
                        "Use cell(sheet,address), values() for a flat column, or cells(...)[row][column]."
                    )
                if not COMPARE[type(operation)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return self.evaluate(
                node.body if self.evaluate(node.test, env) else node.orelse, env
            )
        if isinstance(node, ast.Slice):
            return slice(
                *(
                    self.evaluate(part, env) if part is not None else None
                    for part in (node.lower, node.upper, node.step)
                )
            )
        if isinstance(node, ast.Subscript):
            sequence, index = (
                self.evaluate(node.value, env),
                self.evaluate(node.slice, env),
            )
            if sequence is None or isinstance(
                sequence, (int, float, datetime.date, datetime.timedelta)
            ):
                raise TypeError(
                    f"Cannot index scalar {type(sequence).__name__} in {ast.unparse(node)[:180]} "
                    f"at line {getattr(node, 'lineno', '?')}. "
                    "cell()/num() return scalars; values() is FLAT, not rows. "
                    "If this variable comes from values(sheet,multi_column_range), replace the source "
                    "with cells(sheet,range) for 2D rows, or use the scalar directly; adding more indices cannot fix its shape."
                )
            record = self.sort_targets.get(id(sequence))
            if record is not None:
                if isinstance(index, int):
                    record["selected"].append(
                        index if index >= 0 else len(sequence) + index
                    )
                elif isinstance(index, slice):
                    record["selected"].append(list(range(len(sequence)))[index])
            return sequence[index]
        if isinstance(node, ast.Attribute):
            value = self.evaluate(node.value, env)
            if isinstance(value, datetime.datetime) and node.attr == "timestamp":
                # Excel dates are naive. Make epoch conversion portable instead
                # of inheriting the judge machine's local timezone/DST policy.
                return lambda: value.replace(
                    tzinfo=value.tzinfo or datetime.UTC
                ).timestamp()
            if isinstance(value, list) and node.attr == "sort":
                return lambda key=None, reverse=False: self.sort_in_place(
                    value, key, reverse
                )
            if isinstance(value, list) and node.attr == "insert":
                return partial(self.insert_value, value)
            if isinstance(value, set) and node.attr == "update":
                return partial(self.update_set, value)
            if isinstance(value, set) and node.attr in {
                "issubset",
                "issuperset",
                "isdisjoint",
            }:
                return partial(self.set_relation, value, node.attr)
            if isinstance(value, SimpleNamespace) and node.attr in vars(value):
                return getattr(value, node.attr)
            if value in (datetime.datetime, datetime.date) and node.attr in {
                "strptime",
                "fromisoformat",
                "fromordinal",
            }:
                return getattr(value, node.attr)
            if value is str and node.attr in METHODS[str]:
                return getattr(str, node.attr)
            if any(
                isinstance(value, kind) and node.attr in names
                for kind, names in METHODS.items()
            ):
                return getattr(value, node.attr)
            raise ValueError(f"Attribute not allowed: {node.attr}")
        if isinstance(node, ast.Call):
            fn = self.evaluate(node.func, env)
            if fn is MODULES["datetime"]:
                raise TypeError(
                    "datetime is a module namespace, not a constructor: use datetime.datetime(year,month,day), "
                    "or 'from datetime import datetime' before calling datetime(...)."
                )
            args = []
            for arg in node.args:
                if isinstance(arg, ast.Starred):
                    args.extend(self.evaluate(arg.value, env))
                else:
                    args.append(self.evaluate(arg, env))
            kwargs = {}
            for item in node.keywords:
                if item.arg is None:
                    kwargs.update(self.evaluate(item.value, env))
                else:
                    kwargs[item.arg] = self.evaluate(item.value, env)
            return self.bounded(fn(*args, **kwargs))
        if isinstance(node, ast.Lambda):
            return self.function(node, env)
        if isinstance(node, ast.GeneratorExp) and self.iterator_helpers:

            def generate(index: int, scope: dict[str, Any]) -> Iterator[Any]:
                if index == len(node.generators):
                    yield self.evaluate(node.elt, scope)
                    return
                gen = node.generators[index]
                for value in self.evaluate(gen.iter, scope):
                    local = dict(scope)
                    self.bind(gen.target, value, local, origin=gen.iter)
                    if all(self.evaluate(condition, local) for condition in gen.ifs):
                        yield from generate(index + 1, local)

            return generate(0, dict(env))
        if isinstance(
            node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            items = []

            def visit(index: int, scope: dict[str, Any]) -> None:
                if index == len(node.generators):
                    items.append(
                        (
                            self.evaluate(node.key, scope),
                            self.evaluate(node.value, scope),
                        )
                        if isinstance(node, ast.DictComp)
                        else self.evaluate(node.elt, scope)
                    )
                    self.bounded(items)
                    return
                gen = node.generators[index]
                for value in self.evaluate(gen.iter, scope):
                    local = dict(scope)
                    self.bind(gen.target, value, local, origin=gen.iter)
                    if all(self.evaluate(condition, local) for condition in gen.ifs):
                        visit(index + 1, local)

            visit(0, dict(env))
            return (
                dict(items)
                if isinstance(node, ast.DictComp)
                else set(items)
                if isinstance(node, ast.SetComp)
                else items
            )
        if isinstance(node, ast.JoinedStr):
            return "".join(str(self.evaluate(value, env)) for value in node.values)
        if isinstance(node, ast.FormattedValue):
            value = self.evaluate(node.value, env)
            if node.conversion == 114:
                value = repr(value)
            spec = self.evaluate(node.format_spec, env) if node.format_spec else ""
            return format(value, spec)
        raise ValueError(f"Unsupported expression: {type(node).__name__}")

    def block(self, nodes: list[ast.stmt], env: dict[str, Any]) -> None:
        for node in nodes:
            self.tick()
            if isinstance(node, ast.Assign):
                value = self.evaluate(node.value, env)
                for target in node.targets:
                    self.bind(target, value, env, origin=node.value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                self.bind(node.target, self.evaluate(node.value, env), env)
            elif isinstance(node, ast.AugAssign):
                self.bind(
                    node.target,
                    BINARY[type(node.op)](
                        self.evaluate(node.target, env), self.evaluate(node.value, env)
                    ),
                    env,
                )
            elif isinstance(node, ast.Expr):
                self.evaluate(node.value, env)
            elif isinstance(node, ast.If):
                self.block(
                    node.body if self.evaluate(node.test, env) else node.orelse, env
                )
            elif isinstance(node, ast.Raise):
                if node.exc is None or node.cause is not None:
                    raise ValueError(
                        "Use an explicit supported exception without chaining"
                    )
                error = self.evaluate(node.exc, env)
                supported = (ValueError, TypeError, RuntimeError)
                if error in supported:
                    error = error()
                if not isinstance(error, supported):
                    raise TypeError(
                        "Only ValueError, TypeError and RuntimeError may be raised"
                    )
                raise error
            elif isinstance(node, (ast.For, ast.While)):
                iterator = (
                    self.evaluate(node.iter, env)
                    if isinstance(node, ast.For)
                    else iter(int, 1)
                )
                broken = False
                for value in iterator:
                    self.tick()
                    if isinstance(node, ast.While):
                        if not self.evaluate(node.test, env):
                            break
                    else:
                        self.bind(node.target, value, env, origin=node.iter)
                    try:
                        self.block(node.body, env)
                    except FlowSignal as signal:
                        if signal.action == "break":
                            broken = True
                            break
                        if signal.action != "continue":
                            raise
                if not broken:
                    self.block(node.orelse, env)
            elif isinstance(node, ast.FunctionDef):
                if node.decorator_list:
                    raise ValueError("Decorators are not allowed")
                env[node.name] = self.function(node, env)
            elif isinstance(node, (ast.Return, ast.Break, ast.Continue)):
                action = {
                    ast.Return: "return",
                    ast.Break: "break",
                    ast.Continue: "continue",
                }[type(node)]
                raise FlowSignal(
                    action,
                    self.evaluate(node.value, env)
                    if isinstance(node, ast.Return) and node.value
                    else None,
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in MODULES:
                        raise ValueError(
                            f"Import not allowed: {alias.name}. Available modules: {', '.join(MODULES)}. "
                            "Use these modules or builtin lists/arithmetic; do not retry the unavailable module."
                        )
                    env[alias.asname or alias.name] = MODULES[alias.name]
            elif isinstance(node, ast.ImportFrom):
                if node.level or node.module not in MODULES:
                    rejected = "." * node.level + (node.module or "")
                    raise ValueError(
                        f"Import not allowed: {rejected}. Available modules: {', '.join(MODULES)}. "
                        "Use these modules or builtin lists/arithmetic; do not retry the unavailable module."
                    )
                for alias in node.names:
                    exports = vars(MODULES[node.module])
                    if alias.name not in exports:
                        raise ValueError(
                            f"Import not allowed: {node.module}.{alias.name}. "
                            f"Available names in {node.module}: {', '.join(exports)}. "
                            "Implement other operations with builtin lists/arithmetic."
                        )
                    env[alias.asname or alias.name] = exports[alias.name]
            elif not isinstance(node, ast.Pass):
                raise ValueError(f"Unsupported statement: {type(node).__name__}")

    def run(self, code: str, result_variable: str = "result") -> Any:
        code = normalise_program(code)
        tree = ast.parse(code)
        if len(code) > 50_000:
            raise ValueError("Program exceeds code size limit")
        for node in ast.walk(tree):
            if not isinstance(node, ALLOWED_NODES):
                raise TypeError(f"AST node not allowed: {type(node).__name__}")
            if isinstance(node, ast.Name) and node.id.startswith("__"):
                raise ValueError("Private identifiers are not allowed")
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                raise ValueError("Private attributes are not allowed")
        self.block(tree.body, self.env)
        for name in (result_variable, "result", "answer", "ans", "final_answer"):
            if name in self.env:
                result = self.env[name]
                encoded = json.dumps(result, allow_nan=False, default=_encode)
                if len(encoded.encode()) > MAX_OUTPUT_BYTES:
                    raise ValueError("Result exceeds output limit")
                if result is None or isinstance(result, (dict, set)):
                    raise ValueError("Final result must be a scalar or ordered list")
                return result
        raise ValueError(
            "Declare result explicitly; intermediate variables are not answers"
        )


def _encode(value: Any) -> str:
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    raise TypeError(f"Unsupported result type: {type(value).__name__}")


def _grounded(code: str, result_variable: str = "result") -> bool:
    """Reject literal results and unused reads; this is not a semantic proof."""
    dependencies: dict[str, set[str]] = {}

    def names(node: ast.AST) -> set[str]:
        return {
            item.id
            for item in ast.walk(node)
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
        }

    def inspect(nodes: list[ast.stmt], control: set[str]) -> None:
        for node in nodes:
            if (
                isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
                and node.value is not None
            ):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for target in targets:
                    for item in ast.walk(target):
                        if isinstance(item, ast.Name):
                            dependencies.setdefault(item.id, set()).update(
                                names(node.value) | control
                            )
            elif isinstance(node, ast.FunctionDef):
                dependencies[node.name] = names(node)
            elif isinstance(node, ast.If):
                inspect(node.body + node.orelse, control | names(node.test))
            elif isinstance(node, (ast.For, ast.While)):
                source = names(node.iter if isinstance(node, ast.For) else node.test)
                if isinstance(node, ast.For):
                    for item in ast.walk(node.target):
                        if isinstance(item, ast.Name):
                            dependencies.setdefault(item.id, set()).update(source)
                inspect(node.body + node.orelse, control | source)
            elif (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
            ):
                for item in ast.walk(node.value.func.value):
                    if isinstance(item, ast.Name):
                        dependencies.setdefault(item.id, set()).update(
                            names(node.value) | control
                        )

    inspect(ast.parse(code).body, set())
    queue = [
        name
        for name in (result_variable, "result", "answer", "ans", "final_answer")
        if name in dependencies
    ]
    visited: set[str] = set()
    while queue:
        name = queue.pop()
        if name in {
            "cell",
            "num",
            "cells",
            "values",
            "label",
            "rows",
            "text",
            "age_days",
            "find_rows",
            "data_rows",
            "age_order",
            "latest_rows",
            "argmax",
            "category_rows",
        }:
            return True
        if name not in visited:
            visited.add(name)
            queue.extend(dependencies.get(name, set()))
    return False


@dataclass
class ExecutionResult:
    success: bool
    result: Any = None
    error: str | None = None
    reads: dict[str, Any] = field(default_factory=dict)
    peak_memory_bytes: int = 0
    sorts: list[dict[str, Any]] = field(default_factory=list)


def execute_program(
    code: str,
    workbook: dict[str, Any] | None = None,
    timeout: float = 5,
    memory_mb: int = 256,
    result_variable: str = "result",
    iterator_helpers: bool = False,
) -> ExecutionResult:
    if type(iterator_helpers) is not bool:
        raise TypeError("iterator_helpers must be a boolean")
    payload = json.dumps(
        {
            "code": code,
            "workbook": workbook or {},
            "memory_mb": memory_mb,
            "result_variable": result_variable,
            "iterator_helpers": iterator_helpers,
        }
    ).encode()
    if len(payload) > 64 * 1024**2:
        return ExecutionResult(False, error="Worker payload exceeds memory budget")
    # Isolated Python and a clean environment: no API credentials reach the worker.
    process = subprocess.Popen(
        [sys.executable, "-I", str(Path(__file__).resolve())],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": os.defpath},
    )
    peak = 0
    stopped = threading.Event()
    exceeded = threading.Event()

    def monitor() -> None:
        nonlocal peak
        proc = psutil.Process(process.pid)
        while not stopped.wait(0.02):
            try:
                peak = max(peak, proc.memory_info().rss)
                if peak > memory_mb * 1024**2:
                    exceeded.set()
                    process.kill()
                    return
            except psutil.NoSuchProcess:
                return

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        output, stderr = process.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return ExecutionResult(
            False, error="Code execution timed out", peak_memory_bytes=peak
        )
    finally:
        stopped.set()
        thread.join()
    if exceeded.is_set():
        return ExecutionResult(
            False, error="Worker memory limit exceeded", peak_memory_bytes=peak
        )
    if process.returncode or len(output) > MAX_OUTPUT_BYTES:
        return ExecutionResult(
            False,
            error=f"Worker failed ({process.returncode}): {stderr.decode()[:300]}",
            peak_memory_bytes=peak,
        )
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return ExecutionResult(
            False, error="Invalid worker response", peak_memory_bytes=peak
        )
    worker_peak = data.pop("worker_peak_bytes", 0)
    return ExecutionResult(**data, peak_memory_bytes=max(peak, worker_peak))


def execute_code(code: str) -> tuple[bool, Any, str | None]:
    """Execute Python in a worker and accept only explicit result variables."""
    result = execute_program(code)
    return result.success, result.result, result.error


def _worker() -> None:
    payload = json.load(sys.stdin)
    if sys.platform == "linux":
        import resource

        limit = payload["memory_mb"] * 1024**2
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    access = WorkbookAccess(payload["workbook"])
    interpreter = Interpreter(
        {
            "cell": access.cell,
            "num": access.num,
            "cells": access.cells,
            "values": access.values,
            "age_days": access.age_days,
            "label": access.label,
            "rows": access.rows,
            "find_rows": access.find_rows,
            "data_rows": access.data_rows,
            "age_order": access.age_order,
            "latest_rows": access.latest_rows,
            "argmax": access.argmax,
            "category_rows": access.category_rows,
            "sheets": list(access.data),
        },
        iterator_helpers=payload.get("iterator_helpers", False),
    )
    access.sorter = interpreter.sorted_values
    try:
        result = interpreter.run(payload["code"], payload["result_variable"])
        if access.data and not _grounded(
            normalise_program(payload["code"]), payload["result_variable"]
        ):
            raise ValueError("Final result does not depend on workbook reads")
        data = {"success": True, "result": result, "error": None, "reads": access.reads}
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        NameError,
        SyntaxError,
        ArithmeticError,
        AttributeError,
        MemoryError,
        TimeoutError,
        RecursionError,
        RuntimeError,
        FlowSignal,
        StopIteration,
    ) as error:
        data = {
            "success": False,
            "result": None,
            "error": f"{type(error).__name__}: {error}",
            "reads": access.reads,
        }
    data["sorts"] = interpreter.sorts
    data["worker_peak_bytes"] = psutil.Process().memory_info().rss
    sys.stdout.write(json.dumps(data, default=_encode, allow_nan=False))


if __name__ == "__main__":
    _worker()
