"""Explicit, expandable workbook views when full input cannot fit model context."""

import json
import re
from collections import Counter
from typing import Any

from openpyxl.utils import coordinate_to_tuple, get_column_letter, range_boundaries


def cell_line(name: str, address: str, entry: dict[str, Any]) -> str:
    return f"{name!r}!{address} " + json.dumps(
        entry, ensure_ascii=False, separators=(",", ":")
    )


def project_workbook(
    workbook: dict[str, Any], query: str, max_bytes: int = 80_000
) -> str:
    """Retrieve labelled context; no data is removed from the executor's workbook."""
    lines = [
        (
            "EXPANDABLE WORKBOOK VIEW: this is a retrieved projection, NOT all cells. "
            "All original cells remain accessible to cell/num/rows/data_rows/find_rows in Python. "
            "Before answering, if more headers/values are needed, return JSON "
            '{"code":"result=0","request_regions":[{"sheet":"actual sheet","range":"A1:D20"}]}. '
            "The application supplies those original cells in the next turn. "
            "Inspection shares the three-inference limit; request narrow regions together."
        )
    ]
    used = len(lines[0].encode())
    candidates = []
    words = {word for word in re.findall(r"\w+", query.casefold()) if len(word) >= 3}
    count = 0
    for name, sheet in workbook.items():
        count += len(sheet["cells"])
        positions = [coordinate_to_tuple(address) for address in sheet["cells"]]
        if not positions:
            continue
        bottom, right = (
            max(row for row, _ in positions),
            max(col for _, col in positions),
        )
        summary = f"SHEET {name!r}: {len(positions)} stored cells, extent A1:{get_column_letter(right)}{bottom}, types={dict(Counter(e['kind'] for e in sheet['cells'].values()))}."
        if used + len(summary.encode()) > max_bytes:
            raise ValueError("Workbook sheet catalog exceeds explicit context budget")
        lines.append(summary)
        used += len(summary.encode()) + 1
        for address, entry in sheet["cells"].items():
            row, col = coordinate_to_tuple(address)
            text = str(entry["value"]).casefold()
            relevance = (
                len(words & set(re.findall(r"\w+", text)))
                if entry["kind"] == "string"
                else 0
            )
            priority = (
                relevance * 100
                + (20 if row <= 12 else 0)
                + (5 if entry["kind"] == "string" else 0)
            )
            if priority:
                candidates.append((-priority, name, row, col, address, entry))
    visible = 0
    for _, name, _, _, address, entry in sorted(candidates, key=lambda item: item[:4]):
        line = cell_line(name, address, entry)
        size = len(line.encode()) + 1
        if used + size > max_bytes:
            continue
        lines.append(line)
        used += size
        visible += 1
    lines.append(
        f"Projection includes {visible}/{count} stored cells; {count - visible} omitted from this VIEW only. Request regions or compute over the complete backend; do not treat this view as a full data range."
    )
    return "\n".join(lines)


def inspect_regions(
    workbook: dict[str, Any], regions: list[dict[str, str]], max_bytes: int = 80_000
) -> str:
    """Return complete sparse requested regions, or explicitly reject excess output."""
    lines = []
    used = 0
    for selection in regions:
        name, area = selection["sheet"], selection["range"]
        if name not in workbook or not re.fullmatch(
            r"[A-Z]+[1-9]\d*(?::[A-Z]+[1-9]\d*)?", area
        ):
            raise ValueError(
                "Inspection requires an existing sheet and explicit cell/range"
            )
        left, top, right, bottom = range_boundaries(area)
        if not 1 <= left <= right <= 16384 or not 1 <= top <= bottom <= 1048576:
            raise ValueError("Inspection range is outside Excel bounds")
        header = f"REGION {name!r}!{area}: all stored cells below; absent coordinates are blank. MERGES={workbook[name].get('merges', [])!r}"
        lines.append(header)
        used += len(header.encode()) + 1
        for address, entry in workbook[name]["cells"].items():
            row, col = coordinate_to_tuple(address)
            if left <= col <= right and top <= row <= bottom:
                line = cell_line(name, address, entry)
                used += len(line.encode()) + 1
                if used > max_bytes:
                    raise ValueError(
                        "Requested inspection exceeds view budget; request narrower regions; no partial region was returned"
                    )
                lines.append(line)
        if used > max_bytes:
            raise ValueError("Requested region metadata exceeds view budget")
    return "\n".join(lines)
