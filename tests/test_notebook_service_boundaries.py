"""Result projection is separate from Notebook lifecycle authority."""
import ast
from pathlib import Path

import pytest


def test_execution_outcome_has_one_owner():
    from workbench.agent.notebook.execution_results import ExecutionOutcome
    from workbench.agent.notebook.service import ExecutionOutcome as public_outcome

    assert ExecutionOutcome is public_outcome
    assert ExecutionOutcome.__module__ == 'workbench.agent.notebook.execution_results'


def test_service_imports_are_locally_used_or_public():
    from workbench.agent.notebook import service

    tree = ast.parse(Path(service.__file__).read_text())
    imported = {
        alias.asname or alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, (ast.ImportFrom, ast.Import))
        and getattr(node, "module", None) != "__future__"
        for alias in node.names
    }
    referenced = {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    assert imported - referenced - set(service.__all__) == set()


@pytest.mark.parametrize(
    ("source", "function"),
    [
        ("http/notebook_routes.py", "propose_options_endpoint"),
        ("agent/planning/agent_phase.py", "consume"),
    ],
)
def test_provider_entry_points_share_notebook_planning_admission(source, function):
    path = Path(__file__).parents[1] / "backend/workbench" / source
    tree = ast.parse(path.read_text())
    entry = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function
    )
    calls = {
        node.func.attr for node in ast.walk(entry)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "submit_planned_options" in calls
    assert "derive_server_recommendation" not in calls


def test_result_projection_cannot_reach_lifecycle_or_provider():
    path = Path(__file__).parents[1] / 'backend/workbench/agent/notebook/execution_results.py'
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module not in {'service', 'planning_agent', 'producer'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert {'workflow_execution_receipt', 'workflow_produced_artifacts'} <= {n.name for n in functions}
    assert all('self' not in {arg.arg for arg in node.args.args} for node in functions)
