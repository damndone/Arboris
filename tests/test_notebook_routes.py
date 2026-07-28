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
from workbench.agent.notebook.evidence import DataEvidencePackV1, EvidenceRecord
from workbench.contracts.agent.notebook_option import (
    EvidenceRef,
    ExpectedArtifact,
    NOTEBOOK_OPTION_CONTRACT_VERSION,
    NotebookOptionRevision,
    NotebookOptionRevisionV12,
    RecommendationDecision,
    RecommendationDecisionV11,
)
from workbench.lineage.upload_store import store_upload_bytes
from workbench.http.notebook_routes import (
    _execution_results_packet,
    _planning_agent,
    _supports_rerun_model_options,
    _trace,
)


def test_notebook_route_projects_trusted_capability_completion_refs() -> None:
    from types import SimpleNamespace

    capability_execution = {
        "dispatch_status": "completed",
        "attempt_id": "attempt.custom",
        "receipt_ref": "a" * 64,
        "completion_ref": "b" * 64,
        "artifact_validation_ref": "c" * 64,
        "object_graph_ref": "d" * 64,
        "assessment_ref": "e" * 64,
        "output_bundle_ref": "f" * 64,
        "attestation_ref": "0" * 64,
        "ignored_payload": {"coefficient": 99},
    }
    service = SimpleNamespace(
        store=SimpleNamespace(
            read_option=lambda _notebook_id, _option_id: SimpleNamespace(
                execution_results=(
                    {
                        "option_revision": 1,
                        "run_id": "run.custom",
                        "execution_status": "succeeded",
                        "committed": True,
                        "capability_execution": capability_execution,
                    },
                )
            )
        )
    )

    result = _execution_results_packet(
        service,
        "notebook.custom",
        [SimpleNamespace(option_id="option.custom", option_revision=1)],
    )

    assert result == {
        "option.custom": {
            "option_id": "option.custom",
            "option_revision": 1,
            "run_id": "run.custom",
            "execution_status": "succeeded",
            "committed": True,
            "capability_execution": {
                "dispatch_status": "completed",
                "attempt_id": "attempt.custom",
                "receipt_ref": "a" * 64,
                "completion_ref": "b" * 64,
                "artifact_validation_ref": "c" * 64,
                "object_graph_ref": "d" * 64,
                "assessment_ref": "e" * 64,
                "output_bundle_ref": "f" * 64,
                "attestation_ref": "0" * 64,
            },
        }
    }
from workbench.app import configure_notebook_capability_bindings


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


