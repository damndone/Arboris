"""v1.7 priority 6 — the NL Agent proposes the SAME typed data-cast proposal.

The point of this slice is not that a model can emit JSON. It is that the model
supplies only intent, and every fact that makes the proposal *executable* is
re-derived by the backend — so a proposal the user can confirm is one that will
actually run, and a model cannot aim it at data nobody selected.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from workbench.agent.context_tools import (
    InspectDataSchemaRequest,
    NodeOperationContextProvider,
)
from workbench.agent.events import AgentEventStream
from workbench.agent.operations import OperationRegistry
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.session import JsonlSessionRepository
from workbench.data_operations import (
    DataCastItem,
    DataColumnsCastSpecV1,
    preview_data_columns_cast,
)

from tests.test_data_column_cast import _source_project


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"age": ["10", "11"], "name": ["a", "b"]})


def _orchestrator(project: Path) -> WorkbenchOrchestrator:
    workbench_root = project / "workbench"
    repository = JsonlSessionRepository(workbench_root)
    return WorkbenchOrchestrator(
        repository,
        AgentEventStream(workbench_root),
        main_session_id="agent_main",
        operation_registry=OperationRegistry(),
        context_provider=NodeOperationContextProvider(project),
    )


def _seed_node_index(project: Path, run_id: str, node_id: str = "stage:source") -> None:
    """Give the node a Merkle identity — the inspect tools answer canonically."""

    from workbench.artifacts import write_json
    from workbench.lineage.node_index import NODE_INDEX_FILENAME

    write_json(
        project / "runs" / run_id / NODE_INDEX_FILENAME,
        {
            node_id: {
                "node_hash": "a" * 64,
                "producing_stage": "cleaning",
                "cas_ref": {"node_hash": "a" * 64, "artifact": "data.csv"},
            }
        },
    )


def test_inspect_data_schema_shows_columns_but_withholds_the_artifact_id(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    _seed_node_index(project, run_id)
    provider = NodeOperationContextProvider(project)

    result = provider.inspect_data_schema(
        InspectDataSchemaRequest(
            request_id="r1",
            owner_run_id=run_id,
            op_node_id="stage:source",
            active_head_run_id=run_id,
        )
    )

    schema = result["data_schema"]
    assert schema["available"] is True
    assert schema["row_count"] == 2
    assert {c["name"] for c in schema["columns"]} == {"age", "name"}
    # The Agent can see WHAT the columns are without being handed the durable
    # artifact identity it must never choose.
    assert artifact_id not in str(result)


def test_data_node_contract_is_readable_because_the_registry_owns_it(
    tmp_path: Path,
) -> None:
    """Found by the live DeepSeek smoke, not by the deterministic suite.

    The model was allowed to propose `data.columns.cast`, then tried to read its
    contract and got OperationContractUnavailableError: the lineage resolver
    only answers for model nodes. An Agent that may propose an operation must be
    able to inspect it.
    """

    from workbench.agent.context_tools import InspectOperationContractRequest

    project, run_id, _artifact_id = _source_project(tmp_path, _frame())
    _seed_node_index(project, run_id)
    provider = NodeOperationContextProvider(project)

    result = provider.inspect_operation_contract(
        InspectOperationContractRequest(
            request_id="r1",
            owner_run_id=run_id,
            op_node_id="stage:source",
            active_head_run_id=run_id,
            operation_id="data.columns.cast",
        ),
        operation_registry=OperationRegistry(),
    )

    assert result["operation"]["operation_id"] == "data.columns.cast"
    assert result["contract"]["contract_owner"] == "operation_registry"
    casts = result["contract"]["editable_schema"]["properties"]["casts"]
    assert casts["items"]["properties"]["target_dtype"]["enum"] == [
        "numeric",
        "string",
        "datetime",
    ]


def test_model_rerun_on_a_data_node_still_fails_closed(tmp_path: Path) -> None:
    """The registry fallback must not hand back a permissive passthrough.

    model.rerun's registry schema is `additionalProperties: true`; answering
    with it when the lineage contract is missing would claim "anything goes".
    """

    from workbench.agent.context_tools import (
        InspectOperationContractRequest,
        OperationContractUnavailableError,
    )

    project, run_id, _artifact_id = _source_project(tmp_path, _frame())
    _seed_node_index(project, run_id)
    provider = NodeOperationContextProvider(project)

    with pytest.raises(OperationContractUnavailableError):
        provider.inspect_operation_contract(
            InspectOperationContractRequest(
                request_id="r1",
                owner_run_id=run_id,
                op_node_id="stage:source",
                active_head_run_id=run_id,
                operation_id="model.rerun",
            ),
            operation_registry=OperationRegistry(),
        )


def test_canonicalization_binds_the_artifact_and_the_real_preview_fingerprint(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    orchestrator = _orchestrator(project)

    # What a model can honestly know: the run, the node, the intent.
    proposed = {
        "operation_id": "data.columns.cast",
        "target": {
            "run_id": run_id,
            "node_ref": "stage:source",
            "casts": [{"column": "age", "target_dtype": "numeric"}],
        },
        "preconditions": {"active_head_run_id": run_id},
        "changes": {},
    }

    canonical = orchestrator._canonicalize_proposal_arguments(
        "data.columns.cast", proposed, session_id="s1"
    )

    expected = preview_data_columns_cast(
        project,
        DataColumnsCastSpecV1(
            source_run_id=run_id,
            source_node_id="stage:source",
            source_artifact_id=artifact_id,
            casts=(DataCastItem("age", "numeric"),),
        ),
    )
    assert canonical["target"]["artifact_id"] == artifact_id
    assert canonical["preconditions"]["context_fingerprint"] != "f" * 64
    assert canonical["preconditions"]["context_fingerprint"] == expected.fingerprint
    assert canonical["preconditions"]["context_version"] == "data-columns-cast.v1"
    assert canonical["preconditions"]["owner_resolution"] == "typed_data_node"
    assert canonical["changes"]["casts"] == [{"column": "age", "target_dtype": "numeric"}]
    assert canonical["changes"]["output_format"] == "csv"


def test_a_model_supplied_artifact_id_and_fingerprint_are_overridden(
    tmp_path: Path,
) -> None:
    """A model guessing these must not be able to steer the operation.

    The live smoke showed a model inventing a fingerprint; execution rejected
    it, which is correct but leaves the user with a dead proposal. Overriding
    means the confirmable proposal is the executable one.
    """

    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    orchestrator = _orchestrator(project)

    canonical = orchestrator._canonicalize_proposal_arguments(
        "data.columns.cast",
        {
            "operation_id": "data.columns.cast",
            "target": {
                "run_id": run_id,
                "node_ref": "stage:source",
                "artifact_id": "some_other_artifact_the_model_named",
                "casts": [{"column": "age", "target_dtype": "numeric"}],
            },
            "preconditions": {
                "active_head_run_id": run_id,
                "context_fingerprint": "f" * 64,
            },
            "changes": {},
        },
        session_id="s1",
    )

    assert canonical["target"]["artifact_id"] == artifact_id
    assert canonical["preconditions"]["context_fingerprint"] != "f" * 64


def test_a_workflow_proposal_binds_the_real_source_artifact_id(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame(
            {
                "wave": [1, 2],
                "outcome": [100.0, 110.0],
                "rate": [10.0, 20.0],
            }
        ),
    )
    orchestrator = _orchestrator(project)

    canonical = orchestrator._canonicalize_proposal_arguments(
        "operation.multi_step",
        {
            "operation_id": "operation.multi_step",
            "target": {
                "run_id": run_id,
                "node_ref": "stage:source",
                "artifact_id": "model_supplied_node_hash",
            },
            "preconditions": {"active_head_run_id": run_id},
            "changes": {
                "steps": [
                    {
                        "step_id": "describe",
                        "operation_id": "statistical.explore",
                        "spec": {
                            "operation": "summarize",
                            "selected_columns": ["outcome", "rate"],
                        },
                    }
                ]
            },
        },
        session_id="s1",
    )

    assert canonical["target"]["artifact_id"] == artifact_id


def test_the_canonical_proposal_passes_the_operation_validator(tmp_path: Path) -> None:
    """The whole point: intent in, executable typed proposal out."""

    project, run_id, _artifact_id = _source_project(tmp_path, _frame())
    orchestrator = _orchestrator(project)

    canonical = orchestrator._canonicalize_proposal_arguments(
        "data.columns.cast",
        {
            "operation_id": "data.columns.cast",
            "target": {
                "run_id": run_id,
                "node_ref": "stage:source",
                "casts": [{"column": "age", "target_dtype": "numeric"}],
            },
            "preconditions": {"active_head_run_id": run_id},
            "changes": {},
        },
        session_id="s1",
    )

    definition = OperationRegistry().require("data.columns.cast", "v1")
    definition.validate(
        target=canonical["target"],
        preconditions=canonical["preconditions"],
        changes=canonical["changes"],
    )


def test_a_bad_column_is_left_to_the_validator_not_silently_dropped(
    tmp_path: Path,
) -> None:
    project, run_id, _artifact_id = _source_project(tmp_path, _frame())
    orchestrator = _orchestrator(project)

    proposed = {
        "operation_id": "data.columns.cast",
        "target": {
            "run_id": run_id,
            "node_ref": "stage:source",
            "casts": [{"column": "does_not_exist", "target_dtype": "numeric"}],
        },
        "preconditions": {"active_head_run_id": run_id},
        "changes": {},
    }

    canonical = orchestrator._canonicalize_proposal_arguments(
        "data.columns.cast", proposed, session_id="s1"
    )

    # Preview raised, so nothing was canonicalized: the proposal keeps the
    # model's own words and fails validation with the vocabulary the Agent
    # already knows, rather than being quietly rewritten into something else.
    assert canonical["target"]["casts"] == proposed["target"]["casts"]
    assert "context_fingerprint" not in canonical["preconditions"]


def test_agent_confirm_rederives_the_cast_preview_fingerprint(tmp_path: Path) -> None:
    """Found by the live smoke: the Agent could propose it but not confirm it.

    The confirm endpoint re-derived the node-operation-context fingerprint
    (`nocv1:…`), which is the right freshness identity for model.rerun but not
    for a cast — whose identity is its preview over the real data.
    """

    from workbench.http.agent_routes import _current_data_columns_cast_fingerprint

    project, run_id, artifact_id = _source_project(tmp_path, _frame())

    class _Proposal:
        proposal_id = "p1"
        operation_id = "data.columns.cast"
        target = {
            "run_id": run_id,
            "node_ref": "stage:source",
            "artifact_id": artifact_id,
            "casts": [{"column": "age", "target_dtype": "numeric"}],
            "output_format": "csv",
        }

    fingerprint = _current_data_columns_cast_fingerprint(project, _Proposal())

    expected = preview_data_columns_cast(
        project,
        DataColumnsCastSpecV1(
            source_run_id=run_id,
            source_node_id="stage:source",
            source_artifact_id=artifact_id,
            casts=(DataCastItem("age", "numeric"),),
        ),
    )
    assert fingerprint == expected.fingerprint


def test_agent_confirm_refuses_a_cast_that_cannot_convert(tmp_path: Path) -> None:
    from workbench.api_errors import WorkbenchAPIError
    from workbench.http.agent_routes import _current_data_columns_cast_fingerprint

    project, run_id, artifact_id = _source_project(tmp_path, _frame())

    class _Proposal:
        proposal_id = "p1"
        operation_id = "data.columns.cast"
        target = {
            "run_id": run_id,
            "node_ref": "stage:source",
            "artifact_id": artifact_id,
            # "name" holds "a"/"b" — not convertible to numbers.
            "casts": [{"column": "name", "target_dtype": "numeric"}],
        }

    with pytest.raises(WorkbenchAPIError) as excinfo:
        _current_data_columns_cast_fingerprint(project, _Proposal())
    assert excinfo.value.code == "DATA_OPERATION_BLOCKED"


def test_canonicalization_is_a_no_op_without_a_project_bound_provider() -> None:
    """Pure contract tests have no provider; execution still revalidates."""

    repository_root = Path("/tmp/does-not-matter")
    orchestrator = WorkbenchOrchestrator(
        JsonlSessionRepository(repository_root),
        AgentEventStream(repository_root),
        main_session_id="agent_main",
        operation_registry=OperationRegistry(),
        context_provider=None,
    )
    arguments = {
        "operation_id": "data.columns.cast",
        "target": {"run_id": "r", "node_ref": "n", "casts": [{"column": "c", "target_dtype": "numeric"}]},
        "preconditions": {},
        "changes": {},
    }

    assert orchestrator.data_operation_project_root is None
    assert (
        orchestrator._canonicalize_proposal_arguments(
            "data.columns.cast", arguments, session_id="s1"
        )
        == arguments
    )
