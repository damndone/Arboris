from __future__ import annotations

import json
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.canonical import sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.foundation_status import TransactionStatusV1
from workbench.contracts.evidence.envelope import EvidenceEnvelopeV1, NotApplicableV1
from workbench.contracts.evidence.persistence import (
    EvidenceCommitBindingV1,
    EvidenceCommitRequestV1,
)
from workbench.evidence.consumer_adapters import (
    PersistedEvidenceEnvelopeV1,
    default_projection_registry,
)
from workbench.api import app
from workbench.http import runs_routes
from workbench.report_view_model import (
    build_indexed_report_evidence,
    build_persisted_evidence_report_view,
)


_ROOT = Path(__file__).parents[1]
_FIXTURE = _ROOT / "tests" / "fixtures" / "contracts" / "v189" / "evidence_envelope.json"


def _ref(kind: str, logical_id: str) -> ContractRefV1:
    return ContractRefV1(
        kind=kind,
        logical_id=logical_id,
        semantic_version="1.0",
        contract_digest=sha256_canonical(
            {"kind": kind, "logical_id": logical_id, "semantic_version": "1.0"}
        ),
    )


def _persisted_record() -> PersistedEvidenceEnvelopeV1:
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
        sensitivity="public",
        binding=binding,
        envelope=envelope,
    )


def _indexed_artifact(**updates: object) -> dict[str, object]:
    return {
        "artifact_id": "workflow_model_quadratic_stationary_point_1",
        "artifact_type": "post_estimation",
        "path": "artifacts/post_estimation/result.json",
        "sha256": "a" * 64,
        "step": "locate_stationary_point",
        **updates,
    }


def test_indexed_post_estimation_without_committed_binding_is_unavailable_and_not_scalarized() -> None:
    view = build_indexed_report_evidence(
        _indexed_artifact(),
        {
            "source": {"run_id": "run-1", "model_run_id": "run-1"},
            "result": {
                "stationary_point": 211.59338521178753,
                "nested": {"secret_scalar": 99},
            },
        },
    )

    assert view["status"] == "unavailable"
    assert view["reasonCode"] == "EVIDENCE_COMMIT_BINDING_REQUIRED"
    assert view["facts"] == []
    assert "211.59338521178753" not in json.dumps(view, sort_keys=True)
    assert "secret_scalar" not in json.dumps(view, sort_keys=True)


def test_tampered_committed_envelope_is_blocked_without_facts() -> None:
    record = _persisted_record()
    tampered_envelope = record.envelope.to_dict()
    tampered_envelope["numeric_facts"][0]["value"] = 999.0  # type: ignore[index]

    view = build_indexed_report_evidence(
        _indexed_artifact(
            evidence_commit_binding=record.binding.to_dict(),
            evidence_envelope=tampered_envelope,
            evidence_envelope_ref=record.envelope_ref,
            evidence_sensitivity=record.sensitivity,
        ),
    )

    assert view["status"] == "blocked"
    assert view["reasonCode"] == "PROJECTION_DIGEST_MISMATCH"
    assert view["facts"] == []


def test_committed_projection_exposes_digest_provenance_and_bounded_facts() -> None:
    record = _persisted_record()
    projection = default_projection_registry().project(
        record,
        consumer_id="report",
        destination="local",
    )

    view = build_persisted_evidence_report_view(projection)

    assert view["status"] == "available"
    assert view["commitId"] == record.commit_id
    assert view["envelopeDigest"] == record.binding.envelope_digest
    assert view["provenance"] == {
        "artifactRef": record.artifact_ref,
        "commitId": record.commit_id,
        "envelopeRef": record.envelope_ref,
        "lineageRefs": list(record.envelope.lineage_refs),
        "projectionRef": projection.projection_ref.to_dict(),
        "resultIdentity": dict(record.envelope.result_identity),
    }
    assert [fact["value"] for fact in view["facts"]] == [2.0, 0.2]


def test_indexed_canonical_commit_is_the_only_path_that_admits_report_facts() -> None:
    record = _persisted_record()
    view = build_indexed_report_evidence(
        _indexed_artifact(
            evidence_commit_binding=record.binding.to_dict(),
            evidence_envelope=record.envelope.to_dict(),
            evidence_envelope_ref=record.envelope_ref,
            evidence_artifact_ref=record.artifact_ref,
            evidence_sensitivity=record.sensitivity,
        ),
    )

    assert view["status"] == "available"
    assert view["envelopeDigest"] == record.binding.envelope_digest
    assert [fact["value"] for fact in view["facts"]] == [2.0, 0.2]


def test_run_detail_exposes_typed_unavailable_projection_for_indexed_result(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-1"
    artifact_path = run_root / "artifacts" / "post_estimation.json"
    artifact_path.parent.mkdir(parents=True)
    payload = {
        "source": {"run_id": "run-1", "model_run_id": "run-1"},
        "result": {"stationary_point": 211.5, "nested": {"secret_scalar": 99}},
    }
    raw_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    artifact_path.write_bytes(raw_payload)
    record = _indexed_artifact(
        path="artifacts/post_estimation.json",
        sha256=hashlib.sha256(raw_payload).hexdigest(),
    )
    run_root.mkdir(exist_ok=True)
    (run_root / "run_manifest.json").write_text(
        json.dumps({"run_id": "run-1", "status": "completed", "mode": "auto", "lineage": []}),
        encoding="utf-8",
    )
    (run_root / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": [record]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runs_routes,
        "collect_post_estimation_results",
        lambda *_: [
            {
                "artifact_id": record["artifact_id"],
                "artifact_type": record["artifact_type"],
                "operation_id": "model.quadratic_stationary_point",
                "run_id": "run-1",
                "model_run_id": "run-1",
                "workflow_id": "wf-1",
                "workflow_step_id": "step-1",
                "result": payload["result"],
            }
        ],
    )

    response = TestClient(app).get("/runs/run-1", params={"project_root": str(project_root)})

    assert response.status_code == 200, response.text
    report_evidence = response.json()["report_evidence"]
    assert report_evidence["status"] == "unavailable"
    assert report_evidence["reasonCode"] == "EVIDENCE_COMMIT_BINDING_REQUIRED"
    assert report_evidence["facts"] == []
    assert "211.5" not in json.dumps(report_evidence, sort_keys=True)
    assert "secret_scalar" not in json.dumps(report_evidence, sort_keys=True)
