"""Postestimation service for workflow execution."""

from __future__ import annotations
from dataclasses import replace
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import numpy as np
import pandas as pd
from scipy import stats
from ...artifacts import read_json, register_artifact, sha256_file, write_json, write_text_durable
from ...graph_model import BranchRef, Edge, Graph, Node, NodeKind, Stage, Trust
from ...graph_store import GraphStore
from ...model_terms import polynomial_column_name
from ...native_research import NATIVE_RESEARCH_OPERATIONS, native_result_caption
from ..context_compiler import read_workflow_artifact_index
from ..workflow import WorkflowDraft, WorkflowExecutionError, WorkflowStepResult
from ..workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
from .artifacts import _ensure_runtime_artifact
from .models import (
    _branch_covariance,
    _branch_kernel,
    _dependent_model_branch,
    _fitted_term_positions,
    _refit_completed_ols_branch,
    _selected_model_terms,
)
from .constants import _PRODUCED_DATASET_SCHEMA


def _persist_model_post_estimation_result(
    root: Path,
    draft: WorkflowDraft,
    step: Any,
    *,
    artifact_type: str,
    result: Mapping[str, Any],
    model_run_id: str,
    lineage: Mapping[str, str],
    model_artifact_id: str = "ols_1",
) -> WorkflowStepResult:
    """Persist one durable, idempotent post-estimation artifact on the source run.

    ``model_artifact_id`` defaults to the OLS branch the older model.* steps
    refit; the kernel-based postestimation.* steps name the model they read.
    """

    run_root = root / "runs" / str(draft.target["run_id"])
    token = str(step.fingerprint).removeprefix("sha256:")[:24]
    operation_token = str(step.operation_id).replace(".", "_")
    workflow_token = hashlib.sha256(draft.workflow_id.encode("utf-8")).hexdigest()[:16]
    artifact_id = f"workflow_{operation_token}_{workflow_token}_{token}"
    artifact_path = run_root / "artifacts" / artifact_type / f"{artifact_id}.json"
    payload = {
        "schema_version": "workbench.workflow.post-estimation/v1",
        "source": {
            # run_id stays the workflow's target run because that is where this
            # artifact is written; the node, artifact and digest name the data
            # the test was computed on, which a `source` commitment moves.
            "run_id": str(draft.target["run_id"]),
            "node_ref": str(lineage["node_ref"]),
            "artifact_id": str(lineage["artifact_id"]),
            "sha256": str(lineage["sha256"]),
            "model_run_id": model_run_id,
            "model_artifact_id": model_artifact_id,
            "workflow_id": draft.workflow_id,
            "workflow_step_id": step.step_id,
            "workflow_step_fingerprint": step.fingerprint,
        },
        "result": dict(result),
    }
    if artifact_type == "post_estimation":
        # Retain the compiled request whose fingerprints the durable executor
        # committed to, so exports can distinguish changed hypotheses from
        # genuinely executed results even if an artifact is re-registered.
        payload["execution"] = draft.to_dict()
    if artifact_path.exists():
        if read_json(artifact_path) != payload:
            raise WorkflowExecutionError("post-estimation artifact path is occupied")
    else:
        write_json(artifact_path, payload)
    index = read_workflow_artifact_index(run_root)
    existing = [
        item for item in index.get("artifacts", []) if item.get("artifact_id") == artifact_id
    ]
    if len(existing) > 1:
        raise WorkflowExecutionError("post-estimation artifact identity is duplicated")
    if not existing:
        register_artifact(
            run_root,
            artifact_id,
            artifact_path,
            artifact_type,
            str(step.operation_id),
            [str(lineage["artifact_id"])],
        )
    else:
        record = existing[0]
        if (
            record.get("artifact_type") != artifact_type
            or record.get("path") != artifact_path.relative_to(run_root).as_posix()
        ):
            raise WorkflowExecutionError("post-estimation artifact identity is inconsistent")
    return WorkflowStepResult(
        artifact_ids=[artifact_id],
        row_counts={},
        result_fingerprint=str(step.fingerprint),
        payload={"result": dict(result), "model_run_id": model_run_id},
    )



