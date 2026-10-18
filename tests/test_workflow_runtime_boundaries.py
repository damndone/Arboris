"""Runtime services have real owners behind the stable workflow entry point."""
from __future__ import annotations

import ast
from pathlib import Path


def test_runtime_services_are_owned_by_dependency_directed_modules():
    from workbench.agent import workflow_runtime
    from workbench.agent.workflow_runtime_parts import inputs, models, projection

    assert workflow_runtime._workflow_input_frame is inputs._workflow_input_frame
    assert workflow_runtime._execute_model_genesis_branches is models._execute_model_genesis_branches
    assert workflow_runtime.collect_post_estimation_results is projection.collect_post_estimation_results
    assert inputs._workflow_input_frame.__module__ == inputs.__name__
    assert models._execute_model_genesis_branches.__module__ == models.__name__


def test_runtime_services_do_not_import_the_facade():
    root = Path(__file__).parents[1] / 'backend/workbench/agent/workflow_runtime_parts'
    assert root.is_dir()
    for path in root.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert node.module != 'workflow_runtime', path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {'exec', 'eval'}, path


def test_runtime_service_dependencies_are_acyclic():
    root = Path(__file__).parents[1] / 'backend/workbench/agent/workflow_runtime_parts'
    graph = {}
    for path in root.glob('*.py'):
        graph[path.stem] = {
            node.module for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module
        }

    def visit(name, ancestors):
        assert name not in ancestors, ' -> '.join([*ancestors, name])
        for dependency in graph.get(name, ()):
            visit(dependency, [*ancestors, name])

    for name in graph:
        visit(name, [])
