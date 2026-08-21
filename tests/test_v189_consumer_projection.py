from __future__ import annotations

import json
import copy
import pickle
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from workbench.canonical import sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.foundation_status import TransactionStatusV1
from workbench.contracts.agent.context_egress import (
    ContextEgressGatewayV1,
    ContextEgressPolicyV1,
    ContextEgressReceiptIssuerV1,
    ContextMaterializationStoreV1,
    SensitivityClassV1,
)
from workbench.contracts.evidence.envelope import EvidenceEnvelopeV1, NotApplicableV1
from workbench.contracts.evidence.persistence import (
    EvidenceCommitBindingV1,
    EvidenceCommitRequestV1,
)
from workbench.evidence.consumer_adapters import (
    ConsumerProjectionRegistryV1,
    ConsumerProjectionSpecV1,
    EvidenceProjectionError,
    PersistedEvidenceEnvelopeV1,
    ProjectionStatus,
    ServerOwnedEvidenceProjectionSourceV1,
    ServerOwnedEvidenceSensitivityPolicyV1,
    default_projection_registry,
)
from workbench.services.results_service import PersistedEvidenceResultsFacadeV1
from workbench.agent.context_tools import project_persisted_evidence_for_agent
from workbench.agent.notebook.evidence import project_persisted_evidence_for_notebook
from workbench.report_view_model import build_persisted_evidence_report_view


_ROOT = Path(__file__).parents[1]
_FIXTURE = _ROOT / "tests" / "fixtures" / "contracts" / "v189" / "evidence_envelope.json"
_LIVE_SOURCE_CONTEXTS: list[object] = []
_CONSUMER_PROJECTION_EVIDENCE_DIGEST = "a80048ec382239a8e8050f1219322201591816828f1ccf8f12570f38a45c7361"


def _ref(kind: str, logical_id: str, semantic_version: str = "1.0") -> ContractRefV1:
    return ContractRefV1(
        kind=kind,
        logical_id=logical_id,
        semantic_version=semantic_version,
        contract_digest=sha256_canonical(
            {"kind": kind, "logical_id": logical_id, "semantic_version": semantic_version}
        ),
    )


def _persisted_record(*, sensitivity: str = "public") -> PersistedEvidenceEnvelopeV1:
    envelope = EvidenceEnvelopeV1.from_dict(json.loads(_FIXTURE.read_text(encoding="utf-8")))
    projector_ref = _ref("projection", "workbench.consumer_projection.results")
    request = EvidenceCommitRequestV1(
        artifact_admission_ref="artifact-1",
        projector_ref=projector_ref,
        envelope_digest=sha256_canonical(envelope.to_dict()),
        idempotency_key="evidence-commit:result-1",
        supersedes_ref=NotApplicableV1("no supersession"),
        invalidation_refs=(),
    )
    binding = EvidenceCommitBindingV1(
        commit_id="evidence-commit-1",
        request_digest=request.request_digest,
        artifact_admission_ref=request.artifact_admission_ref,
        projector_ref=projector_ref,
        envelope_digest=request.envelope_digest,
        idempotency_key=request.idempotency_key,
        transaction_status=TransactionStatusV1.COMMITTED,
        supersedes_ref=request.supersedes_ref,
        invalidation_refs=(),
        failure_receipt=NotApplicableV1("not failed"),
    )
    return PersistedEvidenceEnvelopeV1(
        commit_id=binding.commit_id,
        artifact_ref="artifact-1",
        envelope_ref="evidence-envelope:result-1",
        sensitivity=sensitivity,
        binding=binding,
        envelope=envelope,
    )


