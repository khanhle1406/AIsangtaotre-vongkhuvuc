"""Hand-check new holdout oracles independently of model/runtime helpers."""

import csv
import datetime as dt
import hashlib
import json
from fractions import Fraction
from pathlib import Path

import pytest

from benchmarks.decision_holdout import covers, effective_amounts, generate, posterior


def test_exact_joint_probabilities_and_evidence_normalization() -> None:
    prior = {"A": Fraction(1, 2), "B": Fraction(3, 10), "C": Fraction(1, 5)}
    likelihood = {"A": Fraction(4, 5), "B": Fraction(2, 5), "C": Fraction(1, 10)}
    assert posterior(prior, likelihood, [True])["A"] == Fraction(20, 27)
    assert posterior(prior, likelihood, [True, False])["B"] == Fraction(36, 85)
    assert posterior(prior, likelihood, [False, False])["C"] == Fraction(81, 145)
    assert posterior(prior, likelihood, []) == prior
    assert sum(posterior(prior, likelihood, [False, True, True]).values()) == 1


def test_cover_oracle_enumerates_feasible_sets_and_exclusions() -> None:
    costs = {"A": 8, "B": 5, "C": 5, "D": 4, "E": 7, "F": 9}
    coverage = {
        "A": {"R", "S"},
        "B": {"R"},
        "C": {"S", "T"},
        "D": {"T", "U"},
        "E": {"U"},
        "F": {"S", "U"},
    }
    required = {"R", "S", "T", "U"}
    assert covers(costs, coverage, required)[0] == (12, ("A", "D"))
    assert covers(costs, coverage, required, frozenset({"A"}))[0][0] == 14
    assert covers(costs, coverage, {"R", "T"})[0] == (9, ("B", "D"))
    assert covers(costs, coverage, {"absent"}) == []
    assert covers(costs, coverage, set())[0] == (0, ())
    assert covers({**costs, "B": 2, "C": 2}, coverage, required)[0] == (
        8,
        ("B", "C", "D"),
    )


def test_interval_join_has_inclusive_start_exclusive_end_and_exact_currency() -> None:
    first, boundary, last = (
        dt.datetime(2031, 1, 1),
        dt.datetime(2031, 1, 16),
        dt.datetime(2031, 2, 1),
    )
    transactions = [("EUR", first, 10), ("EUR", boundary, 20), ("GBP", boundary, 8)]
    rates = [
        ("EUR", first, boundary, Fraction(11, 10)),
        ("EUR", boundary, last, Fraction(5, 4)),
        ("GBP", first, last, Fraction(3, 2)),
    ]
    assert effective_amounts(transactions, rates) == [
        Fraction(11),
        Fraction(25),
        Fraction(12),
    ]
    with pytest.raises(ValueError, match="exactly one"):
        effective_amounts(transactions, [*rates, ("EUR", first, last, Fraction(1))])
    with pytest.raises(ValueError, match="exactly one"):
        effective_amounts([("EUR", last, 10)], rates)


def test_frozen_decision_dataset_matches_hand_answers_and_hashes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "unseen"
    manifest = generate(root)
    assert manifest["questions"] == 18 and len(manifest["families"]) == 3
    with (root / "references.csv").open(newline="") as file:
        answers = [row["answer"] for row in csv.DictReader(file)]
    assert answers == [
        "12",
        "Aster, Dune",
        "14",
        "9",
        "2",
        "1",
        "0.740741",
        "0.423529",
        "0.558621",
        "0.540000",
        "0.370000",
        "Clear source",
        "111.00",
        "51.00",
        "60.00",
        "50.00",
        "37.00",
        "3",
    ]
    queries = json.loads((root / "queries.json").read_text())
    assert len({q["file_name"] for q in queries}) == 3
    assert not (root / "evaluated.json").exists()
    for name, digest in manifest["hashes"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    with pytest.raises(ValueError, match="Preserve frozen"):
        generate(root)
