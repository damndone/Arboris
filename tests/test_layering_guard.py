"""Lower layers never import the Agent layer (V1812-CONTRACT-LAYERING).

The model-family contracts, the estimation engine, the orchestrator,
admission and the statistics packages are what the Agent plans over; the
Agent depends on them, not the reverse. Before v1.8.12 the family contract
table lived in ``agent/workflow_contracts.py`` and the engine, orchestrator
and admission reached up for it.

Imports are read statically, including ones inside functions (the usual way
an upward dependency hides), and relative imports are resolved to the module
they name.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "backend" / "workbench"

#: Packages and modules below the Agent layer. A new low-level package belongs here.
LOWER_LAYERS = (
    "contracts",
    "econometrics",
    "postestimation",
    "engine",
    "orchestrator",
    "survey",
    "combinators",
    "admission.py",
    "events.py",
    "exploration_log.py",
    "formula_terms.py",
    "jsonl_store.py",
    "model_options.py",
    "model_terms.py",
)
UPPER = "workbench.agent"


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(PACKAGE.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                target = ".".join([*base, node.module] if node.module else base)
            else:
                target = node.module or ""
            found.append((node.lineno, target))
            # `from workbench import agent` / `from .. import agent`
            found.extend((node.lineno, f"{target}.{alias.name}") for alias in node.names)
    return found


def _lower_layer_files() -> list[Path]:
    files: list[Path] = []
    for entry in LOWER_LAYERS:
        target = PACKAGE / entry
        assert target.exists(), f"declared lower layer {entry} does not exist"
        files.extend(sorted(target.rglob("*.py")) if target.is_dir() else [target])
    return files


def test_lower_layers_do_not_import_the_agent_layer() -> None:
    offenders = sorted({
        f"{path.relative_to(PACKAGE.parent)}:{line}"
        for path in _lower_layer_files()
        for line, name in _imported_modules(path)
        if name == UPPER or name.startswith(UPPER + ".")
    })
    assert not offenders, "lower layers import the Agent layer:\n" + "\n".join(offenders)


def test_the_guard_sees_relative_and_function_level_imports(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "workbench"
    (fake / "engine" / "stages").mkdir(parents=True)
    (fake / "engine" / "stages" / "probe.py").write_text(
        "def f():\n    from ...agent.workflow_contracts import X\n", encoding="utf-8"
    )
    (fake / "engine" / "plain.py").write_text("from workbench import agent\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "PACKAGE", fake)
    names = [name for path in sorted((fake / "engine").rglob("*.py")) for _, name in _imported_modules(path)]
    assert "workbench.agent.workflow_contracts" in names
    assert "workbench.agent" in names


def test_the_family_contract_table_lives_in_the_contracts_layer() -> None:
    from workbench.contracts.model import family

    assert family.ModelFamilyContract.__module__ == "workbench.contracts.model.family"
    assert "ols" in family.MODEL_FAMILY_CONTRACTS