def _persist_p7_pack_result(
    root: Path,
    draft: WorkflowDraft,
    step: Any,
    *,
    result: Mapping[str, Any],
    lineage: Mapping[str, str],
    pack_family: str,
) -> WorkflowStepResult:
    """Persist one bounded P7 result with deterministic source provenance."""

    run_root = root / "runs" / str(draft.target["run_id"])
    token = str(step.fingerprint).removeprefix("sha256:")[:24]
    operation_token = str(step.operation_id).replace(".", "_")
    workflow_token = hashlib.sha256(draft.workflow_id.encode("utf-8")).hexdigest()[:16]
    artifact_id = f"workflow_p7_{operation_token}_{workflow_token}_{token}"
    artifact_path = run_root / "artifacts" / "p7_analysis" / f"{artifact_id}.json"
    payload = {
        "schema_version": "workbench.workflow.p7-pack/v1",
        "source": {
            "run_id": str(draft.target["run_id"]),
            "node_ref": str(lineage["node_ref"]),
            "artifact_id": str(lineage["artifact_id"]),
            "sha256": str(lineage["sha256"]),
            "workflow_id": draft.workflow_id,
            "workflow_step_id": step.step_id,
            "workflow_step_fingerprint": step.fingerprint,
            "operation_id": step.operation_id,
            "pack_family": pack_family,
        },
        "result": dict(result),
    }
    if artifact_path.exists():
        if read_json(artifact_path) != payload:
            raise WorkflowExecutionError("P7 analysis artifact path is occupied")
    else:
        write_json(artifact_path, payload)
    index = read_workflow_artifact_index(run_root)
    existing = [
        item for item in index.get("artifacts", []) if item.get("artifact_id") == artifact_id
    ]
    if len(existing) > 1:
        raise WorkflowExecutionError("P7 analysis artifact identity is duplicated")
    if not existing:
        register_artifact(
            run_root,
            artifact_id,
            artifact_path,
            "p7_analysis",
            str(step.operation_id),
            [str(lineage["artifact_id"])],
        )
    else:
        record = existing[0]
        if (
            record.get("artifact_type") != "p7_analysis"
            or record.get("path") != artifact_path.relative_to(run_root).as_posix()
        ):
            raise WorkflowExecutionError("P7 analysis artifact identity is inconsistent")
    row_counts: dict[str, int] = {}
    for field_name in ("n_observations", "n_rows", "n_units"):
        value = result.get(field_name)
        if type(value) is int and value >= 0:
            row_counts[field_name] = value
    return WorkflowStepResult(
        artifact_ids=[artifact_id],
        row_counts=row_counts,
        result_fingerprint=str(step.fingerprint),
        payload={"result": dict(result)},
    )