def _server_committed_source(
    tmp_path: Path,
    *,
    sensitivity: str = "public",
    payload: dict[str, object] | None = None,
) -> tuple[ServerOwnedEvidenceProjectionSourceV1, PersistedEvidenceEnvelopeV1]:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry

    payload = json.loads(_FIXTURE.read_text(encoding="utf-8")) if payload is None else payload
    registry, _host = _authorized_registry("scope:consumer:projection")
    artifact = registry.admit_artifact(
        artifact_id="artifact-1",
        artifact_type="post_estimation",
        scope_ref="scope:consumer:projection",
        content=payload,
        source_ref="source:dataset:1",
        validator_ref="validator:evidence-envelope:1",
        execution_ref="execution:run:1",
        contract_digest=_CONSUMER_PROJECTION_EVIDENCE_DIGEST,
    )
    store_context = _admit_store(tmp_path, registry)
    store = store_context.__enter__()
    _LIVE_SOURCE_CONTEXTS.append(store_context)
    receipt = registry.persistence_receipt(artifact)
    binding = store.commit(artifact, receipt=receipt)
    loaded = store.load(binding.commit_id, registry=registry, receipt=receipt)
    packet = store.load_packet(binding.commit_id, registry=registry, receipt=receipt)
    record = PersistedEvidenceEnvelopeV1(
        commit_id=loaded.commit_id,
        artifact_ref=packet.artifact_id,
        envelope_ref=f"evidence-envelope:{packet.envelope_digest}",
        sensitivity=sensitivity,
        binding=loaded,
        envelope=packet.envelope.envelope,
    )
    policy = ServerOwnedEvidenceSensitivityPolicyV1._from_host(
        scope_ref=registry.scope_ref,
        artifact_id=packet.artifact_id,
        commit_id=loaded.commit_id,
        envelope_digest=loaded.envelope_digest,
        sensitivity=sensitivity,
        authority_handle=_host.channel,
    )
    source = ServerOwnedEvidenceProjectionSourceV1(
        store,
        registry,
        receipt,
        scope_ref=registry.scope_ref,
        artifact_id=packet.artifact_id,
        commit_id=loaded.commit_id,
        sensitivity_policy=policy,
        envelope_digest=loaded.envelope_digest,
        authority_handle=_host.channel,
    )
    return source, record


def _empty_facts_payload() -> dict[str, object]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["numeric_facts"] = []
    payload["figures"] = []
    payload["validation_summary"] = {
        "levels_present": [],
        "minimum_required": payload["validation_summary"]["minimum_required"],  # type: ignore[index]
        "requirement_status": "not_met",
    }
    return payload


class _FakeLoadPort:
    def load(self, _commit_id: str) -> object:
        return {"facts": {"fact-mean": 99}}


def test_retired_results_facade_rejects_fake_load_ports() -> None:
    with pytest.raises(EvidenceProjectionError, match="EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED"):
        PersistedEvidenceResultsFacadeV1(_FakeLoadPort(), _FakeLoadPort())


def test_agent_notebook_and_shared_registry_reject_direct_forged_persisted_envelope() -> None:
    forged = _persisted_record()
    registry = default_projection_registry()

    with pytest.raises(EvidenceProjectionError, match="EVIDENCE_SERVER_SOURCE_REQUIRED"):
        registry.project(forged, consumer_id="agent", destination="local")
    with pytest.raises(EvidenceProjectionError, match="EVIDENCE_SERVER_SOURCE_REQUIRED"):
        registry.project(forged, consumer_id="report", destination="local")
    with pytest.raises(EvidenceProjectionError, match="EVIDENCE_SERVER_SOURCE_REQUIRED"):
        project_persisted_evidence_for_agent(forged)
    with pytest.raises(EvidenceProjectionError, match="EVIDENCE_SERVER_SOURCE_REQUIRED"):
        project_persisted_evidence_for_notebook(forged)


def test_actual_packet_store_registry_receipt_path_can_project_positive(tmp_path: Path) -> None:
    source, record = _server_committed_source(tmp_path)

    projection = default_projection_registry().project(
        source,
        consumer_id="agent",
        destination="local",
    )

    assert projection.artifact_ref == "artifact-1"
    assert projection.commit_id.startswith("commit:evidence:")
    assert projection.envelope_digest == record.binding.envelope_digest
    assert projection.fact_ids == tuple(fact.fact_id for fact in record.envelope.numeric_facts)


def test_shared_registry_exposes_no_raw_persisted_record_projection_path() -> None:
    registry = default_projection_registry()

    assert not hasattr(registry, "_project_record")


def test_server_source_does_not_expose_private_raw_record_reader(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path)

    assert not hasattr(source, "_load_record")


