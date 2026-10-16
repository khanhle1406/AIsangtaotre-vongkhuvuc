"""Disclosed numeric sampling for program planning; the executor keeps every cell."""

import json
from collections import defaultdict
from dataclasses import replace
from typing import Any

from openpyxl.utils import coordinate_to_tuple, range_boundaries

from src.excel_parser import WorkbookData

from .efficient import dense_text, metadata_ranges


def backend_view(
    workbook: WorkbookData,
    wire: dict[str, Any],
    *,
    column_catalog: bool = True,
    deduplicate_headers: bool = False,
) -> str:
    """Keep text, dates, formulas, errors and schema; sample only long numeric columns."""
    sheets = {}
    omitted: dict[str, dict[str, Any]] = {}
    for name, sheet in workbook.sheets.items():
        metadata = wire[name]
        tables = [range_boundaries(t["range"]) for t in metadata["tables"]]
        headings = {
            label
            for headers in [
                metadata["headers"],
                *[t["headers"] for t in metadata["tables"]],
            ]
            for path in headers.values()
            for label in path
        }
        columns: dict[tuple[int | None, int], list[tuple[int, str]]] = defaultdict(list)
        for address, cell in sheet.cells.items():
            if cell.kind != "number" or cell.formula or str(cell.value) in headings:
                continue
            row, column = coordinate_to_tuple(address)
            regions = [
                i
                for i, (left, top, right, bottom) in enumerate(tables)
                if left <= column <= right and top <= row <= bottom
            ]
            if len(regions) > 1:
                continue  # Ambiguous table hints do not justify sampling this cell.
            columns[regions[0] if regions else None, column].append((row, address))
        dropped = {
            address
            for entries in columns.values()
            if len(entries) >= 8
            for _, address in sorted(entries)[2:-1]
        }
        sheets[name] = replace(
            sheet,
            cells={
                address: cell
                for address, cell in sheet.cells.items()
                if address not in dropped
            },
        )
        if not dropped:
            continue
        attributes: dict[str, list[str]] = defaultdict(list)
        for address in sorted(dropped, key=coordinate_to_tuple):
            schema = sheet.cells[address].wire()
            del schema["value"]
            attributes[
                json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            ].append(address)
        omitted[name] = {
            "stored_cells": len(sheet.cells),
            "visible_cells": len(sheet.cells) - len(dropped),
            "omitted_numeric_values": len(dropped),
            "omitted_cell_schema": [
                {"ranges": metadata_ranges(addresses), "attributes": json.loads(schema)}
                for schema, addresses in attributes.items()
            ],
        }
    if not omitted:
        return dense_text(
            workbook,
            wire,
            column_catalog=column_catalog,
            deduplicate_headers=deduplicate_headers,
        )
    projected = (
        "BACKEND PROGRAM VIEW: all original cells remain in Python. Numeric values in long "
        "columns are SAMPLED (first two and last eligible cells per original table/column). "
        "All text labels, dates, booleans, errors, formulas, merges, header paths, units and "
        "nondefault metadata are retained. Omitted coordinates below are stored numeric cells, "
        "NOT blanks or zero. Never select a maximum, rank, total or predicate from sampled values; "
        "write code reading the complete original ranges/rows. If source meaning is unclear, use "
        "request_regions to inspect original cells before computing. Sampling changes only this "
        "view, never helper results or row bounds.\n"
        + dense_text(
            WorkbookData(sheets),
            wire,
            column_catalog=column_catalog,
            deduplicate_headers=deduplicate_headers,
            complete=False,
        )
        + "\nOMITTED NUMERIC CELL CATALOG (original coordinates and metadata): "
        + json.dumps(omitted, ensure_ascii=False, separators=(",", ":"))
    )
    full = dense_text(
        workbook,
        wire,
        column_catalog=column_catalog,
        deduplicate_headers=deduplicate_headers,
    )
    return projected if len(projected.encode()) < len(full.encode()) else full
