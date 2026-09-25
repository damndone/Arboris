from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from workbench.canonical import canonical_json_v1
from workbench.agent.workflow import (
    MAX_WORKFLOW_STATE_BYTES,
    UnsupportedVersionError,
    WorkflowExecutionState,
    WorkflowStateStore,
    WorkflowStepState,
)
from workbench.agent.workflow_runtime import (
    bootstrap_local_workflow_host,
    collect_post_estimation_results,
    issue_server_evidence_port,
)
from workbench.evidence.authority import (
    EvidenceAuthorityRequestV1,
    build_authority_request,
    issue_host_proof,
    validate_host_proof,
)
from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1
from workbench.services.local_host_bootstrap import (
    LocalServerIdentityV1,
    bootstrap_local_workbench_host,
)
from workbench.http.notebook_routes import _notebook_cutover_project_ref


def test_local_bootstrap_owns_empty_process_local_provider_authority(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta
    from workbench.services.provider_egress import ProviderEgressAuthorityV1, ProviderEgressError

    def assemble(host_bundle):
        authority = host_bundle.provider_egress_authority
        authority.classify(authority_handle=host_bundle.evidence_authority,
            source_ref="source:bootstrap-fixture", source_digest="a" * 64,
            category="user_text", sensitivity="public")
        return authority.mint_trusted_assembly(authority_handle=host_bundle.evidence_authority,
            project_ref="project:egress-bootstrap", payload={"synthetic": "bootstrap"},
            sources=(("source:bootstrap-fixture", "a" * 64, "user_text"),), admitted_rows=0)

    scope = dict(project_ref="project:egress-bootstrap", provider_ref="provider:test",
                 purpose_ref="purpose:analysis")

    bundle = bootstrap_local_workbench_host(
        project_root=tmp_path, project_ref="project:egress-bootstrap",
        session_ref="session:egress-bootstrap", actor_ref="principal:egress-bootstrap",
    )
    try:
        egress = bundle.provider_egress_authority
        assert type(egress) is ProviderEgressAuthorityV1
        # A host authority is not itself permission to send: no grants are
        # implicitly installed by local bootstrap or copied from API settings.
        assembly = assemble(bundle)
        with pytest.raises(ProviderEgressError, match="EGRESS_GRANT_REQUIRED"):
            egress.prepare(assembly=assembly, **scope)
        egress.grant(authority_handle=bundle.evidence_authority,
            provider_ref="provider:test", purpose_ref="purpose:analysis",
            categories=("user_text",), allowed_sensitivity=("public",),
            expires_at=datetime.now(UTC) + timedelta(minutes=1))
        admitted = egress.prepare(assembly=assembly, **scope)
        egress.require(admitted, payload={"synthetic": "bootstrap"}, **scope)
    finally:
        bundle.close()
    with pytest.raises(ProviderEgressError, match="EGRESS_HOST_AUTHORITY_REQUIRED"):
        egress.grant(authority_handle=bundle.evidence_authority,
            provider_ref="provider:test", purpose_ref="purpose:analysis",
            categories=("user_text",), allowed_sensitivity=("public",),
            expires_at=datetime.now(UTC) + timedelta(minutes=1))
    restarted = bootstrap_local_workbench_host(
        project_root=tmp_path, project_ref="project:egress-bootstrap",
        session_ref="session:egress-bootstrap", actor_ref="principal:egress-bootstrap",
    )
    try:
        assert restarted.identity.server_id == bundle.identity.server_id
        with pytest.raises(ProviderEgressError, match="EGRESS_GRANT_REQUIRED"):
            restarted.provider_egress_authority.prepare(assembly=assemble(restarted), **scope)
    finally:
        restarted.close()


def test_old_workflow_state_is_rejected_with_one_stable_version_code(tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path, "workflow-old-state")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "record_type": "workflow_state",
                "workflow_id": "workflow-old-state",
                "plan_fingerprint": "sha256:old",
                "status": "completed",
                "steps": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(UnsupportedVersionError) as exc_info:
        store.current()

    assert exc_info.value.code == "UNSUPPORTED_VERSION"


def test_new_workflow_state_round_trips_with_explicit_schema_version(tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path, "workflow-new-state")
    state = WorkflowExecutionState(
        workflow_id="workflow-new-state",
        plan_fingerprint="sha256:new",
        status="completed",
        project_ref="project:resume",
        session_ref="session:resume",
        model_branch_ids={"model": ("branch:m1", "branch:m2")},
        steps={
            "step": WorkflowStepState(
                step_id="step",
                fingerprint="sha256:step",
                status="completed",
            )
        },
    )

    store.append(state)
    raw = json.loads(store.path.read_text(encoding="utf-8").splitlines()[-1])
    restored = store.current()

    assert raw["schema_version"] == "workflow-execution-state.v1.8.9"
    assert raw["project_ref"] == "project:resume"
    assert raw["session_ref"] == "session:resume"
    assert raw["model_branch_ids"] == {"model": ["branch:m1", "branch:m2"]}
    assert restored is not None
    assert restored.workflow_id == state.workflow_id
    assert restored.project_ref == state.project_ref
    assert restored.session_ref == state.session_ref
    assert restored.model_branch_ids == state.model_branch_ids


def test_new_process_can_resume_local_state_from_the_persisted_host_bootstrap(
    tmp_path: Path,
) -> None:
    workflow_id = "workflow-subprocess-resume"
    store = WorkflowStateStore(tmp_path, workflow_id)
    store.append(
        WorkflowExecutionState(
            workflow_id=workflow_id,
            plan_fingerprint="sha256:cross-process",
            status="running",
            steps={
                "step": WorkflowStepState(
                    step_id="step",
                    fingerprint="sha256:step",
                    status="completed",
                    artifact_ids=("artifact:cross-process",),
                )
            },
        )
    )
    store.close()

    backend_root = Path(__file__).resolve().parents[1] / "backend"
    script = (
        "from pathlib import Path; "
        "import sys; "
        "from workbench.agent.workflow import WorkflowStateStore; "
        "state = WorkflowStateStore(Path(sys.argv[1]), sys.argv[2]).current(); "
        "assert state is not None and state.steps['step'].artifact_ids == ('artifact:cross-process',); "
        "print(state.workflow_id)"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend_root)
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), workflow_id],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == workflow_id