def test_server_source_requires_non_empty_sha256_digest(tmp_path: Path) -> None:
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry

    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    registry, host = _authorized_registry("scope:consumer:digest-required")
    artifact = registry.admit_artifact(
        artifact_id="artifact-1",
        artifact_type="post_estimation",
        scope_ref="scope:consumer:digest-required",
        content=payload,
        source_ref="source:dataset:1",
        validator_ref="validator:evidence-envelope:1",
        execution_ref="execution:run:1",
        contract_digest="c" * 64,
    )
    store_context = _admit_store(tmp_path, registry)
    store = store_context.__enter__()
    _LIVE_SOURCE_CONTEXTS.append(store_context)
    receipt = registry.persistence_receipt(artifact)
    binding = store.commit(artifact, receipt=receipt)
    policy = ServerOwnedEvidenceSensitivityPolicyV1._from_host(
        scope_ref=registry.scope_ref,
        artifact_id=artifact.artifact_id,
        commit_id=binding.commit_id,
        envelope_digest=binding.envelope_digest,
        sensitivity="public",
        authority_handle=host.channel,
    )

    with pytest.raises(TypeError):
        ServerOwnedEvidenceProjectionSourceV1(  # type: ignore[call-arg]
            store,
            registry,
            receipt,
            scope_ref=registry.scope_ref,
            artifact_id=artifact.artifact_id,
            commit_id=binding.commit_id,
            sensitivity_policy=policy,
            authority_handle=host.channel,
        )
    with pytest.raises(EvidenceProjectionError, match="PROJECTION_IDENTITY_INVALID"):
        ServerOwnedEvidenceProjectionSourceV1(
            store,
            registry,
            receipt,
            scope_ref=registry.scope_ref,
            artifact_id=artifact.artifact_id,
            commit_id=binding.commit_id,
            sensitivity_policy=policy,
            envelope_digest="",
            authority_handle=host.channel,
        )


def test_object_new_slots_clone_of_server_source_cannot_project(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path)
    cloned = object.__new__(type(source))
    for slot in type(source).__slots__:  # type: ignore[attr-defined]
        if slot == "__weakref__":
            continue
        if hasattr(source, slot):
            object.__setattr__(cloned, slot, getattr(source, slot))

    with pytest.raises(EvidenceProjectionError, match="EVIDENCE_SERVER_SOURCE_REQUIRED"):
        default_projection_registry().project(
            cloned,
            consumer_id="agent",
            destination="local",
        )


def test_remote_projection_audit_retains_validated_egress_receipt_identity(tmp_path: Path) -> None:
    source, record = _server_committed_source(tmp_path)
    policy_ref = _ref(kind="egress-policy", logical_id="provider.remote.consumer")
    policy = ContextEgressPolicyV1(
        policy_ref=policy_ref,
        destination="remote",
        provider_ref="provider:remote:1",
        allowed_sensitivity=(SensitivityClassV1.PUBLIC,),
        max_token_budget=1000,
        max_row_budget=100,
        max_time_budget_ms=5000,
    )
    materializer = ContextMaterializationStoreV1(
        materializer_ref=_ref(kind="materializer", logical_id="server.consumer.context"),
        redaction_policy_ref=_ref(kind="redaction-policy", logical_id="default"),
    )
    selected_refs = tuple(f"evidence:{fact.fact_id}" for fact in record.envelope.numeric_facts)
    result = materializer.materialize(
        {
            ref: {"mean": fact.value}
            for ref, fact in zip(selected_refs, record.envelope.numeric_facts, strict=True)
        },
        selected_refs=selected_refs,
    )
    gateway = ContextEgressGatewayV1.from_materialization_result(
        result,
        request_id="egress-request:consumer-projection",
        destination="remote",
        provider_ref="provider:remote:1",
        sensitivity_policy_ref=policy_ref,
        sensitivity=SensitivityClassV1.PUBLIC,
        token_budget=500,
        row_budget=10,
        time_budget_ms=1000,
        purpose_ref="purpose:consumer-projection",
        requested_at="2026-08-15T17:02:00+00:00",
        expires_at="2026-08-15T18:00:00+00:00",
    )
    issuer = ContextEgressReceiptIssuerV1(
        policy,
        materializer_store=materializer,
        clock=lambda: __import__("datetime").datetime.fromisoformat("2026-08-15T17:30:00+00:00"),
    )
    receipt = issuer.issue(gateway)

    projection = default_projection_registry().project(
        source,
        consumer_id="agent",
        destination="remote",
        gateway=gateway,
        receipt=receipt,
        issuer=issuer,
    )

    assert projection.status is ProjectionStatus.AVAILABLE
    assert projection.audit.egress_receipt_id == receipt.receipt_id
    assert projection.audit.egress_receipt_digest == receipt.receipt_digest
    assert projection.to_dict()["audit"]["egress_receipt_digest"] == receipt.receipt_digest


