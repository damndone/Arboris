from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from workbench.canonical import sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.foundation_status import TransactionStatusV1
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
    default_projection_registry,
)
from workbench.services.results_service import PersistedEvidenceResultsFacadeV1
from workbench.agent.context_tools import project_persisted_evidence_for_agent
from workbench.agent.notebook.evidence import project_persisted_evidence_for_notebook
from workbench.report_view_model import build_persisted_evidence_report_view


_ROOT = Path(__file__).parents[1]
_FIXTURE = _ROOT / "tests" / "fixtures" / "contracts" / "v189" / "evidence_envelope.json"


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
        artifact_admission_ref="artifact:admitted:result-1",
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


class _FakeLoadPort:
    def load(self, _commit_id: str) -> object:
        return {"facts": {"fact-mean": 99}}


def test_retired_results_facade_rejects_fake_load_ports() -> None:
    with pytest.raises(EvidenceProjectionError, match="EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED"):
        PersistedEvidenceResultsFacadeV1(_FakeLoadPort(), _FakeLoadPort())


def test_cross_consumer_projection_preserves_identity_values_and_status_axes() -> None:
    record = _persisted_record()
    registry = default_projection_registry()
    projections = [
        registry.project(record, consumer_id=consumer_id, destination="local")
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
        for projection in projections
    )


def test_restricted_remote_projection_is_blocked_without_raw_facts() -> None:
    record = _persisted_record(sensitivity="restricted")
    projection = default_projection_registry().project(
        record,
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


def test_projection_budget_is_degraded_and_audits_omitted_ids() -> None:
    record = _persisted_record()
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

    projection = registry.project(record, consumer_id="tiny", destination="local")

    assert projection.status is ProjectionStatus.DEGRADED
    assert projection.facts == ()
    assert projection.audit.omitted_fact_ids == tuple(
        fact.fact_id for fact in record.envelope.numeric_facts
    )


def test_missing_consumer_is_fail_closed() -> None:
    with pytest.raises(EvidenceProjectionError, match="unknown consumer"):
        default_projection_registry().project(
            _persisted_record(), consumer_id="not-registered", destination="local"
        )


def test_agent_notebook_and_report_contributions_share_the_same_fact_values() -> None:
    record = _persisted_record()
    agent = project_persisted_evidence_for_agent(record)
    notebook = project_persisted_evidence_for_notebook(record)
    report = build_persisted_evidence_report_view(
        default_projection_registry().project(record, consumer_id="report", destination="local")
    )

    assert [row["value"] for row in agent["facts"]] == [row["value"] for row in notebook["facts"]]
    assert report["status"] == "unavailable"
    assert report["facts"] == []
    assert agent["artifact_ref"] == notebook["artifact_ref"] == report["artifactRef"] == "artifact-1"
    assert agent["envelope_digest"] == notebook["envelope_digest"]


def test_agent_notebook_report_projection_replay_is_stable_under_concurrency() -> None:
    record = _persisted_record()
    registry = default_projection_registry()

    def project_all() -> tuple[dict[str, object], ...]:
        return tuple(
            registry.project(record, consumer_id=consumer_id, destination="local").to_dict()
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
