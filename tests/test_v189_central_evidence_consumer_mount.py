from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from collections.abc import Iterator

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.app import configure_report_evidence_owner

from tests.test_v189_evidence_report_boundary import _server_owned_evidence


@contextmanager
def _local_authority(tmp_path: Path) -> Iterator[None]:
    """Keep the test authority socket inside pytest's writable directory."""

    from tests.test_v189_evidence_envelope import _ExternalHostAuthority, _TestAuthorityServer

    previous_server = _ExternalHostAuthority._server
    previous_pid = _ExternalHostAuthority._server_pid
    # Use the helper's process-private /private/tmp directory.  It owns and
    # chmods that directory before binding the socket; pytest's shared
    # tempfile directory is not suitable for this authority boundary.
    server = _TestAuthorityServer()
    _ExternalHostAuthority._server = server
    _ExternalHostAuthority._server_pid = os.getpid()
    try:
        yield
    finally:
        _ExternalHostAuthority._server = previous_server
        _ExternalHostAuthority._server_pid = previous_pid
        server.close()


def _completed_run(project_root: Path, run_id: str = "run-1") -> Path:
    run_root = project_root / "runs" / run_id
    (run_root / "model_results").mkdir(parents=True)
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "completed",
                "mode": "auto",
                "lineage": [],
            }
        ),
        encoding="utf-8",
    )
    return run_root


def test_run_detail_projects_results_from_server_owned_typed_evidence(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _completed_run(project_root)
    (project_root / "runs" / "run-1" / "model_results" / "ols_1.json").write_text(
        json.dumps({"coefficients": {"leaked": {"estimate": 999.0}}}),
        encoding="utf-8",
    )

    with _local_authority(tmp_path / "authority"):
        with _server_owned_evidence(
            tmp_path / "owner-store",
            run_id="run-1",
            model_run_id="run-1",
            canonical_project_root=project_root,
        ) as (record, binding, owner):
            configure_report_evidence_owner(owner)
            try:
                with TestClient(app) as client:
                    response = client.get(
                        "/runs/run-1",
                        params={"project_root": str(project_root)},
                    )
            finally:
                configure_report_evidence_owner(None)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["model_results"] == []
    assert payload["model_results_authority"] == "non-authoritative"
    for compatibility_field in (
        "table_1",
        "statistical_evidence",
        "labels",
        "model_family_evidence",
        "prediction_evidence",
        "post_estimation_results",
    ):
        assert payload[f"{compatibility_field}_authority"] == "non-authoritative"
    assert payload["classification_evidence_authority"] == "server-owned"
    assert "results_evidence" in payload
    assert payload["results_evidence_authority"] == "server-owned"
    evidence = payload["results_evidence"]
    assert evidence["status"] == "available"
    assert evidence["consumer_id"] == "results"
    assert evidence["facts"]
    assert evidence["commit_id"] == binding.commit_id
    assert evidence["envelope_digest"] == record.envelope_digest
    assert payload["results_evidence_receipt"]["projectionDigest"] == evidence["projection_digest"]
    assert "999.0" not in json.dumps(payload, sort_keys=True)


def test_agent_notebook_and_results_use_one_server_owned_projection_source(
    tmp_path: Path,
) -> None:
    from workbench.agent.context_tools import read_persisted_evidence_for_agent
    from workbench.agent.notebook.evidence import read_persisted_evidence_for_notebook
    from workbench.services.results_service import (
        configure_report_evidence_persistence,
        read_persisted_consumer_evidence_for_run,
    )

    project_root = tmp_path / "project"
    with _local_authority(tmp_path / "authority"):
        with _server_owned_evidence(
            tmp_path / "owner-store",
            run_id="run-1",
            model_run_id="run-1",
            canonical_project_root=project_root,
        ) as (record, binding, owner):
            configure_report_evidence_persistence(owner)
            try:
                results = read_persisted_consumer_evidence_for_run(
                    consumer_id="results",
                    project_root=project_root,
                    run_id="run-1",
                )
                agent = read_persisted_evidence_for_agent(project_root / "runs" / "run-1")
                notebook = read_persisted_evidence_for_notebook(project_root / "runs" / "run-1")
            finally:
                configure_report_evidence_persistence(None)

    assert {results["status"], agent["status"], notebook["status"]} == {"available"}
    assert results["artifact_ref"] == agent["artifact_ref"] == notebook["artifact_ref"] == record.artifact_id
    assert results["commit_id"] == agent["commit_id"] == notebook["commit_id"] == binding.commit_id
    assert results["envelope_digest"] == agent["envelope_digest"] == notebook["envelope_digest"] == record.envelope_digest
    assert results["projection_digest"] != agent["projection_digest"]
    assert agent["projection_digest"] == notebook["projection_digest"]
    assert results["receipt"]["projection_digest"] == results["projection_digest"]
    assert agent["receipt"]["projection_digest"] == agent["projection_digest"]
    assert notebook["receipt"]["projection_digest"] == notebook["projection_digest"]
    assert agent["receipt"]["projection_digest"] == notebook["receipt"]["projection_digest"]


@pytest.mark.parametrize(
    "reason_code",
    ("EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED", "EVIDENCE_OWNER_CONTEXT_CONFLICT"),
)
def test_notebook_execution_results_are_not_facts_without_central_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
) -> None:
    from workbench.http import notebook_routes
    from workbench.services import results_service

    monkeypatch.setattr(
        results_service,
        "read_persisted_consumer_evidence_for_run",
        lambda **_kwargs: {
            "status": "unavailable",
            "availability": "unavailable",
            "execution_status": "unavailable",
            "completeness_status": "unavailable",
            "facts": [],
            "projection_digest": None,
            "reason_code": reason_code,
            "receipt": None,
        },
    )

    class _Store:
        def read_option(self, _notebook_id: str, _option_id: str) -> object:
            return SimpleNamespace(
                execution_results=[
                    {
                        "option_revision": 1,
                        "run_id": "run-1",
                        "execution_status": "completed",
                        "committed": True,
                        "model_specific_execution_results": {
                            "estimate": 999.0,
                        },
                        "capability_execution": {
                            "dispatch_status": "completed",
                            "attempt_id": "attempt:local",
                            "receipt_ref": "receipt:local",
                        },
                    }
                ]
            )

    service = SimpleNamespace(
        project_root=tmp_path / "project",
        store=_Store(),
    )
    revisions = [SimpleNamespace(option_id="option-1", option_revision=1)]

    packet = notebook_routes._execution_results_packet(
        service,
        "notebook-1",
        revisions,
    )

    entry = packet["option-1"]
    assert entry["execution_results_authority"] == "non-authoritative"
    assert entry["persisted_evidence"]["status"] == "unavailable"
    assert entry["persisted_evidence"]["reason_code"] == reason_code
    assert entry["persisted_evidence"]["facts"] == []
    assert "999.0" not in json.dumps(entry, sort_keys=True)


