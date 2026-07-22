"""A natural-language ARMA-GARCH request must become a *legal* typed patch.

The transport already accepted any object as `model_options`, so an Agent could
produce a confirmable proposal that the frozen contract would reject only once
the child run executed — the user pays for a failed run to learn the patch was
never valid. These tests pin the other half of the loop: the pack judges the
patch when the proposal is created.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.agent.context_tools import NodeOperationContextProvider
from workbench.agent.events import AgentEventStream
from workbench.agent.operations import OperationRegistry
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.session import JsonlSessionRepository

from tests.test_agent_context_tools import _write_project_run


VIX_CONTRACT: dict[str, object] = {
    "dataset_ref": "dataset:vix:1",
    "time_column": "observation_date",
    "value_column": "VIXCLS",
    "time_index_semantics": "business_or_trading_observations",
    "transform": "log_return_pct",
    "transform_confirmed": True,
    "validation": {"validation_n": 250},
}


def _project(tmp_path: Path, *, time_series: bool = True) -> Path:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    run_root = project_root / "runs" / "run-a"
    if not time_series:
        return project_root

    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["model_routing"] = {
        "requested_model_type": "time_series.arma_garch",
        "effective_model_type": "time_series.arma_garch",
    }
    (run_root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract

    artifact_root = run_root / "artifacts" / "time_series"
    artifact_root.mkdir(parents=True)
    (artifact_root / "ts.analysis_contract.json").write_text(
        json.dumps(
            {
                "artifact_id": "ts.analysis_contract",
                "metadata": {
                    "run_id": "run-a",
                    "source_run_id": None,
                    "node_id": "model:ols_1",
                },
                "payload": ArmaGarchAnalysisContract.from_dict(VIX_CONTRACT).to_dict(),
            }
        ),
        encoding="utf-8",
    )
    return project_root


def _orchestrator(project_root: Path) -> WorkbenchOrchestrator:
    workbench_root = project_root / "workbench"
    repository = JsonlSessionRepository(workbench_root)
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    return WorkbenchOrchestrator(
        repository,
        AgentEventStream(workbench_root),
        main_session_id="agent_main",
        operation_registry=OperationRegistry(),
        context_provider=NodeOperationContextProvider(project_root),
    )


def _proposal(patch: dict[str, object]) -> dict[str, object]:
    return {
        "operation_id": "model.rerun",
        "target": {"run_id": "run-a", "node_ref": "model:ols_1"},
        "preconditions": {"active_head_run_id": "run-a"},
        "changes": {"model_options": patch},
    }


def _canonicalize(project_root: Path, patch: dict[str, object]) -> dict[str, object]:
    return _orchestrator(project_root)._canonicalize_proposal_arguments(
        "model.rerun", _proposal(patch), session_id="chain-session"
    )


def test_a_legal_patch_survives_canonicalization(tmp_path: Path) -> None:
    """"Use Student-t innovations and hold out 500 observations." """

    project_root = _project(tmp_path)

    canonical = _canonicalize(
        project_root,
        {"innovation_distribution": "student_t", "validation": {"validation_n": 500}},
    )

    assert canonical["changes"]["model_options"] == {
        "innovation_distribution": "student_t",
        "validation": {"validation_n": 500},
    }
    # The backend still owns identity; the patch is the only thing the model supplied.
    assert canonical["target"]["node_hash"] == "hash-a"


def test_missing_value_recovery_is_a_typed_model_rerun_patch(tmp_path: Path) -> None:
    canonical = _canonicalize(
        _project(tmp_path),
        {"missing_value_policy": "drop_missing_confirmed"},
    )
    assert canonical["changes"]["model_options"] == {
        "missing_value_policy": "drop_missing_confirmed"
    }


def test_a_partial_section_patch_is_merged_not_replaced(tmp_path: Path) -> None:
    """A patch naming one key of `validation` must not blank out the others."""

    project_root = _project(tmp_path)

    # refit_every is absent from the patch; if the merge replaced the section
    # wholesale the contract would reject the payload as missing keys.
    canonical = _canonicalize(project_root, {"validation": {"refit_every": 5}})

    assert canonical["changes"]["model_options"] == {"validation": {"refit_every": 5}}


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"arma": {"p": 1, "q": 1}}, "INVALID_ORDER"),
        (
            {
                "selection_mode": "manual",
                "estimation_strategy": "joint",
                "arma": {"p": 1, "q": 1},
                "variance": {"model": "garch", "garch_p": 1, "garch_q": 1},
            },
            "UNSUPPORTED_JOINT_ARMA_GARCH",
        ),
        ({"arma": {"auto_max_p": 9}}, "CANDIDATE_LIMIT_EXCEEDED"),
        ({"transform": "not_a_transform"}, "INVALID_ORDER"),
        ({"invented_field": 1}, "INVALID_ORDER"),
    ],
    ids=[
        "fixed_orders_in_auto_mode",
        "joint_estimation_with_an_ma_term",
        "auto_search_cap_exceeded",
        "value_outside_the_closed_set",
        "field_the_contract_does_not_have",
    ],
)
def test_an_illegal_patch_is_rejected_before_the_user_can_confirm_it(
    tmp_path: Path, patch: dict[str, object], code: str
) -> None:
    project_root = _project(tmp_path)

    with pytest.raises(ValueError) as excinfo:
        _canonicalize(project_root, patch)

    # The pack's own code reaches the Agent, so it can correct the patch rather
    # than guess why it was refused.
    assert code in str(excinfo.value)


def test_a_pack_without_a_validator_is_left_alone(tmp_path: Path) -> None:
    """OLS declares no patch validator; the precheck must not invent one."""

    project_root = _project(tmp_path, time_series=False)

    canonical = _canonicalize(project_root, {"random_slope": False})

    assert canonical["changes"]["model_options"] == {"random_slope": False}


def test_an_empty_patch_is_left_to_the_generic_validator(tmp_path: Path) -> None:
    project_root = _project(tmp_path)

    canonical = _canonicalize(project_root, {})

    assert canonical["changes"]["model_options"] == {}


def test_the_refusal_reaches_the_model_not_just_the_exception_class(
    tmp_path: Path,
) -> None:
    """Found by a live DeepSeek turn, not by the deterministic suite.

    The pack refused an auto-mode patch with a specific code, but the tool
    layer reported only `ValueError` to the model. It could not tell a bad
    field name from a bad combination, retried, and burned the turn. A refusal
    is only useful if the reason travels with it.
    """

    import asyncio

    from workbench.agent.tools import ToolRegistry, ToolVisibleError

    project_root = _project(tmp_path)
    orchestrator = _orchestrator(project_root)

    with pytest.raises(ToolVisibleError) as excinfo:
        orchestrator._precheck_model_options(
            owner_run_id="run-a",
            changes={"model_options": {"arma": {"p": 1, "q": 1}}},
        )
    assert "INVALID_ORDER" in str(excinfo.value)

    # And the registry must forward that message rather than swallowing it.
    registry = ToolRegistry()
    registry.register(
        __import__("workbench.agent.tools", fromlist=["ToolDefinition"]).ToolDefinition(
            tool_id="boom",
            version="v1",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            side_effect="none",
            scope_requirements=(),
            handler=lambda _a, _c: (_ for _ in ()).throw(ToolVisibleError("SPECIFIC_CODE: do this")),
        )
    )
    result = asyncio.run(
        registry.execute(
            {"tool_call_id": "t1", "tool_id": "boom", "arguments": {}},
            session_id="s",
        )
    )
    assert result.ok is False
    assert result.error_details == [{"message": "SPECIFIC_CODE: do this"}]
    assert "SPECIFIC_CODE" in json.dumps(result.to_payload())
