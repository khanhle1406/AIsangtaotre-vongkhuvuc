"""Independent small arithmetic examples and a value-changing frozen test protocol."""

import datetime as dt
import hashlib
import json
from fractions import Fraction
from pathlib import Path

import pytest

from benchmarks.prospective_holdout import (
    generate,
    linear_optimum,
    panel_contrasts,
    service_dates,
)


def test_prospective_oracles_against_hand_calculation() -> None:
    panel = [
        ("A", "Intervention", "Pre", 10),
        ("A", "Intervention", "Post", 14),
        ("B", "Intervention", "Pre", 20),
        ("B", "Intervention", "Post", 26),
        ("C", "Reference", "Pre", 5),
        ("C", "Reference", "Post", 7),
        ("D", "Reference", "Pre", 15),
        ("D", "Reference", "Post", 18),
        ("Excluded", "Reference", "Pre", 1000),
    ]
    assert panel_contrasts(panel) == (Fraction(5), Fraction(15, 2), Fraction(5, 2))
    constraints = [(1, 1, 10), (2, 1, 14), (1, 1, 30)]
    assert linear_optimum(constraints, (3, 2)) == (4, 6, 24)
    for x in range(15):
        for y in range(15):
            if all(a * x + b * y <= cap for a, b, cap in constraints):
                assert 3 * x + 2 * y <= 24
    dates = [dt.date(2035, 4, day) for day in [2, 3, 7, 8]]
    assert service_dates(
        dates, [("A", dt.date(2035, 4, 2), 2), ("B", dt.date(2035, 4, 4), 1)]
    ) == {"A": dt.date(2035, 4, 7), "B": dt.date(2035, 4, 7)}


def test_prospective_freeze_has_new_values_and_no_evaluation_receipt(
    tmp_path: Path,
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    manifest = generate(a)
    generate(b, seed=16062027)
    assert manifest["queries"] == 18 and len(manifest["families"]) == 3
    assert manifest["numeric_values_randomized"]
    assert (a / "references.csv").read_bytes() != (b / "references.csv").read_bytes()
    assert len(json.loads((a / "queries.json").read_text())) == 18
    assert len(list((a / "xlsx_files").glob("*.xlsx"))) == 6
    for name, digest in manifest["hashes"].items():
        assert hashlib.sha256((a / name).read_bytes()).hexdigest() == digest
    assert not (a / "evaluated.json").exists()
    with pytest.raises(ValueError, match="Preserve"):
        generate(a)
