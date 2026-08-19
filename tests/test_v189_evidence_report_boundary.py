from __future__ import annotations

import json
import hashlib
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator

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
from workbench.evidence.contracts import ArtifactAdmissionV1
from workbench.api import app
from workbench.http import runs_routes
from workbench.report_view_model import (
    build_indexed_report_evidence,
    build_persisted_evidence_report_view,
    build_report_evidence_bundle,
)
from workbench.services.results_service import ServerOwnedReportEvidencePersistenceV1


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


def _canonical_indexed_artifact(
    record: ArtifactAdmissionV1,
    binding: EvidenceCommitBindingV1,
    *,
    artifact_id: str | None = None,
    run_id: str = "run-1",
    model_run_id: str = "run-1",
    raw_payload: bytes | None = None,
) -> tuple[dict[str, object], dict[str, object], str]:
    resolved_artifact_id = artifact_id or record.artifact_id
    payload: dict[str, object] = {
        "source": {"run_id": run_id, "model_run_id": model_run_id},
        "result": {"committed": True},
    }
    content = raw_payload or json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    index = _indexed_artifact(
        artifact_id=resolved_artifact_id,
        sha256=hashlib.sha256(content).hexdigest(),
        run_id=run_id,
        model_run_id=model_run_id,
        content_hash=record.content_hash,
        evidence_content_hash=record.content_hash,
        evidence_commit_ref=binding.commit_id,
        evidence_commit_binding=binding.to_dict(),
        evidence_envelope=record.envelope.to_dict(),
        evidence_envelope_ref=f"evidence-envelope:{record.envelope_digest}",
        evidence_artifact_ref=resolved_artifact_id,
        evidence_artifact_admission_ref=record.artifact_id,
        evidence_run_id=run_id,
        evidence_model_run_id=model_run_id,
    )
    return index, payload, hashlib.sha256(content).hexdigest()


@contextmanager
def _server_owned_evidence(
    tmp_path: Path,
    *,
    run_id: str = "run-1",
    model_run_id: str = "run-1",
) -> Iterator[tuple[ArtifactAdmissionV1, EvidenceCommitBindingV1, ServerOwnedReportEvidencePersistenceV1]]:
    """Build the same C0 registry/store/receipt capability as the owner seam."""

    from tests.test_v189_evidence_envelope import _admit, _admit_store, _authorized_registry

    registry, _host = _authorized_registry("scope:project:1")
    record = _admit(
        registry,
        json.loads(_FIXTURE.read_text(encoding="utf-8")),
        artifact_id="artifact-1",
        scope_ref="scope:project:1",
        execution_ref=f"execution:{run_id}",
    )
    with _admit_store(tmp_path, registry) as store:
        receipt = registry.persistence_receipt(record)
        binding = store.commit(record, receipt=receipt)
        capability = ServerOwnedReportEvidencePersistenceV1(
            store,
            registry,
            receipt,
            run_id=run_id,
            model_run_id=model_run_id,
        )
        yield record, binding, capability


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