def test_workflow_state_store_rejects_unbounded_state_files(tmp_path: Path) -> None:
    store = WorkflowStateStore(tmp_path, "workflow-oversized-state")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_bytes(b"{" + b"x" * MAX_WORKFLOW_STATE_BYTES)

    with pytest.raises(Exception, match="WORKFLOW_STATE_TOO_LARGE"):
        store.current()


def test_local_workflow_host_authority_is_reusable_after_rebootstrap(tmp_path: Path) -> None:
    first = bootstrap_local_workflow_host(tmp_path)
    first_port = issue_server_evidence_port(tmp_path)
    first_authority = first_port._authority_id
    first_port.close()

    second = bootstrap_local_workflow_host(tmp_path)
    second_port = issue_server_evidence_port(tmp_path)
    try:
        assert second.authority_id == first.authority_id
        assert second_port._authority_id == first_authority
    finally:
        second_port.close()


def test_local_server_identity_and_report_owner_are_bound_to_project_session(tmp_path: Path) -> None:
    bundle = bootstrap_local_workbench_host(
        project_root=tmp_path,
        project_ref="project:local-first",
        session_ref="session:local-first",
        actor_ref="principal:local-first",
    )
    try:
        assert type(bundle.identity) is LocalServerIdentityV1
        assert bundle.identity.project_ref == "project:local-first"
        assert bundle.identity.session_ref == "session:local-first"
        assert bundle.identity.host_platform == "darwin"
        assert bundle.report_owner_factory._project_ref == "project:local-first"
        assert bundle.report_owner_factory._session_ref == "session:local-first"
        assert bundle.identity_resolver(
            None,
            "project:local-first",
            "session:local-first",
            None,
        ) == (
            "principal:local-first",
            "session:local-first",
            "project:local-first",
        )
    finally:
        bundle.close()

    persisted_identity = json.loads(
        (tmp_path / "workbench" / ".server-identity.v1").read_text(encoding="utf-8")
    )
    assert persisted_identity["authority_id"] == bundle.identity.authority_id
    second = bootstrap_local_workbench_host(
        project_root=tmp_path,
        project_ref="project:local-first",
        session_ref="session:local-first",
        actor_ref="principal:local-first",
    )
    try:
        assert second.identity.server_id == bundle.identity.server_id
        assert second.identity.authority_id == bundle.identity.authority_id
    finally:
        second.close()


def test_local_notebook_cutover_uses_bootstrapped_project_scope_not_directory_name(
    tmp_path: Path,
) -> None:
    bundle = bootstrap_local_workbench_host(
        project_root=tmp_path,
        project_ref="project:local-notebook-scope",
        session_ref="session:local-notebook-scope",
        actor_ref="principal:local-notebook-scope",
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                local_host_bundle=bundle,
            )
        )
    )
    notebook = SimpleNamespace(project_id=tmp_path.name)
    try:
        assert _notebook_cutover_project_ref(
            tmp_path,
            notebook,
            "project:local-notebook-scope",
            request=request,
        ) == "project:local-notebook-scope"
    finally:
        bundle.close()


def test_local_evidence_authority_rejects_copied_or_mismatched_request(tmp_path: Path) -> None:
    bundle = bootstrap_local_workbench_host(
        project_root=tmp_path,
        project_ref="project:authority",
        session_ref="session:authority",
        actor_ref="principal:authority",
    )
    try:
        request = build_authority_request(
            bundle.evidence_authority,
            purpose="evidence.registry",
            scope_ref="project:authority",
            subject_id=123,
            payload_digest="a" * 64,
        )
        proof = issue_host_proof(bundle.evidence_authority, request)
        validate_host_proof(bundle.evidence_authority, request, proof)

        forged = EvidenceAuthorityRequestV1(
            purpose=request.purpose,
            scope_ref=request.scope_ref,
            owner_pid=request.owner_pid,
            session_ref=request.session_ref,
            root_fd=request.root_fd,
            root_device=request.root_device,
            root_inode=request.root_inode,
            subject_id=request.subject_id,
            payload_digest="b" * 64,
        )
        with pytest.raises(Exception):
            validate_host_proof(bundle.evidence_authority, forged, proof)
    finally:
        bundle.close()


