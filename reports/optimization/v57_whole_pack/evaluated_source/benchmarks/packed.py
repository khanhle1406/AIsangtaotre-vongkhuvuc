"""Experimental shared planning across books, with a separate backend per question."""

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar

from src.excel_parser import WorkbookData, load_workbook_data
from src.executor import ExecutionResult

from .backend_view import backend_view
from .batched import BatchedAgent
from .efficient import dense_text
from .structured_batch import CoherentPlanningAgent, StructuredBatchedAgent


@dataclass
class OwnedBook(WorkbookData):
    formula_sheets: dict[str, str] = field(default_factory=dict)

    def wire(self) -> dict[str, Any]:
        result = super().wire()
        for sheet in result.values():
            sheet["formula_sheet_aliases"] = self.formula_sheets
        return result


@dataclass
class ScopedBooks(WorkbookData):
    owners: dict[str, WorkbookData] = field(default_factory=dict)


@dataclass
class DeferredBooks(WorkbookData):
    paths: dict[str, Path] = field(default_factory=dict)
    reason: str = ""


def namespace_books(books: dict[str, WorkbookData]) -> ScopedBooks:
    """Copy sheet containers, keeping original cell coordinates/types and metadata."""
    if not books:
        raise ValueError("Cannot plan an empty workbook pack")
    owners: dict[str, WorkbookData] = {}
    for index, (filename, book) in enumerate(sorted(books.items())):
        owners[filename] = OwnedBook(
            {
                f"W{index}::{name}": replace(sheet, name=f"W{index}::{name}")
                for name, sheet in book.sheets.items()
            },
            book.estimated_bytes,
            {name: f"W{index}::{name}" for name in book.sheets},
        )
    return ScopedBooks(
        {
            name: sheet
            for book in owners.values()
            for name, sheet in book.sheets.items()
        },
        sum(book.estimated_bytes for book in owners.values()),
        owners,
    )


