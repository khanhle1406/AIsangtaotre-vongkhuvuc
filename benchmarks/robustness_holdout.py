"""Freeze unseen weighted quantile, confusion matrix and recurrence workbooks."""

import argparse
import csv
import hashlib
import json
import math
import random
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl


def generate(root: Path, seed: int = 290317) -> None:
    """Oracles use expanded observations and Decimal arithmetic, never solver helpers."""
    if root.exists():
        raise ValueError("Preserve existing independent data")
    files = root / "xlsx_files"
    files.mkdir(parents=True)
    rng = random.Random(seed)
    queries: list[dict[str, Any]] = []
    answers: list[dict[str, str]] = []

    def save(
        family: str,
        tables: list[tuple[str, list[list[Any]]]],
        cases: list[tuple[str, str]],
    ) -> None:
        book = openpyxl.Workbook()
        book.remove(book.active)
        for name, rows in tables:
            sheet = book.create_sheet(name)
            start, left = rng.choice([23, 319, 607]), rng.choice([3, 5, 7])
            for row, values in enumerate(rows, start):
                for col, value in enumerate(values, left):
                    sheet.cell(row, col, value)
        book.create_sheet("Superseded notes").append(
            ["Old values excluded from this audit", 99999]
        )
        filename = f"ledger_{rng.randrange(100000, 999999)}.xlsx"
        book.save(files / filename)
        book.close()
        for question, answer in cases:
            key = f"robust-{len(queries) + 1:03d}"
            queries.append(
                {"id": key, "file_name": filename, "family": family, "query": question}
            )
            answers.append({"id": key, "answer": answer})

    scored = [(12, 3), (27, 4), (41, 2), (27, 5), (58, 6), (73, 2), (89, 3)]
    expanded = sorted(value for value, frequency in scored for _ in range(frequency))
    cases = []
    for percent in [25, 50, 75, 90]:
        value = expanded[math.ceil(len(expanded) * percent / 100) - 1]
        cases.append(
            (
                f"Using Frequency data only, find the weighted {percent}th percentile of Score: the smallest Score whose cumulative Frequency, sorted by Score, reaches at least {percent}% of total Frequency. Combine duplicate Scores. Answer only the integer.",
                str(value),
            )
        )
    cases.extend(
        [
            (
                "Using Frequency data only, what is the Frequency-weighted mean of Score? Answer to two decimal places.",
                f"{sum(expanded) / len(expanded):.2f}",
            ),
            (
                "Using Frequency data only, what percent of observations have Score at least 41? Frequency is the number of observations. Answer to two decimal places without percent sign.",
                f"{100 * sum(value >= 41 for value in expanded) / len(expanded):.2f}",
            ),
            (
                "Using Frequency data only, how many observations have Score at most 27? Frequency counts observations. Answer only the integer.",
                str(sum(value <= 27 for value in expanded)),
            ),
            (
                "Using Frequency data only, find the interquartile range Q75 minus Q25. Each quantile is the smallest Score reaching at least its percentile of total Frequency. Answer only the integer.",
                str(
                    expanded[math.ceil(0.75 * len(expanded)) - 1]
                    - expanded[math.ceil(0.25 * len(expanded)) - 1]
                ),
            ),
        ]
    )
    rng.shuffle(scored)
    save(
        "weighted_discrete_quantile",
        [("Frequency data", [["Score", "Frequency"], *[list(row) for row in scored]])],
        cases,
    )

    labels = ["Azure", "Coral", "Ivory"]
    counts = [[17, 3, 5], [2, 23, 4], [6, 1, 19]]
    observations = [
        (actual, predicted)
        for i, actual in enumerate(labels)
        for j, predicted in enumerate(labels)
        for _ in range(counts[i][j])
    ]
    precision, recall, f1, fp, fn = {}, {}, {}, {}, {}
    for label in labels:
        tp = observations.count((label, label))
        fp[label] = sum(
            actual != label and predicted == label for actual, predicted in observations
        )
        fn[label] = sum(
            actual == label and predicted != label for actual, predicted in observations
        )
        precision[label] = tp / (tp + fp[label])
        recall[label] = tp / (tp + fn[label])
        f1[label] = (
            2 * precision[label] * recall[label] / (precision[label] + recall[label])
        )
    cases = [
        (
            "Using Classifier counts only, calculate overall accuracy: correctly classified Count divided by all Count. Express as percent, two decimal places, without percent sign.",
            f"{100 * sum(a == b for a, b in observations) / len(observations):.2f}",
        ),
        (
            "Using Classifier counts only, calculate macro precision: compute TP/(TP+FP) for each of the three labels, then their unweighted mean. Express as percent to two decimal places without percent sign.",
            f"{100 * sum(precision.values()) / 3:.2f}",
        ),
        (
            "Using Classifier counts only, calculate macro recall: compute TP/(TP+FN) for each label, then their unweighted mean. Express as percent to two decimal places without percent sign.",
            f"{100 * sum(recall.values()) / 3:.2f}",
        ),
        (
            "Using Classifier counts only, calculate macro F1: compute 2*TP/(2*TP+FP+FN) for each label, then their unweighted mean. Express as percent to two decimal places without percent sign.",
            f"{100 * sum(f1.values()) / 3:.2f}",
        ),
        (
            "Using Classifier counts only, which label has the most false-positive observations: Predicted is that label but Actual differs? Sum Count, break ties alphabetically. Answer only the label.",
            min(labels, key=lambda label: (-fp[label], label)),
        ),
        (
            "Using Classifier counts only, calculate Azure F1: 2*TP/(2*TP+FP+FN), counting observations with Count weights. Express as percent, two decimal places without percent sign.",
            f"{100 * f1['Azure']:.2f}",
        ),
        (
            "Using Classifier counts only, calculate Coral recall TP/(TP+FN), counting observations with Count weights. Express as percent, two decimal places without percent sign.",
            f"{100 * recall['Coral']:.2f}",
        ),
        (
            "Using Classifier counts only, which label has the most false-negative observations: Actual is that label but Predicted differs? Sum Count, break ties alphabetically. Answer only the label.",
            min(labels, key=lambda label: (-fn[label], label)),
        ),
    ]
    matrix_rows = [
        [a, b, counts[i][j]] for i, a in enumerate(labels) for j, b in enumerate(labels)
    ]
    rng.shuffle(matrix_rows)
    save(
        "categorical_confusion_metrics",
        [("Classifier counts", [["Actual", "Predicted", "Count"], *matrix_rows])],
        cases,
    )

    flows = [
        ["2031-01", 0.01, 40, 130],
        ["2031-02", 0.015, 10, 180],
        ["2031-03", 0.005, 80, 20],
        ["2031-04", 0.02, 5, 95],
        ["2031-05", 0.01, 140, 20],
        ["2031-06", 0.0125, 35, 60],
    ]

    def balances(initial: int, extra: int = 0) -> tuple[list[Decimal], list[Decimal]]:
        amount = Decimal(initial)
        closed, interests = [], []
        for period, rate, deposit, withdrawal in flows:
            interest = amount * Decimal(str(rate))
            interests.append(interest)
            amount += interest + Decimal(deposit) - Decimal(withdrawal)
            if period == "2031-03":
                amount += extra
            closed.append(amount)
        return closed, interests

    closed, interests = balances(230)
    prefix = "Use Settings and Monthly flows only, sorting Period chronologically. Each period first accrues Opening balance * Rate fraction interest, then adds Deposit and subtracts Withdrawal; carry Closing balance forward. Do not round intermediate results. "
    cases = [
        (
            prefix + "What is final Closing balance? Answer to two decimal places.",
            f"{closed[-1]:.2f}",
        ),
        (
            prefix
            + "What is total interest across all periods? Answer to two decimal places.",
            f"{sum(interests):.2f}",
        ),
        (
            prefix
            + "Which Period has highest Closing balance? Answer only the Period.",
            flows[max(range(len(closed)), key=lambda i: closed[i])][0],
        ),
        (
            prefix + "Which Period has lowest Closing balance? Answer only the Period.",
            flows[min(range(len(closed)), key=lambda i: closed[i])][0],
        ),
        (
            prefix
            + "Which is the first chronological Period with negative Closing balance? Answer only the Period.",
            next(flows[i][0] for i, value in enumerate(closed) if value < 0),
        ),
        (
            prefix
            + "How many periods have strictly negative Closing balance? Answer only the integer.",
            str(sum(value < 0 for value in closed)),
        ),
        (
            prefix
            + "If the 2031-03 Deposit alone increased by 100, what would final Closing balance be? Answer to two decimal places.",
            f"{balances(230, 100)[0][-1]:.2f}",
        ),
        (
            prefix
            + "If Initial balance were instead zero, with flows and rates unchanged, what would final Closing balance be? Answer to two decimal places.",
            f"{balances(0)[0][-1]:.2f}",
        ),
    ]
    shuffled = [list(row) for row in flows]
    rng.shuffle(shuffled)
    save(
        "sequential_capital_recurrence",
        [
            ("Settings", [["Parameter", "Value"], ["Initial balance", 230]]),
            (
                "Monthly flows",
                [["Period", "Rate fraction", "Deposit", "Withdrawal"], *shuffled],
            ),
        ],
        cases,
    )
    (root / "queries.json").write_text(
        json.dumps(queries, ensure_ascii=False, indent=2)
    )
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
                    str(path.relative_to(root)): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in paths
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    generate(parser.parse_args().root)
