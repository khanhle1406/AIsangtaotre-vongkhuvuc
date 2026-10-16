"""Schedule independent repairs without multiplying live model/worker concurrency."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, ClassVar

from src.excel_parser import WorkbookData
from src.llm_agent import QueryState, SolveResult

from .batched import apportioned_calls


class ScheduledPlanningMixin:
    """One shared semaphore covers both planning and complete per-question solves."""

    concurrent_repairs: ClassVar[bool] = True

    def __init__(self, *, repair_concurrency: int = 4, **kwargs: Any) -> None:
        if type(repair_concurrency) is not int or repair_concurrency not in {1, 2, 4}:
            raise ValueError("Repair concurrency must be 1, 2 or 4")
        super().__init__(**kwargs)
        self.repair_concurrency = repair_concurrency
        self.repair_slots = threading.BoundedSemaphore(repair_concurrency)

    def planning_request(
        self, messages: list[dict[str, str]], state: QueryState
    ) -> str:
        with self.repair_slots:
            return super().planning_request(messages, state)

    def solve_workbook(
        self, workbook: WorkbookData, query: str, max_retries: int = 2
    ) -> SolveResult:
        waiting = time.monotonic()
        with self.repair_slots:
            queued = time.monotonic() - waiting
            result = super().solve_workbook(workbook, query, max_retries)
        result.elapsed += queued
        return result

    def finish_plans(
        self,
        workbook: WorkbookData,
        questions: list[dict[str, Any]],
        programs: list[str],
        calls: list[dict[str, Any]],
        plan_seconds: float,
    ) -> list[dict[str, Any]]:
        with ThreadPoolExecutor(max_workers=self.repair_concurrency) as workers:
            futures = [
                workers.submit(
                    self.solve_prepared_question,
                    workbook,
                    question,
                    program,
                    apportioned_calls(calls, index, len(questions)),
                    plan_seconds,
                )
                for index, (question, program) in enumerate(
                    zip(questions, programs, strict=True)
                )
            ]
            return [future.result() for future in futures]
