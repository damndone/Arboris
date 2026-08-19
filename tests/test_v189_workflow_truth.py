"""P0 workflow truth contracts: typed outputs, lineage, admission, and resume."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import multiprocessing
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tests.workflow_fixtures import compile_fixture_workflow
from workbench.artifacts import initialize_artifact_index, register_artifact, sha256_file
from workbench.agent.workflow import (
    SERVER_COMPILER_AUTHORITY,
    WorkflowExecutionError,
    WorkflowExecutor,
    WorkflowStepResult,
    WorkflowStepState,
    _fingerprint,
)
from workbench.agent.workflow_runtime import (
    EvidencePersistencePort as EvidencePersistencePortClass,
    WorkflowHostEndpointV1,
    WorkflowAdmissionReceipt,
    _ReceiptGatedWorkflowExecutor,
    _append_evidence_record,
    _evidence_lock,
    _execute_model_joint_f_test,
    _execute_model_white_test,
    _execute_workflow_report,
    _persist_model_post_estimation_result,
    _PENDING_RUNTIME_OUTPUTS,
    _WRITE_CONTEXT,
    _write_runtime_artifact_bytes,
    _validate_persisted_model_branch,
    _model_artifact_id,
    _admit_workflow_host_endpoint_from_supervisor,
    issue_server_evidence_port,
)
from workbench.reporting import render_html_report



def _test_evidence_port(project_root):
    root = Path(project_root).expanduser().resolve()
    workflow_directory = root / "workbench" / "workflows"
    workflow_directory.mkdir(parents=True, exist_ok=True)
    endpoint_fd = os.open(
        workflow_directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        import workbench.agent.workflow_runtime as workflow_runtime

        endpoint = _admit_workflow_host_endpoint_from_supervisor(root, endpoint_fd)
        with patch.object(
            workflow_runtime,
            "_deployment_host_endpoint_from_supervisor",
            return_value=endpoint,
        ):
            return issue_server_evidence_port(root)
    finally:
        os.close(endpoint_fd)


EvidencePersistencePort = _test_evidence_port
from workbench.agent.post_estimation_registry import (
    POST_ESTIMATION_UNKNOWN_FAMILY,
    POST_ESTIMATION_UNKNOWN_OPERATION,
    POST_ESTIMATION_UNKNOWN_OUTPUT,
    POST_ESTIMATION_UNSUPPORTED_FAMILY,
    PostEstimationRegistryError,
    post_estimation_registry,
)


def test_typed_output_bindings_and_lineage_round_trip() -> None:
    raw = {
        "step_id": "derive",
        "fingerprint": "sha256:derive",
        "status": "completed",
        "artifact_ids": ["artifact-derived"],
        "row_counts": {"source": 12},
        "error": None,
        "result_fingerprint": "sha256:result",
        "output_bindings": {
            "dataset": {
                "binding_type": "dataset",
                "run_id": "run-1",
                "node_ref": "node-derived",
                "artifact_id": "artifact-derived",
                "content_sha256": "sha256:content",
            }
        },
        "lineage": {
            "source_commitments": [
                {
                    "from_step": "source",
                    "output": "dataset",
                    "artifact_id": "artifact-source",
                    "content_sha256": "sha256:source",
                }
            ]
        },
    }

    restored = WorkflowStepState.from_dict(raw)

    assert restored.to_dict()["output_bindings"] == raw["output_bindings"]
    assert restored.to_dict()["lineage"] == raw["lineage"]


def test_legacy_produced_dataset_is_normalized_and_traceable() -> None:
    raw = {
        "step_id": "legacy",
        "fingerprint": "sha256:legacy",
        "status": "completed",
        "artifact_ids": ["artifact-legacy"],
        "row_counts": {},
        "produced_dataset": {
            "schema_version": "workflow-produced-dataset.v1",
            "run_id": "run-1",
            "node_ref": "node-legacy",
            "artifact_id": "artifact-legacy",
            "content_sha256": "sha256:legacy-content",
        },
    }

    restored = WorkflowStepState.from_dict(raw)

    assert restored.produced_dataset == raw["produced_dataset"]
    assert restored.output_bindings["produced_dataset"]["binding_type"] == "dataset"
    assert restored.to_dict()["output_bindings"]["produced_dataset"]["artifact_id"] == "artifact-legacy"


def test_lineage_persistence_is_bounded_and_corruption_fails_closed() -> None:
    with pytest.raises(WorkflowExecutionError, match="item bound"):
        WorkflowStepState.from_dict(
            {
                "step_id": "too-wide",
                "fingerprint": "sha256:wide",
                "output_bindings": {},
                "lineage": {"branches": ["x"] * 129},
            }
        )

    with pytest.raises(WorkflowExecutionError, match="binding_type"):
        WorkflowStepState.from_dict(
            {
                "step_id": "corrupt",
                "fingerprint": "sha256:corrupt",
                "output_bindings": {"dataset": {"artifact_id": "a"}},
                "lineage": {},
            }
        )


def test_server_admission_rejects_client_draft_before_callback(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-client-draft")
    client_draft = dataclasses.replace(draft, compiler_authority="client")
    calls: list[str] = []

    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_CLIENT_COMPILED"):
        WorkflowExecutor(tmp_path).execute(
            client_draft,
            lambda step, previous: calls.append(step.step_id) or WorkflowStepResult(),
            evidence_port=EvidencePersistencePort(tmp_path),
        )

    assert calls == []
    assert not (tmp_path / "workbench" / "workflows" / "wf-client-draft.evidence.jsonl").exists()


def test_evidence_port_is_idempotent_and_duplicate_admission_is_closed(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-evidence-port")
    step = draft.steps[0]
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, step)
    result = _evidence_result(
        tmp_path, port=port, receipt=receipt, draft=draft, step=step
    )
    port.complete(receipt, result)
    port.complete(receipt, result)

    resumed = port.admit(draft, step)
    assert resumed.completed_result is not None
    records = json.loads("[" + ",".join(
        (tmp_path / "workbench" / "workflows" / "wf-evidence-port.evidence.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ) + "]")
    assert len([item for item in records if item["record_type"] == "workflow_completion"]) == 1


def test_public_evidence_port_requires_a_real_server_host_endpoint(tmp_path) -> None:
    """A caller cannot mint the write capability by invoking its class."""

    with pytest.raises(
        WorkflowExecutionError, match="WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED"
    ):
        EvidencePersistencePortClass(tmp_path)


def test_default_evidence_port_requires_an_external_host_endpoint(tmp_path) -> None:
    """Production bootstrap must fail closed until the host wires a real endpoint."""

    with pytest.raises(
        WorkflowExecutionError, match="WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED"
    ):
        issue_server_evidence_port(tmp_path)


def test_forged_evidence_port_object_is_rejected(tmp_path) -> None:
    """A real fd alone cannot turn an arbitrary object into the issued port."""

    workflow_directory = tmp_path / "workbench" / "workflows"
    workflow_directory.mkdir(parents=True)
    endpoint_fd = os.open(
        workflow_directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        forged = object.__new__(EvidencePersistencePortClass)
        forged._host_endpoint_fd = endpoint_fd
        with pytest.raises(
            WorkflowExecutionError,
            match="WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED|WORKFLOW_PROCESS_BOUNDARY",
        ):
            forged.require_server_host()
    finally:
        os.close(endpoint_fd)


def test_completion_rejects_a_registered_artifact_from_another_run(tmp_path) -> None:
    """Project ownership is not enough: completion must stay on the admitted run."""

    draft = compile_fixture_workflow(workflow_id="wf-cross-run-remediation-4")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])

    foreign_root = tmp_path / "runs" / "foreign-run"
    foreign_root.mkdir(parents=True, exist_ok=True)
    foreign_path = foreign_root / "foreign.json"
    foreign_path.write_text('{"foreign": true}\n', encoding="utf-8")
    initialize_artifact_index(foreign_root)
    register_artifact(
        foreign_root,
        "foreign-artifact",
        foreign_path,
        "workflow_output",
        "statistical.explore",
        [],
    )
    result = WorkflowStepResult(
        artifact_ids=["foreign-artifact"],
        row_counts={"source": 1},
        output_bindings={
            "dataset": {
                "binding_type": "dataset",
                "run_id": "foreign-run",
                "node_ref": "foreign-node",
                "artifact_id": "foreign-artifact",
                "content_sha256": sha256_file(foreign_path),
            }
        },
    )

    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_TARGET_RUN_MISMATCH"):
        port.complete(receipt, result)

    evidence_path = (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )
    records = [json.loads(line) for line in evidence_path.read_text().splitlines()]
    assert not any(item["record_type"] == "workflow_completion" for item in records)


@pytest.mark.parametrize("helper", (_execute_model_joint_f_test, _execute_model_white_test))
def test_direct_post_estimation_helpers_require_receipt_before_any_work(
    tmp_path, helper
) -> None:
    """Calling inference helpers directly cannot reach branch lookup or persistence."""

    draft = compile_fixture_workflow(workflow_id="wf-direct-post-estimation")
    step = draft.steps[0]
    with pytest.raises(
        WorkflowExecutionError, match="WORKFLOW_ADMISSION_RECEIPT_REQUIRED"
    ):
        helper(
            tmp_path,
            draft,
            {"node_ref": "node-1", "artifact_id": "artifact-1", "sha256": "sha256:x"},
            pd.DataFrame({"value": [1.0]}),
            step,
            {},
        )
    assert not list(tmp_path.glob("**/artifacts/**"))


def test_direct_post_estimation_persistence_requires_receipt_before_write(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-direct-post-persist")
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True, exist_ok=True)
    initialize_artifact_index(run_root)

    with pytest.raises(
        WorkflowExecutionError, match="WORKFLOW_ADMISSION_RECEIPT_REQUIRED"
    ):
        _persist_model_post_estimation_result(
            tmp_path,
            draft,
            draft.steps[0],
            artifact_type="post_estimation",
            result={"ok": True},
            model_run_id="model-run",
            model_artifact_id="ols_1",
            lineage={"node_ref": "node-1", "artifact_id": "raw-1", "sha256": "sha256:x"},
        )
    assert not list(run_root.glob("artifacts/**"))


def test_post_estimation_writer_rejects_a_symlink_parent_before_external_write(
    tmp_path,
) -> None:
    """A run artifact writer must not create an outside file before failing."""

    draft = compile_fixture_workflow(workflow_id="wf-post-estimation-path")
    step = draft.steps[0]
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True, exist_ok=True)
    initialize_artifact_index(run_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    artifacts_root = run_root / "artifacts"
    artifacts_root.mkdir()
    (artifacts_root / "post_estimation").symlink_to(
        outside, target_is_directory=True
    )
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, step)
    context_token = _WRITE_CONTEXT.set((port, receipt, draft, step))
    try:
        with pytest.raises(WorkflowExecutionError, match="WORKFLOW_ARTIFACT_PATH"):
            _persist_model_post_estimation_result(
                tmp_path,
                draft,
                step,
                artifact_type="post_estimation",
                result={"ok": True},
                model_run_id="model-run",
                model_artifact_id="ols_1",
                lineage={
                    "node_ref": "node-1",
                    "artifact_id": "raw-1",
                    "sha256": "sha256:x",
                },
            )
    finally:
        _WRITE_CONTEXT.reset(context_token)

    assert not list(outside.iterdir())


def test_direct_report_helper_requires_receipt_before_any_write(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-direct-report-remediation-4")
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True, exist_ok=True)
    initialize_artifact_index(run_root)

    with pytest.raises(
        WorkflowExecutionError, match="WORKFLOW_ADMISSION_RECEIPT_REQUIRED"
    ):
        _execute_workflow_report(tmp_path, draft, {})
    assert not list(run_root.glob("artifacts/**"))
    assert not list(run_root.glob("reports/**"))
    assert not list(run_root.glob("exports/**"))


def test_workflow_path_replacement_cannot_split_the_admitted_lock_domain(
    tmp_path, monkeypatch
) -> None:
    """Replacing the workflow directory while admitted must fail closed."""

    draft = compile_fixture_workflow(workflow_id="wf-lock-domain-remediation-4")
    port = EvidencePersistencePort(tmp_path)
    import workbench.agent.workflow_runtime as workflow_runtime

    original_append = workflow_runtime._append_evidence_record

    def replace_path_before_write(path, record, **kwargs):
        replacement = path.parent.with_name("workflows-replacement")
        path.parent.rename(replacement)
        path.parent.mkdir(parents=True, exist_ok=True)
        return original_append(path, record, **kwargs)

    monkeypatch.setattr(workflow_runtime, "_append_evidence_record", replace_path_before_write)

    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_EVIDENCE_PATH_CHANGED"):
        port.admit(draft, draft.steps[0])

    assert not (
        tmp_path
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    ).exists()


def test_post_estimation_registry_is_family_and_output_strict() -> None:
    operations = {
        post_estimation_registry.resolve(
            model_family="ols", operation_id=operation
        ).operation_id
        for operation in (
            "model.joint_f_test",
            "model.white_test",
            "model.quadratic_stationary_point",
        )
    }
    assert operations == {
        "model.joint_f_test",
        "model.white_test",
        "model.quadratic_stationary_point",
    }

    cases = (
        ("unknown_family", POST_ESTIMATION_UNKNOWN_FAMILY),
        ("panel_ols", POST_ESTIMATION_UNSUPPORTED_FAMILY),
    )
    for family, code in cases:
        with pytest.raises(PostEstimationRegistryError) as error:
            post_estimation_registry.resolve(
                model_family=family, operation_id="model.white_test"
            )
        assert error.value.code == code

    with pytest.raises(PostEstimationRegistryError) as error:
        post_estimation_registry.resolve(model_family="ols", operation_id="model.unknown")
    assert error.value.code == POST_ESTIMATION_UNKNOWN_OPERATION

    with pytest.raises(PostEstimationRegistryError) as error:
        post_estimation_registry.resolve(
            model_family="ols", operation_id="model.white_test", output_id="wrong"
        )
    assert error.value.code == POST_ESTIMATION_UNKNOWN_OUTPUT


def test_provider_manifest_is_declaration_only() -> None:
    from workbench.contracts.common.provider import ProviderContributionV1

    manifest = json.loads(
        (
            Path(__file__).parents[1]
            / "backend/workbench/providers/builtin/workflow_post_estimation.json"
        ).read_text(encoding="utf-8")
    )
    contribution = ProviderContributionV1.from_dict(manifest)
    assert contribution.provider_id == "workflow.post_estimation"
    assert {path.family_contract_ref.logical_id for path in contribution.exposure_paths} == {
        "workflow.post_estimation.family.ols"
    }
    assert all(
        adapter.executor_ref.startswith("executor:workflow.post_estimation.")
        for adapter in contribution.adapter_declarations
    )


def _evidence_result(
    project_root: Path,
    *,
    register: bool = True,
    port=None,
    receipt=None,
    draft=None,
    step=None,
) -> WorkflowStepResult:
    run_root = project_root / "runs" / "run-1"
    if register:
        run_root.mkdir(parents=True, exist_ok=True)
        artifact_path = run_root / "artifact.json"
        artifact_path.write_text('{"ok": true}\n', encoding="utf-8")
        initialize_artifact_index(run_root)
        register_artifact(
            run_root,
            "artifact-1",
            artifact_path,
            "workflow_output",
            "statistical.explore",
            [],
        )
        content_sha256 = sha256_file(artifact_path)
    else:
        content_sha256 = "sha256:unregistered"
    result = WorkflowStepResult(
        artifact_ids=["artifact-1"],
        row_counts={"source": 1},
        output_bindings={
            "dataset": {
                "binding_type": "dataset",
                "run_id": "run-1",
                "node_ref": "node-1",
                "artifact_id": "artifact-1",
                "content_sha256": content_sha256,
            }
        },
        lineage={"source_commitments": []},
    )
    if register and port is not None and receipt is not None and draft is not None and step is not None:
        context_token = _WRITE_CONTEXT.set((port, receipt, draft, step))
        try:
            port._admit_server_artifact(
                receipt,
                run_id="run-1",
                artifact_id="artifact-1",
                path=artifact_path,
                artifact_type="workflow_output",
                producer_step=step.operation_id,
                inputs=(),
                expected_artifacts=step.expected_artifacts,
            )
            port.admit_result_artifacts(receipt, result)
        finally:
            _WRITE_CONTEXT.reset(context_token)
    return result


@pytest.mark.parametrize(
    "mutation",
    (
        "target",
        "scope",
        "step",
        "plan",
        "workflow",
        "template",
        "bindings",
        "preconditions",
    ),
)
def test_compiler_receipt_binds_target_scope_step_and_plan_before_admission(
    tmp_path, mutation: str
) -> None:
    draft = compile_fixture_workflow(workflow_id=f"wf-forged-{mutation}")
    if mutation == "target":
        forged = dataclasses.replace(
            draft,
            target={**draft.target, "artifact_id": "foreign-artifact"},
        )
    elif mutation == "scope":
        forged = dataclasses.replace(
            draft,
            preconditions={
                **draft.preconditions,
                "context_fingerprint": "sha256:foreign-context",
            },
        )
    elif mutation == "step":
        altered_step = dataclasses.replace(
            draft.steps[0],
            spec={**draft.steps[0].spec, "forged_contract_field": True},
        )
        forged = dataclasses.replace(draft, steps=(altered_step, *draft.steps[1:]))
    elif mutation == "workflow":
        forged = dataclasses.replace(draft, workflow_id="wf-foreign-workflow")
    elif mutation == "template":
        forged = dataclasses.replace(draft, workflow_template="forged-template")
    elif mutation == "bindings":
        forged = dataclasses.replace(draft, bindings={"foreign": "binding"})
    elif mutation == "preconditions":
        forged = dataclasses.replace(
            draft,
            preconditions={**draft.preconditions, "owner_resolution": "foreign"},
        )
    else:
        forged_plan = "sha256:" + ("f" * 64)
        public_hash = hashlib.sha256(
            f"{SERVER_COMPILER_AUTHORITY}:v1:{forged_plan}".encode("utf-8")
        ).hexdigest()
        forged = dataclasses.replace(
            draft,
            plan_fingerprint=forged_plan,
            compiler_receipt=public_hash,
        )

    port = EvidencePersistencePort(tmp_path)
    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_CLIENT_COMPILED"):
        port.admit(forged, forged.steps[0])


def test_concurrent_admission_reservation_is_one_atomic_decision(tmp_path, monkeypatch) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-concurrent-admission")
    port = EvidencePersistencePort(tmp_path)

    import workbench.agent.workflow_runtime as workflow_runtime

    original_append = workflow_runtime._append_evidence_record

    def delayed_append(path, record, **kwargs):
        if path.name.endswith(".evidence.jsonl"):
            time.sleep(0.05)
        return original_append(path, record, **kwargs)

    monkeypatch.setattr(workflow_runtime, "_append_evidence_record", delayed_append)

    def attempt():
        try:
            return port.admit(draft, draft.steps[0])
        except WorkflowExecutionError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _item: attempt(), (1, 2)))

    receipts = [item for item in outcomes if isinstance(item, WorkflowAdmissionReceipt)]
    errors = [str(item) for item in outcomes if isinstance(item, WorkflowExecutionError)]
    assert len(receipts) == 1
    assert errors == [
        "WORKFLOW_DUPLICATE_EXECUTION: an admitted workflow step has no completion"
    ]
    records = [
        json.loads(line)
        for line in (
            tmp_path / "workbench" / "workflows" / "wf-concurrent-admission.evidence.jsonl"
        )
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len([item for item in records if item["record_type"] == "workflow_admission"]) == 1


def _admit_from_process(project_root: str, start_event, result_queue) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-cross-process-admission")
    start_event.wait(5)
    try:
        receipt = EvidencePersistencePort(project_root).admit(draft, draft.steps[0])
    except WorkflowExecutionError as error:
        result_queue.put(("error", str(error)))
    else:
        result_queue.put(("receipt", receipt.receipt_id))


def _admit_after_worker_restart(project_root: str, result_queue) -> None:
    """Spawned worker probe: the old process authority must not be adopted."""

    draft = compile_fixture_workflow(workflow_id="wf-worker-boundary")
    try:
        EvidencePersistencePort(project_root).admit(draft, draft.steps[0])
    except WorkflowExecutionError as error:
        result_queue.put(("error", str(error)))
    else:
        result_queue.put(("receipt", "unexpected"))


def test_cross_process_admission_has_one_durable_winner(tmp_path, monkeypatch) -> None:
    original_records = EvidencePersistencePortClass._records

    def delayed_records(self, workflow_id):
        records = original_records(self, workflow_id)
        time.sleep(0.15)
        return records

    monkeypatch.setattr(EvidencePersistencePortClass, "_records", delayed_records)
    context = multiprocessing.get_context("fork")
    start_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_admit_from_process,
            args=(str(tmp_path), start_event, result_queue),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start_event.set()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0

    outcomes = [result_queue.get(timeout=2) for _ in processes]
    assert [kind for kind, _value in outcomes].count("receipt") == 1
    assert [kind for kind, _value in outcomes].count("error") == 1
    assert re.search(
        "WORKFLOW_DUPLICATE_EXECUTION|WORKFLOW_RESTART_AUTHORITY_REQUIRED",
        next(value for kind, value in outcomes if kind == "error"),
    )


def test_eight_process_admission_probe_has_one_durable_winner(tmp_path) -> None:
    """The durable directory lock serializes more than a two-worker sample."""

    context = multiprocessing.get_context("fork")
    start_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_admit_from_process,
            args=(str(tmp_path), start_event, result_queue),
        )
        for _ in range(8)
    ]
    for process in processes:
        process.start()
    start_event.set()
    outcomes = []
    for process in processes:
        process.join(15)
        assert process.exitcode == 0
        outcomes.append(result_queue.get(timeout=3))

    assert [kind for kind, _value in outcomes].count("receipt") == 1
    assert [kind for kind, _value in outcomes].count("error") == 7
    assert all(
        "WORKFLOW_DUPLICATE_EXECUTION" in value
        or "WORKFLOW_RESTART_AUTHORITY_REQUIRED" in value
        for kind, value in outcomes
        if kind == "error"
    )


def test_admission_rejects_a_step_with_a_reused_public_fingerprint(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-forged-admission-step")
    original = draft.steps[0]
    forged = dataclasses.replace(
        original,
        spec={**original.spec, "forged_contract_field": True},
        fingerprint=original.fingerprint,
    )
    port = EvidencePersistencePort(tmp_path)

    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_CHANGED_CONTRACT"):
        port.admit(draft, forged)

    assert not (
        tmp_path / "workbench" / "workflows" / "wf-forged-admission-step.evidence.jsonl"
    ).exists()


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    (
        ("step_id", "forged-step", "WORKFLOW_ADMISSION_MISMATCH"),
        ("scope_ref", "run-foreign:sha256:foreign:run-foreign", "WORKFLOW_CROSS_SCOPE"),
        ("contract_fingerprint", "f" * 64, "WORKFLOW_CHANGED_CONTRACT"),
        ("plan_fingerprint", "sha256:" + ("f" * 64), "WORKFLOW_STALE"),
    ),
)
def test_complete_reparses_original_admission_before_any_append(
    tmp_path, field: str, value: str, error_code: str
) -> None:
    draft = compile_fixture_workflow(workflow_id=f"wf-complete-{field}")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    evidence_path = tmp_path / "workbench" / "workflows" / f"{draft.workflow_id}.evidence.jsonl"
    records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
    for record in records:
        if record["record_type"] == "workflow_admission":
            record[field] = value
    evidence_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    with pytest.raises(WorkflowExecutionError, match=error_code):
        port.complete(
            receipt,
            _evidence_result(
                tmp_path, port=port, receipt=receipt, draft=draft, step=draft.steps[0]
            ),
        )

    records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
    assert not any(item["record_type"] == "workflow_completion" for item in records)


def test_replay_rejects_a_paired_tampered_completion(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-tampered-completion")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    port.complete(
        receipt,
        _evidence_result(
            tmp_path, port=port, receipt=receipt, draft=draft, step=draft.steps[0]
        ),
    )
    evidence_path = tmp_path / "workbench" / "workflows" / f"{draft.workflow_id}.evidence.jsonl"
    records = [
        json.loads(line)
        for line in evidence_path.read_text(encoding="utf-8").splitlines()
    ]
    for record in records:
        if record["record_type"] == "workflow_completion":
            record["artifact_ids"] = ["forged-artifact"]
    evidence_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    with pytest.raises(WorkflowExecutionError, match="completion integrity"):
        port.admit(draft, draft.steps[0])


def test_complete_rejects_persisted_cross_target_before_side_effect(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-cross-target-completion")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    evidence_path = tmp_path / "workbench" / "workflows" / f"{draft.workflow_id}.evidence.jsonl"
    records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
    foreign_target = {**draft.target, "artifact_id": "foreign-artifact"}
    for record in records:
        if record["record_type"] == "workflow_admission":
            record["target"] = foreign_target
            record["target_fingerprint"] = _fingerprint(foreign_target)
    evidence_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_TARGET_MISMATCH"):
        port.complete(
            receipt,
            _evidence_result(
                tmp_path, port=port, receipt=receipt, draft=draft, step=draft.steps[0]
            ),
        )

    records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
    assert not any(item["record_type"] == "workflow_completion" for item in records)


def test_complete_rejects_aborted_receipt_before_side_effect(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-aborted-completion")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    port.abort(receipt, "executor failed")

    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_ADMISSION_ABORTED"):
        port.complete(
            receipt,
            _evidence_result(
                tmp_path, port=port, receipt=receipt, draft=draft, step=draft.steps[0]
            ),
        )

    records = [
        json.loads(line)
        for line in (
            tmp_path / "workbench" / "workflows" / "wf-aborted-completion.evidence.jsonl"
        )
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [item["record_type"] for item in records] == [
        "workflow_admission",
        "workflow_abort",
    ]


def test_complete_requires_a_server_issued_receipt_owner(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-forged-receipt")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    forged = WorkflowAdmissionReceipt(
        workflow_id=receipt.workflow_id,
        step_id=receipt.step_id,
        plan_fingerprint=receipt.plan_fingerprint,
        step_fingerprint=receipt.step_fingerprint,
        scope_ref=receipt.scope_ref,
        contract_fingerprint=receipt.contract_fingerprint,
        receipt_id=receipt.receipt_id,
        attempt=receipt.attempt,
    )

    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_RECEIPT_AUTHORITY_REQUIRED"):
        port.complete(
            forged,
            _evidence_result(
                tmp_path, port=port, receipt=receipt, draft=draft, step=draft.steps[0]
            ),
        )


def test_replay_rejects_a_completion_with_a_forged_receipt_owner(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-forged-replay-owner")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    port.complete(
        receipt,
        _evidence_result(
            tmp_path, port=port, receipt=receipt, draft=draft, step=draft.steps[0]
        ),
    )
    evidence_path = tmp_path / "workbench" / "workflows" / f"{draft.workflow_id}.evidence.jsonl"
    records = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()]
    for record in records:
        if record["record_type"] == "workflow_completion":
            record["receipt_owner"] = "workflow-evidence-process:forged"
    evidence_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_RESTART_AUTHORITY_REQUIRED"):
        port.admit(draft, draft.steps[0])


def test_executor_rejects_duck_typed_evidence_port_before_callback(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-duck-port")
    calls: list[str] = []

    class DuckPort:
        def admit(self, _draft, _step):
            calls.append("admit")
            return None

        def complete(self, _receipt, _result):
            calls.append("complete")

        def abort(self, _receipt, _error):
            calls.append("abort")

    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_EVIDENCE_PORT_REQUIRED"):
        WorkflowExecutor(tmp_path).execute(
            draft,
            lambda _step, _previous: calls.append("callback") or WorkflowStepResult(),
            evidence_port=DuckPort(),
        )

    assert calls == []
    assert not (tmp_path / "workbench" / "workflows" / "wf-duck-port.evidence.jsonl").exists()


def test_executor_does_not_callback_or_persist_state_without_admission_receipt(
    tmp_path, monkeypatch
) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-no-receipt")
    calls: list[str] = []
    monkeypatch.setattr(EvidencePersistencePortClass, "admit", lambda _self, _draft, _step: None)

    with pytest.raises(Exception):
        WorkflowExecutor(tmp_path).execute(
            draft,
            lambda _step, _previous: calls.append("callback") or WorkflowStepResult(),
        )

    assert calls == []
    workflow_path = tmp_path / "workbench" / "workflows" / "wf-no-receipt.jsonl"
    evidence_path = tmp_path / "workbench" / "workflows" / "wf-no-receipt.evidence.jsonl"
    assert not workflow_path.exists()
    assert not evidence_path.exists()
    assert not (tmp_path / "workbench").exists()


@pytest.mark.parametrize(
    "mutation",
    ("target", "preconditions", "bindings", "template", "plan", "step"),
)
def test_receipt_gate_rejects_every_post_admission_snapshot_mutation(
    tmp_path, mutation: str
) -> None:
    """Admission seals the complete execution snapshot before callback entry."""

    draft = compile_fixture_workflow(workflow_id=f"wf-toctou-{mutation}")
    port = EvidencePersistencePort(tmp_path)
    calls: list[str] = []
    gated = _ReceiptGatedWorkflowExecutor(
        lambda _step, _previous: calls.append("callback") or WorkflowStepResult(),
        draft,
    )
    gated._bind_evidence_port(port)
    receipt = port.admit(draft, draft.steps[0])

    if mutation == "target":
        draft.target["artifact_id"] = "foreign-artifact"
        candidate_step = draft.steps[0]
    elif mutation == "preconditions":
        draft.preconditions["owner_resolution"] = "foreign"
        candidate_step = draft.steps[0]
    elif mutation == "bindings":
        draft.bindings["foreign"] = "binding"
        candidate_step = draft.steps[0]
    elif mutation == "template":
        object.__setattr__(draft, "workflow_template", "forged-template")
        candidate_step = draft.steps[0]
    elif mutation == "plan":
        object.__setattr__(draft, "plan_fingerprint", "sha256:" + ("f" * 64))
        candidate_step = draft.steps[0]
    else:
        candidate_step = dataclasses.replace(
            draft.steps[0],
            spec={**draft.steps[0].spec, "operation": "forged-operation"},
            fingerprint=draft.steps[0].fingerprint,
        )

    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_ADMISSION_MISMATCH"):
        gated(candidate_step, {}, admission_receipt=receipt)

    assert calls == []


def test_workflow_executor_rejects_plain_callback_before_any_side_effect(tmp_path) -> None:
    """A legacy callback cannot become a write-capable executor by omission."""

    draft = compile_fixture_workflow(workflow_id="wf-plain-callback")
    calls: list[str] = []

    with pytest.raises(WorkflowExecutionError, match="WORKFLOW_RECEIPT_GATED_CALLBACK_REQUIRED"):
        WorkflowExecutor(tmp_path).execute(
            draft,
            lambda _step, _previous: calls.append("callback") or WorkflowStepResult(),
            evidence_port=EvidencePersistencePort(tmp_path),
        )

    assert calls == []
    assert not list((tmp_path / "workbench" / "workflows").glob("*.evidence.jsonl"))


def test_completion_rejects_an_artifact_missing_from_the_project_registry(tmp_path) -> None:
    """A typed result is not evidence until its artifact is registered and owned."""

    draft = compile_fixture_workflow(workflow_id="wf-unregistered-completion")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])

    with pytest.raises(WorkflowExecutionError, match="registered project artifact"):
        port.complete(
            receipt,
            _evidence_result(
                tmp_path,
                register=False,
                port=port,
                receipt=receipt,
                draft=draft,
                step=draft.steps[0],
            ),
        )

    records = (
        tmp_path / "workbench" / "workflows" / "wf-unregistered-completion.evidence.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert not any(json.loads(line)["record_type"] == "workflow_completion" for line in records)


@pytest.mark.parametrize("tamper", ("path_escape", "symlink", "digest"))
def test_completion_rejects_registry_artifact_path_or_content_tampering(
    tmp_path, tamper: str
) -> None:
    draft = compile_fixture_workflow(workflow_id=f"wf-completion-{tamper}")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    result = _evidence_result(
        tmp_path, port=port, receipt=receipt, draft=draft, step=draft.steps[0]
    )
    run_root = tmp_path / "runs" / "run-1"
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    record = next(item for item in index["artifacts"] if item["artifact_id"] == "artifact-1")
    if tamper == "path_escape":
        record["path"] = "../outside.json"
    elif tamper == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_text('{"outside": true}\n', encoding="utf-8")
        (run_root / "artifact.json").unlink()
        (run_root / "artifact.json").symlink_to(outside)
    else:
        (run_root / "artifact.json").write_text('{"tampered": true}\n', encoding="utf-8")
    index_path.write_text(json.dumps(index), encoding="utf-8")

    if tamper == "path_escape":
        # The public index is metadata, not authority. Completion must use the
        # path frozen in the server registry before the index was rewritten.
        port.complete(receipt, result)
        records = [
            json.loads(line)
            for line in (
                tmp_path
                / "workbench"
                / "workflows"
                / f"{draft.workflow_id}.evidence.jsonl"
            )
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert any(item["record_type"] == "workflow_completion" for item in records)
    else:
        with pytest.raises(WorkflowExecutionError, match="(registered|admitted) artifact"):
            port.complete(receipt, result)


def test_model_branch_rejects_a_path_like_model_run_ref(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-model-run-ref")
    branch = {
        "branch_id": "main",
        "run_id": "../../foreign-run",
        "artifact_ids": ["ols_1"],
        "model_artifact_id": "ols_1",
        "workflow_id": draft.workflow_id,
        "workflow_step_id": draft.steps[0].step_id,
        "source_run_id": "run-1",
        "source_artifact_id": "raw-1",
        "source_sha256": "sha256:source-1",
        "branch_spec": {
            "model_family": "ols",
            "covariance": "unadjusted",
            "outcome": "outcome",
            "predictors": ["rate_a"],
            "categorical": [],
            "polynomials": [],
        },
        "predictor_columns": ["rate_a"],
        "term_groups": {"linear": {"rate_a": ["rate_a"]}, "polynomial": {}, "categorical": {}},
    }

    with pytest.raises(WorkflowExecutionError, match="opaque model run reference"):
        _validate_persisted_model_branch(tmp_path, draft, draft.steps[0].step_id, branch)


def _model_branch_with_forged_declaration(
    draft, model_step, *, field: str, forged_value: object
) -> dict[str, object]:
    branch_spec: dict[str, object] = {
        "model_family": "ols",
        "covariance": "unadjusted",
        "outcome": "outcome",
        "predictors": ["rate_a"],
        "categorical": [],
        "polynomials": [],
    }
    branch_spec[field] = forged_value
    return {
        "branch_id": "m1",
        "run_id": "model-run",
        "artifact_ids": ["ols_1"],
        "model_artifact_id": "ols_1",
        "workflow_id": draft.workflow_id,
        "workflow_step_id": model_step.step_id,
        "source_run_id": "run-1",
        "source_artifact_id": "raw-1",
        "source_sha256": "sha256:source-1",
        "branch_spec": branch_spec,
        "predictor_columns": ["rate_a"],
        "term_groups": {
            "linear": {"rate_a": ["rate_a"]},
            "polynomial": {},
            "categorical": {},
        },
    }


def test_model_branch_rejects_predictor_forgery_against_compiled_step(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-model-declaration-binding")
    model_step = next(
        step for step in draft.steps if step.operation_id == "model.genesis"
    )
    branch = _model_branch_with_forged_declaration(
        draft, model_step, field="predictors", forged_value=["rate_b"]
    )

    with pytest.raises(WorkflowExecutionError, match="compiled model step"):
        _validate_persisted_model_branch(tmp_path, draft, model_step.step_id, branch)


def test_model_branch_rejects_covariance_forgery_against_compiled_step(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-model-declaration-binding")
    model_step = next(
        step for step in draft.steps if step.operation_id == "model.genesis"
    )
    branch = _model_branch_with_forged_declaration(
        draft, model_step, field="covariance", forged_value="robust"
    )

    with pytest.raises(WorkflowExecutionError, match="compiled model step"):
        _validate_persisted_model_branch(tmp_path, draft, model_step.step_id, branch)


def _custom_model_branch_fixture(tmp_path, *, bindings=None):
    draft = compile_fixture_workflow(
        workflow_id="wf-custom-model-declaration",
        steps=[
            {
                "step_id": "custom-model",
                "operation_id": "model.custom",
                "spec": {
                    "capability_ref": "capability:example",
                    "binding_ref": "binding:example",
                    "operation": "fit",
                },
            }
        ],
    )
    if bindings is not None:
        draft = dataclasses.replace(draft, bindings=bindings)

    source_root = tmp_path / "runs" / "run-1"
    source_root.mkdir(parents=True)
    source_path = source_root / "data.csv"
    source_path.write_text("outcome,rate_a\n1,2\n", encoding="utf-8")
    initialize_artifact_index(source_root)
    register_artifact(
        source_root,
        "raw-1",
        source_path,
        "dataset",
        "ingestion",
        [],
    )

    model_root = tmp_path / "runs" / "model-run"
    model_path = model_root / "model_results" / "ols_1.json"
    model_path.parent.mkdir(parents=True)
    model_path.write_text(json.dumps({"model_family": "ols"}), encoding="utf-8")
    (model_root / "run_manifest.json").write_text(
        json.dumps({"run_id": "model-run", "status": "completed"}),
        encoding="utf-8",
    )
    initialize_artifact_index(model_root)
    register_artifact(
        model_root,
        "ols_1",
        model_path,
        "model_result",
        "model.custom",
        ["raw-1"],
    )

    branch = {
        "branch_id": "m1",
        "run_id": "model-run",
        "artifact_ids": ["ols_1"],
        "model_artifact_id": "ols_1",
        "workflow_id": draft.workflow_id,
        "workflow_step_id": "custom-model",
        "source_run_id": "run-1",
        "source_artifact_id": "raw-1",
        "source_sha256": sha256_file(source_path),
        "branch_spec": {
            "model_family": "ols",
            "covariance": "unadjusted",
            "outcome": "outcome",
            "predictors": ["rate_a"],
            "categorical": [],
            "polynomials": [],
        },
        "predictor_columns": ["rate_a"],
        "term_groups": {
            "linear": {"rate_a": ["rate_a"]},
            "polynomial": {},
            "categorical": {},
        },
    }
    return draft, branch


def test_model_custom_branch_requires_a_server_branch_declaration(tmp_path) -> None:
    draft, branch = _custom_model_branch_fixture(tmp_path)

    with pytest.raises(WorkflowExecutionError, match="server.*declaration|branch-producing"):
        _validate_persisted_model_branch(tmp_path, draft, "custom-model", branch)


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("model_family", "forged-family"),
        ("outcome", "rate_b"),
        ("predictors", ["rate_b"]),
        ("covariance", "robust"),
    ),
)
def test_model_custom_branch_rejects_forged_server_declaration_fields(
    tmp_path, field, forged_value
) -> None:
    bindings = {
        "server_model_declarations": {
            "custom-model": {
                "operation_id": "model.custom",
                "branch_producing": True,
                "model_family": "ols",
                "branches": [
                    {
                        "branch_id": "m1",
                        "model_family": "ols",
                        "outcome": "outcome",
                        "predictors": ["rate_a"],
                        "covariance": "unadjusted",
                    }
                ],
            }
        }
    }
    draft, branch = _custom_model_branch_fixture(tmp_path, bindings=bindings)
    branch["branch_spec"][field] = forged_value

    with pytest.raises(WorkflowExecutionError, match="declaration|compiled model step"):
        _validate_persisted_model_branch(tmp_path, draft, "custom-model", branch)


def test_model_branch_rejects_a_symlinked_model_run_ref(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-model-run-symlink")
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "real-model").mkdir()
    (runs_root / "model-link").symlink_to(runs_root / "real-model", target_is_directory=True)
    branch = {
        "branch_id": "main",
        "run_id": "model-link",
        "artifact_ids": ["ols_1"],
        "model_artifact_id": "ols_1",
        "workflow_id": draft.workflow_id,
        "workflow_step_id": draft.steps[0].step_id,
        "source_run_id": "run-1",
        "source_artifact_id": "raw-1",
        "source_sha256": "sha256:source-1",
        "branch_spec": {
            "model_family": "ols",
            "covariance": "unadjusted",
            "outcome": "outcome",
            "predictors": ["rate_a"],
            "categorical": [],
            "polynomials": [],
        },
        "predictor_columns": ["rate_a"],
        "term_groups": {"linear": {"rate_a": ["rate_a"]}, "polynomial": {}, "categorical": {}},
    }

    with pytest.raises(WorkflowExecutionError, match="project-owned"):
        _validate_persisted_model_branch(tmp_path, draft, draft.steps[0].step_id, branch)


def test_model_branch_recomputes_the_source_file_digest(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-model-source-file-digest")
    source_root = tmp_path / "runs" / "run-1"
    source_root.mkdir(parents=True)
    source_path = source_root / "data.csv"
    source_path.write_text("actual source bytes\n", encoding="utf-8")
    (source_root / "artifacts_index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": [
                    {
                        "artifact_id": "raw-1",
                        "path": "data.csv",
                        "sha256": "sha256:declared-but-wrong",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    model_root = tmp_path / "runs" / "model-run"
    model_artifact = model_root / "artifacts" / "model" / "ols_1.json"
    model_artifact.parent.mkdir(parents=True)
    model_artifact.write_text(json.dumps({"model_family": "ols"}), encoding="utf-8")
    (model_root / "run_manifest.json").write_text(
        json.dumps({"run_id": "model-run", "status": "completed"}),
        encoding="utf-8",
    )
    (model_root / "artifacts_index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": [
                    {
                        "artifact_id": "ols_1",
                        "path": "artifacts/model/ols_1.json",
                        "sha256": sha256_file(model_artifact),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    branch = {
        "branch_id": "main",
        "run_id": "model-run",
        "artifact_ids": ["ols_1"],
        "model_artifact_id": "ols_1",
        "workflow_id": draft.workflow_id,
        "workflow_step_id": draft.steps[0].step_id,
        "source_run_id": "run-1",
        "source_artifact_id": "raw-1",
        "source_sha256": "sha256:declared-but-wrong",
        "branch_spec": {
            "model_family": "ols",
            "covariance": "unadjusted",
            "outcome": "outcome",
            "predictors": ["rate_a"],
            "categorical": [],
            "polynomials": [],
        },
        "predictor_columns": ["rate_a"],
        "term_groups": {"linear": {"rate_a": ["rate_a"]}, "polynomial": {}, "categorical": {}},
    }

    with pytest.raises(WorkflowExecutionError, match="content digest"):
        _validate_persisted_model_branch(tmp_path, draft, draft.steps[0].step_id, branch)


def test_restart_without_persisted_authority_fails_closed(tmp_path) -> None:
    """A new worker cannot silently adopt a receipt issued by another worker."""

    draft = compile_fixture_workflow(workflow_id="wf-worker-boundary")
    port = EvidencePersistencePort(tmp_path)
    port.admit(draft, draft.steps[0])

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_admit_after_worker_restart,
        args=(str(tmp_path), result_queue),
    )
    process.start()
    process.join(15)
    assert process.exitcode == 0
    kind, message = result_queue.get(timeout=3)
    assert kind == "error"
    assert "WORKFLOW_RESTART_AUTHORITY_REQUIRED" in message


def test_source_commitment_persists_a_canonical_digest(tmp_path) -> None:
    draft = compile_fixture_workflow(
        workflow_id="wf-source-digest",
        steps=[
            {
                "step_id": "publish",
                "operation_id": "statistical.explore",
                "spec": {"operation": "misstable", "selected_columns": ["rate_a"]},
            }
        ],
    )
    port = EvidencePersistencePort(tmp_path)
    def produce(step, _previous, **kwargs):
        return dataclasses.replace(
            _evidence_result(
                tmp_path,
                port=kwargs["evidence_port"],
                receipt=kwargs["admission_receipt"],
                draft=draft,
                step=step,
            ),
            lineage={},
        )

    gated = _ReceiptGatedWorkflowExecutor(produce, draft)
    gated._bind_evidence_port(port)
    state = WorkflowExecutor(tmp_path).execute(draft, gated, evidence_port=port)

    commitment = state.steps["publish"].lineage["source_commitments"][0]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", commitment["source_digest"])
    canonical = json.dumps(
        {
            "artifact_id": "raw-1",
            "node_ref": "stage:raw",
            "run_id": "run-1",
            "source_artifact_fingerprint": "sha256:source-1",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert commitment["source_digest"] == "sha256:" + hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def test_model_post_estimation_does_not_infer_ols_artifact_identity() -> None:
    with pytest.raises(WorkflowExecutionError, match="model artifact identity"):
        _model_artifact_id(
            {
                "artifact_ids": ["ols_1"],
                "branch_spec": {"model_family": "ols"},
            }
        )


def test_model_post_estimation_rejects_unpersisted_cross_scope_branch(tmp_path) -> None:
    draft = compile_fixture_workflow(
        workflow_id="wf-forged-model-identity",
        steps=[
            {
                "step_id": "estimate",
                "operation_id": "model.genesis",
                "spec": {
                    "model_family": "ols",
                    "covariance": "unadjusted",
                    "branches": [
                        {"branch_id": "main", "outcome": "outcome", "predictors": ["rate_a"]}
                    ],
                },
            },
            {
                "step_id": "joint",
                "operation_id": "model.joint_f_test",
                "depends_on": ["estimate"],
                "spec": {
                    "branch_id": "main",
                    "term_selectors": [{"kind": "linear", "column": "rate_a"}],
                },
            },
        ],
    )
    forged_branch = {
        "branch_id": "main",
        "run_id": "foreign-model-run",
        "artifact_ids": ["ols_1"],
        "model_artifact_id": "ols_1",
        "workflow_id": draft.workflow_id,
        "workflow_step_id": "estimate",
        "source_run_id": "run-1",
        "source_artifact_id": "raw-1",
        "source_sha256": "sha256:source-1",
        "branch_spec": {
            "model_family": "ols",
            "covariance": "unadjusted",
            "outcome": "outcome",
            "predictors": ["rate_a"],
            "categorical": [],
            "polynomials": [],
        },
        "predictor_columns": ["rate_a"],
        "term_groups": {"linear": {"rate_a": ["rate_a"]}, "polynomial": {}, "categorical": {}},
    }
    previous = {
        "estimate": WorkflowStepResult(payload={"branches": [forged_branch]})
    }

    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[1])
    context_token = _WRITE_CONTEXT.set((port, receipt, draft, draft.steps[1]))
    try:
        with pytest.raises(WorkflowExecutionError, match="persisted model run"):
            _execute_model_joint_f_test(
                tmp_path,
                draft,
                {"artifact_id": "raw-1", "node_ref": "stage:raw", "sha256": "sha256:source"},
                pd.DataFrame({"outcome": [1.0, 2.0, 3.0, 4.0], "rate_a": [0.0, 1.0, 2.0, 3.0]}),
                draft.steps[1],
                previous,
            )
    finally:
        _WRITE_CONTEXT.reset(context_token)

    assert not (tmp_path / "runs" / "run-1" / "artifacts").exists()


def test_model_post_estimation_rejects_source_artifact_mismatch(tmp_path) -> None:
    draft = compile_fixture_workflow(workflow_id="wf-model-source-mismatch")
    source_root = tmp_path / "runs" / "run-1"
    source_root.mkdir(parents=True)
    (source_root / "artifacts_index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": [
                    {
                        "artifact_id": "raw-1",
                        "path": "data.csv",
                        "sha256": "sha256:source-1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    model_root = tmp_path / "runs" / "model-run"
    model_artifact = model_root / "artifacts" / "model" / "ols_1.json"
    model_artifact.parent.mkdir(parents=True)
    model_artifact.write_text(json.dumps({"model_family": "ols"}), encoding="utf-8")
    (model_root / "run_manifest.json").write_text(
        json.dumps({"run_id": "model-run", "status": "completed"}),
        encoding="utf-8",
    )
    (model_root / "artifacts_index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": [
                    {
                        "artifact_id": "ols_1",
                        "path": "artifacts/model/ols_1.json",
                        "sha256": "sha256:model-artifact",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    branch = {
        "branch_id": "main",
        "run_id": "model-run",
        "artifact_ids": ["ols_1"],
        "model_artifact_id": "ols_1",
        "workflow_id": draft.workflow_id,
        "workflow_step_id": "estimate",
        "source_run_id": "run-1",
        "source_artifact_id": "foreign-raw",
        "source_sha256": "sha256:foreign-source",
        "branch_spec": {
            "model_family": "ols",
            "covariance": "unadjusted",
            "outcome": "outcome",
            "predictors": ["rate_a"],
            "categorical": [],
            "polynomials": [],
        },
        "predictor_columns": ["rate_a"],
        "term_groups": {
            "linear": {"rate_a": ["rate_a"]},
            "polynomial": {},
            "categorical": {},
        },
    }

    with pytest.raises(WorkflowExecutionError, match="source artifact"):
        _validate_persisted_model_branch(tmp_path, draft, "estimate", branch)


def test_public_host_endpoint_arguments_are_not_a_workflow_trust_root(tmp_path) -> None:
    """A caller-selected directory fd must not become production authority."""

    workflow_directory = tmp_path / "workbench" / "workflows"
    workflow_directory.mkdir(parents=True)
    endpoint_fd = os.open(
        workflow_directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        with pytest.raises(
            WorkflowExecutionError,
            match="caller-selected workflow host endpoint is not a trust root",
        ):
            issue_server_evidence_port(
                tmp_path,
                {
                    "project_root": tmp_path,
                    "workflow_evidence_root_fd": endpoint_fd,
                },
            )
    finally:
        os.close(endpoint_fd)


def test_completion_rejects_a_forged_same_run_registry(tmp_path) -> None:
    """A public artifact index row is not a server-owned producer admission."""

    draft = compile_fixture_workflow(workflow_id="wf-forged-same-run-registry")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])

    with pytest.raises(
        WorkflowExecutionError,
        match="server-owned artifact registry",
    ):
        port.complete(receipt, _evidence_result(tmp_path))


def test_completion_rejects_a_forged_foreign_run_branch(tmp_path) -> None:
    """Branch-shaped metadata cannot authorize an unadmitted model run."""

    draft = compile_fixture_workflow(workflow_id="wf-forged-foreign-branch")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])

    foreign_root = tmp_path / "runs" / "foreign-model-run"
    foreign_root.mkdir(parents=True)
    foreign_path = foreign_root / "ols.json"
    foreign_path.write_text('{"model": "forged"}\n', encoding="utf-8")
    initialize_artifact_index(foreign_root)
    register_artifact(
        foreign_root,
        "ols_1",
        foreign_path,
        "model_result",
        "model.genesis",
        ["raw-1"],
    )
    branch = {
        "branch_id": "main",
        "run_id": "foreign-model-run",
        "artifact_ids": ["ols_1"],
        "model_artifact_id": "ols_1",
        "workflow_id": draft.workflow_id,
        "workflow_step_id": draft.steps[0].step_id,
        "source_run_id": "run-1",
        "source_artifact_id": "raw-1",
        "source_sha256": "sha256:source-1",
    }
    result = WorkflowStepResult(
        artifact_ids=["foreign-model-run:ols_1"],
        row_counts={"source": 1},
        lineage={"branches": [branch]},
        output_bindings={
            "model": {
                "binding_type": "model",
                "run_id": "foreign-model-run",
                "node_ref": "model-node",
                "artifact_id": "ols_1",
                "content_sha256": sha256_file(foreign_path),
            }
        },
    )

    with pytest.raises(
        WorkflowExecutionError,
        match="server-owned artifact registry",
    ):
        port.complete(receipt, result)


def test_caller_cannot_replace_the_deployment_resolver_with_a_self_created_endpoint(
    tmp_path, monkeypatch
) -> None:
    """A Python caller cannot turn a self-created directory fd into host authority."""

    import workbench.agent.workflow_runtime as workflow_runtime

    workflow_directory = tmp_path / "workbench" / "workflows"
    workflow_directory.mkdir(parents=True)
    endpoint_fd = os.open(
        workflow_directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        forged_endpoint = object.__new__(WorkflowHostEndpointV1)
        object.__setattr__(forged_endpoint, "project_root", tmp_path)
        object.__setattr__(forged_endpoint, "workflow_evidence_root_fd", endpoint_fd)
        monkeypatch.setattr(
            workflow_runtime,
            "_deployment_host_endpoint_from_supervisor",
            lambda _root: forged_endpoint,
        )
        with pytest.raises(
            WorkflowExecutionError,
            match="deployment|supervisor|admitted",
        ):
            issue_server_evidence_port(tmp_path)
    finally:
        os.close(endpoint_fd)


def test_public_index_cannot_be_promoted_to_a_server_artifact_admission(tmp_path) -> None:
    """A caller-created index row is not a producer receipt."""

    draft = compile_fixture_workflow(workflow_id="wf-public-index-promotion")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    result = _evidence_result(tmp_path)

    with pytest.raises(
        WorkflowExecutionError,
        match="server-owned artifact registry|producer|admission",
    ):
        context_token = _WRITE_CONTEXT.set((port, receipt, draft, draft.steps[0]))
        try:
            port.admit_result_artifacts(receipt, result)
            port.complete(receipt, result)
        finally:
            _WRITE_CONTEXT.reset(context_token)


def test_foreign_run_requires_a_server_admitted_model_branch(tmp_path) -> None:
    """A self-consistent manifest/index/file trio cannot authorize a foreign model."""

    draft = compile_fixture_workflow(workflow_id="wf-foreign-server-admission")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])

    source_root = tmp_path / "runs" / "run-1"
    source_root.mkdir(parents=True)
    source_path = source_root / "data.csv"
    source_path.write_text("outcome,rate_a\n1,2\n", encoding="utf-8")
    initialize_artifact_index(source_root)
    register_artifact(
        source_root,
        "raw-1",
        source_path,
        "dataset",
        "ingestion",
        [],
    )

    foreign_root = tmp_path / "runs" / "foreign-model-run"
    model_path = foreign_root / "model_results" / "ols_1.json"
    model_path.parent.mkdir(parents=True)
    model_path.write_text(json.dumps({"model_family": "ols"}), encoding="utf-8")
    (foreign_root / "run_manifest.json").write_text(
        json.dumps({"run_id": "foreign-model-run", "status": "completed"}),
        encoding="utf-8",
    )
    initialize_artifact_index(foreign_root)
    register_artifact(
        foreign_root,
        "ols_1",
        model_path,
        "model_result",
        "model.genesis",
        ["raw-1"],
    )
    branch = {
        "branch_id": "main",
        "run_id": "foreign-model-run",
        "artifact_ids": ["ols_1"],
        "model_artifact_id": "ols_1",
        "workflow_id": draft.workflow_id,
        "workflow_step_id": draft.steps[0].step_id,
        "source_run_id": "run-1",
        "source_artifact_id": "raw-1",
        "source_sha256": sha256_file(source_path),
        "branch_spec": {
            "model_family": "ols",
            "covariance": "unadjusted",
            "outcome": "outcome",
            "predictors": ["rate_a"],
            "categorical": [],
            "polynomials": [],
        },
        "predictor_columns": ["rate_a"],
        "term_groups": {
            "linear": {"rate_a": ["rate_a"]},
            "polynomial": {},
            "categorical": {},
        },
    }
    result = WorkflowStepResult(
        artifact_ids=["foreign-model-run:ols_1"],
        row_counts={"source": 1},
        lineage={"branches": [branch]},
        output_bindings={
            "model": {
                "binding_type": "model",
                "run_id": "foreign-model-run",
                "node_ref": "model-node",
                "artifact_id": "ols_1",
                "content_sha256": sha256_file(model_path),
            }
        },
    )

    with pytest.raises(
        WorkflowExecutionError,
        match="server-owned artifact registry|admitted model branch|result artifact was not admitted",
    ):
        context_token = _WRITE_CONTEXT.set((port, receipt, draft, draft.steps[0]))
        try:
            port.admit_result_artifacts(receipt, result)
            port.complete(receipt, result)
        finally:
            _WRITE_CONTEXT.reset(context_token)


def test_completion_rejects_a_post_admission_digest_rebind_even_when_public_hash_changes(
    tmp_path,
) -> None:
    """Completion uses the frozen admission digest, not a rewritten public hash."""

    draft = compile_fixture_workflow(workflow_id="wf-post-admission-rebind")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    result = _evidence_result(
        tmp_path,
        port=port,
        receipt=receipt,
        draft=draft,
        step=draft.steps[0],
    )
    artifact_path = tmp_path / "runs" / "run-1" / "artifact.json"
    index_path = tmp_path / "runs" / "run-1" / "artifacts_index.json"
    artifact_path.write_text('{"tampered": true}\n', encoding="utf-8")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for item in index["artifacts"]:
        if item["artifact_id"] == "artifact-1":
            item["sha256"] = sha256_file(artifact_path)
    index_path.write_text(json.dumps(index), encoding="utf-8")
    result.output_bindings["dataset"]["content_sha256"] = sha256_file(artifact_path)

    with pytest.raises(
        WorkflowExecutionError,
        match="server-owned artifact|digest|admission",
    ):
        port.complete(receipt, result)


def test_report_rejects_previous_results_without_completed_admitted_registry_entries(
    tmp_path,
) -> None:
    """Report cannot turn caller-supplied previous results into evidence."""

    draft = compile_fixture_workflow(workflow_id="wf-report-forged-previous")
    report_step = next(step for step in draft.steps if step.operation_id == "report.compose")
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)
    initialize_artifact_index(run_root)
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, report_step)
    forged_previous = {
        "grouped": WorkflowStepResult(
            artifact_ids=["forged-previous-artifact"],
            row_counts={"source": 1},
        )
    }
    context_token = _WRITE_CONTEXT.set((port, receipt, draft, report_step))
    try:
        with pytest.raises(
            WorkflowExecutionError,
            match="completed|admitted|dependency|registry",
        ):
            _execute_workflow_report(tmp_path, draft, forged_previous, report_step)
    finally:
        _WRITE_CONTEXT.reset(context_token)


def test_formal_writer_rolls_back_when_parent_is_replaced_during_commit(
    tmp_path, monkeypatch
) -> None:
    """A root/path race must not leave the committed output in an outside directory."""

    import workbench.agent.workflow_runtime as workflow_runtime

    draft = compile_fixture_workflow(workflow_id="wf-formal-commit-race")
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)
    initialize_artifact_index(run_root)
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    outside = tmp_path / "outside"
    outside.mkdir()
    reports = run_root / "reports"

    original_replace = workflow_runtime.os.replace

    def replace_after_parent_move(*args, **kwargs):
        if reports.is_dir() and not reports.is_symlink():
            moved = outside / "reports"
            reports.rename(moved)
            reports.symlink_to(outside, target_is_directory=True)
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(workflow_runtime.os, "replace", replace_after_parent_move)
    context_token = _WRITE_CONTEXT.set((port, receipt, draft, draft.steps[0]))
    try:
        with pytest.raises(WorkflowExecutionError, match="PATH|registry|admission"):
            render_html_report(
                {"title": "race"},
                run_root,
                filename="race.html",
                evidence_port=port,
                admission_receipt=receipt,
            )
    finally:
        _WRITE_CONTEXT.reset(context_token)

    assert not (outside / "reports" / "race.html").exists()


def test_formal_registration_rolls_back_when_run_root_is_replaced_after_commit(
    tmp_path,
) -> None:
    """A post-commit root replacement cannot leave a file or index outside."""

    from workbench import reporting

    draft = compile_fixture_workflow(workflow_id="wf-formal-registration-race")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)
    initialize_artifact_index(run_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    moved_root = outside / "run-1"
    original_admit = EvidencePersistencePortClass._admit_server_artifact
    moved = False

    def move_then_admit(self, *args, **kwargs):
        nonlocal moved
        if not moved:
            moved = True
            os.replace(run_root, moved_root)
            run_root.mkdir(parents=True)
            initialize_artifact_index(run_root)
        return original_admit(self, *args, **kwargs)

    context_token = _WRITE_CONTEXT.set((port, receipt, draft, draft.steps[0]))
    try:
        with patch.object(
            EvidencePersistencePortClass,
            "_admit_server_artifact",
            move_then_admit,
        ):
            with pytest.raises(Exception):
                reporting.render_html_report(
                    {"title": "Race", "facts": [], "warnings": []},
                    run_root,
                    filename="race.html",
                    artifact_id="race_html",
                    evidence_port=port,
                    admission_receipt=receipt,
                )
    finally:
        _WRITE_CONTEXT.reset(context_token)

    assert moved
    assert not (moved_root / "reports" / "race.html").exists()
    for index_path in (
        moved_root / "artifacts_index.json",
        run_root / "artifacts_index.json",
    ):
        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert all(item.get("artifact_id") != "race_html" for item in index["artifacts"])


def test_formal_index_publish_rolls_back_when_run_root_is_replaced_after_admission(
    tmp_path,
) -> None:
    """Index publication must fail closed after admission, too."""

    from workbench import reporting

    draft = compile_fixture_workflow(workflow_id="wf-formal-index-race")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)
    initialize_artifact_index(run_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    moved_root = outside / "run-1"
    original_publish = EvidencePersistencePortClass._publish_formal_artifact_index
    moved = False

    def move_then_publish(self, output_target, row):
        nonlocal moved
        if not moved:
            moved = True
            os.replace(run_root, moved_root)
            run_root.mkdir(parents=True)
            initialize_artifact_index(run_root)
        return original_publish(self, output_target, row)

    context_token = _WRITE_CONTEXT.set((port, receipt, draft, draft.steps[0]))
    try:
        with patch.object(
            EvidencePersistencePortClass,
            "_publish_formal_artifact_index",
            move_then_publish,
        ):
            with pytest.raises(Exception):
                reporting.render_html_report(
                    {"title": "Race", "facts": [], "warnings": []},
                    run_root,
                    filename="race.html",
                    artifact_id="race_html",
                    evidence_port=port,
                    admission_receipt=receipt,
                )
    finally:
        _WRITE_CONTEXT.reset(context_token)

    assert moved
    assert not (moved_root / "reports" / "race.html").exists()
    for index_path in (
        moved_root / "artifacts_index.json",
        run_root / "artifacts_index.json",
    ):
        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert all(item.get("artifact_id") != "race_html" for item in index["artifacts"])


def test_formal_admission_rejects_file_rebind_after_commit(tmp_path) -> None:
    """A replacement at the final filename cannot become server evidence."""

    import workbench.agent.workflow_runtime as workflow_runtime

    draft = compile_fixture_workflow(workflow_id="wf-formal-file-rebind")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)
    initialize_artifact_index(run_root)
    original_admit = EvidencePersistencePortClass._admit_server_artifact

    def replace_file_before_admission(self, *args, **kwargs):
        path = Path(kwargs["path"])
        rebound = path.with_name(".rebound.html")
        rebound.write_bytes(b"attacker-controlled")
        os.replace(rebound, path)
        return original_admit(self, *args, **kwargs)

    context_token = _WRITE_CONTEXT.set((port, receipt, draft, draft.steps[0]))
    try:
        with patch.object(
            workflow_runtime.EvidencePersistencePort,
            "_admit_server_artifact",
            replace_file_before_admission,
        ):
            with pytest.raises(WorkflowExecutionError, match="PATH|registry|admission"):
                render_html_report(
                    {"title": "Rebind", "facts": [], "warnings": []},
                    run_root,
                    filename="rebind.html",
                    artifact_id="rebind_html",
                    evidence_port=port,
                    admission_receipt=receipt,
                )
    finally:
        _WRITE_CONTEXT.reset(context_token)

    index = json.loads((run_root / "artifacts_index.json").read_text(encoding="utf-8"))
    assert all(item.get("artifact_id") != "rebind_html" for item in index["artifacts"])


def test_formal_failure_restores_existing_destination_content(tmp_path) -> None:
    """A failed replacement preserves a pre-existing formal output."""

    import workbench.agent.workflow_runtime as workflow_runtime

    draft = compile_fixture_workflow(workflow_id="wf-formal-existing-rollback")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)
    initialize_artifact_index(run_root)
    existing = run_root / "reports" / "existing.html"
    existing.parent.mkdir()
    existing.write_bytes(b"old-content")

    def reject_admission(*_args, **_kwargs):
        raise WorkflowExecutionError("forced formal admission failure")

    context_token = _WRITE_CONTEXT.set((port, receipt, draft, draft.steps[0]))
    try:
        with patch.object(
            workflow_runtime.EvidencePersistencePort,
            "_admit_server_artifact",
            reject_admission,
        ):
            with pytest.raises(WorkflowExecutionError, match="forced formal admission failure"):
                render_html_report(
                    {"title": "Replacement", "facts": [], "warnings": []},
                    run_root,
                    filename="existing.html",
                    artifact_id="existing_html",
                    evidence_port=port,
                    admission_receipt=receipt,
                )
    finally:
        _WRITE_CONTEXT.reset(context_token)

    assert existing.read_bytes() == b"old-content"


def test_pending_runtime_output_duplicate_path_closes_replaced_target(tmp_path) -> None:
    """Replacing a pending target must close the superseded FD holder."""

    draft = compile_fixture_workflow(workflow_id="wf-pending-duplicate")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)
    initialize_artifact_index(run_root)
    context_token = _WRITE_CONTEXT.set((port, receipt, draft, draft.steps[0]))
    pending_token = _PENDING_RUNTIME_OUTPUTS.set({})
    try:
        path = _write_runtime_artifact_bytes(
            run_root,
            Path("derived/duplicate.bin"),
            b"same",
            occupied_message="duplicate path changed",
            retain_for_registry=True,
        )
        first = _PENDING_RUNTIME_OUTPUTS.get()[str(path)][0]
        _write_runtime_artifact_bytes(
            run_root,
            Path("derived/duplicate.bin"),
            b"same",
            occupied_message="duplicate path changed",
            retain_for_registry=True,
        )
        assert first.closed
    finally:
        for target, _destination_existed in list((_PENDING_RUNTIME_OUTPUTS.get() or {}).values()):
            target.rollback_committed()
            target.close()
        _PENDING_RUNTIME_OUTPUTS.reset(pending_token)
        _WRITE_CONTEXT.reset(context_token)


def _require_inherited_workflow_port(port, receipt, result_queue) -> None:
    try:
        port.require_receipt(receipt)
    except WorkflowExecutionError as error:
        result_queue.put(("error", str(error)))
    else:
        result_queue.put(("accepted", "inherited authority was accepted"))


def test_forked_process_rejects_inherited_workflow_authority_before_io(tmp_path) -> None:
    """A forked child cannot use the parent's port, receipt or registry."""

    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork is required for inherited-authority probe")
    draft = compile_fixture_workflow(workflow_id="wf-fork-authority")
    port = EvidencePersistencePort(tmp_path)
    receipt = port.admit(draft, draft.steps[0])
    context = multiprocessing.get_context("fork")
    result_queue = context.Queue()
    process = context.Process(
        target=_require_inherited_workflow_port,
        args=(port, receipt, result_queue),
    )
    process.start()
    process.join(10)
    assert process.exitcode == 0
    kind, message = result_queue.get(timeout=3)
    assert kind == "error", message
    assert re.search("process|fork|owner|generation|restart", message, re.IGNORECASE)