def test_server_source_rejects_caller_sensitivity_downgrade_before_projection(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path, sensitivity="restricted")
    blocked = default_projection_registry().project(
        source,
        consumer_id="agent",
        destination="local",
    )
    assert blocked.status is ProjectionStatus.BLOCKED
    assert blocked.facts == ()

    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry

    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    registry, host = _authorized_registry("scope:consumer:downgrade")
    artifact = registry.admit_artifact(
        artifact_id="artifact-1",
        artifact_type="post_estimation",
        scope_ref="scope:consumer:downgrade",
        content=payload,
        source_ref="source:dataset:1",
        validator_ref="validator:evidence-envelope:1",
        execution_ref="execution:run:1",
        contract_digest="c" * 64,
    )
    downgrade_root = tmp_path / "downgrade"
    downgrade_root.mkdir()
    store_context = _admit_store(downgrade_root, registry)
    store = store_context.__enter__()
    _LIVE_SOURCE_CONTEXTS.append(store_context)
    receipt = registry.persistence_receipt(artifact)
    binding = store.commit(artifact, receipt=receipt)

    with pytest.raises(TypeError, match="sensitivity"):
        ServerOwnedEvidenceProjectionSourceV1(
            store,
            registry,
            receipt,
            scope_ref=registry.scope_ref,
            artifact_id=artifact.artifact_id,
            commit_id=binding.commit_id,
            sensitivity="public",
            envelope_digest=binding.envelope_digest,
            authority_handle=host.channel,
        )
    with pytest.raises(EvidenceProjectionError, match="EVIDENCE_SENSITIVITY_POLICY_REQUIRED"):
        ServerOwnedEvidenceProjectionSourceV1(
            store,
            registry,
            receipt,
            scope_ref=registry.scope_ref,
            artifact_id=artifact.artifact_id,
            commit_id=binding.commit_id,
            envelope_digest=binding.envelope_digest,
            authority_handle=host.channel,
        )


def test_server_source_rejects_copy_pickle_and_stale_store(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path)

    with pytest.raises(TypeError, match="cannot be copied"):
        copy.copy(source)
    with pytest.raises(TypeError, match="cannot be copied"):
        copy.deepcopy(source)
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(source)

    context = _LIVE_SOURCE_CONTEXTS.pop()
    context.__exit__(None, None, None)  # type: ignore[attr-defined]
    with pytest.raises(EvidenceProjectionError, match="EVIDENCE_SERVER_SOURCE_REQUIRED"):
        default_projection_registry().project(source, consumer_id="agent", destination="local")


def test_cross_consumer_projection_preserves_identity_values_and_status_axes(tmp_path: Path) -> None:
    source, record = _server_committed_source(tmp_path)
    registry = default_projection_registry()
    projections = [
        registry.project(source, consumer_id=consumer_id, destination="local")
        for consumer_id in ("results", "agent", "notebook", "report", "ui")
    ]

    assert {projection.artifact_ref for projection in projections} == {"artifact-1"}
    assert {projection.envelope_digest for projection in projections} == {
        record.binding.envelope_digest
    }
    assert {projection.fact_ids for projection in projections} == {
        tuple(fact.fact_id for fact in record.envelope.numeric_facts)
    }
    assert [fact.value for fact in projections[0].facts] == [
        fact.value for fact in record.envelope.numeric_facts
    ]
    assert all(
        projection.execution_status == record.envelope.execution_status.value
        and projection.availability == record.envelope.availability.value
        and projection.completeness_status == record.envelope.completeness_status.value
        and projection.to_dict().get("data_snapshot_ref") == "dataset-1"
        and projection.to_dict().get("data_snapshot_digest") == "a" * 64
        for projection in projections
    )