def test_tampered_committed_envelope_is_blocked_without_facts(tmp_path: Path) -> None:
    with _server_owned_evidence(tmp_path) as (record, binding, capability):
        tampered_envelope = record.envelope.to_dict()
        tampered_envelope["numeric_facts"][0]["value"] = 999.0  # type: ignore[index]
        indexed_artifact, payload, content_hash = _canonical_indexed_artifact(record, binding)
        indexed_artifact["evidence_envelope"] = tampered_envelope

        view = build_indexed_report_evidence(
            indexed_artifact,
            payload,
            artifact_content_sha256=content_hash,
            authoritative_persistence=capability,
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


def test_indexed_canonical_commit_is_the_only_path_that_admits_report_facts(tmp_path: Path) -> None:
    with _server_owned_evidence(tmp_path) as (record, binding, capability):
        indexed_artifact, payload, content_hash = _canonical_indexed_artifact(record, binding)
        view = build_indexed_report_evidence(
            indexed_artifact,
            payload,
            artifact_content_sha256=content_hash,
            authoritative_persistence=capability,
        )

        assert view["status"] == "available"
        assert view["envelopeDigest"] == record.envelope_digest
        assert [fact["value"] for fact in view["facts"]] == [2.0, 0.2]


def test_foreign_artifact_cannot_reuse_a_valid_committed_pair(tmp_path: Path) -> None:
    with _server_owned_evidence(tmp_path) as (record, binding, capability):
        indexed_artifact, payload, content_hash = _canonical_indexed_artifact(record, binding)
        indexed_artifact["artifact_id"] = "foreign-artifact"

        view = build_indexed_report_evidence(
            indexed_artifact,
            payload,
            artifact_content_sha256=content_hash,
            authoritative_persistence=capability,
        )

        assert view["status"] == "blocked"
        assert view["reasonCode"] == "EVIDENCE_ARTIFACT_ID_MISMATCH"
        assert view["facts"] == []


def test_registry_rejects_a_self_consistent_foreign_copy_of_a_committed_pair(tmp_path: Path) -> None:
    with _server_owned_evidence(tmp_path) as (record, binding, capability):
        indexed_artifact, payload, content_hash = _canonical_indexed_artifact(record, binding)
        foreign_payload = dict(payload)
        foreign_raw = json.dumps(
            foreign_payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        foreign = dict(indexed_artifact)
        foreign.update(
            {
                "artifact_id": "artifact-foreign",
                "evidence_artifact_ref": "artifact-foreign",
                "sha256": hashlib.sha256(foreign_raw).hexdigest(),
            }
        )

        view = build_indexed_report_evidence(
            foreign,
            foreign_payload,
            artifact_content_sha256=hashlib.sha256(foreign_raw).hexdigest(),
            authoritative_persistence=capability,
        )

    assert view["status"] in {"unavailable", "blocked"}
    assert view["facts"] == []
    assert view["reasonCode"] == "EVIDENCE_ADMISSION_NOT_FOUND"


def test_foreign_run_cannot_reuse_a_valid_committed_pair(tmp_path: Path) -> None:
    with _server_owned_evidence(tmp_path) as (record, binding, capability):
        indexed_artifact, payload, content_hash = _canonical_indexed_artifact(record, binding)
        indexed_artifact["run_id"] = "foreign-run"
        indexed_artifact["model_run_id"] = "foreign-run"
        indexed_artifact["evidence_run_id"] = "foreign-run"
        indexed_artifact["evidence_model_run_id"] = "foreign-run"

        view = build_indexed_report_evidence(
            indexed_artifact,
            payload,
            artifact_content_sha256=content_hash,
            authoritative_persistence=capability,
        )

        assert view["status"] == "blocked"
        assert view["reasonCode"] == "EVIDENCE_RUN_ID_MISMATCH"
        assert view["facts"] == []


def test_foreign_content_hash_and_admission_ref_cannot_reuse_a_pair(tmp_path: Path) -> None:
    with _server_owned_evidence(tmp_path) as (record, binding, capability):
        indexed_artifact, payload, content_hash = _canonical_indexed_artifact(record, binding)
        indexed_artifact["content_hash"] = "f" * 64

        hash_view = build_indexed_report_evidence(
            indexed_artifact,
            payload,
            artifact_content_sha256=content_hash,
            authoritative_persistence=capability,
        )

        assert hash_view["status"] == "blocked"
        assert hash_view["reasonCode"] == "EVIDENCE_ARTIFACT_CONTENT_HASH_MISMATCH"
        assert hash_view["facts"] == []

        indexed_artifact, payload, content_hash = _canonical_indexed_artifact(record, binding)
        indexed_artifact["sha256"] = "f" * 64
        file_hash_view = build_indexed_report_evidence(
            indexed_artifact,
            payload,
            artifact_content_sha256=content_hash,
            authoritative_persistence=capability,
        )

        assert file_hash_view["status"] == "blocked"
        assert file_hash_view["reasonCode"] == "EVIDENCE_ARTIFACT_FILE_HASH_MISMATCH"
        assert file_hash_view["facts"] == []

        indexed_artifact, payload, content_hash = _canonical_indexed_artifact(record, binding)
        indexed_artifact["evidence_artifact_admission_ref"] = "foreign-admission"
        admission_view = build_indexed_report_evidence(
            indexed_artifact,
            payload,
            artifact_content_sha256=content_hash,
            authoritative_persistence=capability,
        )

        assert admission_view["status"] == "blocked"
        assert admission_view["reasonCode"] == "EVIDENCE_ARTIFACT_ADMISSION_MISMATCH"
        assert admission_view["facts"] == []


def test_multi_artifact_bundle_fails_closed_without_a_single_canonical_identity() -> None:
    record = _persisted_record()
    projection = default_projection_registry().project(
        record,
        consumer_id="report",
        destination="local",
    )
    first = build_persisted_evidence_report_view(projection)
    second = dict(first)
    second["projectionId"] = "report:evidence-commit-2"
    second["artifactRef"] = "artifact-2"

    bundle = build_report_evidence_bundle([first, second])

    assert bundle is not None
    assert bundle["status"] == "blocked"
    assert bundle["reasonCode"] == "REPORT_EVIDENCE_BUNDLE_IDENTITY_UNBOUND"
    assert bundle["commitId"] == "UNAVAILABLE"
    assert bundle["envelopeDigest"] == "UNAVAILABLE"
    assert bundle["facts"] == []


def test_runs_route_injects_the_server_owned_projection_capability(tmp_path: Path, monkeypatch) -> None:
    run_root = tmp_path / "run-1"
    artifact_path = run_root / "artifacts" / "post_estimation" / "result.json"
    artifact_path.parent.mkdir(parents=True)

    owner_root = tmp_path / "owner-store"
    owner_root.mkdir()
    with _server_owned_evidence(owner_root) as (record, binding, capability):
        indexed_artifact, payload, _content_hash = _canonical_indexed_artifact(record, binding)
        indexed_artifact["path"] = "artifacts/post_estimation/result.json"
        indexed_artifact.pop("evidence_commit_binding")
        indexed_artifact.pop("evidence_envelope")
        artifact_path.write_bytes(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        (run_root / "artifacts_index.json").write_text(
            json.dumps({"schema_version": 1, "artifacts": [indexed_artifact]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            runs_routes,
            "current_report_evidence_persistence",
            lambda *, run_id: capability if run_id == "run-1" else None,
        )

        view = runs_routes._report_evidence_for_run(run_root, [])

    assert view["status"] == "available"
    assert view["commitId"] == binding.commit_id
    assert view["envelopeDigest"] == record.envelope_digest
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
