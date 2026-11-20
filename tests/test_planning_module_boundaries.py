"""Planning contracts can be used without importing the provider loop."""

from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


def _planning_module(name: str):
    assert importlib.util.find_spec("workbench.agent.planning") is not None, (
        "Planning parsing, validation and correction need independent modules"
    )
    return importlib.import_module(f"workbench.agent.planning.{name}")


@pytest.mark.parametrize(
    ("module_name", "symbols"),
    [
        ("types", ("AgentOptionSubmission", "NotebookPlanningContractError", "PlanningRefusal")),
        ("normalize", ("_parse_submissions", "_canonicalize_provider_option_batch", "_execution_pins")),
        ("validation", ("_validate_submissions", "_assert_user_visible_domain_language")),
        ("corrections", ("_correction_instruction", "_append_contract_correction")),
    ],
)
def test_planning_symbols_are_owned_by_independent_modules(module_name, symbols):
    module = _planning_module(module_name)
    for symbol in symbols:
        assert getattr(module, symbol).__module__ == module.__name__


def test_legacy_planning_module_exposes_only_the_public_contract():
    types = _planning_module("types")
    normalize = _planning_module("normalize")
    agent = _planning_module("agent")
    legacy = importlib.import_module("workbench.agent.notebook.planning_agent")
    for name in (
        "AgentOptionSubmission", "PlanningResult", "PlanningRefusal",
        "NotebookPlanningContractError", "NotebookPlanningUnavailable",
        "NotebookPlanningTimeout", "NotebookNoEligibleCapability",
    ):
        assert getattr(legacy, name) is getattr(types, name)
    assert legacy.NotebookPlanningAgent is agent.NotebookPlanningAgent
    assert {name for name in vars(legacy) if name.startswith("_") and not name.startswith("__")} == set()
    with pytest.raises(legacy.NotebookPlanningContractError, match="option tool arguments"):
        normalize._parse_submissions({"unexpected": []})


def test_planning_module_import_graph_has_no_cycle_or_provider_back_edge():
    root = Path(_planning_module("types").__file__).parent
    graph = {}
    for path in root.glob("*.py"):
        node = f"workbench.agent.planning.{path.stem}"
        dependencies = set()
        tree = ast.parse(path.read_text())
        for statement in ast.walk(tree):
            if isinstance(statement, ast.ImportFrom):
                module = statement.module or ""
                if statement.level:
                    module = importlib.util.resolve_name(
                        "." * statement.level + module, "workbench.agent.planning"
                    )
                assert "notebook.planning_agent" not in module
                if module.startswith("workbench.agent.planning."):
                    dependencies.add(module)
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    assert "notebook.planning_agent" not in alias.name
                    if alias.name.startswith("workbench.agent.planning."):
                        dependencies.add(alias.name)
            elif isinstance(statement, ast.Call) and isinstance(statement.func, ast.Name):
                assert statement.func.id not in {"exec", "eval", "globals", "__import__"}
        graph[node] = dependencies

    def visit(node, visiting):
        assert node not in visiting, f"Planning import cycle through {node}"
        for dependency in graph.get(node, ()):
            visit(dependency, visiting | {node})

    for node in graph:
        visit(node, set())


def test_semantic_validation_uses_explicit_dependencies_without_a_provider():
    validation = _planning_module("validation")
    types = _planning_module("types")
    from workbench.agent.notebook.evidence import DataEvidencePackV1
    from workbench.agent.operations import OperationRegistry

    # Empty batches are rejected before reading context or invoking a validator.
    with pytest.raises(types.NotebookPlanningContractError, match="option batch must contain 1 to 3 options"):
        validation._validate_submissions(
            None, DataEvidencePackV1(source_id="source", records=()), (), {},
            operation_registry=OperationRegistry(),
            proposal_validator=None,
            artifact_types_by_capability={},
        )


@pytest.mark.parametrize("first_module", ["types", "normalize", "validation", "corrections"])
def test_direct_import_does_not_load_the_provider_loop(first_module):
    result = subprocess.run(
        [
            sys.executable, "-c",
            f"import workbench.agent.planning.{first_module}; "
            "import sys; "
            "assert 'workbench.agent.notebook.planning_agent' not in sys.modules; "
            "from workbench.agent.notebook.planning_agent import NotebookPlanningAgent",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