def test_restricted_remote_projection_is_blocked_without_raw_facts(tmp_path: Path) -> None:
    source, record = _server_committed_source(tmp_path, sensitivity="restricted")
    projection = default_projection_registry().project(
        source,
        consumer_id="agent",
        destination="remote",
        raw_rows=[{"value": 2.0}],
    )

    assert projection.status is ProjectionStatus.BLOCKED
    assert projection.facts == ()
    assert projection.audit.redacted_fact_ids == tuple(
        fact.fact_id for fact in record.envelope.numeric_facts
    )
    assert projection.audit.raw_rows_rejected is True
    assert "value" not in json.dumps(projection.to_dict(), sort_keys=True)


def test_empty_restricted_envelope_cannot_return_available(tmp_path: Path) -> None:
    source, _record = _server_committed_source(
        tmp_path,
        sensitivity="restricted",
        payload=_empty_facts_payload(),
    )

    projection = default_projection_registry().project(
        source,
        consumer_id="agent",
        destination="local",
    )

    assert projection.status is ProjectionStatus.BLOCKED
    assert projection.facts == ()
    assert projection.audit.restriction_reason == "sensitivity_not_allowed"


def test_empty_remote_egress_blocked_envelope_cannot_return_available(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path, payload=_empty_facts_payload())

    projection = default_projection_registry().project(
        source,
        consumer_id="agent",
        destination="remote",
    )

    assert projection.status is ProjectionStatus.BLOCKED
    assert projection.facts == ()
    assert projection.audit.restriction_reason == "egress_receipt_required"


def test_raw_rows_are_rejected_fail_closed_even_for_local_projection(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path)

    projection = default_projection_registry().project(
        source,
        consumer_id="agent",
        destination="local",
        raw_rows=[{"value": 999.0}],
    )

    assert projection.status is ProjectionStatus.BLOCKED
    assert projection.facts == ()
    assert projection.audit.raw_rows_rejected is True
    assert projection.audit.restriction_reason == "raw_rows_rejected"
    assert "999.0" not in json.dumps(projection.to_dict(), sort_keys=True)


def test_cross_artifact_identity_is_rejected_before_projection() -> None:
    record = _persisted_record()

    with pytest.raises(EvidenceProjectionError, match="PROJECTION_ARTIFACT_IDENTITY_MISMATCH"):
        replace(record, artifact_ref="artifact-foreign")


@pytest.mark.parametrize("consumer_id", ("agent", "notebook", "report", "results", "ui"))
def test_structural_cross_commit_artifact_binding_cannot_cross_production_boundary(
    consumer_id: str,
) -> None:
    record = _persisted_record()
    request = EvidenceCommitRequestV1(
        artifact_admission_ref="artifact-foreign",
        projector_ref=record.binding.projector_ref,
        envelope_digest=record.binding.envelope_digest,
        idempotency_key=record.binding.idempotency_key,
        supersedes_ref=record.binding.supersedes_ref,
        invalidation_refs=record.binding.invalidation_refs,
    )
    foreign_binding = EvidenceCommitBindingV1(
        commit_id=record.binding.commit_id,
        request_digest=request.request_digest,
        artifact_admission_ref=request.artifact_admission_ref,
        projector_ref=request.projector_ref,
        envelope_digest=request.envelope_digest,
        idempotency_key=request.idempotency_key,
        transaction_status=TransactionStatusV1.COMMITTED,
        supersedes_ref=request.supersedes_ref,
        invalidation_refs=(),
        failure_receipt=NotApplicableV1("not failed"),
    )

    forged = replace(record, binding=foreign_binding)
    with pytest.raises(EvidenceProjectionError, match="EVIDENCE_SERVER_SOURCE_REQUIRED"):
        default_projection_registry().project(
            forged,
            consumer_id=consumer_id,
            destination="local",
        )


def test_notebook_remote_projection_requires_the_existing_egress_seam(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path)

    try:
        projection = project_persisted_evidence_for_notebook(
            source,
            destination="remote",
        )
    except TypeError as exc:
        raise AssertionError(
            "Notebook remote projection must expose the existing egress seam"
        ) from exc

    assert projection["status"] == ProjectionStatus.BLOCKED.value
    assert projection["facts"] == []
    assert projection["audit"]["restriction_reason"] == "egress_receipt_required"


