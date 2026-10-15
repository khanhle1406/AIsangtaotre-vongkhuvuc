"""Sixty sealed oracle tasks in ten independently constructed workbook families."""

import csv
import datetime as dt
import hashlib
import json
import random
import statistics
from pathlib import Path
from typing import Any

import openpyxl


def generate(root: Path, seed: int = 2026101507) -> None:
    """Freeze source-independent arithmetic answers before candidate selection."""
    if root.exists():
        raise ValueError("Refuse to overwrite a sealed dataset")
    files = root / "xlsx_files"
    files.mkdir(parents=True)
    rng = random.Random(seed)
    queries: list[dict[str, Any]] = []
    answers: list[dict[str, str]] = []
    manifests = []

    def save(
        family: str,
        tables: list[tuple[str, list[list[Any]]]],
        cases: list[tuple[str, str]],
    ) -> None:
        book = openpyxl.Workbook()
        book.remove(book.active)
        for name, rows in tables:
            sheet = book.create_sheet(name)
            offset = rng.choice([3, 17, 263, 419])
            column_offset = rng.choice([0, 2, 4])
            for r, values in enumerate(rows, offset):
                for c, value in enumerate(values, column_offset + 1):
                    cell = sheet.cell(r, c, value)
                    if isinstance(value, dt.datetime):
                        cell.number_format = "yyyy-mm-dd hh:mm"
            sheet.cell(1, 12, "Audited source; only the named reporting scope applies.")
        noise = book.create_sheet("Archived distraction")
        noise.append(["Reporting scope", "obsolete", "Total", 999999])
        name = f"ledger_{rng.randrange(100000, 999999)}.xlsx"
        book.save(files / name)
        book.close()
        for query, answer in cases:
            key = f"unseen-{len(queries) + 1:03d}"
            queries.append(
                {"id": key, "file_name": name, "query": query, "family": family}
            )
            answers.append({"id": key, "answer": answer})
        manifests.append({"file": name, "family": family, "questions": len(cases)})

    # Orders require a cross-sheet join; quantities, returns, prices and FX are separate.
    skus = ["Kestrel", "Lumen", "Rivet", "Solace"]
    prices = [rng.randrange(9, 35) for _ in skus]
    quantities = [rng.randrange(12, 31) for _ in skus]
    returns = [rng.randrange(1, 6) for _ in skus]
    net = [q - r for q, r in zip(quantities, returns, strict=True)]
    revenue = [q * p for q, p in zip(net, prices, strict=True)]
    save(
        "catalog_join",
        [
            (
                "Catalog",
                [
                    ["SKU", "Price EUR"],
                    *[[s, p] for s, p in zip(skus, prices, strict=True)],
                ],
            ),
            (
                "Fulfilment",
                [
                    ["SKU", "Shipped", "Returned"],
                    *[
                        [s, q, r]
                        for s, q, r in zip(skus, quantities, returns, strict=True)
                    ],
                ],
            ),
            ("FX", [["Currency", "USD per EUR"], ["EUR", 1.25]]),
        ],
        [
            (
                "Using Fulfilment and Catalog, what is total revenue in EUR after subtracting Returned units from Shipped units for each SKU? Answer only the integer.",
                str(sum(revenue)),
            ),
            (
                "Using Fulfilment, how many units were retained across all SKUs (Shipped minus Returned)? Answer only the integer.",
                str(sum(net)),
            ),
            (
                "Using Catalog and Fulfilment, which SKU has the highest revenue after returns in EUR? Break ties alphabetically. Answer only the SKU.",
                min(skus, key=lambda s: (-revenue[skus.index(s)], s)),
            ),
            (
                "Using Catalog, Fulfilment and FX, calculate total revenue after returns in actual USD. Answer to two decimal places, without currency symbol.",
                f"{sum(revenue) * 1.25:.2f}",
            ),
            (
                "What percentage of all Shipped units were Returned in Fulfilment? Answer to two decimal places, without percent sign.",
                f"{100 * sum(returns) / sum(quantities):.2f}",
            ),
            (
                "For Lumen only, what is revenue after returns in EUR using Catalog and Fulfilment? Answer only the integer.",
                str(revenue[1]),
            ),
        ],
    )

    # Explicit missing observations, zeros, duplicate scores and deterministic tie policy.
    scores = [0, 14, None, 26, 14, 31, None, 8, 26, 19]
    labels = [f"Member-{n + 21}" for n in range(len(scores))]
    observed = [s for s in scores if s is not None]
    positive = [s for s in observed if s > 0]
    save(
        "missing_distribution",
        [
            (
                "Observations",
                [
                    ["Member", "Score"],
                    *[[n, s] for n, s in zip(labels, scores, strict=True)],
                ],
            )
        ],
        [
            (
                "In Observations, how many members have a recorded Score, including zero but excluding blanks? Answer only the integer.",
                str(len(observed)),
            ),
            (
                "In Observations, what is the median of recorded Score values, including zero and excluding blanks? Answer to two decimal places.",
                f"{statistics.median(observed):.2f}",
            ),
            (
                "In Observations, what is the average Score among strictly positive recorded values? Answer to two decimal places.",
                f"{statistics.mean(positive):.2f}",
            ),
            (
                "In Observations, how many members have a blank Score? Answer only the integer.",
                str(len(scores) - len(observed)),
            ),
            (
                "In Observations, list all members whose Score is 26, sorted alphabetically, separated by comma and space.",
                ", ".join(
                    sorted(n for n, s in zip(labels, scores, strict=True) if s == 26)
                ),
            ),
            (
                "In Observations, what is the range of recorded Scores (maximum minus minimum), including zero? Answer only the integer.",
                str(max(observed) - min(observed)),
            ),
        ],
    )

    # Cross-midnight intervals and deadline comparisons use exact typed timestamps.
    names = ["Shift A", "Shift B", "Shift C", "Shift D"]
    starts = [
        dt.datetime(2027, 3, 5, 22, 30),
        dt.datetime(2027, 3, 6, 8),
        dt.datetime(2027, 3, 7, 23, 45),
        dt.datetime(2027, 3, 8, 9, 15),
    ]
    minutes = [155, 305, 80, 245]
    ends = [s + dt.timedelta(minutes=m) for s, m in zip(starts, minutes, strict=True)]
    due = [
        ends[0] + dt.timedelta(minutes=10),
        ends[1] - dt.timedelta(minutes=25),
        ends[2] - dt.timedelta(minutes=5),
        ends[3],
    ]
    late = [
        max(0, int((e - d).total_seconds() / 60))
        for e, d in zip(ends, due, strict=True)
    ]
    save(
        "timestamps",
        [
            (
                "Sessions",
                [
                    ["Session", "Start", "End", "Deadline"],
                    *[
                        [n, s, e, d]
                        for n, s, e, d in zip(names, starts, ends, due, strict=True)
                    ],
                ],
            )
        ],
        [
            (
                "In Sessions, what was total elapsed duration in minutes across all sessions, including intervals crossing midnight? Answer only the integer.",
                str(sum(minutes)),
            ),
            (
                "In Sessions, which session lasted longest from Start to End? Answer only its Session label.",
                names[minutes.index(max(minutes))],
            ),
            (
                "In Sessions, how many sessions ended strictly after Deadline? Answer only the integer.",
                str(sum(m > 0 for m in late)),
            ),
            (
                "In Sessions, sum minutes late, counting sessions that ended on or before Deadline as zero. Answer only the integer.",
                str(sum(late)),
            ),
            (
                "In Sessions, what was the elapsed duration of Shift A in hours? Answer to two decimal places.",
                f"{minutes[0] / 60:.2f}",
            ),
            (
                "In Sessions, what is the ISO calendar date on which Shift C ended? Answer YYYY-MM-DD.",
                ends[2].date().isoformat(),
            ),
        ],
    )

    # Ratios of sums differ from unweighted averages; multi-period long format.
    capacity = [80, 160, 240, 120]
    occupied = [48, 112, 204, 96]
    sites = ["Aster", "Birch", "Cedar", "Dogwood"]
    records = [
        [s, "Actual", c, o] for s, c, o in zip(sites, capacity, occupied, strict=True)
    ] + [[s, "Budget", c, c] for s, c in zip(sites, capacity, strict=True)]
    rates = [o / c for c, o in zip(capacity, occupied, strict=True)]
    save(
        "capacity_weighting",
        [("Occupancy", [["Site", "Scenario", "Capacity", "Occupied"], *records])],
        [
            (
                "For Actual only in Occupancy, what is overall utilization: total Occupied divided by total Capacity, in percent? Answer to two decimal places without percent sign.",
                f"{100 * sum(occupied) / sum(capacity):.2f}",
            ),
            (
                "For Actual only in Occupancy, what is the unweighted average of the four site utilization percentages? Answer to two decimal places without percent sign.",
                f"{100 * statistics.mean(rates):.2f}",
            ),
            (
                "For Actual only in Occupancy, how much total unused Capacity remains (Capacity minus Occupied)? Answer only the integer.",
                str(sum(capacity) - sum(occupied)),
            ),
            (
                "For Actual only in Occupancy, which Site has the highest utilization ratio? Answer only the Site.",
                sites[rates.index(max(rates))],
            ),
            (
                "For Actual only in Occupancy, how many sites have utilization strictly above 75 percent? Answer only the integer.",
                str(sum(r > 0.75 for r in rates)),
            ),
            (
                "For Actual only in Occupancy, sum Occupied for Birch and Cedar. Answer only the integer.",
                str(occupied[1] + occupied[2]),
            ),
        ],
    )

    # A bridge contains negative adjustments; 'absolute magnitude' is explicit.
    changes = [
        rng.randrange(30, 80),
        -rng.randrange(12, 28),
        rng.randrange(9, 26),
        -rng.randrange(4, 11),
    ]
    movements = ["New", "Cancelled", "Reactivated", "Corrected"]
    opening = rng.randrange(90, 140)
    save(
        "signed_bridge",
        [
            (
                "Bridge",
                [
                    ["Movement", "Change"],
                    *[[n, v] for n, v in zip(movements, changes, strict=True)],
                ],
            ),
            ("Opening", [["Metric", "Value"], ["Opening accounts", opening]]),
        ],
        [
            (
                "Using Opening and all signed Changes in Bridge, what is closing accounts? Answer only the integer.",
                str(opening + sum(changes)),
            ),
            (
                "In Bridge, what is net Change? Keep its sign. Answer only the integer.",
                str(sum(changes)),
            ),
            (
                "In Bridge, sum the absolute magnitudes of negative Changes. Report positive magnitude, answer only the integer.",
                str(-sum(v for v in changes if v < 0)),
            ),
            (
                "In Bridge, which Movement has the largest absolute Change? Answer only the Movement label.",
                movements[max(range(4), key=lambda i: abs(changes[i]))],
            ),
            (
                "In Bridge, what percentage of all positive Changes is attributable to Reactivated? Answer to two decimal places without percent sign.",
                f"{100 * changes[2] / sum(v for v in changes if v > 0):.2f}",
            ),
            (
                "Using Opening and Bridge, what is closing accounts minus opening accounts, keeping its sign? Answer only the integer.",
                str(sum(changes)),
            ),
        ],
    )

    # Mixed measurement units must be explicitly converted before comparison.
    amounts = [1250, 1.8, 725, 0.95]
    factors = [1, 1000, 1, 1000]
    codes = ["Lot-J", "Lot-K", "Lot-L", "Lot-M"]
    kilograms = [a * f for a, f in zip(amounts, factors, strict=True)]
    save(
        "mixed_mass_units",
        [
            (
                "Loads",
                [
                    ["Lot", "Mass", "Unit"],
                    *[
                        [n, a, u]
                        for n, a, u in zip(
                            codes,
                            amounts,
                            ["kg", "tonnes", "kg", "tonnes"],
                            strict=True,
                        )
                    ],
                ],
            )
        ],
        [
            (
                "In Loads, sum all Mass in kilograms; one tonne is 1000 kg. Answer only the integer.",
                str(int(sum(kilograms))),
            ),
            (
                "In Loads, which Lot is heaviest after converting all masses to kilograms? Answer only the Lot.",
                codes[kilograms.index(max(kilograms))],
            ),
            (
                "In Loads, what is total Mass in tonnes, with 1000 kg per tonne? Answer to three decimal places.",
                f"{sum(kilograms) / 1000:.3f}",
            ),
            (
                "In Loads, what Mass is displayed for Lot-K? Keep its displayed scale; answer to two decimal places with no unit.",
                f"{amounts[1]:.2f}",
            ),
            (
                "In Loads, how many lots weigh strictly more than 1000 kg after conversion? Answer only the integer.",
                str(sum(v > 1000 for v in kilograms)),
            ),
            (
                "In Loads, how many kilograms heavier is Lot-K than Lot-M? Answer only the integer.",
                str(int(kilograms[1] - kilograms[3])),
            ),
        ],
    )

    # Tie policies and distinct values: rank need not be an individual row's ordinal.
    names = ["Amara", "Bastien", "Cleo", "Dario", "Esme", "Faris"]
    points = [84, 97, 84, 73, 97, 65]
    save(
        "ties_and_distinct_rank",
        [
            (
                "Ranking",
                [
                    ["Name", "Points"],
                    *[[n, p] for n, p in zip(names, points, strict=True)],
                ],
            )
        ],
        [
            (
                "In Ranking, list every Name tied for the highest Points, in alphabetical order, separated by comma and space.",
                ", ".join(
                    sorted(
                        n
                        for n, p in zip(names, points, strict=True)
                        if p == max(points)
                    )
                ),
            ),
            (
                "In Ranking, what is the second-highest DISTINCT Points value? Answer only the integer.",
                str(sorted(set(points), reverse=True)[1]),
            ),
            (
                "In Ranking, how many people have Points at least 84? Answer only the integer.",
                str(sum(p >= 84 for p in points)),
            ),
            (
                "In Ranking, which Name comes first when ordered by descending Points then ascending Name? Answer only the Name.",
                min(names, key=lambda n: (-points[names.index(n)], n)),
            ),
            (
                "In Ranking, what is the average Points of people tied at the highest Points? Answer to two decimal places.",
                f"{max(points):.2f}",
            ),
            (
                "In Ranking, list Names with Points strictly less than 84, sorted alphabetically, separated by comma and space.",
                ", ".join(
                    sorted(n for n, p in zip(names, points, strict=True) if p < 84)
                ),
            ),
        ],
    )

    # One sheet has repeated metric labels in separate scopes and years.
    periods = [2025, 2026]
    regions = ["Coastal", "Inland", "All regions"]
    actual = [[rng.randrange(50, 130), rng.randrange(50, 130)] for _ in range(2)]
    rows = [["Year", "Region", "Metric", "Value"]]
    for i, year in enumerate(periods):
        for metric in ("Approved", "Rejected"):
            vals = actual[i] if metric == "Approved" else [7 + i, 13 + i]
            for region, val in zip(regions, [*vals, sum(vals)], strict=True):
                rows.append([year, region, metric, val])
    save(
        "long_format_scopes",
        [("Decisions", rows)],
        [
            (
                "In Decisions, what is Approved Value for Coastal in 2026? Answer only the integer.",
                str(actual[1][0]),
            ),
            (
                "In Decisions, what is Approved Value for All regions in 2026? Use the published row and do not add it to regional rows. Answer only the integer.",
                str(sum(actual[1])),
            ),
            (
                "In Decisions, what is the change in Approved Value for Inland from 2025 to 2026 (2026 minus 2025)? Keep its sign; answer only the integer.",
                str(actual[1][1] - actual[0][1]),
            ),
            (
                "In Decisions, what percentage of 2026 Approved Value for All regions comes from Coastal? Answer to two decimal places without percent sign.",
                f"{100 * actual[1][0] / sum(actual[1]):.2f}",
            ),
            (
                "In Decisions, for 2025 Coastal only, what is Approved plus Rejected Value? Answer only the integer.",
                str(actual[0][0] + 7),
            ),
            (
                "In Decisions, what is total Rejected Value across both years for Inland only? Answer only the integer.",
                "27",
            ),
        ],
    )

    # Tax-inclusive vs tax-exclusive arithmetic and per-item rounding instructions.
    descriptions = ["Notebook", "Cable", "Adapter"]
    counts = [3, 7, 2]
    ex_prices = [11.2, 4.5, 23.8]
    tax = [0.05, 0.2, 0.2]
    ex_totals = [q * p for q, p in zip(counts, ex_prices, strict=True)]
    taxes = [v * t for v, t in zip(ex_totals, tax, strict=True)]
    inclusive = [v + t for v, t in zip(ex_totals, taxes, strict=True)]
    save(
        "tax_and_currency_rounding",
        [
            (
                "Receipt",
                [
                    ["Description", "Quantity", "Price excluding tax", "Tax fraction"],
                    *[
                        [n, q, p, t]
                        for n, q, p, t in zip(
                            descriptions, counts, ex_prices, tax, strict=True
                        )
                    ],
                ],
            )
        ],
        [
            (
                "In Receipt, what is total cost excluding tax (Quantity times Price excluding tax)? Answer to two decimal places.",
                f"{sum(ex_totals):.2f}",
            ),
            (
                "In Receipt, what is total tax (Quantity times Price excluding tax times Tax fraction)? Answer to two decimal places.",
                f"{sum(taxes):.2f}",
            ),
            (
                "In Receipt, what is total cost including tax? Answer to two decimal places.",
                f"{sum(inclusive):.2f}",
            ),
            (
                "In Receipt, what is Adapter cost including tax for its entire Quantity? Answer to two decimal places.",
                f"{inclusive[2]:.2f}",
            ),
            (
                "In Receipt, which Description contributes the highest total tax amount? Answer only the Description.",
                descriptions[taxes.index(max(taxes))],
            ),
            (
                "In Receipt, what is the effective tax rate: total tax divided by total cost excluding tax, in percent? Answer to two decimal places without percent sign.",
                f"{100 * sum(taxes) / sum(ex_totals):.2f}",
            ),
        ],
    )

    # A dashboard compares concentration, not raw magnitude or an unweighted mean.
    labels = ["Tank R", "Tank S", "Tank T"]
    volumes = [180, 420, 250]
    contaminants = [9, 42, 20]
    concentrations = [m / v for m, v in zip(contaminants, volumes, strict=True)]
    save(
        "concentration_ratios",
        [
            (
                "Water quality",
                [
                    ["Tank", "Volume litres", "Contaminant grams"],
                    *[
                        [n, v, m]
                        for n, v, m in zip(labels, volumes, contaminants, strict=True)
                    ],
                ],
            )
        ],
        [
            (
                "In Water quality, which Tank has the highest contaminant concentration in grams per litre? Answer only the Tank.",
                labels[concentrations.index(max(concentrations))],
            ),
            (
                "In Water quality, what is combined contaminant concentration: total grams divided by total litres? Answer to four decimal places.",
                f"{sum(contaminants) / sum(volumes):.4f}",
            ),
            (
                "In Water quality, what is the unweighted mean of the three tank concentrations in grams per litre? Answer to four decimal places.",
                f"{statistics.mean(concentrations):.4f}",
            ),
            (
                "In Water quality, how many Tanks have concentration strictly above 0.07 grams per litre? Answer only the integer.",
                str(sum(c > 0.07 for c in concentrations)),
            ),
            (
                "In Water quality, how many grams of contaminant are in Tank R and Tank T combined? Answer only the integer.",
                str(contaminants[0] + contaminants[2]),
            ),
            (
                "In Water quality, what percentage of total Volume litres is in Tank S? Answer to two decimal places without percent sign.",
                f"{100 * volumes[1] / sum(volumes):.2f}",
            ),
        ],
    )

    (root / "queries.json").write_text(
        json.dumps(queries, ensure_ascii=False, indent=2)
    )
    with (root / "references.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "answer"])
        writer.writeheader()
        writer.writerows(answers)
    hashes = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [
            root / "queries.json",
            root / "references.csv",
            *sorted(files.glob("*.xlsx")),
        ]
    }
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "seed": seed,
                "families": manifests,
                "questions": len(queries),
                "hashes": hashes,
                "status": "sealed; evaluate only after locking candidate",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    generate(Path("reports/optimization/efficiency_v3/sealed_holdout"))