def test_local_evidence_owner_persists_a_scope_bound_backend_receipt(tmp_path: Path) -> None:
    bundle = bootstrap_local_workbench_host(
        project_root=tmp_path,
        project_ref="project:evidence-owner",
        session_ref="session:evidence-owner",
        actor_ref="principal:evidence-owner",
    )
    context = ProviderRuntimeContextV1(
        compilation_record_id="compilation-record:local",
        execution_instance_hash="a" * 64,
        actor_ref=bundle.identity.actor_ref,
        session_ref=bundle.identity.session_ref,
        project_ref=bundle.identity.project_ref,
        effect="read",
    )
    result = {"status": "completed", "source": "local-backend"}
    try:
        receipt = bundle.evidence_committer(context, result)
        assert receipt.matches_context(context)
        assert receipt.matches_result(context, result)
        persisted = (
            tmp_path
            / "workbench"
            / "evidence"
            / "agent-receipts"
            / f"{receipt.evidence_digest}.json"
        )
        assert persisted.is_file()
        assert json.loads(persisted.read_text(encoding="utf-8"))["authority_id"] == bundle.identity.authority_id

        forged = replace(context, project_ref="project:outside")
        with pytest.raises(ValueError, match="outside the server identity"):
            bundle.evidence_committer(forged, result)
    finally:
        bundle.close()


def test_local_report_owner_rehydrates_from_persisted_run_after_rebootstrap(tmp_path: Path) -> None:
    from workbench.services.report_evidence_owner_factory import (
        build_workflow_report_evidence_envelope,
        register_report_evidence_artifact,
    )
    from workbench.services.results_service import (
        ServerOwnedReportEvidencePersistenceV1,
        configure_report_evidence_persistence,
        register_report_evidence_owner,
    )

    run_id = "run-rehydrate-report-owner"
    model_run_id = "ols_1"
    run_root = tmp_path / "runs" / run_id
    run_root.mkdir(parents=True)
    (run_root / "artifacts_index.json").write_text(
        canonical_json_v1({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    bundle = bootstrap_local_workbench_host(
        project_root=tmp_path,
        project_ref="project:rehydrate",
        session_ref="session:rehydrate",
        actor_ref="principal:rehydrate",
    )
    try:
        envelope = build_workflow_report_evidence_envelope(
            run_id=run_id,
            model_run_id=model_run_id,
            upload_hash="a" * 64,
            primary_model_type="ols",
            regression_table={
                "models": [{"id": model_run_id}],
                "rows": [{"term": "x", "models": {model_run_id: {"estimate": 1.25}}}],
            },
            issue_dicts=[{"code": "CATEGORICAL_CANDIDATE", "severity": "INFO"}],
        )
        artifact_file_sha256 = bundle.report_owner_factory.report_evidence_file_sha256(envelope)
        production_receipt = bundle.report_owner_factory.issue_production_receipt(
            run_id=run_id,
            model_run_id=model_run_id,
            upload_hash="a" * 64,
        )
        owner = bundle.report_owner_factory.create_for_run(
            run_id=run_id,
            model_run_id=model_run_id,
            production_receipt=production_receipt,
            envelope=envelope,
            artifact_file_sha256=artifact_file_sha256,
        )
        bundle.report_owner_factory.write_report_evidence_file(
            owner=owner,
            production_receipt=production_receipt,
            envelope=envelope,
        )
        register_report_evidence_owner(owner)
        register_report_evidence_artifact(
            owner,
            run_root=run_root,
            path=run_root / "report_evidence.json",
            inputs=[f"model_results/{model_run_id}.json"],
        )
        # Report evidence has its own owner/projection contract.  Its index
        # row must not be mistaken for a model post-estimation artifact when
        # the workflow runtime collects typed model results.
        assert collect_post_estimation_results(tmp_path, run_id) == []
    finally:
        bundle.close()
        configure_report_evidence_persistence(None)

    rehydrated_bundle = bootstrap_local_workbench_host(
        project_root=tmp_path,
        project_ref="project:rehydrate",
        session_ref="session:rehydrate",
        actor_ref="principal:rehydrate",
    )
    try:
        rehydrated = rehydrated_bundle.report_owner_factory.rehydrate_for_run(run_id=run_id)
        assert type(rehydrated) is ServerOwnedReportEvidencePersistenceV1
        assert rehydrated.model_run_id == model_run_id
        assert rehydrated._canonical_report_wire()["facts"]
    finally:
        rehydrated_bundle.close()
        configure_report_evidence_persistence(None)
