"""Prove constant column projections without replacing the actual read audit."""

import ast
from dataclasses import replace

from openpyxl.utils import coordinate_to_tuple, range_boundaries

from .executor import ExecutionResult

SOURCE_HELPERS = frozenset(
    {
        "cell",
        "num",
        "cells",
        "values",
        "label",
        "rows",
        "text",
        "age_days",
        "find_rows",
        "data_rows",
        "age_order",
        "latest_rows",
        "argmax",
        "category_rows",
    }
)


def column_projection(execution: ExecutionResult, code: str) -> ExecutionResult | None:
    """Narrow field evidence only for one closed, immutable row iteration.

    All row loads must be constant-index projections. Aliasing, escaping, helper
    shadowing, nested scopes, mutations, extra sources or formula dependencies
    leave evidence unchanged. Original reads/results/selection remain available
    to every other check and to the trace. This is not general Python taint analysis.
    """
    tree = ast.parse(code)
    nodes = list(ast.walk(tree))
    if any(
        isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        )
        for node in nodes
    ):
        return None
    parent = {child: node for node in nodes for child in ast.iter_child_nodes(node)}
    source_names = [
        node
        for node in nodes
        if isinstance(node, ast.Name) and node.id in SOURCE_HELPERS
    ]
    calls = [
        node
        for node in nodes
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in SOURCE_HELPERS
    ]
    if len(calls) != 1 or calls[0].func.id != "cells" or len(source_names) != 1:
        return None
    call = calls[0]
    if (
        call.keywords
        or len(call.args) != 2
        or any(
            not isinstance(arg, ast.Constant) or not isinstance(arg.value, str)
            for arg in call.args
        )
    ):
        return None
    assignment = parent.get(call)
    if (
        not isinstance(assignment, ast.Assign)
        or assignment.value is not call
        or len(assignment.targets) != 1
        or not isinstance(assignment.targets[0], ast.Name)
        or assignment not in tree.body
    ):
        return None
    container = assignment.targets[0].id
    uses = [
        node for node in nodes if isinstance(node, ast.Name) and node.id == container
    ]
    loads = [node for node in uses if isinstance(node.ctx, ast.Load)]
    if len(uses) != 2 or len(loads) != 1:
        return None
    loop = parent.get(loads[0])
    if (
        not isinstance(loop, ast.For)
        or loop.iter is not loads[0]
        or loop not in tree.body
        or not isinstance(loop.target, ast.Name)
        or tree.body.index(assignment) >= tree.body.index(loop)
    ):
        return None
    row = loop.target.id
    row_uses = [node for node in nodes if isinstance(node, ast.Name) and node.id == row]
    if sum(isinstance(node.ctx, ast.Store) for node in row_uses) != 1:
        return None
    sheet, area = (arg.value for arg in call.args)
    try:
        left, top, right, bottom = range_boundaries(area)
    except ValueError:
        return None
    if (
        any(value is None for value in (left, top, right, bottom))
        or left > right
        or top > bottom
    ):
        return None
    columns = set()
    loop_nodes = set(ast.walk(loop))
    for use in row_uses:
        if use is loop.target:
            continue
        subscript = parent.get(use)
        if (
            not isinstance(use.ctx, ast.Load)
            or not isinstance(subscript, ast.Subscript)
            or subscript.value is not use
            or not isinstance(subscript.ctx, ast.Load)
            or not isinstance(subscript.slice, ast.Constant)
            or type(subscript.slice.value) is not int
            or not 0 <= subscript.slice.value < right - left + 1
            or use not in loop_nodes
        ):
            return None
        columns.add(left + subscript.slice.value)
    if not columns:
        return None
    reads = {}
    for key, entry in execution.reads.items():
        name, address = key.rsplit("!", 1)
        try:
            r, c = coordinate_to_tuple(address)
        except (ValueError, KeyError):
            return None
        if name != sheet or not left <= c <= right or not top <= r <= bottom:
            return None
        if c in columns:
            reads[key] = entry
    return replace(execution, reads=reads)
