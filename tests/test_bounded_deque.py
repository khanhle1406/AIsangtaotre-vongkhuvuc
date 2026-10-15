"""Bounded standard queues must preserve order and fail before oversized mutation."""

import collections
import itertools

import pytest

from src.excel_parser import CellData, SheetData, WorkbookData
from src.executor import MAX_ITEMS, BoundedDeque, execute_program


@pytest.mark.parametrize("maxlen", [None, 3, 0])
def test_queue_operations_match_the_standard_library(maxlen: int | None) -> None:
    expected = collections.deque([1, 2], maxlen=maxlen)
    actual = BoundedDeque([1, 2], maxlen=maxlen)
    for method, arg in [
        ("append", 3),
        ("appendleft", 4),
        ("extend", [5, 6]),
        ("extendleft", [7, 8]),
        ("rotate", -2),
    ]:
        getattr(actual, method)(arg)
        getattr(expected, method)(arg)
        assert list(actual) == list(expected) and actual.maxlen == expected.maxlen
    if actual:
        assert actual.popleft() == expected.popleft()
        assert actual.pop() == expected.pop()
    actual += [9]
    expected += [9]
    assert list(actual * 2) == list(expected * 2)
    assert list(2 * actual) == list(2 * expected)
    assert list(actual + BoundedDeque([10])) == list(expected + collections.deque([10]))


def test_queue_limits_do_not_silently_drop_data_or_partially_extend() -> None:
    full = BoundedDeque(range(MAX_ITEMS))
    for action in [
        lambda: full.append(1),
        lambda: full.appendleft(1),
        lambda: full.extend([1]),
        lambda: full.extendleft([1]),
        lambda: full * 2,
    ]:
        with pytest.raises(MemoryError, match="item cap"):
            action()
        assert len(full) == MAX_ITEMS and full[0] == 0 and full[-1] == MAX_ITEMS - 1
    with pytest.raises(MemoryError, match="input"):
        BoundedDeque(itertools.repeat(1))
    with pytest.raises(ValueError, match="maxlen"):
        BoundedDeque(maxlen=MAX_ITEMS + 1)


def test_queue_is_available_in_the_worker_without_private_attribute_access() -> None:
    wire = WorkbookData(
        {
            "Moved": SheetData(
                "Moved",
                cells={
                    "G408": CellData(17, "number"),
                    "G409": CellData(23, "number"),
                    "G410": CellData(29, "number"),
                },
            )
        }
    ).wire()
    code = "from collections import deque\nq=deque(values('Moved','G408:G410'));q.append(q.popleft()*2);result=list(q)"
    result = execute_program(code, wire)
    assert result.success and result.result == [23, 29, 34]
    aliased = execute_program(
        "from collections import deque\nq=deque(values('Moved','G408:G410'));alias=q;q += [num('Moved','G408')];q*=2;result=list(alias)",
        wire,
    )
    assert aliased.success and aliased.result == [17, 23, 29, 17, 17, 23, 29, 17]
    assert not execute_program(
        "from collections import deque\nresult=deque().__class__"
    ).success
    excessive = execute_program(
        "from collections import deque\nq=deque([1]);q*=200001;result=list(q)"
    )
    assert not excessive.success and "item cap" in excessive.error
