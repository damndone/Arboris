"""No ``sum(map(float, values))`` outside the places that define what the Rust kernel repeats.

That expression walks an array one boxed float at a time: about 20 ms per million values, and
the statistics stage of a 1,000,000-row OLS ran it 64 times (2026-11-03 profile).
``native_kernels.python_sum`` returns the same bits from the array. The guard reads the source
statically, so a new call site fails here instead of in a profile.
"""
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "backend" / "workbench"

#: (module, function) pairs allowed to keep it: the kernel's self-check reference and the
#: Python fallback when the kernel is not built.
ALLOWED = {
    ("native_kernels.py", "_agrees_with_reference"),
    ("statistical_test_kernels.py", "__init__"),
}


def _is_sum_of_float_map(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sum"
            and len(node.args) >= 1 and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name) and node.args[0].func.id == "map"
            and len(node.args[0].args) == 2 and isinstance(node.args[0].args[0], ast.Name)
            and node.args[0].args[0].id == "float")


def _offenders() -> list[str]:
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        scopes = [(node.name, node) for node in ast.walk(tree)
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for node in ast.walk(tree):
            if not _is_sum_of_float_map(node):
                continue
            enclosing = [name for name, scope in scopes
                         if scope.lineno <= node.lineno <= (scope.end_lineno or scope.lineno)]
            function = enclosing[-1] if enclosing else "<module>"
            if (str(path.relative_to(PACKAGE)), function) not in ALLOWED:
                found.append(f"{path.relative_to(PACKAGE)}:{node.lineno} in {function}")
    return found


def test_no_python_float_sum_over_arrays():
    assert _offenders() == [], "use native_kernels.python_sum: " + ", ".join(_offenders())


def test_the_guard_recognises_the_pattern():
    assert _is_sum_of_float_map(ast.parse("sum(map(float, values))").body[0].value)
    assert not _is_sum_of_float_map(ast.parse("sum(values)").body[0].value)
    assert not _is_sum_of_float_map(ast.parse("sum(map(int, values))").body[0].value)
