"""Runtime services have real owners behind the stable workflow entry point."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest


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


def test_runtime_services_read_run_indexes_through_the_context_compiler():
    root = Path(__file__).parents[1] / "backend/workbench/agent/workflow_runtime_parts"
    repository_readers = {"_read_artifacts_index", "_read_artifact_records", "read_artifacts_index"}
    managed_files = {"artifacts_index.json", "graph.json", "data_profile.json"}
    violations = []
    for path in sorted(root.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                names = {alias.name for alias in node.names} & repository_readers
            elif isinstance(node, ast.Attribute) and node.attr in repository_readers:
                names = {node.attr}
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names = {Path(node.value).name} & managed_files
            else:
                continue
            if names:
                violations.append(f"{path.name}:{node.lineno}: {', '.join(sorted(names))}")
    assert not violations, (
        "Read workflow artifact indexes through context_compiler.read_workflow_artifact_index "
        "and use context compiler accessors for other managed run files.\n"
        + "\n".join(violations)
    )


def test_workflow_artifact_index_preserves_missing_and_legacy_indexes(tmp_path):
    from workbench.agent import context_compiler

    read_index = getattr(context_compiler, "read_workflow_artifact_index", None)
    assert callable(read_index), "the context compiler must expose the workflow artifact-index reader"
    assert read_index(tmp_path) == {"artifacts": []}
    index = {"artifacts": [{"artifact_id": "output"}], "owner": "runtime"}
    (tmp_path / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")
    assert read_index(tmp_path) == index


@pytest.mark.parametrize(
    ("schema_version", "code"),
    [(True, "REGISTRY_VERSION_INVALID"), (0, "REGISTRY_VERSION_INVALID"),
     (2, "REGISTRY_VERSION_UNSUPPORTED")],
)
def test_workflow_artifact_index_preserves_registry_validation(tmp_path, schema_version, code):
    from workbench.agent import context_compiler
    from workbench.api_errors import WorkbenchAPIError

    read_index = getattr(context_compiler, "read_workflow_artifact_index", None)
    assert callable(read_index), "the context compiler must expose the workflow artifact-index reader"
    index = {"schema_version": schema_version, "artifacts": []}
    (tmp_path / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(WorkbenchAPIError) as error:
        read_index(tmp_path)
    assert error.value.code == code


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