def test_agent_and_notebook_reject_custom_projection_registry_injection(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path, sensitivity="restricted")
    permissive_registry = ConsumerProjectionRegistryV1(
        (
            ConsumerProjectionSpecV1(
                consumer_id="agent",
                semantic_version="1.0",
                projection_ref=_ref("projection", "workbench.consumer_projection.agent"),
                policy_ref=_ref("policy", "workbench.consumer_projection.agent.permissive"),
                renderer_key="typed-evidence",
                max_token_budget=999999,
                max_row_budget=999999,
                allowed_sensitivity=("public", "internal", "restricted"),
                ordering=("fact_id",),
            ),
            ConsumerProjectionSpecV1(
                consumer_id="notebook",
                semantic_version="1.0",
                projection_ref=_ref("projection", "workbench.consumer_projection.notebook"),
                policy_ref=_ref("policy", "workbench.consumer_projection.notebook.permissive"),
                renderer_key="typed-evidence",
                max_token_budget=999999,
                max_row_budget=999999,
                allowed_sensitivity=("public", "internal", "restricted"),
                ordering=("fact_id",),
            ),
        )
    )

    with pytest.raises(EvidenceProjectionError, match="PROJECTION_REGISTRY_INJECTION_REJECTED"):
        project_persisted_evidence_for_agent(source, registry=permissive_registry)
    with pytest.raises(EvidenceProjectionError, match="PROJECTION_REGISTRY_INJECTION_REJECTED"):
        project_persisted_evidence_for_notebook(source, registry=permissive_registry)


def test_unknown_fact_identity_is_blocked_without_partial_success(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path)
    projection = default_projection_registry().project(
        source,
        consumer_id="agent",
        destination="local",
        requested_fact_ids=("fact-unknown",),
    )

    assert projection.status is ProjectionStatus.BLOCKED
    assert projection.facts == ()
    assert projection.audit.restriction_reason == "unknown_fact_identity"


def test_cross_data_snapshot_identity_is_rejected() -> None:
    record = _persisted_record()
    envelope_wire = record.envelope.to_dict()
    envelope_wire["input_provenance"] = {
        "artifact_ref": "dataset-foreign",
        "artifact_digest": "c" * 64,
    }
    forged_envelope = EvidenceEnvelopeV1.from_dict(envelope_wire)
    request = EvidenceCommitRequestV1(
        artifact_admission_ref=record.artifact_ref,
        projector_ref=record.binding.projector_ref,
        envelope_digest=sha256_canonical(forged_envelope.to_dict()),
        idempotency_key="evidence-commit:foreign-snapshot",
        supersedes_ref=NotApplicableV1("no supersession"),
        invalidation_refs=(),
    )
    forged_binding = EvidenceCommitBindingV1(
        commit_id=record.commit_id,
        request_digest=request.request_digest,
        artifact_admission_ref=request.artifact_admission_ref,
        projector_ref=request.projector_ref,
        envelope_digest=request.envelope_digest,
        idempotency_key=request.idempotency_key,
        transaction_status=TransactionStatusV1.COMMITTED,
        supersedes_ref=request.supersedes_ref,
        invalidation_refs=(),
        failure_receipt=NotApplicableV1("not failed"),
    )

    with pytest.raises(EvidenceProjectionError, match="PROJECTION_DATA_SNAPSHOT_MISMATCH"):
        PersistedEvidenceEnvelopeV1(
            commit_id=record.commit_id,
            artifact_ref=record.artifact_ref,
            envelope_ref=record.envelope_ref,
            sensitivity=record.sensitivity,
            binding=forged_binding,
            envelope=forged_envelope,
        )