def test_central_consumer_evidence_is_explicitly_unavailable_without_owner(
    tmp_path: Path,
) -> None:
    from workbench.services.results_service import (
        configure_report_evidence_persistence,
        read_persisted_consumer_evidence_for_run,
    )

    configure_report_evidence_persistence(None)
    evidence = read_persisted_consumer_evidence_for_run(
        consumer_id="results",
        project_root=tmp_path / "project",
        run_id="run-1",
    )

    assert evidence["status"] == "unavailable"
    assert evidence["availability"] == "unavailable"
    assert evidence["facts"] == []
    assert evidence["receipt"] is None


def test_run_detail_marks_missing_persisted_evidence_unavailable(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _completed_run(project_root)
    (project_root / "runs" / "run-1" / "model_results" / "ols_1.json").write_text(
        json.dumps({"coefficients": {"fallback": {"estimate": 123.0}}}),
        encoding="utf-8",
    )

    response = TestClient(app).get(
        "/runs/run-1",
        params={"project_root": str(project_root)},
    )

    assert response.status_code == 200, response.text
    evidence = response.json()["results_evidence"]
    assert evidence["status"] == "unavailable"
    assert evidence["facts"] == []
    assert evidence["reason_code"] in {
        "EVIDENCE_OWNER_REQUEST_REQUIRED",
        "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
    }
    assert response.json()["results_evidence_receipt"] is None
    assert "123.0" not in json.dumps(response.json(), sort_keys=True)


def test_run_detail_rejects_a_foreign_persisted_evidence_owner(tmp_path: Path) -> None:
    canonical_root = tmp_path / "canonical"
    foreign_root = tmp_path / "foreign"
    _completed_run(foreign_root)

    with _local_authority(tmp_path / "authority"):
        with _server_owned_evidence(
            tmp_path / "owner-store",
            run_id="run-1",
            model_run_id="run-1",
            canonical_project_root=canonical_root,
        ) as (_record, _binding, owner):
            configure_report_evidence_owner(owner)
            try:
                with TestClient(app) as client:
                    response = client.get(
                        "/runs/run-1",
                        params={"project_root": str(foreign_root)},
                    )
            finally:
                configure_report_evidence_owner(None)

    assert response.status_code == 200, response.text
    evidence = response.json()["results_evidence"]
    assert evidence["status"] == "unavailable"
    assert evidence["facts"] == []
    assert evidence["reason_code"] == "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED"
    assert response.json()["results_evidence_receipt"] is None


def test_run_detail_rejects_a_stale_or_hash_mismatched_persisted_packet(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _completed_run(project_root)

    with _local_authority(tmp_path / "authority"):
        with _server_owned_evidence(
            tmp_path / "owner-store",
            run_id="run-1",
            model_run_id="run-1",
            canonical_project_root=project_root,
        ) as (_record, _binding, owner):
            packet_path = next((tmp_path / "owner-store" / "packets").glob("*.json"))
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            packet["payload"]["artifact"]["envelope"]["result_identity"]["result_id"] = "stale-result"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            configure_report_evidence_owner(owner)
            try:
                with TestClient(app) as client:
                    response = client.get(
                        "/runs/run-1",
                        params={"project_root": str(project_root)},
                    )
            finally:
                configure_report_evidence_owner(None)

    assert response.status_code == 200, response.text
    evidence = response.json()["results_evidence"]
    assert evidence["status"] in {"unavailable", "degraded"}
    assert evidence["facts"] == []
    assert evidence["reason_code"] in {
        "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
        "EVIDENCE_PROJECTION_UNAVAILABLE",
    }
    assert response.json()["results_evidence_receipt"] is None
