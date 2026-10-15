"""Independent controlled transformations; no solver or competition answers involved."""

import csv
import json
from pathlib import Path

import openpyxl


def generate(root: Path) -> tuple[Path, Path]:
    files = root / "xlsx_files"
    files.mkdir(parents=True, exist_ok=True)
    queries = []
    references = []
    # Each single transformation has a declared invariant or a known numeric delta.
    for index, (offset, name_col, measure_col, noise, delta) in enumerate(
        [
            (0, 1, 2, False, 0),
            (0, 1, 2, False, 0),
            (307, 1, 2, False, 0),
            (0, 4, 2, False, 0),
            (7, 2, 5, True, 0),
            (307, 4, 2, True, 11),
        ]
    ):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Current" if index == 0 else f"Ledger {index + 51}"
        for row, name, measure in [
            (1, "Company", "Units sold"),
            (2, "Lyra Co.", 37 + delta),
            (3, "Vega Inc.", 89 + delta),
        ]:
            ws.cell(offset + row, name_col, name)
            ws.cell(offset + row, measure_col, measure)
        ws.cell(
            offset + 5, name_col, "Current period, units; excludes previous period."
        )
        if noise:
            other = wb.create_sheet("Previous period")
            other.append(["Company", "Units sold"])
            other.append(["Lyra Co.", 9999])
        file = f"mutation_{index * 17 + 103}.xlsx"
        wb.save(files / file)
        wb.close()
        key = f"changed-{index * 37 + 701}"
        queries.append(
            {
                "id": key,
                "file_name": file,
                "query": "How many units did Lyra Co. sell in the current period? Answer with only the integer.",
                "family": "metamorphic-invoice",
            }
        )
        references.append({"id": key, "answer": str(37 + delta)})
    qpath, rpath = root / "queries.json", root / "references.csv"
    qpath.write_text(json.dumps(queries, indent=2))
    with rpath.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "answer"])
        writer.writeheader()
        writer.writerows(references)
    return qpath, rpath
