"""Workflow contracts have explicit owners and one live declaration registry."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
import subprocess
import sys

import pytest

from workbench.agent import workflow_contracts as facade


PARTS = Path(facade.__file__).with_name("workflow_contract_parts")
OWNERS = {
    "contracts": ("StepSpecContract", "pack_step_contract"),
    "declarations": ("statistical_workflow_step_contracts", "recipe_workflow_step_contracts"),
    "registry": ("WorkflowStepContractRegistry", "register_workflow_step", "workflow_step_vocabulary"),
    "validation": ("validate_model_genesis_spec", "_validate_step_spec"),
    "graph": ("validate_workflow_steps", "_topological_order"),
    "proposal": ("workflow_proposal_schema", "validate_workflow_operation", "workflow_authorization"),
}


@pytest.mark.parametrize("owner,names", OWNERS.items())
def test_contract_behavior_has_one_explicit_owner(owner: str, names: tuple[str, ...]) -> None:
    assert (PARTS / f"{owner}.py").is_file(), f"missing contract owner: {owner}"
    module = importlib.import_module(f"workbench.agent.workflow_contract_parts.{owner}")
    for name in names:
        implementation = getattr(module, name)
        assert getattr(facade, name) is implementation
        assert implementation.__module__ == module.__name__


def test_contract_parts_do_not_import_facade_or_form_cycles() -> None:
    assert PARTS.is_dir(), "workflow contract parts must be real modules"
    edges: dict[str, set[str]] = {}
    for path in PARTS.glob("*.py"):
        imports: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                target = node.module or ""
                assert "workflow_contracts" not in target
                if node.level == 1 and target in OWNERS:
                    imports.add(target)
                elif node.level == 1 and not target:
                    imports.update(alias.name for alias in node.names if alias.name in OWNERS)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"exec", "eval"}
        edges[path.stem] = imports
    def visit(name: str, ancestors: set[str]) -> None:
        assert name not in ancestors, f"contract import cycle at {name}"
        for dependency in edges.get(name, ()):
            visit(dependency, ancestors | {name})
    for name in edges:
        visit(name, set())


def test_registration_preserves_public_view_identity_and_order(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (PARTS / "registry.py").is_file(), "registry must have one explicit owner"
    registry = importlib.import_module("workbench.agent.workflow_contract_parts.registry")
    original = facade.workflow_step_operations()
    contract = facade.StepSpecContract(
        summary="Boundary test declaration.", fields={}, dispatcher_key="test.boundary",
    )
    monkeypatch.setitem(facade.WORKFLOW_STEP_SPEC_CONTRACTS, "test.contract_boundary", contract)
    assert facade.WORKFLOW_STEP_SPEC_CONTRACTS is registry.WORKFLOW_STEP_SPEC_CONTRACTS
    assert facade.WORKFLOW_STEP_OPERATIONS is registry.WORKFLOW_STEP_OPERATIONS

    assert facade.STEP_CONSUMES_INPUT_FRAME is registry.STEP_CONSUMES_INPUT_FRAME
    assert facade.STEP_PRODUCES_DATASET is registry.STEP_PRODUCES_DATASET
    assert facade.STEP_REPLAYABLE_BY_RECIPE is registry.STEP_REPLAYABLE_BY_RECIPE
    assert facade.workflow_step_operations() == (*original, "test.contract_boundary")
    assert facade.workflow_step_vocabulary()["step_operations"]["test.contract_boundary"] == contract.to_payload()
    del facade.WORKFLOW_STEP_SPEC_CONTRACTS["test.contract_boundary"]
    assert facade.workflow_step_operations() == original
    assert facade.WORKFLOW_STEP_OPERATIONS is registry.WORKFLOW_STEP_OPERATIONS


@pytest.mark.parametrize("first", ("registry", "facade"))
def test_cold_import_order_does_not_require_facade_bootstrap(first: str) -> None:
    # Bypass agent.__init__'s eager orchestrator import so registry-first really
    # exercises the registry without the facade already present in sys.modules.
    script = """
import importlib
import sys
import types

agent = types.ModuleType('workbench.agent')
agent.__path__ = [sys.argv[1]]
sys.modules['workbench.agent'] = agent
if sys.argv[2] == 'registry':
    registry = importlib.import_module('workbench.agent.workflow_contract_parts.registry')
    assert 'workbench.agent.workflow_contracts' not in sys.modules
    facade = importlib.import_module('workbench.agent.workflow_contracts')
else:
    facade = importlib.import_module('workbench.agent.workflow_contracts')
    registry = importlib.import_module('workbench.agent.workflow_contract_parts.registry')
assert facade.WORKFLOW_STEP_SPEC_CONTRACTS is registry.WORKFLOW_STEP_SPEC_CONTRACTS
assert facade.WORKFLOW_STEP_OPERATIONS is registry.WORKFLOW_STEP_OPERATIONS
assert facade.workflow_step_operations()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(PARTS.parent), first],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
