from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.domain_memory.local_runtime import bootstrap_local_domain_memory_runtime
from workbench.domain_memory.scope import MemoryScope
from workbench.http.memory_routes import router


def _seed_active_memory(runtime) -> str:
    from workbench.domain_memory.contracts import (
        ApplicabilityPredicate,
        DomainMemoryApprovalRecord,
        DomainMemoryContentRevision,
        DomainMemoryValidityRecord,
        SourceSummaryRef,
    )
    from workbench.domain_memory.redaction import build_redacted_summary_snapshot
    from workbench.domain_memory.source_access import SourceAccessBinding, SourceAccessValidityRecord

    scope = runtime.scope_resolver.global_scope
    snapshot = build_redacted_summary_snapshot(
        summary_text="A bounded reviewed summary.",
        source_ref="source-1",
        source_kind="trace_summary",
        redaction_subject="subject-1",
    )
    binding = SourceAccessBinding(
        binding_ref="binding-1",
        scope=scope,
        summary_snapshot_ref=snapshot.summary_snapshot_ref,
        summary_snapshot_hash=snapshot.summary_snapshot_hash,
        summary_schema_version=snapshot.summary_schema_version,
        redaction_assessment_ref=snapshot.redaction_assessment_ref,
        redaction_subject_hash=snapshot.redaction_subject_hash,
        source_kind=snapshot.source_kind,
        source_ref=snapshot.source_ref,
        source_namespace_id=scope.namespace_id,
        source_profile_id=scope.profile_id,
        source_owner_id=scope.owner_id,
        source_organization_id=scope.organization_id,
        grant_ref="grant-1",
        source_tombstone_ref=None,
    )
    store = runtime.service.store
    store.append_binding(binding)
    store.append_source_validity(SourceAccessValidityRecord(
        binding_ref=binding.binding_ref,
        validity_revision=1,
        control_sequence=1,
        state="valid",
        effective_at="2026-08-01T00:00:00Z",
        reason="approved",
        authority="local-user",
        evidence_refs=("review-1",),
    ))
    content = DomainMemoryContentRevision(
        memory_id="memory-delete-me",
        revision=1,
        scope=scope,
        domain_tags=("domain-a",),
        memory_kind="workflow_lesson",
        applicability_predicates=(ApplicabilityPredicate("analysis_family", "equals", "ols"),),
        compact_lesson="Inspect the registered assumption before fitting.",
        recommended_effect_kind="assumption_check_hint",
        recommended_target_refs=("check-1",),
        source_summary_refs=(SourceSummaryRef("project-1", snapshot.summary_snapshot_ref, snapshot.summary_snapshot_hash, snapshot.summary_schema_version, binding.binding_ref),),
        evidence_status="observed_repeatedly",
        review_after="2030-01-01T00:00:00Z",
        supersedes_revision=None,
        conflicts_with=(),
        created_by="local-user",
    )
    store.append_content(content)
    approval = DomainMemoryApprovalRecord(
        approval_ref="approval-delete-me",
        memory_id=content.memory_id,
        content_revision=content.revision,
        content_hash=content.content_hash,
        scope=scope,
        approver_id="local-user",
        approved_at="2026-08-01T00:00:00Z",
        expected_current_approval_ref=None,
        supersedes_approval_ref=None,
        grant_control_sequence=1,
    )
    store.append_approval(approval)
    store.append_validity(DomainMemoryValidityRecord(
        approval_ref=approval.approval_ref,
        memory_id=content.memory_id,
        content_revision=content.revision,
        validity_revision=1,
        control_sequence=1,
        state="active",
        effective_at="2026-08-01T00:00:00Z",
        reason="approved",
        authority="local-user",
        evidence_refs=("review-1",),
    ))
    return content.memory_id


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _client(tmp_path: Path) -> TestClient:
    project = tmp_path / "project"
    project.mkdir()
    app = FastAPI()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")
    app.state.domain_memory_runtime = runtime
    app.state.domain_memory_service = runtime.service
    app.include_router(router)
    return TestClient(app)


def test_router_is_explicitly_unmounted_from_product_app_and_has_no_run_route() -> None:
    paths = {route.path for route in router.routes}
    assert "/domain-memory/retrieve" in paths
    assert "/domain-memory/candidates" in paths
    assert all("run" not in path for path in paths)


def test_retrieve_route_defaults_to_not_used(tmp_path: Path) -> None:
    project = tmp_path / "project"
    response = _client(tmp_path).post(
        "/domain-memory/retrieve",
        params={"project_root": str(project)},
        json={"facts": {}},
    )
    assert response.status_code == 200
    assert response.json()["reason"] == "DOMAIN_MEMORY_DISABLED"


def test_route_rejects_unknown_fields(tmp_path: Path) -> None:
    project = tmp_path / "project"
    response = _client(tmp_path).post(
        "/domain-memory/retrieve",
        params={"project_root": str(project)},
        json={"execute": True},
    )
    assert response.status_code == 422


