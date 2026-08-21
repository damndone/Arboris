from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from test_v189_data_host_resolver import _record, _write_record
from workbench.services.data_consumer_projection_service import (
    DataConsumerProjectionError,
    DataConsumerRunCapabilityV1,
    _CAPABILITY_RECORDS,
    data_consumer_projection_receipt,
    issue_data_consumer_run_capability,
    read_data_consumer_projection,
)


def _central_record(*, record_id: str = "oprec_projection"):
    record = _record(record_id=record_id)
    return replace(
        record,
        target={**record.target, "data_snapshot_digest": "b" * 64},
        preconditions={**record.preconditions, "data_snapshot_digest": "b" * 64},
    )


def _scope(tmp_path: Path):
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run:data-host"
    run_root.mkdir(parents=True)
    return project_root, run_root


def _capability(tmp_path: Path):
    project_root, run_root = _scope(tmp_path)
    _write_record(project_root, _central_record())
    return project_root, run_root, issue_data_consumer_run_capability(
        run_root,
        project_ref="project:data-host",
        session_ref="session:data-host",
    )


def _assert_no_raw_projection_fields(value: object) -> None:
    forbidden = {
        "path",
        "paths",
        "frame",
        "frames",
        "rows",
        "data",
        "raw",
        "payload",
        "file",
    }
    if isinstance(value, dict):
        for key, nested in value.items():
            assert str(key).lower() not in forbidden
            _assert_no_raw_projection_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_raw_projection_fields(nested)


def test_agent_notebook_and_report_share_one_server_projection_digest(tmp_path: Path) -> None:
    _project_root, _run_root, capability = _capability(tmp_path)

    projections = {
        consumer: read_data_consumer_projection(capability, consumer)
        for consumer in ("agent", "notebook", "report")
    }

    assert {item["status"] for item in projections.values()} == {"available"}
    assert {item["consumer_id"] for item in projections.values()} == {
        "agent",
        "notebook",
        "report",
    }
    assert len({item["projection_digest"] for item in projections.values()}) == 1
    assert projections["agent"]["facts"] == projections["notebook"]["facts"]
    assert projections["notebook"]["facts"] == projections["report"]["facts"]
    for projection in projections.values():
        _assert_no_raw_projection_fields(projection)
        assert projection["receipt"]["projectionDigest"] == projection["projection_digest"]


def test_agent_and_notebook_wrappers_delegate_to_the_same_central_reader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _project_root, _run_root, capability = _capability(tmp_path)
    seen: list[tuple[object, str]] = []

    def central(received: object, consumer_id: str, **_kwargs: object) -> dict[str, object]:
        seen.append((received, consumer_id))
        return {"consumer_id": consumer_id, "projection_digest": "a" * 64}

    import workbench.agent.context_tools as context_tools

    monkeypatch.setattr(context_tools, "read_data_consumer_projection", central)
    from workbench.agent.notebook import evidence as notebook_evidence

    # Notebook imports its service lazily, so patch the service itself for the
    # same central-reader assertion.
    import workbench.services.data_consumer_projection_service as service

    monkeypatch.setattr(service, "read_data_consumer_projection", central)
    assert context_tools.read_data_consumer_evidence_for_agent(capability)["consumer_id"] == "agent"
    assert notebook_evidence.read_data_consumer_evidence_for_notebook(capability)["consumer_id"] == "notebook"
    assert [consumer_id for _received, consumer_id in seen] == ["agent", "notebook"]
    assert all(_received is capability for _received, _consumer_id in seen)


def test_path_raw_and_forged_capabilities_fail_closed(tmp_path: Path) -> None:
    _project_root, run_root, capability = _capability(tmp_path)

    for value in (run_root, str(run_root), {"raw": {"rows": [1]}}):
        with pytest.raises(DataConsumerProjectionError) as error:
            read_data_consumer_projection(value, "agent")
        assert error.value.code == "DATA_CONSUMER_RUN_CAPABILITY_REQUIRED"

    forged = object.__new__(DataConsumerRunCapabilityV1)
    object.__setattr__(forged, "_token", "forged")
    with pytest.raises(DataConsumerProjectionError) as error:
        read_data_consumer_projection(forged, "agent")
    assert error.value.code == "DATA_CONSUMER_RUN_CAPABILITY_REQUIRED"

    assert capability in _CAPABILITY_RECORDS


