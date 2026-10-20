"""Tool publication and proposal shaping have explicit orchestration boundaries."""

from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
from pathlib import Path

import pytest


def _toolsets():
    assert importlib.util.find_spec("workbench.agent.toolsets") is not None, (
        "Tool schemas and assembly need an independent owner"
    )
    return importlib.import_module("workbench.agent.toolsets")


def _proposal_arguments():
    assert importlib.util.find_spec("workbench.agent.operation_handlers") is not None, (
        "Proposal shaping needs an independent operation-handler boundary"
    )
    return importlib.import_module("workbench.agent.operation_handlers.proposal_arguments")


def test_tool_publication_and_proposal_shaping_are_independently_owned():
    toolsets = _toolsets()
    arguments = _proposal_arguments()
    assert toolsets.build_chain_tool_registry.__module__ == toolsets.__name__
    for name in (
        "_canonicalize_data_columns_cast_arguments", "_canonicalize_workflow_arguments",
        "_clustered_analysis_loop_intent", "_precheck_model_options",
        "_overrides_from_proposal_changes", "_require_editable_rerun_target",
    ):
        assert getattr(arguments, name).__module__ == arguments.__name__


def test_extracted_boundaries_do_not_import_or_accept_the_orchestrator():
    for module in (_toolsets(), _proposal_arguments()):
        tree = ast.parse(Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "orchestrator" not in (node.module or "")
            elif isinstance(node, ast.Import):
                assert all("orchestrator" not in alias.name for alias in node.names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert not {arg.arg for arg in node.args.args} & {"self", "orchestrator"}
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"exec", "eval", "globals", "__import__"}


def test_proposal_shaping_retains_nested_options_and_unconfigured_passthrough():
    module = _proposal_arguments()
    options = {"old": {"covariance": "HC0"}, "new": {"covariance": "HC1"}}
    changes = {"model_options": options, "y": {"old": "old_y", "new": "new_y"}}
    overrides = module._overrides_from_proposal_changes(changes)
    assert overrides == {"model_options": options, "y": "new_y"}
    assert overrides["model_options"] is options
    arguments = {"target": {"run_id": "run", "node_ref": "source"}}
    assert module._canonicalize_workflow_arguments(arguments, project_root=None) is arguments
    assert module._canonicalize_data_columns_cast_arguments(arguments, project_root=None) is arguments


def test_tool_builder_uses_injected_handlers_and_preserves_descriptors():
    module = _toolsets()
    from workbench.agent.tools import ToolDefinition

    seen = []

    def inspect(arguments, context):
        seen.append(("inspect", context.session_id))
        return {"read": True}

    async def propose(arguments, context):
        seen.append(("propose", context.session_id))
        return {"requires_confirmation": True}

    registry = module.build_chain_tool_registry(
        context_tools=[ToolDefinition("inspect", "v1", {"type": "object"}, "none", inspect)],
        proposal_tool_schema=lambda: {"type": "object"},
        update_plan=propose,
        run_operation=propose,
        plan_analysis=propose,
        inspect_analysis_completion=inspect,
    )
    descriptors = {item["tool_id"]: item for item in registry.descriptors()}
    assert set(descriptors) == {"inspect", "update_plan", "run_operation", "plan_analysis", "inspect_analysis_completion"}
    assert descriptors["run_operation"]["max_output_budget"] == 24_000
    assert descriptors["update_plan"]["input_schema"] is module._UPDATE_PLAN_SCHEMA
    assert descriptors["run_operation"]["side_effect"] == "proposal"
    assert seen == []
    result = asyncio.run(registry.execute(
        {"tool_id": "run_operation", "tool_call_id": "call", "arguments": {}},
        session_id="chain-session",
    ))
    assert result.ok and result.output == {"requires_confirmation": True}
    assert seen == [("propose", "chain-session")]


def test_duplicate_tool_is_rejected_before_building_the_proposal_schema():
    module = _toolsets()
    from workbench.agent.tools import ToolDefinition

    def schema():
        pytest.fail("Proposal schema must be requested after earlier tools register")

    def handler(arguments, context):
        pytest.fail("Registry assembly must not invoke a handler")

    with pytest.raises(ValueError, match="tool already registered: update_plan"):
        module.build_chain_tool_registry(
            context_tools=[ToolDefinition("update_plan", "v1", {"type": "object"}, "none", handler)],
            proposal_tool_schema=schema,
            update_plan=handler,
            run_operation=handler,
            plan_analysis=handler,
            inspect_analysis_completion=handler,
        )
