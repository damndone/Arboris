"""Result projection is separate from Notebook lifecycle authority."""
import ast
from pathlib import Path


def test_execution_outcome_has_one_owner():
    from workbench.agent.notebook.execution_results import ExecutionOutcome
    from workbench.agent.notebook.service import ExecutionOutcome as public_outcome

    assert ExecutionOutcome is public_outcome
    assert ExecutionOutcome.__module__ == 'workbench.agent.notebook.execution_results'


def test_result_projection_cannot_reach_lifecycle_or_provider():
    path = Path(__file__).parents[1] / 'backend/workbench/agent/notebook/execution_results.py'
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module not in {'service', 'planning_agent', 'producer'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert {'workflow_execution_receipt', 'workflow_produced_artifacts'} <= {n.name for n in functions}
    assert all('self' not in {arg.arg for arg in node.args.args} for node in functions)
