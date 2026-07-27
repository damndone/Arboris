from __future__ import annotations

from dataclasses import replace

import pytest

from workbench.capability_factory.execution_receipt import (
    ArtifactContractValidationV11,
    ExecutionReceiptError,
    derive_stable_side_effect_ref,
    validate_artifact_contract_v11,
)
from workbench.contracts.agent.notebook_option import ArtifactContract, ExpectedArtifact


def _artifact(*, option: str = "1" * 64, run: str = "2" * 64, lineage: str = "3" * 64, projection: str = "4" * 64):
    return {
        "artifact_id": "custom.parameters",
        "artifact_type": "custom_json",
        "step": "fit",
        "lineage_ref": lineage,
        "consumer_projection_ref": projection,
        "run_attempt_ref": run,
        "option_revision_ref": option,
        "artifact_ref": "5" * 64,
        "facet": "parameters",
    }


def _contract() -> ArtifactContract:
    return ArtifactContract(
        expected=(ExpectedArtifact("custom.parameters", "custom_json", required=True, count=1, step="fit"),)
    )


def test_v11_aggregate_requires_all_execution_bindings() -> None:
    result = validate_artifact_contract_v11(
        _contract(),
        [_artifact()],
        option_revision_ref="1" * 64,
        run_attempt_ref="2" * 64,
        consumer_projection_ref="4" * 64,
        lineage_ref="3" * 64,
        allowed_facets=("parameters",),
    )

    assert result.validation_status == "passed"
    assert result.checked_dimensions[-4:] == (
        "lineage",
        "consumer_projection",
        "run_attempt",
        "option_revision",
    )
    assert ArtifactContractValidationV11.from_dict(result.to_dict()) == result


def test_v11_aggregate_rejects_stale_attempt_and_undeclared_facet() -> None:
    result = validate_artifact_contract_v11(
        _contract(),
        [_artifact(run="9" * 64)],
        option_revision_ref="1" * 64,
        run_attempt_ref="2" * 64,
        consumer_projection_ref="4" * 64,
        lineage_ref="3" * 64,
        allowed_facets=("diagnostic",),
    )

    assert result.validation_status == "failed"
    assert {issue["code"] for issue in result.issues} >= {
        "ARTIFACT_BINDING_MISMATCH",
        "ARTIFACT_FACET_UNDECLARED",
    }


def test_v11_validation_can_publish_its_bounded_completion_event() -> None:
    events = []
    result = validate_artifact_contract_v11(
        _contract(),
        [_artifact()],
        option_revision_ref="1" * 64,
        run_attempt_ref="2" * 64,
        consumer_projection_ref="4" * 64,
        lineage_ref="3" * 64,
        allowed_facets=("parameters",),
        trace_sink=events.append,
    )

    assert events[0].event_type == "artifact_contract.v11.validation.completed"
    assert events[0].payload["aggregate_ref"] == result.aggregate_ref


def test_stable_side_effect_ref_does_not_depend_on_author_path_or_order() -> None:
    first = derive_stable_side_effect_ref(
        namespace="artifact.namespace",
        derivation_revision=1,
        producer_revision=2,
        slot_mapping_revision=3,
        stable_key="parameters",
    )
    second = derive_stable_side_effect_ref(
        namespace="artifact.namespace",
        derivation_revision=1,
        producer_revision=2,
        slot_mapping_revision=3,
        stable_key="parameters",
    )
    assert first == second
    with pytest.raises(ExecutionReceiptError):
        derive_stable_side_effect_ref(
            namespace="/tmp/author-output",
            derivation_revision=1,
            producer_revision=2,
            slot_mapping_revision=3,
            stable_key="parameters",
        )