def test_foreign_scope_is_not_promoted_to_central_evidence(tmp_path: Path) -> None:
    project_root, run_root = _scope(tmp_path)
    _write_record(project_root, _central_record())
    capability = issue_data_consumer_run_capability(
        run_root,
        project_ref="project:foreign",
        session_ref="session:data-host",
    )

    projection = read_data_consumer_projection(capability, "agent")

    assert projection["status"] == "unavailable"
    assert projection["reason_code"] == "DATA_CONSUMER_PROJECTION_UNAVAILABLE"
    assert projection["facts"] == []


def test_stale_catalog_is_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _project_root, _run_root, capability = _capability(tmp_path)
    import workbench.services.data_consumer_projection_service as service

    monkeypatch.setattr(service, "_live_catalog_digest", lambda: "c" * 64)

    projection = read_data_consumer_projection(capability, "report")

    assert projection["status"] == "unavailable"
    assert projection["reason_code"] == "DATA_CONSUMER_CATALOG_STALE"


def test_malformed_and_ambiguous_durable_records_are_not_chosen(tmp_path: Path) -> None:
    project_root, run_root = _scope(tmp_path)
    first = _central_record()
    _write_record(project_root, first)
    capability = issue_data_consumer_run_capability(
        run_root,
        project_ref="project:data-host",
        session_ref="session:data-host",
    )
    _write_record(project_root, replace(first, record_id="oprec_projection_2"))

    ambiguous = read_data_consumer_projection(capability, "agent")
    assert ambiguous["status"] == "unavailable"
    assert ambiguous["reason_code"] == "DATA_CONSUMER_PROJECTION_AMBIGUOUS"

    malformed = replace(
        first,
        outputs={
            "ports": {},
            "consumer_slots": {},
            "catalog_digest": first.outputs["catalog_digest"],
        },
    )
    _write_record(project_root, malformed)
    # The latest state for the first record is malformed; the second record is
    # still present, so the reader must report the malformed durable state and
    # never silently select the other record.
    projection = read_data_consumer_projection(capability, "agent")
    assert projection["status"] == "unavailable"
    assert projection["reason_code"] in {
        "DATA_CONSUMER_PROJECTION_AMBIGUOUS",
        "DATA_CONSUMER_HOST_RECORD_INVALID",
    }


def test_fact_selector_and_receipt_are_bounded(tmp_path: Path) -> None:
    _project_root, _run_root, capability = _capability(tmp_path)
    selected = read_data_consumer_projection(
        capability,
        "notebook",
        requested_fact_ids=("data-operation:oprec_projection",),
    )
    assert selected["status"] == "available"
    assert [fact["fact_id"] for fact in selected["facts"]] == [
        "data-operation:oprec_projection"
    ]
    assert data_consumer_projection_receipt(selected)["kind"] == (
        "evidence.data-consumer.server-receipt.v1"
    )

    missing = read_data_consumer_projection(
        capability,
        "notebook",
        requested_fact_ids=("data-operation:missing",),
    )
    assert missing["status"] == "unavailable"
    assert missing["reason_code"] == "DATA_CONSUMER_FACT_NOT_FOUND"


def test_report_run_surface_reads_the_same_server_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root, run_root = _scope(tmp_path)
    (run_root / "model_results").mkdir()
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_root.name,
                "status": "completed",
                "mode": "auto",
                "lineage": [],
            }
        ),
        encoding="utf-8",
    )
    _write_record(project_root, _central_record())

    from workbench.api import app
    from workbench.http import runs_routes
    from workbench.services.results_service import ReportEvidenceRequestIdentityV1

    identity = ReportEvidenceRequestIdentityV1(
        actor_ref="principal:data-host",
        project_ref="project:data-host",
        session_ref="session:data-host",
        scope_ref="scope:data-host",
        run_id=run_root.name,
        model_run_id=run_root.name,
        confirmation_ref="confirmation:data-host",
    )
    monkeypatch.setattr(
        runs_routes,
        "_report_identity_for_request",
        lambda _request, _run_id: identity,
    )

    response = TestClient(app).get(
        f"/runs/{run_root.name}",
        params={"project_root": str(project_root)},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    projection = payload["data_consumer_evidence"]
    assert projection["status"] == "available"
    assert projection["consumer_id"] == "report"
    assert payload["data_consumer_evidence_authority"] == "server-owned"
    assert payload["data_consumer_evidence_receipt"]["projectionDigest"] == (
        projection["projection_digest"]
    )
    _assert_no_raw_projection_fields(projection)
