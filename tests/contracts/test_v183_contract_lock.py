from __future__ import annotations

from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
from workbench.capability_factory.trace_contracts import TRACE_CONTRACT_VERSION
from workbench.contracts.agent.notebook_option import (
    NOTEBOOK_OPTION_CONTRACT_VERSION,
    NOTEBOOK_OPTION_V12_CONTRACT_VERSION,
    NotebookOptionRevisionV11,
    NotebookOptionRevisionV12,
)


def test_v183_contract_versions_and_successor_keys_are_frozen() -> None:
    assert NOTEBOOK_OPTION_CONTRACT_VERSION == "1.1"
    assert NOTEBOOK_OPTION_V12_CONTRACT_VERSION == "1.2"
    assert NotebookOptionRevisionV12._V12_KEYS == (
        NotebookOptionRevisionV11._V11_KEYS
        | {"capability_resolution_binding_ref", "execution_modes"}
    )
    assert "receipt_digest" not in NotebookOptionRevisionV12._V12_KEYS


def test_v183_workflow_and_trace_contracts_are_registered_once() -> None:
    custom = WORKFLOW_STEP_SPEC_CONTRACTS["model.custom"]
    assert custom.dispatcher_key == "capability_factory.custom_dispatcher"
    assert custom.output_schema_ref == "capability_factory.artifact_contract/v1.1"
    assert TRACE_CONTRACT_VERSION == "workbench.capability_factory.trace/v1"
