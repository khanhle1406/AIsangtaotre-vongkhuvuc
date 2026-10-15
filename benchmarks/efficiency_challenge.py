"""Unseen event-history, constrained-choice, clipping and branch-layout oracle tasks."""

import csv
import datetime as dt
import hashlib
import json
import random
from pathlib import Path
from typing import Any

import openpyxl


def generate(root: Path, seed: int = 41370921) -> None:
    """Freeze four new families; no solver, prompt or competition answer imports."""
    if root.exists():
        raise ValueError("Challenge dataset already exists")
    files = root / "xlsx_files"
    files.mkdir(parents=True)
    rng = random.Random(seed)
    queries: list[dict[str, Any]] = []
    answers: list[dict[str, str]] = []

    def save(
        family: str, rows: list[list[Any]], questions: list[tuple[str, str]]
    ) -> None:
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = "Audited data"
        r0 = rng.choice([11, 281, 407])
        c0 = rng.choice([2, 4, 6])
        for r, values in enumerate(rows, r0):
            for c, value in enumerate(values, c0):
                cell = sheet.cell(r, c, value)
                if isinstance(value, dt.datetime):
                    cell.number_format = "yyyy-mm-dd hh:mm"
        book.create_sheet("Discarded draft").append(["Unapproved draft", 999999])
        name = f"source_{rng.randrange(100000, 999999)}.xlsx"
        book.save(files / name)
        book.close()
        for question, answer in questions:
            key = f"challenge-{len(queries) + 1:03d}"
            queries.append(
                {
                    "id": key,
                    "file_name": name,
                    "family": family,
                    "query": "Use Audited data only. " + question,
                }
            )
            answers.append({"id": key, "answer": answer})

    # Rows are shuffled; latest means event timestamp, not final sheet position.
    history = []
    latest = {}
    for i in range(16):
        identity = f"Account-{i + 31}"
        for version in range(3):
            timestamp = dt.datetime(2028, 5, 1) + dt.timedelta(
                days=version * 5 + i % 4, hours=i
            )
            status = "Active" if (i + version) % 3 else "Closed"
            value = rng.randrange(20, 160)
            row = [identity, timestamp, status, value]
            history.append(row)
            if identity not in latest or timestamp > latest[identity][1]:
                latest[identity] = row
    rng.shuffle(history)
    active = [row for row in latest.values() if row[2] == "Active"]
    active.sort(key=lambda row: (-row[3], row[0]))
    cutoff = dt.datetime(2028, 5, 12)
    save(
        "latest_event_per_identity",
        [["Account", "Event time", "Status", "Balance"], *history],
        [
            (
                "For each Account use its latest Event time, regardless of row position. How many accounts are Active at that latest event? Answer only the integer.",
                str(len(active)),
            ),
            (
                "For each Account use its latest Event time. Sum Balance for accounts Active at that event. Answer only the integer.",
                str(sum(row[3] for row in active)),
            ),
            (
                "For each Account use its latest Event time. Which Active account has the largest Balance? Break ties alphabetically; answer only the Account.",
                active[0][0],
            ),
            (
                "For each Account use its latest Event time. What percentage of distinct accounts are Closed at their latest event? Answer to two decimals, no percent sign.",
                f"{100 * (len(latest) - len(active)) / len(latest):.2f}",
            ),
            (
                "For each Account use its latest Event time. What is the average Balance of Active accounts at that event? Answer to two decimal places.",
                f"{sum(row[3] for row in active) / len(active):.2f}",
            ),
            (
                "For each Account use its latest Event time. How many latest events are strictly before 2028-05-12 00:00? Answer only the integer.",
                str(sum(row[1] < cutoff for row in latest.values())),
            ),
            (
                "How many event records are in the table, counting historical versions separately? Answer only the integer.",
                str(len(history)),
            ),
            (
                "For each Account use its latest Event time. List the three Active accounts with largest Balance in descending Balance order, ties alphabetically. Separate names with comma and space.",
                ", ".join(row[0] for row in active[:3]),
            ),
        ],
    )

    # Independent combinatorial oracle enumerates every eligible pair.
    projects = [
        [
            f"Project-{i + 61}",
            rng.randrange(25, 105),
            rng.randrange(1, 6),
            rng.randrange(50, 350),
        ]
        for i in range(12)
    ]
    eligible = [p for p in projects if p[1] <= 80 and p[2] <= 4]
    single = min(eligible, key=lambda p: (-p[3], p[0]))
    pairs = []
    for i, p in enumerate(projects):
        for q in projects[i + 1 :]:
            if p[1] + q[1] <= 140 and p[2] + q[2] <= 7:
                pairs.append(
                    (p[3] + q[3], tuple(sorted([p[0], q[0]])), p[1] + q[1], p[2] + q[2])
                )
    best = min(pairs, key=lambda p: (-p[0], p[1]))
    efficient = min(eligible, key=lambda p: (-p[3] / p[1], p[0]))
    save(
        "budget_and_staff_constraints",
        [["Project", "Cost", "Staff", "Benefit"], *projects],
        [
            (
                "Among single projects with Cost <= 80 and Staff <= 4, which has highest Benefit? Break ties alphabetically; answer only the Project.",
                single[0],
            ),
            (
                "How many single projects satisfy both Cost <= 80 and Staff <= 4? Answer only the integer.",
                str(len(eligible)),
            ),
            (
                "Select exactly two different projects with combined Cost <= 140 and combined Staff <= 7. What is the maximum combined Benefit? Answer only the integer.",
                str(best[0]),
            ),
            (
                "Select exactly two different projects with combined Cost <= 140 and Staff <= 7 to maximize combined Benefit. Break equal-benefit ties by alphabetically sorted project names. List the chosen pair alphabetically, separated by comma and space.",
                ", ".join(best[1]),
            ),
            (
                "How many unordered pairs of different projects have combined Cost <= 140 and combined Staff <= 7? Answer only the integer.",
                str(len(pairs)),
            ),
            (
                "Among single projects with Cost <= 80 and Staff <= 4, which has highest Benefit divided by Cost? Break ties alphabetically; answer only the Project.",
                efficient[0],
            ),
            (
                "Among single projects with Cost <= 80 and Staff <= 4, sum their Cost. Answer only the integer.",
                str(sum(p[1] for p in eligible)),
            ),
            (
                "Select exactly two different projects with combined Cost <= 140 and Staff <= 7 to maximize Benefit. Break equal-benefit ties by alphabetically sorted project names. What is the pair's combined Cost? Answer only the integer.",
                str(best[2]),
            ),
        ],
    )

    # Work intervals must be clipped to the reporting window before pricing them.
    beginning = dt.datetime(2028, 6, 7, 9)
    ending = dt.datetime(2028, 6, 7, 17)
    shifts = []
    clipped = []
    for i in range(12):
        start = beginning + dt.timedelta(minutes=-180 + 75 * i)
        end = start + dt.timedelta(minutes=rng.choice([90, 150, 210]))
        rate = rng.randrange(12, 35)
        row = [f"Worker-{i % 5 + 11}", start, end, rate]
        shifts.append(row)
        minutes = max(
            0, (min(end, ending) - max(start, beginning)).total_seconds() / 60
        )
        clipped.append(minutes)
    cost = [m / 60 * row[3] for row, m in zip(shifts, clipped, strict=True)]
    per_worker = {
        worker: sum(c for row, c in zip(shifts, cost, strict=True) if row[0] == worker)
        for worker in {row[0] for row in shifts}
    }
    save(
        "clipped_time_window",
        [["Worker", "Start", "End", "Hourly rate"], *shifts],
        [
            (
                "Clip every shift to 2028-06-07 09:00 through 17:00. What is total worker-minutes inside that window, counting overlapping shifts separately? Answer only the integer.",
                str(int(sum(clipped))),
            ),
            (
                "Clip every shift to 2028-06-07 09:00 through 17:00. Sum each shift's clipped hours times its Hourly rate. Answer to two decimal places.",
                f"{sum(cost):.2f}",
            ),
            (
                "How many shifts overlap 2028-06-07 09:00 through 17:00 by a positive duration? Touching an endpoint alone does not count. Answer only the integer.",
                str(sum(m > 0 for m in clipped)),
            ),
            (
                "How many distinct Workers have positive-duration overlap with 2028-06-07 09:00 through 17:00? Answer only the integer.",
                str(
                    len(
                        {
                            row[0]
                            for row, m in zip(shifts, clipped, strict=True)
                            if m > 0
                        }
                    )
                ),
            ),
            (
                "Clip shifts to 2028-06-07 09:00 through 17:00 and price clipped hours by Hourly rate. Which Worker has the highest summed cost? Break ties alphabetically; answer only the Worker.",
                min(per_worker, key=lambda w: (-per_worker[w], w)),
            ),
            (
                "What is total duration in minutes of all complete shifts without clipping? Answer only the integer.",
                str(int(sum((row[2] - row[1]).total_seconds() / 60 for row in shifts))),
            ),
            (
                "How many shifts start strictly before 2028-06-07 09:00? Answer only the integer.",
                str(sum(row[1] < beginning for row in shifts)),
            ),
            (
                "Clip shifts to 2028-06-07 09:00 through 17:00 and price clipped hours by Hourly rate. What is summed cost for Worker-11? Answer to two decimal places.",
                f"{per_worker['Worker-11']:.2f}",
            ),
        ],
    )

    # First differences and rolling windows are distinct from level extrema.
    levels = [rng.randrange(100, 250)]
    for i in range(13):
        levels.append(levels[-1] + rng.randrange(-18, 28))
    dates = [dt.datetime(2028, 7, 1) + dt.timedelta(days=i) for i in range(len(levels))]
    differences = [levels[i] - levels[i - 1] for i in range(1, len(levels))]
    rolling = [sum(levels[i - 2 : i + 1]) / 3 for i in range(2, len(levels))]
    max_diff = max(range(len(differences)), key=lambda i: differences[i]) + 1
    min_diff = min(range(len(differences)), key=lambda i: differences[i]) + 1
    max_roll = max(range(len(rolling)), key=lambda i: rolling[i]) + 2
    save(
        "time_series_differences",
        [["Date", "Level"], *[[d, v] for d, v in zip(dates, levels, strict=True)]],
        [
            (
                "Sort by Date ascending. On which date was the largest increase from the preceding recorded date? Break ties by earliest Date; answer YYYY-MM-DD.",
                dates[max_diff].date().isoformat(),
            ),
            (
                "Sort by Date ascending. What is the largest Level increase from the preceding recorded date? Answer only the signed integer.",
                str(max(differences)),
            ),
            (
                "Sort by Date ascending. On which date was the smallest signed change from the preceding recorded date? Break ties by earliest Date; answer YYYY-MM-DD.",
                dates[min_diff].date().isoformat(),
            ),
            (
                "Sort by Date ascending. How many consecutive-date changes in Level are negative? Answer only the integer.",
                str(sum(d < 0 for d in differences)),
            ),
            (
                "Sort by Date ascending. Compute the trailing three-record arithmetic mean of Level, including each date and its preceding two records. On which ending date is this mean highest? Break ties by earliest date; answer YYYY-MM-DD.",
                dates[max_roll].date().isoformat(),
            ),
            (
                "Sort by Date ascending. What is the highest trailing three-record arithmetic mean of Level? Answer to two decimal places.",
                f"{max(rolling):.2f}",
            ),
            (
                "What is last Level minus first Level by Date ascending? Keep the sign; answer only the integer.",
                str(levels[-1] - levels[0]),
            ),
            (
                "What is the relative change from first Level to last Level by Date ascending, as a percent of first Level? Answer to two decimal places, no percent sign.",
                f"{100 * (levels[-1] - levels[0]) / levels[0]:.2f}",
            ),
        ],
    )
    (root / "queries.json").write_text(json.dumps(queries, indent=2))
    with (root / "references.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "answer"])
        writer.writeheader()
        writer.writerows(answers)
    paths = [
        root / "queries.json",
        root / "references.csv",
        *sorted(files.glob("*.xlsx")),
    ]
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "seed": seed,
                "questions": len(queries),
                "families": sorted({q["family"] for q in queries}),
                "hashes": {
                    p.relative_to(root).as_posix(): hashlib.sha256(
                        p.read_bytes()
                    ).hexdigest()
                    for p in paths
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    generate(Path("reports/optimization/efficiency_v4/sealed_challenge"))