def test_projection_budget_is_degraded_and_audits_omitted_ids(tmp_path: Path) -> None:
    source, record = _server_committed_source(tmp_path)
    registry = ConsumerProjectionRegistryV1(
        (
            ConsumerProjectionSpecV1(
                consumer_id="tiny",
                semantic_version="1.0",
                projection_ref=_ref("projection", "workbench.consumer_projection.tiny"),
                policy_ref=_ref("policy", "workbench.consumer_projection.tiny"),
                renderer_key="typed-evidence",
                max_token_budget=1,
                max_row_budget=1,
                allowed_sensitivity=("public",),
                ordering=("fact_id",),
            ),
        )
    )

    projection = registry.project(source, consumer_id="tiny", destination="local")

    assert projection.status is ProjectionStatus.DEGRADED
    assert projection.facts == ()
    assert projection.audit.omitted_fact_ids == tuple(
        fact.fact_id for fact in record.envelope.numeric_facts
    )


def test_projection_rejects_an_unaccepted_evidence_contract(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path)
    registry = ConsumerProjectionRegistryV1(
        (
            ConsumerProjectionSpecV1(
                consumer_id="wrong-evidence",
                semantic_version="1.0",
                projection_ref=_ref("projection", "workbench.consumer_projection.wrong-evidence"),
                policy_ref=_ref("policy", "workbench.consumer_projection.wrong-evidence"),
                renderer_key="typed-evidence",
                max_token_budget=100,
                max_row_budget=10,
                allowed_sensitivity=("public",),
                ordering=("fact_id",),
                accepted_evidence_refs=(_ref("evidence", "not-the-admitted-contract"),),
                fact_kinds=("numeric_fact",),
            ),
        )
    )

    projection = registry.project(source, consumer_id="wrong-evidence", destination="local")

    assert projection.status is ProjectionStatus.BLOCKED
    assert projection.facts == ()
    assert projection.audit.restriction_reason == "evidence_contract_not_allowed"


def test_projection_rejects_an_undeclared_fact_kind(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path)
    registry = ConsumerProjectionRegistryV1(
        (
            ConsumerProjectionSpecV1(
                consumer_id="wrong-kind",
                semantic_version="1.0",
                projection_ref=_ref("projection", "workbench.consumer_projection.wrong-kind"),
                policy_ref=_ref("policy", "workbench.consumer_projection.wrong-kind"),
                renderer_key="typed-evidence",
                max_token_budget=100,
                max_row_budget=10,
                allowed_sensitivity=("public",),
                ordering=("fact_id",),
                fact_kinds=("future_fact_kind",),
            ),
        )
    )

    projection = registry.project(source, consumer_id="wrong-kind", destination="local")

    assert projection.status is ProjectionStatus.BLOCKED
    assert projection.facts == ()
    assert projection.audit.restriction_reason == "fact_kind_not_allowed"


def test_missing_consumer_is_fail_closed(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path)
    with pytest.raises(EvidenceProjectionError, match="unknown consumer"):
        default_projection_registry().project(
            source, consumer_id="not-registered", destination="local"
        )


def test_agent_notebook_and_report_contributions_share_the_same_fact_values(tmp_path: Path) -> None:
    source, _record = _server_committed_source(tmp_path)
    agent = project_persisted_evidence_for_agent(source)
    notebook = project_persisted_evidence_for_notebook(source)
    report = build_persisted_evidence_report_view(
        default_projection_registry().project(source, consumer_id="report", destination="local")
    )

    assert [row["value"] for row in agent["facts"]] == [row["value"] for row in notebook["facts"]]
    assert report["status"] == "unavailable"
    assert report["facts"] == []
    assert agent["artifact_ref"] == notebook["artifact_ref"] == report["artifactRef"] == "artifact-1"
    assert agent["envelope_digest"] == notebook["envelope_digest"]


def test_agent_notebook_report_projection_replay_is_stable_under_concurrency(tmp_path: Path) -> None:
    source, record = _server_committed_source(tmp_path)
    registry = default_projection_registry()

    def project_all() -> tuple[dict[str, object], ...]:
        return tuple(
            registry.project(source, consumer_id=consumer_id, destination="local").to_dict()
            for consumer_id in ("agent", "notebook", "report")
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        replays = list(pool.map(lambda _index: project_all(), range(8)))

    assert all(replay == replays[0] for replay in replays)
    assert {
        replay[0]["artifact_ref"]
        for replay in replays
    } == {"artifact-1"}
    assert {
        replay[2]["envelope_digest"]
        for replay in replays
    } == {record.binding.envelope_digest}