def test_real_planner_reads_current_server_owned_custom_projection(
    tmp_path: Path, monkeypatch
) -> None:
    from test_notebook_capability_binding import _binding_and_verifier
    from workbench.agent.notebook import NotebookService
    from workbench.capability_factory.notebook_catalog import CapabilityBindingCatalog
    from workbench.llm.config import LLMConfig

    project = make_project(tmp_path, name="project.alpha")
    upload_sha = store_upload_bytes(
        project, b"outcome,predictor\n1,2\n2,3\n", filename="data.csv"
    )
    binding, verifier = _binding_and_verifier()
    catalog = CapabilityBindingCatalog(verifier=verifier)
    catalog.register(
        "custom.ols",
        binding,
        planner_projection={
            "key": "custom.ols",
            "label": "Verified custom OLS",
            "model_type": "ols",
            "notebook_proposal_adapters": ["model.genesis"],
            "params": [],
            "artifact_types": {"custom.ols.result": "custom_json"},
        },
    )
    service = NotebookService(project, capability_bindings=catalog)
    notebook = service.ensure_default_projection(
        dataset={
            "kind": "dataset",
            "upload_sha256": upload_sha,
            "filename": "data.csv",
            "sheet_names": [],
        },
        created_by="test",
        available_capabilities=["custom.ols"],
    )
    context = service.compile_context(notebook.notebook_id)
    trace = _trace(project, notebook.notebook_id, notebook.run_family_id)
    monkeypatch.setattr(
        "workbench.http.notebook_routes.load_llm_config",
        lambda: LLMConfig(
            base_url="https://provider.invalid",
            api_key="test-key",
            model="test-model",
        ),
    )

    planner = _planning_agent(
        project,
        service,
        notebook.notebook_id,
        context,
        trace,
    )

    assert "custom.ols" in planner.capability_catalog
    assert planner.capability_catalog["custom.ols"]["label"] == "Verified custom OLS"
    assert planner.capability_catalog["custom.ols"]["artifact_types"] == {
        "custom.ols.result": "custom_json"
    }
    assert "binding" not in planner.capability_catalog["custom.ols"]
    assert "entrypoint_ref" not in planner.capability_catalog["custom.ols"]


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
    evidence_pack = DataEvidencePackV1(
        source_id="agent:bounded",
        records=(
            EvidenceRecord(
                evidence_id="evidence:time",
                inspection_id="time_index.v1",
                source_refs=("time_index:run_001",),
                protocol_version="time/v1",
                status="completed",
                result_hash="sha256:time-result",
            ),
        ),
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
                evidence_pack=evidence_pack,
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
    assert persisted["contract_version"] == "1.1"
    assert persisted["batch_id"] == decision.batch_id
    assert persisted["recommendation_decision_id"].startswith("rec11_")
    assert persisted["recommendation_status"] == "recommended"
    stored_decision = NotebookService(project).store.read_decision(
        notebook["notebook_id"], persisted["batch_id"]
    )
    RecommendationDecisionV11.from_dict(stored_decision.to_dict())
    listed = client.get(
        f"/notebooks/{notebook['notebook_id']}/options",
        params={"project_root": str(project)},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["options"][0]["recommendation_decision_id"] == persisted["recommendation_decision_id"]
    trace = client.get(
        f"/notebooks/{notebook['notebook_id']}/traces/{response.json()['trace_id']}",
        params={"project_root": str(project)},
    )
    assert trace.status_code == 200, trace.text
    completed = [
        event for event in trace.json()["events"]
        if event["event_type"] == "agent.plan.completed/v1"
    ]
    assert completed[0]["payload"]["recommendation_decision_id"] == persisted["recommendation_decision_id"]
    assert completed[0]["payload"]["evidence_pack_hashes"] == list(
        stored_decision.evidence_pack_hashes
    )


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
    evidence_pack = DataEvidencePackV1(
        source_id=f"dataset:{upload_sha}",
        records=(
            EvidenceRecord(
                evidence_id="evidence:profile",
                inspection_id="profile.v1",
                source_refs=(f"dataset_profile:{upload_sha}",),
                protocol_version="profile/v1",
                status="completed",
                observations={"columns": ["outcome", "predictor"]},
                result_hash="sha256:profile-result",
            ),
        ),
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
                evidence_pack=evidence_pack,
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


def test_model_custom_route_uses_runtime_binding_then_stops_at_gateway_authorization(
    tmp_path: Path, monkeypatch
) -> None:
    """Exercise the production HTTP seam without opening a host execution path."""

    from test_notebook_capability_binding import _binding_and_verifier
    from workbench.agent.context_compiler import (
        freshness_dependency_fingerprint,
        generation_context_hash,
    )
    from workbench.app import (
        configure_capability_factory_runtime,
    )
    from workbench.capability_factory.notebook_catalog import CapabilityBindingCatalog
    from workbench.capability_factory.runtime import CapabilityFactoryRuntime

    project = make_project(tmp_path, name="project.alpha")
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
                    "evidence_id": "evidence:custom-profile",
                    "inspection_id": "profile.v1",
                    "source_refs": [f"dataset_profile:{upload_sha}"],
                    "protocol_version": "profile/v1",
                    "status": "completed",
                    "observations": {"columns": ["outcome", "predictor"]},
                    "metrics": {},
                    "warnings": [],
                    "omissions": [],
                    "failure_code": None,
                    "result_hash": "sha256:custom-profile-result",
                }
            ],
            "pack_omissions": [],
            "content_hash": "sha256:custom-profile-pack",
            "evidence_pack_hash": "sha256:custom-profile-pack",
        },
    )

    binding, verifier = _binding_and_verifier()
    catalog = CapabilityBindingCatalog(verifier=verifier)
    catalog.register(
        "custom.adapter",
        binding,
        planner_projection={
            "key": "custom.adapter",
            "label": "Controlled custom adapter",
            "model_type": "custom.adapter",
            "notebook_proposal_adapters": ["model.custom"],
            "params": [],
            "artifact_types": {"custom.result": "custom_json"},
        },
    )
    runtime = CapabilityFactoryRuntime(
        authority_id="authority.test.runtime",
        catalog=catalog,
    )

    class FakePlanningAgent:
        def plan(self, *, context, initial_evidence):
            del initial_evidence
            option = OptionDraft(
                rank=1,
                rationale="The server-registered custom adapter is the selected experimental path.",
                proposal=TypedProposal(
                    proposal_id="proposal_custom_route",
                    operation_id="model.custom",
                    target={"dataset_source_id": upload_sha},
                    preconditions={
                        "context_version": "node-operation-context/v1",
                        "context_fingerprint": context.context_id,
                        "owner_resolution": "dataset_projection",
                    },
                    changes={
                        "operation": "fit",
                        "parameters": {"alpha": 0.1},
                        "consumer_slots": ["report_projection"],
                    },
                ),
                expected_artifacts=(
                    ExpectedArtifact(
                        artifact_id="custom.result",
                        artifact_type="custom_json",
                        required=True,
                        count=1,
                    ),
                ),
                capability_id="custom.adapter",
                option_id="opt_custom_route",
                evidence_refs=(),
                comparative_claims=(),
            )
            decision = RecommendationDecision(
                recommendation_decision_id="rec_custom_route",
                batch_id="batch_custom_route",
                generation_context_hash=generation_context_hash(context),
                freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
                evidence_pack_hashes=(),
                comparison_protocol_refs=(),
                candidate_option_ids=(option.option_id,),
                outcome="recommended",
                recommended_option_id=option.option_id,
                reason_refs=(),
            )
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
    configure_capability_factory_runtime(runtime)
    try:
        proposed = client.post(
            f"/notebooks/{notebook_id}/options/propose",
            params=params,
            json={"count": 1},
        )
        assert proposed.status_code == 200, proposed.text
        option = proposed.json()["options"][0]
        assert option["risk_level"] == "high"
        assert option["execution_modes"] == [
            "materialize_only",
            "experimental_confirm_and_execute",
        ]
        assert option["capability_resolution_binding_ref"] == binding.content_digest

        selected = client.post(
            f"/notebooks/{notebook_id}/options/{option['option_id']}/decision",
            params=params,
            json={"decision": "selected", "actor": "ui"},
        )
        assert selected.status_code == 200, selected.text

        confirmed = client.post(
            f"/notebooks/{notebook_id}/options/{option['option_id']}/confirm",
            params=params,
            json={
                "option_revision": option["option_revision"],
                "proposal_id": option["typed_proposal_id"],
                "proposal_revision": option["typed_proposal_revision"],
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        # Dataset-backed Drafts retain the genesis source mode; the model node
        # carries the canonical custom capability identity below.
        assert confirmed.json()["materialization"]["draft_execution_mode"] == "genesis"
        model_node = next(
            node
            for node in confirmed.json()["draft"]["graph"]["nodes"]
            if node["node_type"] == "model"
        )
        assert model_node["model_type"] == "custom"
        assert confirmed.json()["draft"]["notebook_provenance"][
            "capability_resolution_binding_ref"
        ] == binding.content_digest

        blocked = client.post(
            f"/notebooks/{notebook_id}/options/{option['option_id']}/confirm-and-execute",
            params=params,
            json={
                "option_revision": option["option_revision"],
                "proposal_id": option["typed_proposal_id"],
                "proposal_revision": option["typed_proposal_revision"],
            },
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error"]["code"] == "OPTION_EXECUTION_GATEWAY_UNAVAILABLE"
        assert list((project / "runs").iterdir()) == []
    finally:
        configure_capability_factory_runtime(None)


def test_model_custom_route_runs_generated_adapter_through_local_experimental_gateway(
    tmp_path: Path, monkeypatch
) -> None:
    """Exercise the complete user-confirmed local custom capability path."""

    import sys
    from datetime import datetime, timezone

    import pytest

    if sys.platform != "darwin":
        pytest.skip("real local Darwin containment is only available on macOS")

    from workbench.agent.context_compiler import (
        freshness_dependency_fingerprint,
        generation_context_hash,
    )
    from workbench.app import (
        configure_capability_factory_runtime,
        configure_local_experimental_capability_runtime,
    )
    from workbench.capability_factory.adapter_contract import (
        AdapterContract,
        AdapterSourceGenerator,
        PythonAdapterExecutionBinding,
        PythonAdapterExecutionGateway,
    )
    from workbench.capability_factory.control import ExecutionControlStore
    from workbench.capability_factory.custom_dispatcher import CustomCapabilityDispatcher
    from workbench.capability_factory.dependency_service import DependencyService
    from workbench.capability_factory.execution_authorization import (
        OptionExecutionAuthorizationStore,
    )
    from workbench.capability_factory.execution_receipt import CapabilityDispatchCoordinator
    from workbench.capability_factory.notebook_bridge import (
        CapabilityExecutionCompletion,
        NotebookCapabilityBridge,
        NotebookCapabilityDispatchBinding,
    )
    from workbench.capability_factory.notebook_catalog import CapabilityBindingCatalog
    from workbench.capability_factory.supervisor import DurableSupervisorStore
    from workbench.lineage.run_family import ensure_run_family_binding
    from workbench.native_containment.broker import ContainmentBroker
    from workbench.native_containment.contracts import ContainmentRequest, ResourceBudget
    from workbench.native_containment.executor_darwin import DarwinExperimentalExecutor
    from workbench.native_containment.platform_darwin import DarwinCanaryHarness
    from workbench.native_containment.policy import ContainmentPolicy
    from workbench.agent.notebook import OptionDraft, TypedProposal

    from test_capability_custom_dispatcher import _records
    from test_capability_execution_receipt import (
        _expectations,
        _store_subjects,
        _terminal_reconciliation,
        _termination_proof,
    )

    project = make_project(tmp_path, name="project.alpha")
    upload_sha = store_upload_bytes(
        project, b"outcome,predictor\n1,2\n2,3\n", filename="data.csv"
    )
    implementation, adapter_template, binding_template = _records()
    source = AdapterSourceGenerator().generate(
        implementation=implementation,
        provider=lambda _context: (
            "def adapter(document):\n"
            "    value = document['payload']['value']\n"
            "    return {'status': 'ok', 'value': value}\n"
        ),
        output_root=(tmp_path / "generated-adapter").resolve(),
    )
    adapter = AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.route.local",
        revision=1,
        entrypoint_ref=source.entrypoint_ref,
        operations=("fit", "predict", "model.custom"),
        consumer_support=dict(adapter_template.consumer_support),
    )
    binding = replace(
        binding_template,
        adapter_ref=adapter.content_digest,
        scope_ref="project.alpha",
    )
    catalog = CapabilityBindingCatalog(verifier=lambda _binding: None)
    catalog.register(
        "custom.route.adapter",
        binding,
        planner_projection={
            "key": "custom.route.adapter",
            "label": "Local experimental generated adapter",
            "model_type": "custom.route.adapter",
            "notebook_proposal_adapters": ["model.custom"],
            "params": [],
            "artifact_types": {"custom.route.result": "custom_json"},
        },
    )
    now = datetime.now(timezone.utc)
    requests: dict[str, ContainmentRequest] = {}
    reports: dict[str, object] = {}
    result_paths: list[Path] = []
    dependency_checks: list[str] = []
    run_ids: list[str] = []
    dependency_service = DependencyService()
    dependency_service.assert_execution_bundle = (  # type: ignore[method-assign]
        lambda bundle_ref: dependency_checks.append(bundle_ref)
    )

    policy = ContainmentPolicy(
        profile_id="darwin-seatbelt-experimental-v1",
        filesystem_mode="sealed_readonly",
        network_mode="disabled",
        process_mode="isolated",
        inherited_descriptors=False,
        dependency_tree_writable=False,
        environment_allowlist={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        locale="C.UTF-8",
        thread_count=1,
        budget=ResourceBudget(10_000, 8_000, 64 * 1024 * 1024, 8, 1_000_000, 100_000),
        allow_weaker_fallback=False,
        resource_enforcement="observed_memory",
    )
    canary = DarwinCanaryHarness(
        python_executable="/usr/bin/python3",
        backend_executable="/usr/bin/sandbox-exec",
    ).run(policy)
    if canary.status != "supported":
        pytest.skip(f"Darwin experimental canary unavailable: {canary.reason_code}")

    def binding_factory(**kwargs):
        authorization = kwargs["authorization"]
        draft = kwargs["draft"]
        notebook = NotebookService(project).get_notebook(kwargs["notebook_id"])
        from workbench.projects import create_run

        run = create_run(project, mode="custom")
        ensure_run_family_binding(
            project,
            run.root,
            rerun_of=None,
            created_by="local_experimental_capability_factory",
            run_family_id=notebook.run_family_id,
        )
        run_ids.append(run.run_id)
        model = next(
            node for node in draft["graph"]["nodes"] if node["node_type"] == "model"
        )
        parameters = dict(model["params"]["parameters"])
        intent = NotebookCapabilityBridge.prepare_intent(
            authorization=authorization,
            run_id=run.run_id,
            input_contract_ref=authorization.artifact_contract_ref,
            output_contract_ref="a" * 64,
            host_containment_ref="b" * 64,
            host_validity_revision=1,
            bundle_validity_revision=1,
            evidence_validity_revision=1,
            admission_validity_revision=1,
        ).intent
        plan = CustomCapabilityDispatcher.prepare(
            intent=intent,
            binding=binding,
            adapter=adapter,
            implementation=implementation,
            operation_id="model.custom",
            requested_consumers=("notebook_option_planner", "report_projection"),
        )
        auth_store = OptionExecutionAuthorizationStore(project, clock=lambda: now)
        control_store = ExecutionControlStore(clock=lambda: now)
        _store_subjects(control_store, intent, authorization.authorization_id, now)
        supervisor = DurableSupervisorStore(project)
        coordinator = CapabilityDispatchCoordinator(
            authorization_store=auth_store,
            control_store=control_store,
            supervisor_store=supervisor,
        )
        input_root = (tmp_path / "adapter-input").resolve()
        output_root = (tmp_path / "adapter-output").resolve()
        adapter_binding = PythonAdapterExecutionBinding(
            bundle_ref=intent.bundle_ref,
            output_namespace_ref="c" * 64,
            adapter=adapter,
            source_artifact=source,
            operation="fit",
            payload=parameters,
            input_root=input_root,
            output_root=output_root,
            interpreter=Path("/usr/bin/python3"),
        )
        result_paths.append(adapter_binding.result_path)
        darwin_executor = DarwinExperimentalExecutor(
            resolver=adapter_binding.prepare,
            assessment_ref=binding.assessment_ref,
            backend_executable="/usr/bin/sandbox-exec",
        )
        adapter_executor = PythonAdapterExecutionGateway(
            binding=adapter_binding,
            executor=darwin_executor,
        )

        class CapturingExecutor:
            def spawn(self, request, current_policy, current_canary):
                return adapter_executor.spawn(request, current_policy, current_canary)

            def terminate(self, spawned):
                return adapter_executor.terminate(spawned)

            def __call__(self, request, current_policy, current_canary):
                report = adapter_executor(request, current_policy, current_canary)
                reports[request.attempt_id] = report
                return report

        executor = CapturingExecutor()

        def request_factory(attempt_id: str) -> ContainmentRequest:
            request = ContainmentRequest(
                request_id="request.route.custom",
                attempt_id=attempt_id,
                intent_digest=intent.content_digest,
                input_bundle_ref=intent.bundle_ref,
                output_namespace_ref="c" * 64,
                policy_digest=policy.content_digest,
                harness_digest="d" * 64,
            )
            requests[attempt_id] = request
            return request

        def completion_factory(*, result, receipt, binding):
            from workbench.capability_factory.execution_receipt import (
                validate_artifact_contract_v11,
            )
            from workbench.contracts.agent.notebook_option import (
                ArtifactContract,
                ExpectedArtifact,
            )

            payload = adapter_binding.read_result(
                requests[receipt.attempt_id], reports[receipt.attempt_id]
            )
            assert payload == {"status": "ok", "value": 42}
            attempt = binding.coordinator.supervisor_store.read(receipt.attempt_id)
            artifact = {
                "artifact_id": "custom.route.result",
                "artifact_type": "custom_json",
                "step": "fit",
                "lineage_ref": "e" * 64,
                "consumer_projection_ref": authorization.consumer_projection_ref,
                "run_attempt_ref": attempt.content_digest,
                "option_revision_ref": authorization.artifact_contract_ref,
                "artifact_ref": "f" * 64,
                "facet": "parameters",
            }
            validation = validate_artifact_contract_v11(
                ArtifactContract(
                    expected=(
                        ExpectedArtifact(
                            "custom.route.result", "custom_json", step="fit"
                        ),
                    )
                ),
                [artifact],
                option_revision_ref=authorization.artifact_contract_ref,
                run_attempt_ref=attempt.content_digest,
                consumer_projection_ref=authorization.consumer_projection_ref,
                lineage_ref="e" * 64,
                allowed_facets=("parameters",),
            )
            return CapabilityExecutionCompletion(
                artifact_validation=validation,
                object_graph_ref="1" * 64,
                termination_proof=_termination_proof(
                    attempt, authorization.authorization_id
                ),
                terminal_reconciliation=_terminal_reconciliation(
                    attempt,
                    authorization.authorization_id,
                    validation,
                    "1" * 64,
                ),
            )

        return NotebookCapabilityDispatchBinding(
            intent=intent,
            plan=plan,
            policy=policy,
            canary=canary,
            expectations=_expectations(intent, authorization.authorization_id),
            request_factory=request_factory,
            coordinator=coordinator,
            broker=ContainmentBroker(
                host_assessor=lambda _policy: canary,
                executor=executor,
                report_verifier=lambda **_kwargs: "2" * 64,
                require_authenticated_reports=True,
            ),
            executor=executor,
            owner_id="supervisor.route.custom",
            lease_seconds=60,
            attempt_id="attempt.route.custom",
            lease_epoch=1,
            executor_idempotency_key="executor-route-custom",
            reservation_id="reservation.route.custom",
            reservation_idempotency_key="reservation-route-custom",
            now=now,
            completion_factory=completion_factory,
        )

    class FakePlanningAgent:
        def plan(self, *, context, initial_evidence):
            del initial_evidence
            option = OptionDraft(
                rank=1,
                rationale="The server-admitted generated adapter is the selected local experimental path.",
                assumptions=("the controlled local fixture is representative",),
                proposal=TypedProposal(
                    proposal_id="proposal_route_custom",
                    operation_id="model.custom",
                    target={"dataset_source_id": upload_sha},
                    preconditions={
                        "context_version": "node-operation-context/v1",
                        "context_fingerprint": context.context_id,
                        "owner_resolution": "dataset_projection",
                    },
                    changes={
                        "operation": "fit",
                        "parameters": {"value": 42},
                        "consumer_slots": [
                            "notebook_option_planner",
                            "report_projection",
                        ],
                    },
                ),
                expected_artifacts=(
                    ExpectedArtifact(
                        artifact_id="custom.route.result",
                        artifact_type="custom_json",
                        required=True,
                        count=1,
                        step="fit",
                    ),
                ),
                capability_id="custom.route.adapter",
                option_id="opt_route_custom",
            )
            decision = RecommendationDecision(
                recommendation_decision_id="rec_route_custom",
                batch_id="batch_route_custom",
                generation_context_hash=generation_context_hash(context),
                freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
                evidence_pack_hashes=(),
                comparison_protocol_refs=(),
                candidate_option_ids=(option.option_id,),
                outcome="recommended",
                recommended_option_id=option.option_id,
                reason_refs=(),
            )
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
    runtime = configure_local_experimental_capability_runtime(
        authority_id="authority.local.experimental",
        catalog=catalog,
        dependency_service=dependency_service,
        binding_factory=binding_factory,
        enable=True,
    )
    try:
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
        proposed = client.post(
            f"/notebooks/{notebook_id}/options/propose",
            params=params,
            json={"count": 1},
        )
        assert proposed.status_code == 200, proposed.text
        option = proposed.json()["options"][0]
        assert option["risk_level"] == "high"
        assert option["execution_modes"] == [
            "materialize_only",
            "experimental_confirm_and_execute",
        ]
        selected = client.post(
            f"/notebooks/{notebook_id}/options/{option['option_id']}/decision",
            params=params,
            json={"decision": "selected", "actor": "ui"},
        )
        assert selected.status_code == 200, selected.text
        executed = client.post(
            f"/notebooks/{notebook_id}/options/{option['option_id']}/confirm-and-execute",
            params=params,
            json={
                "option_revision": option["option_revision"],
                "proposal_id": option["typed_proposal_id"],
                "proposal_revision": option["typed_proposal_revision"],
            },
        )
        assert executed.status_code == 200, executed.text
        assert executed.json()["dispatch"]["status"] == "completed"
        assert dependency_checks == [binding.dependency_bundle_ref]
        assert result_paths and result_paths[0].read_text(encoding="utf-8") == (
            '{"status":"ok","value":42}'
        )
        listed = client.get(
            f"/notebooks/{notebook_id}/options", params=params
        )
        assert listed.status_code == 200, listed.text
        result = listed.json()["execution_results"][option["option_id"]]
        assert result["committed"] is True
        assert result["capability_execution"]["dispatch_status"] == "completed"
        assert run_ids == [executed.json()["dispatch"]["run_id"]]
        assert result["capability_execution"]["object_graph_ref"] == "1" * 64
        assert runtime.public_status()["execution_gateway_configured"] is True
    finally:
        configure_capability_factory_runtime(None)


def test_notebook_route_uses_server_owned_catalog_for_v12_options(
    tmp_path: Path, monkeypatch
) -> None:
    from test_notebook_capability_binding import _binding_and_verifier
    from workbench.agent.context_compiler import (
        freshness_dependency_fingerprint,
        generation_context_hash,
    )
    from workbench.agent.notebook import OptionDraft, TypedProposal
    from workbench.capability_factory.notebook_catalog import CapabilityBindingCatalog

    project = make_project(tmp_path, name="project.alpha")
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

    binding, verifier = _binding_and_verifier()
    catalog = CapabilityBindingCatalog(verifier=verifier)
    catalog.register("ols", binding)

    option = OptionDraft(
        rank=1,
        rationale="The admitted capability is available for this notebook.",
        assumptions=("the capability admission remains current",),
        proposal=TypedProposal(
            proposal_id="p_http_registered",
            operation_id="model.genesis",
            target={"dataset_source_id": upload_sha},
            preconditions={
                "context_version": "notebook-planning-context/v1",
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
            ExpectedArtifact("ols_1", "model_result", required=True, count=1),
        ),
        capability_id="ols",
        option_id="opt_http_registered",
        evidence_refs=(),
        comparative_claims=(),
    )

    class FakePlanningAgent:
        def plan(self, *, context, initial_evidence):
            del initial_evidence
            planned_option = replace(
                option,
                proposal=replace(
                    option.proposal,
                    preconditions={
                        **option.proposal.preconditions,
                        "context_fingerprint": context.context_id,
                    },
                ),
            )
            decision = RecommendationDecision(
                recommendation_decision_id="rec_http_registered",
                batch_id="batch_http_registered",
                generation_context_hash=generation_context_hash(context),
                freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
                evidence_pack_hashes=(),
                comparison_protocol_refs=(),
                candidate_option_ids=(planned_option.option_id,),
                outcome="recommended",
                recommended_option_id=planned_option.option_id,
                reason_refs=(),
            )
            return SimpleNamespace(
                option_drafts=(
                    replace(
                        planned_option,
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
    configure_notebook_capability_bindings(catalog)
    try:
        response = client.post(
            f"/notebooks/{notebook_id}/options/propose",
            params=params,
            json={"count": 1},
        )
        assert response.status_code == 200, response.text
        [persisted] = response.json()["options"]
        assert persisted["contract_version"] == "1.2"
        assert persisted["capability_resolution_binding_ref"] == binding.content_digest
        assert persisted["execution_modes"] == ["materialize_only"]
        parsed = NotebookOptionRevisionV12.from_dict(persisted)
        assert parsed.execution_allowed is False
        assert parsed.capability_resolution_binding_ref == binding.content_digest
        listed = client.get(
            f"/notebooks/{notebook_id}/options",
            params=params,
        )
        assert listed.status_code == 200, listed.text
        [reloaded] = listed.json()["options"]
        assert reloaded["contract_version"] == "1.2"
        assert reloaded["capability_resolution_binding_ref"] == binding.content_digest
    finally:
        configure_notebook_capability_bindings(None)


def test_notebook_route_rejects_invalid_server_catalog_configuration(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    client = TestClient(app)
    app.state.notebook_capability_bindings = object()
    try:
        response = client.post(
            "/notebooks",
            params={"project_root": str(project)},
            json={"title": "invalid provider", "created_by": "test"},
        )
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "NOTEBOOK_CAPABILITY_BINDING_PROVIDER_INVALID"
    finally:
        configure_notebook_capability_bindings(None)


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
    evidence_pack = DataEvidencePackV1(
        source_id="agent:bounded",
        records=(
            EvidenceRecord(
                evidence_id="evidence:time",
                inspection_id="time_index.v1",
                source_refs=("time_index:run_001",),
                protocol_version="time/v1",
                status="completed",
                result_hash="sha256:time-result",
            ),
        ),
    )

    class FakePlanningAgent:
        def plan(self, *, context, initial_evidence):
            del context, initial_evidence
            return SimpleNamespace(
                option_drafts=(replanned,), decision=decision, evidence_pack=evidence_pack
            )

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
