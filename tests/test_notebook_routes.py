"""HTTP contract tests for the v1.8.1 Notebook lifecycle seam."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from dataclasses import replace
from types import SimpleNamespace

from tests.test_notebook_support import make_project, make_run, model_rerun_proposal
from workbench.api import app
from workbench.agent.notebook import NotebookService, OptionDraft, TypedProposal
from workbench.contracts.agent.notebook_option import (
    EvidenceRef,
    ExpectedArtifact,
    NOTEBOOK_OPTION_CONTRACT_VERSION,
    NotebookOptionRevision,
    RecommendationDecision,
)
from workbench.lineage.upload_store import store_upload_bytes
from workbench.http.notebook_routes import _supports_rerun_model_options


def _persisted_run(project: Path, run_id: str, *, rerun_of: str | None = None) -> None:
    root = make_run(project, run_id, rerun_of=rerun_of)
    (root / "graph.json").write_text(
        json.dumps({"nodes": {"model": {"id": "model", "stage": "model"}}}),
        encoding="utf-8",
    )
    (root / "staged").mkdir()
    (root / "staged" / "data_profile.json").write_text(
        json.dumps({"columns": [{"name": "outcome", "dtype": "float64"}]}),
        encoding="utf-8",
    )
    (root / "errors.json").write_text(json.dumps({"issues": []}), encoding="utf-8")


def _create(client: TestClient, project: Path) -> dict:
    response = client.post(
        "/notebooks",
        params={"project_root": str(project)},
        json={
            "title": "Notebook route test",
            "created_by": "user_1",
            "analysis_contract": {"revision": 1, "target": "y"},
            "user_focus": {"selected_text_hash": "sha256:seed"},
            "available_capabilities": ["time_series.arma_garch"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_run_notebook_catalog_only_advertises_model_packs_with_options_owner() -> None:
    assert _supports_rerun_model_options({"params": [{"key": "model_options"}]})
    assert not _supports_rerun_model_options(
        {"params": [{"key": "x"}, {"key": "covariance"}]}
    )


def _drafts() -> list[dict]:
    return [
        {
            "rank": 1,
            "rationale": "Use the robust covariance option as the first path.",
            "assumptions": ["The residual structure is stable."],
            "proposal": model_rerun_proposal("p1", covariance="robust"),
            "expected_artifacts": [
                {
                    "artifact_id": "ts.parameters",
                    "artifact_type": "time_series_json",
                    "required": True,
                    "count": 1,
                    "step": None,
                }
            ],
            "option_id": "opt_route_1",
        }
    ]


def test_notebook_route_creates_reads_and_compiles_a_runless_notebook(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    client = TestClient(app)

    notebook = _create(client, project)

    fetched = client.get(
        f"/notebooks/{notebook['notebook_id']}",
        params={"project_root": str(project)},
    )
    assert fetched.status_code == 200
    assert fetched.json()["run_family_id"] == notebook["run_family_id"]
    assert fetched.json()["active_head_run_id"] is None

    compiled = client.post(
        f"/notebooks/{notebook['notebook_id']}/context/compile",
        params={"project_root": str(project)},
    )
    assert compiled.status_code == 200, compiled.text
    assert compiled.json()["run_family_id"] == notebook["run_family_id"]
    assert compiled.json()["active_head_run_id"] is None
    assert compiled.json()["source_manifest"] == []
    assert compiled.json()["trace_id"].startswith("trace_")


def test_notebook_route_runs_option_lifecycle_through_artifact_validation(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    client = TestClient(app)
    notebook = _create(client, project)
    notebook_id = notebook["notebook_id"]
    params = {"project_root": str(project)}

    proposed = client.post(
        f"/notebooks/{notebook_id}/options/propose",
        params=params,
        json={"drafts": _drafts()},
    )
    assert proposed.status_code == 200, proposed.text
    assert [option["option_id"] for option in proposed.json()["options"]] == [
        "opt_route_1"
    ]
    assert proposed.json()["options"][0]["freshness_status"] == "fresh"
    assert proposed.json()["context"]["active_head_run_id"] is None
    assert proposed.json()["trace_id"].startswith("trace_")

    snapshot = client.get(
        f"/notebooks/{notebook_id}/options",
        params=params,
    )
    assert snapshot.status_code == 200, snapshot.text
    assert [item["option_id"] for item in snapshot.json()["options"]] == [
        "opt_route_1"
    ]
    assert snapshot.json()["options"][0]["freshness_status"] == "fresh"
    assert snapshot.json()["trace_id"] == proposed.json()["trace_id"]

    trace = client.get(
        f"/notebooks/{notebook_id}/traces/{snapshot.json()['trace_id']}",
        params=params,
    )
    assert trace.status_code == 200, trace.text
    assert trace.json()["events"]
    assert trace.json()["events"][0]["trace_id"] == snapshot.json()["trace_id"]

    decision = client.post(
        f"/notebooks/{notebook_id}/options/opt_route_1/decision",
        params=params,
        json={"decision": "selected", "actor": "user_1"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["lifecycle_status"] == "selected"
    NotebookOptionRevision.from_dict(decision.json())

    repeated_decision = client.post(
        f"/notebooks/{notebook_id}/options/opt_route_1/decision",
        params=params,
        json={"decision": "selected", "actor": "user_1"},
    )
    assert repeated_decision.status_code == 200, repeated_decision.text
    assert repeated_decision.json()["lifecycle_status"] == "selected"

    confirmed = client.post(
        f"/notebooks/{notebook_id}/options/opt_route_1/confirm",
        params=params,
        json={
            "option_revision": 1,
            "proposal_id": "p1",
            "proposal_revision": 1,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["execution"]["option_id"] == "opt_route_1"
    assert confirmed.json()["execution"]["run_id"] is None

    after_confirm = client.get(
        f"/notebooks/{notebook_id}/options",
        params=params,
    )
    assert after_confirm.status_code == 200, after_confirm.text
    assert after_confirm.json()["options"][0]["lifecycle_status"] == "executing"

    completed = client.post(
        f"/notebooks/{notebook_id}/options/opt_route_1/execute",
        params=params,
        json={
            "execution_status": "succeeded",
            "produced_artifacts": [
                {
                    "artifact_id": "ts.parameters",
                    "artifact_type": "time_series_json",
                    "count": 1,
                    "step": None,
                }
            ],
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["execution_status"] == "succeeded"
    assert completed.json()["artifact_validation"]["validation_status"] == "passed"
    assert completed.json()["lifecycle_status"] == "executed"

    reloaded = client.get(
        f"/notebooks/{notebook_id}/options",
        params=params,
    )
    assert reloaded.status_code == 200, reloaded.text
    persisted_result = reloaded.json()["execution_results"]["opt_route_1"]
    assert persisted_result == {
        "option_id": "opt_route_1",
        "option_revision": 1,
        "run_id": None,
        "execution_status": "succeeded",
        "committed": True,
        "artifact_validation": {
            "contract_profile": "artifact-identity-type-count/v1",
            "validation_status": "passed",
            "checked_dimensions": ["artifact_id", "artifact_type", "count", "step"],
            "not_evaluated_dimensions": ["payload_schema"],
            "issues": [],
        },
    }


def test_notebook_route_uses_server_planner_when_drafts_are_omitted(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    client = TestClient(app)
    notebook = _create(client, project)

    response = client.post(
        f"/notebooks/{notebook['notebook_id']}/options/propose",
        params={"project_root": str(project)},
        json={"count": 3},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "NOTEBOOK_PLANNING_UNAVAILABLE"


def test_notebook_route_persists_agent_decision_as_evidence_option_revision(
    tmp_path: Path, monkeypatch
) -> None:
    project = make_project(tmp_path)
    client = TestClient(app)
    notebook = _create(client, project)
    option = OptionDraft(
        rank=1,
        rationale="The bounded time-index inspection is complete.",
        assumptions=("the observed index remains valid",),
        proposal=TypedProposal.from_dict(model_rerun_proposal("p_agent")),
        expected_artifacts=(
            ExpectedArtifact(
                artifact_id="ets_1",
                artifact_type="model_result",
                required=True,
                count=1,
            ),
        ),
        capability_id="time_series.ets",
        option_id="opt_agent_1",
        evidence_refs=(
            EvidenceRef(
                evidence_id="evidence:time",
                result_hash="sha256:time-result",
                source_refs=("time_index:run_001",),
            ),
        ),
        comparative_claims=("evidence:time supports the proposed path",),
    )
    decision = RecommendationDecision(
        recommendation_decision_id="rec_agent_1",
        batch_id="batch_agent_route",
        generation_context_hash="sha256:context",
        freshness_dependency_fingerprint="fresh1:context",
        evidence_pack_hashes=("sha256:pack",),
        comparison_protocol_refs=(),
        candidate_option_ids=("opt_agent_1",),
        outcome="insufficient_evidence",
        recommended_option_id=None,
        reason_refs=("evidence:time",),
    )

    class FakePlanningAgent:
        def plan(self, *, context, initial_evidence):
            del initial_evidence
            return SimpleNamespace(
                option_drafts=(replace(
                    option,
                    recommendation_decision_id=decision.recommendation_decision_id,
                    recommendation_status=decision.outcome,
                ),),
                decision=decision,
            )

    monkeypatch.setattr(
        "workbench.http.notebook_routes._planning_agent",
        lambda *args, **kwargs: FakePlanningAgent(),
    )
    response = client.post(
        f"/notebooks/{notebook['notebook_id']}/options/propose",
        params={"project_root": str(project)},
        json={"count": 1},
    )

    assert response.status_code == 200, response.text
    persisted = response.json()["options"][0]
    assert persisted["contract_version"] == NOTEBOOK_OPTION_CONTRACT_VERSION
    assert persisted["batch_id"] == decision.batch_id
    assert persisted["recommendation_decision_id"] == decision.recommendation_decision_id
    assert persisted["recommendation_status"] == "insufficient_evidence"
    listed = client.get(
        f"/notebooks/{notebook['notebook_id']}/options",
        params={"project_root": str(project)},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["options"][0]["recommendation_decision_id"] == decision.recommendation_decision_id
    trace = client.get(
        f"/notebooks/{notebook['notebook_id']}/traces/{response.json()['trace_id']}",
        params={"project_root": str(project)},
    )
    assert trace.status_code == 200, trace.text
    completed = [
        event for event in trace.json()["events"]
        if event["event_type"] == "agent.plan.completed/v1"
    ]
    assert completed[0]["payload"]["recommendation_decision_id"] == decision.recommendation_decision_id
    assert completed[0]["payload"]["evidence_pack_hashes"] == list(decision.evidence_pack_hashes)


def test_projection_route_binds_real_run_context_and_hashes_graph(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    _persisted_run(project, "run_001")
    client = TestClient(app)

    projection = client.post(
        "/notebooks/projection",
        params={"project_root": str(project)},
        json={"from_run_id": "run_001", "created_by": "ui"},
    )
    assert projection.status_code == 200, projection.text
    notebook = projection.json()
    assert notebook["projection_source"] == {"kind": "run", "run_id": "run_001"}
    assert notebook["active_head_run_id"] == "run_001"

    context = client.post(
        f"/notebooks/{notebook['notebook_id']}/context/compile",
        params={"project_root": str(project)},
    )
    assert context.status_code == 200, context.text
    packet = context.json()
    assert packet["active_head_run_id"] == "run_001"
    assert packet["current_family_head_run_id"] == "run_001"
    assert "ols" in packet["available_capabilities"]
    assert packet["graph_hash"].startswith("sha256:")
    assert {item["kind"] for item in packet["source_manifest"]} >= {"graph", "errors"}


def test_projection_route_compiles_verified_dataset_without_inventing_run(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sha256 = store_upload_bytes(project, b"outcome,predictor\n1,2\n", filename="data.csv")
    client = TestClient(app)

    projection = client.post(
        "/notebooks/projection",
        params={"project_root": str(project)},
        json={
            "dataset": {"upload_sha256": sha256, "filename": "data.csv", "sheet_names": []},
            "created_by": "ui",
        },
    )
    assert projection.status_code == 200, projection.text
    notebook = projection.json()
    assert notebook["projection_source"]["kind"] == "dataset"
    assert notebook["active_head_run_id"] is None
    assert list((project / "runs").iterdir()) == []

    context = client.post(
        f"/notebooks/{notebook['notebook_id']}/context/compile",
        params={"project_root": str(project)},
    )
    assert context.status_code == 200, context.text
    packet = context.json()
    assert packet["active_head_run_id"] is None
    assert packet["current_family_head_run_id"] is None
    assert [column["name"] for column in packet["dataset_profile"]["columns"]] == [
        "outcome",
        "predictor",
    ]
    assert "rows" not in packet["dataset_profile"]


def test_projection_route_rejects_ambiguous_source(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/notebooks/projection",
        params={"project_root": str(project)},
        json={"created_by": "ui"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NOTEBOOK_PROJECTION_SOURCE_INVALID"


def test_materialize_route_creates_genesis_draft_and_confirm_is_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    project = make_project(tmp_path)
    upload_sha = store_upload_bytes(
        project, b"outcome,predictor\n1,2\n2,3\n", filename="data.csv"
    )
    client = TestClient(app)
    params = {"project_root": str(project)}
    notebook = client.post(
        "/notebooks/projection",
        params=params,
        json={
            "dataset": {
                "upload_sha256": upload_sha,
                "filename": "data.csv",
                "sheet_names": [],
            },
            "created_by": "ui",
        },
    ).json()
    notebook_id = notebook["notebook_id"]
    service = NotebookService(project)
    service.store.append_evidence_pack(
        notebook_id,
        {
            "schema_version": "data-evidence-pack/v1",
            "source_id": f"dataset:{upload_sha}",
            "records": [
                {
                    "evidence_id": "evidence:profile",
                    "inspection_id": "profile.v1",
                    "source_refs": [f"dataset_profile:{upload_sha}"],
                    "protocol_version": "profile/v1",
                    "status": "completed",
                    "observations": {"columns": ["outcome", "predictor"]},
                    "metrics": {},
                    "warnings": [],
                    "omissions": [],
                    "failure_code": None,
                    "result_hash": "sha256:profile-result",
                }
            ],
            "pack_omissions": [],
            "content_hash": "sha256:profile-pack",
            "evidence_pack_hash": "sha256:profile-pack",
        },
    )
    context = service.compile_context(notebook_id)
    option = OptionDraft(
        rank=1,
        rationale="The verified dataset exposes the declared outcome and predictor columns.",
        proposal=TypedProposal(
            proposal_id="p_genesis_route",
            operation_id="model.genesis",
            target={"dataset_source_id": upload_sha},
            preconditions={
                "context_version": "notebook-planning-context/v1",
                "context_fingerprint": context.context_id,
                "owner_resolution": "dataset_projection",
            },
            changes={
                "model_params": {
                    "model_type": "ols",
                    "y": "outcome",
                    "x": ["predictor"],
                }
            },
        ),
        expected_artifacts=(
            ExpectedArtifact(
                artifact_id="ols_1",
                artifact_type="model_result",
                required=True,
                count=1,
            ),
        ),
        capability_id="ols",
        option_id="opt_genesis_route",
        evidence_refs=(
            EvidenceRef(
                evidence_id="evidence:profile",
                result_hash="sha256:profile-result",
                source_refs=(f"dataset_profile:{upload_sha}",),
            ),
        ),
        comparative_claims=("evidence:profile supports the declared model columns",),
    )
    decision = RecommendationDecision(
        recommendation_decision_id="rec_genesis_route",
        batch_id="batch_genesis_route",
        generation_context_hash="sha256:placeholder",
        freshness_dependency_fingerprint="fresh1:placeholder",
        evidence_pack_hashes=("sha256:profile-pack",),
        comparison_protocol_refs=(),
        candidate_option_ids=("opt_genesis_route",),
        outcome="recommended",
        recommended_option_id="opt_genesis_route",
        reason_refs=("evidence:profile",),
    )

    class FakePlanningAgent:
        def plan(self, *, context, initial_evidence):
            del context, initial_evidence
            return SimpleNamespace(
                option_drafts=(
                    replace(
                        option,
                        recommendation_decision_id=decision.recommendation_decision_id,
                        recommendation_status=decision.outcome,
                    ),
                ),
                decision=decision,
            )

    monkeypatch.setattr(
        "workbench.http.notebook_routes._planning_agent",
        lambda *args, **kwargs: FakePlanningAgent(),
    )
    proposed = client.post(
        f"/notebooks/{notebook_id}/options/propose",
        params=params,
        json={"count": 1},
    )
    assert proposed.status_code == 200, proposed.text
    persisted = proposed.json()["options"][0]
    assert persisted["recommendation_status"] == "recommended"

    selected = client.post(
        f"/notebooks/{notebook_id}/options/{option.option_id}/decision",
        params=params,
        json={"decision": "selected", "actor": "ui"},
    )
    assert selected.status_code == 200, selected.text

    materialized = client.post(
        f"/notebooks/{notebook_id}/options/{option.option_id}/materialize",
        params=params,
    )
    assert materialized.status_code == 200, materialized.text
    packet = materialized.json()
    assert packet["materialization"]["draft_execution_mode"] == "genesis"
    assert packet["draft"]["created_from"]["source_type"] == "genesis"
    assert packet["draft"]["notebook_provenance"]["notebook_id"] == notebook_id

    confirmed = client.post(
        f"/notebooks/{notebook_id}/options/{option.option_id}/confirm",
        params=params,
        json={
            "option_revision": 1,
            "proposal_id": "p_genesis_route",
            "proposal_revision": 1,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["materialization"]["materialization_id"] == packet["materialization"]["materialization_id"]

    listed = client.get(
        f"/notebooks/{notebook_id}/options",
        params=params,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["materializations"][option.option_id]["draft_id"] == packet["draft"]["draft_id"]


def test_replan_route_returns_replanned_option_and_deferred_sibling(
    tmp_path: Path, monkeypatch
) -> None:
    project = make_project(tmp_path)
    client = TestClient(app)
    notebook = _create(client, project)
    notebook_id = notebook["notebook_id"]
    params = {"project_root": str(project)}
    initial = _drafts()
    initial.append(
        {
            **_drafts()[0],
            "rank": 2,
            "option_id": "opt_route_2",
            "proposal": model_rerun_proposal("p2", covariance="clustered"),
        }
    )
    first = client.post(
        f"/notebooks/{notebook_id}/options/propose",
        params=params,
        json={"drafts": initial},
    )
    assert first.status_code == 200, first.text

    evidence = EvidenceRef(
        evidence_id="evidence:time",
        result_hash="sha256:time-result",
        source_refs=("time_index:run_001",),
    )
    replanned = OptionDraft(
        rank=1,
        rationale="The bounded time-index inspection still supports the robust path.",
        proposal=TypedProposal.from_dict(model_rerun_proposal("p1-replanned")),
        expected_artifacts=(
            ExpectedArtifact(
                artifact_id="ts.parameters",
                artifact_type="time_series_json",
                required=True,
                count=1,
            ),
        ),
        option_id="opt_route_1",
        evidence_refs=(evidence,),
        comparative_claims=("evidence:time supports the replanned robust path",),
        recommendation_decision_id="rec_replan",
        recommendation_status="insufficient_evidence",
    )
    decision = RecommendationDecision(
        recommendation_decision_id="rec_replan",
        batch_id="batch_replan",
        generation_context_hash="sha256:context",
        freshness_dependency_fingerprint="fresh1:context",
        evidence_pack_hashes=("sha256:pack",),
        comparison_protocol_refs=(),
        candidate_option_ids=("opt_route_1",),
        outcome="insufficient_evidence",
        recommended_option_id=None,
        reason_refs=("evidence:time",),
    )

    class FakePlanningAgent:
        def plan(self, *, context, initial_evidence):
            del context, initial_evidence
            return SimpleNamespace(option_drafts=(replanned,), decision=decision)

    monkeypatch.setattr(
        "workbench.http.notebook_routes._planning_agent",
        lambda *args, **kwargs: FakePlanningAgent(),
    )
    second = client.post(
        f"/notebooks/{notebook_id}/options/propose",
        params=params,
        json={"count": 3},
    )
    assert second.status_code == 200, second.text
    options = second.json()["options"]
    assert {item["option_id"] for item in options} == {
        "opt_route_1",
        "opt_route_2",
    }
    assert next(item for item in options if item["option_id"] == "opt_route_1")[
        "option_revision"
    ] == 2
    assert next(item for item in options if item["option_id"] == "opt_route_2")[
        "option_revision"
    ] == 1


def test_external_family_focus_marks_options_stale_without_rebinding_source(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    _persisted_run(project, "run_001")
    _persisted_run(project, "run_002", rerun_of="run_001")
    client = TestClient(app)
    params = {"project_root": str(project)}
    projection = client.post(
        "/notebooks/projection",
        params=params,
        json={"from_run_id": "run_001", "created_by": "ui"},
    ).json()
    notebook_id = projection["notebook_id"]

    proposed = client.post(
        f"/notebooks/{notebook_id}/options/propose",
        params=params,
        json={"drafts": _drafts()},
    )
    assert proposed.status_code == 200, proposed.text

    after = client.get(
        f"/notebooks/{notebook_id}/options",
        params={**params, "focused_run_id": "run_002"},
    )
    assert after.status_code == 200, after.text
    assert after.json()["context"]["active_head_run_id"] == "run_001"
    assert after.json()["context"]["current_family_head_run_id"] == "run_002"
    assert after.json()["options"][0]["freshness_status"] == "stale"
    assert client.get(
        f"/notebooks/{notebook_id}", params=params
    ).json()["projection_source"] == {"kind": "run", "run_id": "run_001"}