def test_retrieve_uses_persisted_project_opt_in_not_a_request_body_switch(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")
    app = FastAPI()
    app.state.domain_memory_runtime = runtime
    app.state.domain_memory_service = runtime.service
    app.include_router(router)
    client = TestClient(app)

    confirmation = client.post(
        "/domain-memory/settings/confirmations",
        params={"project_root": str(project)},
        json={"action": "enable_project_library", "expected_revision": 0, "target_refs": []},
    )
    enabled = client.put(
        "/domain-memory/settings/project",
        params={"project_root": str(project)},
        json={
            "setting": "library_enabled",
            "enabled": True,
            "expected_revision": 0,
            "confirmation_receipt": confirmation.json()["receipt"],
        },
    )
    assert enabled.status_code == 200

    response = client.post(
        "/domain-memory/retrieve",
        params={"project_root": str(project)},
        json={"facts": {}, "preferences": {"cross_project_domain_memory_use": False}},
    )
    assert response.status_code == 422

    response = client.post(
        "/domain-memory/retrieve",
        params={"project_root": str(project)},
        json={"facts": {}},
    )
    assert response.status_code == 200
    assert response.json()["reason"] == "no_eligible_memory"


def test_local_settings_are_server_scoped_and_require_a_one_time_confirmation(tmp_path: Path) -> None:
    project = tmp_path / "current-project"
    project.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")
    app = FastAPI()
    app.state.domain_memory_runtime = runtime
    app.state.domain_memory_service = runtime.service
    app.state.domain_memory_review_service = runtime.review_service
    app.include_router(router)
    client = TestClient(app)

    initial = client.get("/domain-memory/settings", params={"project_root": str(project)})
    assert initial.status_code == 200
    assert initial.json()["global"]["library_enabled"] is False
    assert initial.json()["project"]["library_enabled"] is False
    assert initial.json()["project"]["inherit_global"] is False
    assert initial.json()["project"]["candidate_generation_enabled"] is False

    issued = client.post(
        "/domain-memory/settings/confirmations",
        params={"project_root": str(project)},
        json={"action": "enable_global_library", "expected_revision": 0, "target_refs": []},
    )
    assert issued.status_code == 200
    receipt = issued.json()["receipt"]

    enabled = client.put(
        "/domain-memory/settings/global",
        params={"project_root": str(project)},
        json={"library_enabled": True, "expected_revision": 0, "confirmation_receipt": receipt},
    )
    assert enabled.status_code == 200
    assert enabled.json()["global"]["library_enabled"] is True

    replay = client.put(
        "/domain-memory/settings/global",
        params={"project_root": str(project)},
        json={"library_enabled": True, "expected_revision": 0, "confirmation_receipt": receipt},
    )
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "DOMAIN_MEMORY_CONFIRMATION_INVALID"


def test_project_settings_cannot_be_written_with_a_confirmation_for_another_project(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")
    app = FastAPI()
    app.state.domain_memory_runtime = runtime
    app.state.domain_memory_service = runtime.service
    app.include_router(router)
    client = TestClient(app)

    issued = client.post(
        "/domain-memory/settings/confirmations",
        params={"project_root": str(first)},
        json={"action": "enable_project_library", "expected_revision": 0, "target_refs": []},
    )
    assert issued.status_code == 200

    response = client.put(
        "/domain-memory/settings/project",
        params={"project_root": str(second)},
        json={
            "setting": "library_enabled",
            "enabled": True,
            "expected_revision": 0,
            "confirmation_receipt": issued.json()["receipt"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DOMAIN_MEMORY_CONFIRMATION_INVALID"


def test_enabled_project_library_fails_closed_when_its_store_is_corrupt(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")
    app = FastAPI()
    app.state.domain_memory_runtime = runtime
    app.state.domain_memory_service = runtime.service
    app.include_router(router)
    client = TestClient(app)

    confirmation = client.post(
        "/domain-memory/settings/confirmations",
        params={"project_root": str(project)},
        json={"action": "enable_project_library", "expected_revision": 0, "target_refs": []},
    )
    enabled = client.put(
        "/domain-memory/settings/project",
        params={"project_root": str(project)},
        json={
            "setting": "library_enabled",
            "enabled": True,
            "expected_revision": 0,
            "confirmation_receipt": confirmation.json()["receipt"],
        },
    )
    assert enabled.status_code == 200
    runtime.service_for_project(project).store.journal_path.write_text("not valid json\n", encoding="utf-8")

    response = client.get("/domain-memory/libraries/project", params={"project_root": str(project)})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DOMAIN_MEMORY_LIBRARY_UNAVAILABLE"

    retrieval = client.post(
        "/domain-memory/retrieve",
        params={"project_root": str(project)},
        json={"facts": {}},
    )
    assert retrieval.status_code == 503
    assert retrieval.json()["detail"]["code"] == "DOMAIN_MEMORY_UNAVAILABLE"


def test_archive_removes_memory_from_future_use_without_erasing_its_provenance(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")
    memory_id = _seed_active_memory(runtime)
    app = FastAPI()
    app.state.domain_memory_runtime = runtime
    app.state.domain_memory_service = runtime.service
    app.state.domain_memory_review_service = runtime.review_service
    app.include_router(router)
    client = TestClient(app)

    library = client.get("/domain-memory/libraries/global", params={"project_root": str(project)})
    assert library.status_code == 200
    assert library.json()["entries"] == [{
        "memory_id": memory_id,
        "revision": 1,
        "state": "active",
        "validity_revision": 1,
        "memory_kind": "workflow_lesson",
        "domain_tags": ["domain-a"],
        "compact_lesson": "Inspect the registered assumption before fitting.",
        "apply_mode": "inform_only",
    }]

    confirmation = client.post(
        "/domain-memory/libraries/global/archive/confirmations",
        params={"project_root": str(project)},
        json={"memory_ids": [memory_id]},
    )
    assert confirmation.status_code == 200
    archived = client.post(
        "/domain-memory/libraries/global/archive",
        params={"project_root": str(project)},
        json={"memory_ids": [memory_id], "confirmation_receipt": confirmation.json()["receipt"]},
    )
    assert archived.status_code == 200
    assert archived.json()["archived_count"] == 1
    assert runtime.service.store.active_contents() == ()
    assert runtime.service.store.get_content(memory_id, 1).compact_lesson.startswith("Inspect")

    after = client.get("/domain-memory/libraries/global", params={"project_root": str(project)})
    assert after.json()["entries"][0]["state"] == "archived"