def _workflow_request_fingerprint(request: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()



def _persist_quant_replay_ledger(run_root, primary_id, frame, lineage, rows):
    """Save the existing replay's local table beside its unchanged primary result."""
    from ...checks.ar_cancellation import check_cancellation
    from ...data_operations.frames import _write_frame_artifact
    from ...native_quant_replay import REPLAY_LEDGER_COLUMNS, MAX_PERIODS

    if (not isinstance(frame, pd.DataFrame) or not 1 <= len(frame) <= MAX_PERIODS
            or len(frame) != rows or tuple(frame.columns) != REPLAY_LEDGER_COLUMNS):
        raise WorkflowExecutionError("quant.replay returned an invalid complete ledger")
    artifact_id = "quant_replay_ledger_" + primary_id.removeprefix("workflow_capability_quant_replay_")
    path = run_root / "tables" / "quant_replay" / f"{artifact_id}.csv"
    primary_path = run_root / "artifacts" / "workflow_capability" / f"{primary_id}.json"
    records = read_workflow_artifact_index(run_root).get("artifacts", [])
    for identity, expected_path, kind, inputs, required in (
        (primary_id, primary_path, "workflow_capability_result", [str(lineage["artifact_id"])], True),
        (artifact_id, path, "quant_replay_ledger", [str(lineage["artifact_id"]), primary_id], False),
    ):
        matches = [item for item in records if item.get("artifact_id") == identity]
        if (len(matches) > 1 or required and not matches or matches and (
                any(matches[0].get(key) != value for key, value in {
                    "path": expected_path.relative_to(run_root).as_posix(), "artifact_type": kind,
                    "step": "quant.replay", "inputs": inputs,
                }.items()) or not expected_path.is_file() or matches[0].get("sha256") != sha256_file(expected_path))):
            raise WorkflowExecutionError("quant.replay ledger source or artifact binding changed")
    check_cancellation()
    _write_frame_artifact(path, frame, "csv")
    check_cancellation()
    _ensure_runtime_artifact(run_root, artifact_id=artifact_id, path=path,
        artifact_type="quant_replay_ledger", step="quant.replay", inputs=[str(lineage["artifact_id"]), primary_id])
    return {"type": "quant_replay_ledger", "artifact_id": artifact_id,
            "sha256": sha256_file(path), "row_count": len(frame)}


def _publish_native_result_node(
    run_root: Path,
    lineage: Mapping[str, str],
    artifact_id: str,
    artifact_path: Path,
    label: str,
    operation_id: str,
    caption: str,
    *,
    replay_ledger: Mapping[str, Any] | None = None,
) -> None:
    node_id = f"native-result:{artifact_id}"
    source_node = lineage["node_ref"]
    relative = artifact_path.relative_to(run_root).as_posix()
    node_hash = sha256_file(artifact_path)
    index_path = run_root / "node_index.json"
    entry = {"node_hash": node_hash, "producing_stage": operation_id,
             "cas_ref": {"node_hash": node_hash, "artifact": relative}}
    edge_id = f"edge:{node_id}"

    def attach(graph: Graph) -> Graph:
        if source_node not in graph.nodes:
            raise WorkflowExecutionError("native result source node is missing")
        index = read_json(index_path) if index_path.is_file() else {}
        if node_id in index and index[node_id] != entry:
            raise WorkflowExecutionError("native result node index identity changed")
        existing = graph.nodes.get(node_id)
        if existing is not None and (existing.payload_ref != relative or existing.parent_stage_id != source_node):
            raise WorkflowExecutionError("native result node identity changed")
        if replay_ledger is not None and existing is not None and (
                existing.node_hash != node_hash or existing.kind != NodeKind.OPERATION):
            raise WorkflowExecutionError("native replay result node identity changed")
        if node_id not in index:
            write_json(index_path, {**index, node_id: entry})
        if existing is not None:
            if replay_ledger is not None:
                recorded = [item for item in existing.annotations if item.get("type") == "quant_replay_ledger"]
                if recorded and recorded != [replay_ledger]:
                    raise WorkflowExecutionError("native replay ledger binding changed")
                if not recorded:
                    return replace(graph, nodes={**graph.nodes,
                        node_id: replace(existing, annotations=(*existing.annotations, dict(replay_ledger)))})
            return graph
        return replace(
            graph,
            nodes={**graph.nodes, node_id: Node(
                id=node_id, kind=NodeKind.OPERATION, display_label=label, stage=Stage.MODEL,
                parent_stage_id=source_node, branch_id=node_id,
                created_at=datetime.now(timezone.utc).isoformat(), payload_ref=relative,
                node_hash=node_hash, summary=caption,
                annotations=() if replay_ledger is None else (dict(replay_ledger),),
            )},
            edges={**graph.edges, edge_id: Edge(edge_id, source_node, node_id, operation_id)},
            branches={**graph.branches, node_id: BranchRef(node_id, source_node, (node_id,))},
        )

    GraphStore(run_root.parent).mutate(run_root.name, attach)


def _persist_workflow_capability_result(
    root: Path,
    draft: WorkflowDraft,
    step: Any,
    *,
    lineage: Mapping[str, str],
    request: Mapping[str, Any],
    execution: Any,
) -> WorkflowStepResult:
    """Persist one generic capability result or one typed dataset child.

    The adapter decides whether it produced a dataset.  This function owns the
    common durability boundary: normalized request, source binding, result
    digest, registered artifact, and (for datasets) a graph/node binding that a
    later step can resolve without reopening the original target.
    """

    run_id = str(draft.target["run_id"])
    run_root = root / "runs" / run_id
    token = str(step.fingerprint).removeprefix("sha256:")[:24]
    operation_token = str(step.operation_id).replace(".", "_")
    request_fingerprint = _workflow_request_fingerprint(request)
    result_payload = dict(execution.payload)
    replay_ledger = step.operation_id == "quant.replay"
    if replay_ledger:
        from ...checks.ar_cancellation import check_cancellation

        check_cancellation()
    if execution.output_frame is None or replay_ledger:
        # One artifact per workflow: the same step asked for again (a second
        # conversation, a repeated question) is a new run with its own record.
        workflow_token = hashlib.sha256(draft.workflow_id.encode("utf-8")).hexdigest()[:16]
        artifact_id = f"workflow_capability_{operation_token}_{workflow_token}_{token}"
        artifact_path = run_root / "artifacts" / "workflow_capability" / f"{artifact_id}.json"
        result_digest = hashlib.sha256(
            json.dumps(result_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        envelope = {
            "schema_version": "workbench.workflow.capability/v1",
            "contract_version": "v1",
            "source": {
                "run_id": run_id,
                "node_ref": str(lineage["node_ref"]),
                "artifact_id": str(lineage["artifact_id"]),
                "sha256": str(lineage["sha256"]),
                "workflow_id": draft.workflow_id,
                "workflow_step_id": str(step.step_id),
                "workflow_step_fingerprint": str(step.fingerprint),
                "operation_id": str(step.operation_id),
            },
            "request": dict(request),
            "request_fingerprint": request_fingerprint,
            "result_schema": str(step.contract.output_schema_ref) if hasattr(step, "contract") else str(
                WORKFLOW_STEP_SPEC_CONTRACTS[step.operation_id].output_schema_ref
            ),
            "result_sha256": result_digest,
            "result": result_payload,
        }
        # Local artifact views can display bounded timelines. The operation
        # receipt and the report/Agent evidence readers only receive result.
        artifact_payload = envelope
        if execution.local_detail is not None:
            artifact_payload = {**envelope, "local_detail": execution.local_detail}
        if artifact_path.exists():
            if read_json(artifact_path) != artifact_payload:
                raise WorkflowExecutionError("workflow capability artifact path is occupied")
        else:
            write_json(artifact_path, artifact_payload)
        index = read_workflow_artifact_index(run_root)
        existing = [item for item in index.get("artifacts", []) if item.get("artifact_id") == artifact_id]
        if len(existing) > 1:
            raise WorkflowExecutionError("workflow capability artifact identity is duplicated")
        if not existing:
            register_artifact(
                run_root,
                artifact_id,
                artifact_path,
                "workflow_capability_result",
                str(step.operation_id),
                [str(lineage["artifact_id"])],
            )
        elif existing[0].get("path") != artifact_path.relative_to(run_root).as_posix():
            raise WorkflowExecutionError("workflow capability artifact identity is inconsistent")
        ledger = (_persist_quant_replay_ledger(run_root, artifact_id, execution.output_frame,
                  lineage, result_payload.get("n_rows")) if replay_ledger else None)
        native = NATIVE_RESEARCH_OPERATIONS.get(step.operation_id)
        if native is not None:
            _publish_native_result_node(
                run_root, lineage, artifact_id, artifact_path, native.label, step.operation_id,
                native_result_caption(result_payload),
                replay_ledger=ledger,
            )
        row_counts = {
            key: int(result_payload[key])
            for key in ("n_observations", "n_rows", "input_rows", "output_rows", "row_count")
            if type(result_payload.get(key)) is int and result_payload[key] >= 0
        }
        return WorkflowStepResult(
            artifact_ids=[artifact_id, *([ledger["artifact_id"]] if ledger is not None else [])],
            row_counts=row_counts,
            result_fingerprint=str(step.fingerprint),
            payload={"result": result_payload, "record": envelope},
        )

    output_frame = execution.output_frame
    saved_prediction = step.operation_id == "prediction.native_forest_apply"
    if saved_prediction:
        from ...checks.ar_cancellation import check_cancellation

        check_cancellation()
    if not isinstance(output_frame, pd.DataFrame) or output_frame.empty:
        raise WorkflowExecutionError(
            f"workflow capability {step.operation_id} declared a dataset but returned no non-empty frame"
        )
    dataset_kind = execution.dataset_kind
    if not isinstance(dataset_kind, str) or not dataset_kind:
        raise WorkflowExecutionError(
            f"workflow capability {step.operation_id} returned a dataset without a server-owned dataset role"
        )
    capability_dir = Path("derived") / "workflow_capability" / token
    data_rel = (capability_dir / "data.csv").as_posix()
    data_path = run_root / data_rel
    schema_path = data_path.with_name(data_path.stem + ".schema.json")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    if data_path.exists():
        try:
            existing_frame = pd.read_csv(data_path)
            pd.testing.assert_frame_equal(existing_frame, output_frame.reset_index(drop=True), check_dtype=False)
        except (AssertionError, OSError, ValueError) as exc:
            raise WorkflowExecutionError("workflow capability dataset path is occupied") from exc
    else:
        csv_text = output_frame.to_csv(index=False)
        if saved_prediction:
            check_cancellation()
        write_text_durable(data_path, csv_text)
    schema = {"dtypes": {str(column): str(output_frame[column].dtype) for column in output_frame.columns}}
    if schema_path.exists():
        try:
            existing_schema = read_json(schema_path)
        except (OSError, ValueError) as exc:
            raise WorkflowExecutionError(
                "workflow capability dataset schema path is unreadable"
            ) from exc
        if existing_schema != schema:
            raise WorkflowExecutionError(
                "workflow capability dataset schema path is occupied"
            )
    else:
        write_json(schema_path, schema)
    data_sha256 = sha256_file(data_path)
    data_artifact_id = f"workflow_capability_dataset_{operation_token}_{token}"
    metadata_artifact_id = f"workflow_capability_dataset_metadata_{operation_token}_{token}"
    metadata_rel = (capability_dir / "metadata.json").as_posix()
    metadata_path = run_root / metadata_rel
    metadata = {
        "schema_version": "workbench.workflow.capability-dataset/v1",
        "operation_id": str(step.operation_id),
        "dataset_kind": dataset_kind,
        "source": {
            "run_id": run_id,
            "node_ref": str(lineage["node_ref"]),
            "artifact_id": str(lineage["artifact_id"]),
            "sha256": str(lineage["sha256"]),
        },
        "request": dict(request),
        "request_fingerprint": request_fingerprint,
        "result": result_payload,
        "data_sha256": data_sha256,
    }
    model_source = result_payload.get("model_source") if step.operation_id == "prediction.native_forest_apply" else None
    if saved_prediction:
        check_cancellation()
    inputs = [str(lineage["artifact_id"])]
    if model_source is not None:
        model_input = str(model_source["artifact_id"])
        if model_source["run_id"] != run_id:
            model_input = f"{model_source['run_id']}:{model_input}"
        inputs.append(model_input)
    if metadata_path.exists() and read_json(metadata_path) != metadata:
        raise WorkflowExecutionError("workflow capability dataset metadata path is occupied")
    if not metadata_path.exists():
        write_json(metadata_path, metadata)
    _ensure_runtime_artifact(
        run_root,
        artifact_id=data_artifact_id,
        path=data_path,
        artifact_type=str(execution.artifact_type),
        step=str(step.operation_id),
        inputs=inputs,
    )
    _ensure_runtime_artifact(
        run_root,
        artifact_id=metadata_artifact_id,
        path=metadata_path,
        artifact_type="workflow_capability_metadata",
        step=str(step.operation_id),
        inputs=[*inputs, data_artifact_id],
    )
    child_node_id = f"workflow-capability:{operation_token}:{token}"
    branch_id = f"workflow-capability:{token[:20]}"

    def add_child(graph: Graph) -> Graph:
        if child_node_id in graph.nodes:
            return graph
        model_annotations = () if model_source is None else ({"type": "prediction_model_source", **model_source},)
        model_edges = {}
        if model_source is not None and model_source["run_id"] == run_id:
            model_node = model_source["node_id"]
            if model_node not in graph.nodes:
                raise WorkflowExecutionError("saved prediction model source node is missing")
            edge_id = f"edge:model:{child_node_id}"
            model_edges[edge_id] = Edge(edge_id, model_node, child_node_id, str(step.operation_id),
                                        {"model_sha256": model_source["sha256"]})
        child = Node(
            id=child_node_id,
            kind=NodeKind.DATASET_STAGE,
            display_label=f"{step.operation_id} dataset",
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_stage_id=str(lineage["node_ref"]),
            branch_id=branch_id,
            trust=Trust.OK,
            payload_ref=data_rel,
            summary=f"{dataset_kind}; {len(output_frame)} rows",
            annotations=({
                "type": "workflow_capability_dataset",
                "operation_id": str(step.operation_id),
                "workflow_id": draft.workflow_id,
                "workflow_step_id": str(step.step_id),
                "dataset_kind": dataset_kind,
                "metadata_path": metadata_rel,
            }, *model_annotations),
            stage=Stage.TRANSFORM,
        )
        return Graph(
            schema_version=graph.schema_version,
            run_id=graph.run_id,
            nodes={**graph.nodes, child_node_id: child},
            edges={
                **graph.edges,
                **model_edges,
                f"edge:{child_node_id}": Edge(
                    id=f"edge:{child_node_id}",
                    source_id=str(lineage["node_ref"]),
                    target_id=child_node_id,
                    op=str(step.operation_id),
                    params={"workflow_step_id": str(step.step_id)},
                ),
            },
            branches={
                **graph.branches,
                branch_id: BranchRef(
                    id=branch_id,
                    forked_from_node_id=str(lineage["node_ref"]),
                    head_node_ids=(child_node_id,),
                ),
            },
            legacy=graph.legacy,
        )

    GraphStore(root / "runs").mutate(run_id, add_child)
    node_index_path = run_root / "node_index.json"
    node_index = read_json(node_index_path) if node_index_path.is_file() else {}
    node_entry = {
        "node_hash": data_sha256,
        "producing_stage": str(step.operation_id),
        "cas_ref": {"node_hash": data_sha256, "artifact": data_rel},
    }
    existing_node = node_index.get(child_node_id)
    if existing_node is not None and existing_node != node_entry:
        raise WorkflowExecutionError("workflow capability dataset node identity is not deterministic")
    if existing_node is None:
        write_json(node_index_path, {**node_index, child_node_id: node_entry})
    result_payload = {
        **result_payload,
        "produced_dataset": {
            "schema_version": _PRODUCED_DATASET_SCHEMA,
            "run_id": run_id,
            "node_ref": child_node_id,
            "artifact_id": data_artifact_id,
            "content_sha256": data_sha256,
            "dataset_kind": dataset_kind,
            "result_fingerprint": str(step.fingerprint),
        },
    }
    return WorkflowStepResult(
        artifact_ids=[data_artifact_id, metadata_artifact_id],
        row_counts={
            "input_rows": int(result_payload.get("input_rows", 0) or 0),
            "output_rows": int(len(output_frame)),
        },
        result_fingerprint=str(step.fingerprint),
        payload={"result": result_payload, "produced_dataset": result_payload["produced_dataset"]},
    )



def _execute_model_joint_f_test(
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
) -> WorkflowStepResult:
    """Joint test of declared term groups, read from the branch's kernel.

    Inference engine v2: the test uses the covariance and the degrees of
    freedom the branch reported (F(q, N - K) for unadjusted and robust,
    F(q, G - 1) for clustered), so it cannot disagree with the coefficient
    table, and nothing is refitted.
    """
    from ...postestimation import PostestimationRefusal, wald_test

    branch = _dependent_model_branch(step, previous)
    selectors = step.spec.get("term_selectors")
    if not isinstance(selectors, list):
        raise WorkflowExecutionError("joint F test term selectors are unavailable")
    branch_spec = branch.get("branch_spec")
    family = branch_spec.get("model_family") if isinstance(branch_spec, Mapping) else None
    if family != "ols":
        raise WorkflowExecutionError(
            f"this post-estimation step is defined for OLS models only; branch "
            f"{branch.get('branch_id')} was estimated as {family or 'an undeclared family'}"
        )
    terms = _selected_model_terms(branch, selectors)
    kernel = _branch_kernel(root, branch)
    try:
        test = wald_test(kernel, [{"terms": {term: 1}, "value": 0} for term in terms])
    except PostestimationRefusal as refusal:
        raise WorkflowExecutionError(refusal.message) from refusal
    if test["distribution"] != "F":
        raise WorkflowExecutionError(
            "the branch reports asymptotic inference, so its joint test is a chi-square Wald test; "
            "use postestimation.wald"
        )
    result = {
        "schema_version": "workbench.model.joint-f-test/v1",
        "test": "joint_f_test",
        "branch_id": str(branch["branch_id"]),
        "term_selectors": [dict(item) for item in selectors if isinstance(item, Mapping)],
        "coefficient_terms": terms,
        "f_statistic": float(test["statistic"]),
        "p_value": float(test["p_value"]),
        "numerator_df": float(test["df_num"]),
        "denominator_df": float(test["df_den"]),
        "distribution": test["distribution"],
        "df_method": kernel.get("df_method"),
        "nobs": int(kernel["nobs"]),
        "covariance": _branch_covariance(branch_spec),
    }
    return _persist_model_post_estimation_result(
        root,
        draft,
        step,
        artifact_type="statistical_test",
        result=result,
        model_run_id=str(branch["run_id"]),
        lineage=lineage,
    )



def _white_test_statistics(
    residuals: Any,
    exog: Any,
) -> tuple[float, float, float, float, int, int]:
    """Calculate White's test with one explicit auxiliary-design rank policy.

    The auxiliary design contains every square and pairwise product of the
    completed OLS design.  Its columns can differ widely in scale when a model
    mixes polynomials and categorical expansions.  Normalize non-zero columns
    before choosing the rank and use that exact tolerance for the least-squares
    solve, so statistical validity does not depend on a third-party assertion
    comparing two incompatible rank estimates.
    """

    errors = np.asarray(residuals, dtype=float).reshape(-1)
    design = np.asarray(exog, dtype=float)
    if design.ndim != 2 or design.shape[0] != errors.size:
        raise WorkflowExecutionError("White test received an invalid completed OLS design")
    if errors.size < 3 or not np.isfinite(errors).all() or not np.isfinite(design).all():
        raise WorkflowExecutionError("White test requires finite residuals and design values")

    left, right = np.triu_indices(design.shape[1])
    auxiliary = design[:, left] * design[:, right]
    scales = np.linalg.norm(auxiliary, axis=0)
    usable = scales > 0
    if not bool(usable.any()):
        raise WorkflowExecutionError("White test auxiliary design has no non-zero columns")
    normalized = auxiliary[:, usable] / scales[usable]
    singular_values = np.linalg.svd(normalized, compute_uv=False)
    if singular_values.size == 0 or not math.isfinite(float(singular_values[0])):
        raise WorkflowExecutionError("White test auxiliary design rank is unavailable")
    rcond = max(normalized.shape) * np.finfo(float).eps
    rank = int((singular_values > singular_values[0] * rcond).sum())
    auxiliary_df = rank - 1
    residual_df = errors.size - rank
    if auxiliary_df < 1 or residual_df < 1:
        raise WorkflowExecutionError(
            "White test auxiliary design does not leave enough independent degrees of freedom"
        )

    squared_errors = errors**2
    centered = squared_errors - squared_errors.mean()
    total_sum_squares = float(centered @ centered)
    scale = max(float(squared_errors @ squared_errors), 1.0)
    if total_sum_squares <= np.finfo(float).eps * scale:
        raise WorkflowExecutionError("White test residual squares have no estimable variation")
    coefficients, *_ = np.linalg.lstsq(normalized, squared_errors, rcond=rcond)
    fitted = normalized @ coefficients
    residual_sum_squares = float(np.square(squared_errors - fitted).sum())
    r_squared = 1.0 - residual_sum_squares / total_sum_squares
    if not math.isfinite(r_squared) or r_squared < -1e-9 or r_squared > 1.0 + 1e-9:
        raise WorkflowExecutionError("White test auxiliary regression produced an invalid R-squared")
    r_squared = min(1.0, max(0.0, r_squared))
    unexplained = 1.0 - r_squared
    if unexplained <= np.finfo(float).eps:
        raise WorkflowExecutionError("White test auxiliary regression is saturated")

    lm_statistic = errors.size * r_squared
    f_statistic = (r_squared / auxiliary_df) / (unexplained / residual_df)
    lm_p_value = float(stats.chi2.sf(lm_statistic, auxiliary_df))
    f_p_value = float(stats.f.sf(f_statistic, auxiliary_df, residual_df))
    values = (lm_statistic, lm_p_value, f_statistic, f_p_value)
    if not all(math.isfinite(value) for value in values):
        raise WorkflowExecutionError("White test produced a non-finite result")
    return (*values, auxiliary_df, residual_df)



def _execute_model_white_test(
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
) -> WorkflowStepResult:
    """Persist White's test from the immutable, declared OLS design."""

    branch = _dependent_model_branch(step, previous)
    fitted, _predictor_columns, _analysis_frame = _refit_completed_ols_branch(
        source_frame, branch
    )
    (
        lm_statistic,
        lm_p_value,
        f_statistic,
        f_p_value,
        auxiliary_df,
        residual_df,
    ) = _white_test_statistics(
        fitted.resid,
        fitted.model.exog,
    )
    result = {
        "schema_version": "workbench.model.white-test/v1",
        "test": "white_test",
        "branch_id": str(branch["branch_id"]),
        "lm_statistic": lm_statistic,
        "lm_p_value": lm_p_value,
        "f_statistic": f_statistic,
        "f_p_value": f_p_value,
        "auxiliary_df": auxiliary_df,
        "residual_df": residual_df,
        "nobs": int(fitted.nobs),
        "covariance": _branch_covariance(branch["branch_spec"]),
    }
    return _persist_model_post_estimation_result(
        root,
        draft,
        step,
        artifact_type="statistical_test",
        result=result,
        model_run_id=str(branch["run_id"]),
        lineage=lineage,
    )



def _execute_model_quadratic_stationary_point(
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
) -> WorkflowStepResult:
    branch = _dependent_model_branch(step, previous)
    column = str(step.spec["column"])
    groups = branch.get("term_groups")
    branch_spec = branch.get("branch_spec")
    if not isinstance(groups, Mapping) or not isinstance(branch_spec, Mapping):
        raise WorkflowExecutionError("completed model branch lacks declared-term provenance")
    linear_terms = groups.get("linear", {}).get(column) if isinstance(groups.get("linear"), Mapping) else None
    polynomial_terms = groups.get("polynomial", {}).get(column) if isinstance(groups.get("polynomial"), Mapping) else None
    degree = next(
        (
            item.get("degree")
            for item in branch_spec.get("polynomials", []) or []
            if isinstance(item, Mapping) and item.get("column") == column
        ),
        None,
    )
    if linear_terms != [column] or polynomial_terms != [polynomial_column_name(column, 2)] or degree != 2:
        raise WorkflowExecutionError(
            "stationary point requires a declared linear-plus-degree-two polynomial term: "
            + column
        )
    fitted, _predictor_columns, analysis_frame = _refit_completed_ols_branch(
        source_frame, branch
    )
    linear_position, quadratic_position = _fitted_term_positions(
        fitted,
        [column, polynomial_column_name(column, 2)],
    )
    parameters = np.asarray(fitted.params, dtype=float)
    linear_coefficient = float(parameters[linear_position])
    quadratic_coefficient = float(parameters[quadratic_position])
    if not all(math.isfinite(value) for value in (linear_coefficient, quadratic_coefficient)):
        raise WorkflowExecutionError("stationary point coefficients are non-finite")
    if quadratic_coefficient == 0.0:
        raise WorkflowExecutionError("stationary point is undefined because the quadratic coefficient is zero")
    stationary_point = -linear_coefficient / (2.0 * quadratic_coefficient)
    if not math.isfinite(stationary_point):
        raise WorkflowExecutionError("stationary point is non-finite")
    observed_values = pd.to_numeric(analysis_frame[column], errors="coerce")
    observed_values = observed_values[np.isfinite(observed_values.to_numpy(dtype=float))]
    if observed_values.empty:
        raise WorkflowExecutionError(
            "stationary point analysis sample has no finite values for the declared column"
        )
    observed_min = float(observed_values.min())
    observed_max = float(observed_values.max())
    result = {
        "schema_version": "workbench.model.quadratic-stationary-point/v1",
        "branch_id": str(branch["branch_id"]),
        "column": column,
        "linear_coefficient": linear_coefficient,
        "quadratic_coefficient": quadratic_coefficient,
        "stationary_point": stationary_point,
        "observed_min": observed_min,
        "observed_max": observed_max,
        "stationary_point_within_observed_range": observed_min <= stationary_point <= observed_max,
        "curvature": "minimum" if quadratic_coefficient > 0 else "maximum",
        "nobs": int(fitted.nobs),
        "covariance": _branch_covariance(branch["branch_spec"]),
    }
    return _persist_model_post_estimation_result(
        root,
        draft,
        step,
        artifact_type="post_estimation",
        result=result,
        model_run_id=str(branch["run_id"]),
        lineage=lineage,
    )
