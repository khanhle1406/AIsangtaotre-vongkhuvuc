"""Persist conservative development reservations before any paid experiment."""

import fcntl
import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from src.llm_agent import BudgetExceeded, BudgetLedger


class DevelopmentBudget:
    def __init__(self, path: Path, initial_spent: float, limit: float = 0.5) -> None:
        if (
            not all(math.isfinite(value) for value in (initial_spent, limit))
            or not 0 <= initial_spent <= limit <= 0.5
        ):
            raise ValueError("Invalid development budget provenance or limit")
        self.path = path
        if not path.exists():
            self._save({"limit": limit, "initial_spent": initial_spent, "runs": []})
        data = self._read()
        if data["limit"] != limit or data["initial_spent"] != initial_spent:
            raise ValueError("Development budget provenance changed")

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf8")
        temporary.replace(self.path)

    @property
    def remaining(self) -> float:
        data = self._read()
        return (
            data["limit"]
            - data["initial_spent"]
            - sum(run["cost_upper_usd"] for run in data["runs"])
        )

    @contextmanager
    def stage(self, name: str, limit: float) -> Iterator[BudgetLedger]:
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self._stage(name, limit) as ledger:
                yield ledger

    @contextmanager
    def _stage(self, name: str, limit: float) -> Iterator[BudgetLedger]:
        # A killed process leaves its entire reservation in the persistent ledger.
        if not math.isfinite(limit) or limit <= 0 or limit > self.remaining + 1e-12:
            raise BudgetExceeded("Development reservation exceeds remaining budget")
        data = self._read()
        if any(run["name"] == name for run in data["runs"]):
            raise ValueError("Use a unique experiment name; preserve earlier evidence")
        run = {"name": name, "status": "reserved", "cost_upper_usd": limit}
        data["runs"].append(run)
        self._save(data)
        ledger = BudgetLedger(limit)
        try:
            yield ledger
        finally:
            # Preserve costs from partial runs even when inference raises.
            data = self._read()
            saved = next(item for item in data["runs"] if item["name"] == name)
            saved.update(
                status="settled", cost_upper_usd=ledger.spent + ledger.reserved
            )
            self._save(data)


def workspace_budget() -> DevelopmentBudget:
    """Reuse ledger provenance; an extracted submission starts a fresh dev ledger."""
    path = Path("reports/optimization/development_budget.json")
    if path.exists():
        initial = json.loads(path.read_text())["initial_spent"]
    else:
        manifest = Path("reports/validation_manifest.json")
        initial = (
            json.loads(manifest.read_text())["development_cost_conservative_upper_usd"]
            if manifest.exists()
            else 0.0
        )
    return DevelopmentBudget(path, initial)