class PackedAgent(CoherentPlanningAgent):
    """Only the planner sees all namespaces; each executor/view sees its own book."""

    maximum_group_size: ClassVar[int] = 8
    planning_max_tokens: ClassVar[int | None] = 4096
    planning_strategy: ClassVar[str] = "live-multi-workbook-plan"
    pack_cache_bytes: ClassVar[int] = 32 * 1024**2
    file_cache_bytes: ClassVar[int] = 16 * 1024**2

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.system_prompt += (
            "\nEach question has allowed_sheets, belonging to ONE original workbook. "
            "Use exactly those namespaced sheet names in its program. Other questions' "
            "workbooks are unavailable to that program. Original coordinates/types are unchanged. "
            "Never copy values from another question or use another workbook's namespace.\n"
        )

    @staticmethod
    def planning_chunks(
        queries: list[dict[str, Any]], size: int
    ) -> list[list[dict[str, Any]]]:
        return [queries[i : i + size] for i in range(0, len(queries), size)]

    @classmethod
    def load_group(cls, files: Path, questions: list[dict[str, Any]]) -> WorkbookData:
        paths = {
            name: files / name for name in sorted({q["file_name"] for q in questions})
        }
        books = {}
        total = 0
        try:
            for name, path in paths.items():
                book = load_workbook_data(
                    path,
                    max_bytes=min(cls.file_cache_bytes, cls.pack_cache_bytes - total),
                )
                books[name] = book
                total += book.estimated_bytes
        except MemoryError as error:
            # Retry complete books separately with the original parser budget;
            # no partially parsed book or truncated view enters inference.
            return DeferredBooks(
                {}, estimated_bytes=128 * 1024**2, paths=paths, reason=str(error)
            )
        return namespace_books(books)

    def question_workbook(
        self, workbook: WorkbookData, question: dict[str, Any]
    ) -> WorkbookData:
        if (
            not isinstance(workbook, ScopedBooks)
            or question["file_name"] not in workbook.owners
        ):
            raise ValueError("Question has no owned workbook backend")
        return workbook.owners[question["file_name"]]

    def planning_question(
        self, workbook: WorkbookData, index: int, question: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            **super().planning_question(workbook, index, question),
            "allowed_sheets": list(self.question_workbook(workbook, question).sheets),
        }

    def solve_group(
        self, workbook: WorkbookData, questions: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not isinstance(workbook, DeferredBooks):
            return super().solve_group(workbook, questions)
        records = []
        events = []
        for filename, path in workbook.paths.items():
            owned = namespace_books({filename: load_workbook_data(path)})
            rows, event = super().solve_group(
                owned, [q for q in questions if q["file_name"] == filename]
            )
            records.extend(rows)
            events.append(event)
        order = {str(q["id"]): index for index, q in enumerate(questions)}
        records.sort(key=lambda row: order[row["id"]])
        return records, {
            "mode": "complete-books-separately-after-packed-cache-limit",
            "fallback_reason": workbook.reason,
            "events": events,
            "calls": [call for event in events for call in event.get("calls", [])],
            "question_ids": [str(q["id"]) for q in questions],
        }


class ParallelPackedAgent(PackedAgent):
    """Schedule already-independent questions alongside shared plans, not after them."""

    @staticmethod
    def planning_chunks(
        queries: list[dict[str, Any]], size: int
    ) -> list[list[dict[str, Any]]]:
        separate = [q for q in queries if PackedAgent.independent_question(q)]
        remaining = [q for q in queries if not PackedAgent.independent_question(q)]
        return [[q] for q in separate] + PackedAgent.planning_chunks(remaining, size)


class WidePackedAgent(ParallelPackedAgent):
    """Screen a larger plan; never change default packing without accuracy evidence."""

    maximum_group_size: ClassVar[int] = 16
    planning_max_tokens: ClassVar[int | None] = 8192


class IndependentPackedAgent(ParallelPackedAgent):
    """Independently solve multi-sheet calculations, adjudicating disagreement only."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.system_prompt += (
            "\nDo not carry over predicates, event multiplicity, scope or output shape "
            "from another question sharing the workbook. Derive each program from "
            "its own question.\n"
        )

    def _independent_check_required(
        self, execution: ExecutionResult, code: str
    ) -> bool:
        return (
            len(
                {
                    key.rsplit("!", 1)[0]
                    for key, entry in execution.reads.items()
                    if entry["kind"] == "number"
                }
            )
            > 1
        )


class SampledPackedAgent(ParallelPackedAgent):
    """Plan from a disclosed sample; all source validation/execution remains complete."""

    def planning_text(self, workbook: WorkbookData, wire: dict[str, Any]) -> str:
        return backend_view(
            workbook,
            wire,
            column_catalog=self.column_catalog,
            deduplicate_headers=self.deduplicate_headers,
        )


class NarrowSampledPackedAgent(SampledPackedAgent):
    """Give four programs the same output headroom as the eight-program experiment."""

    maximum_group_size: ClassVar[int] = 4


class RawPackedAgent(ParallelPackedAgent):
    """Keep all original cells/metadata; omit only advisory derived header paths."""

    def planning_text(self, workbook: WorkbookData, wire: dict[str, Any]) -> str:
        return dense_text(
            workbook,
            wire,
            column_catalog=self.column_catalog,
            header_hints=False,
        )


class AllPackedAgent(PackedAgent):
    """Compare one bounded shared plan for every question, retaining all validations."""

    @staticmethod
    def independent_question(question: dict[str, Any]) -> bool:
        return False


class TenPackedAgent(AllPackedAgent):
    """Test two plans for twenty questions with explicit extra output headroom."""

    maximum_group_size: ClassVar[int] = 10
    planning_max_tokens: ClassVar[int | None] = 6144


PLANNING_PROFILES: dict[str, type[BatchedAgent]] = {
    "same-book": StructuredBatchedAgent,
    "coherent": CoherentPlanningAgent,
    "packed8": PackedAgent,
    "parallel8": ParallelPackedAgent,
    "parallel16": WidePackedAgent,
    "independent8": IndependentPackedAgent,
    "sampled8": SampledPackedAgent,
    "sampled4": NarrowSampledPackedAgent,
    "raw8": RawPackedAgent,
    "all8": AllPackedAgent,
    "all10": TenPackedAgent,
}


def planning_agent(profile: str) -> type[BatchedAgent]:
    if profile not in PLANNING_PROFILES:
        raise ValueError("Unknown development planning profile")
    return PLANNING_PROFILES[profile]
