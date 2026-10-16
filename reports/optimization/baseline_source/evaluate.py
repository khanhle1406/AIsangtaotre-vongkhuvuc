"""Strict CSV validation and exact match; no case/whitespace normalization."""

import csv
import sys
from pathlib import Path


def read_answers(path: Path | str) -> dict[str, str]:
    answers = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["id", "answer"]:
            raise ValueError(f"{path}: columns must be exactly id,answer")
        for row in reader:
            if None in row or row["id"] is None or row["answer"] is None:
                raise ValueError(f"{path}: malformed CSV row")
            if not row["id"] or row["id"] in answers:
                raise ValueError(f"{path}: missing or duplicate ID {row['id']!r}")
            answers[row["id"]] = row["answer"]
    return answers


def evaluate(
    pred_file: str | Path = "submission.csv",
    gt_file: str | Path = "data/sample_submission.csv",
) -> tuple[int, int]:
    predictions, references = read_answers(pred_file), read_answers(gt_file)
    if predictions.keys() != references.keys():
        raise ValueError(
            f"ID mismatch: missing={sorted(references.keys() - predictions.keys())}, "
            f"extra={sorted(predictions.keys() - references.keys())}"
        )
    correct = 0
    for q_id, reference in references.items():
        match = predictions[q_id] == reference
        correct += match
        print(
            f"{q_id}: {'PASS' if match else 'FAIL'} | {predictions[q_id]!r} | {reference!r}"
        )
    print(
        f"Exact Match Accuracy: {correct}/{len(references)} "
        f"({100 * correct / len(references) if references else 0:.1f}%)"
    )
    return correct, len(references)


if __name__ == "__main__":
    try:
        evaluate(*sys.argv[1:3])
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
