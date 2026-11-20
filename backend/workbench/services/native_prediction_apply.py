"""Authenticate a saved native forest before preview or shared execution."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..api_errors import WorkbenchAPIError
from ..graph_model import NodeKind
from ..graph_store import GraphStore
from ..lineage.node_write_validation import _is_simple_run_id
from ..native_prediction_apply import (
    OPERATION_ID, CLASSIFICATION_OPERATION, TRAINING_OPERATIONS, apply_output_columns,
    forest_buffer, score_saved_forest, validate_apply_frame,
)
from ..native_research import NATIVE_RESEARCH_OPERATIONS, native_result_operation, read_native_result_bytes
from ..repository.run_repository import _read_artifacts_index, _resolve_artifact_path, _resolve_run_root


def load_saved_forest(project_root, options):
    """Read only the result jointly attested by registry, graph and node index."""
    run_id, artifact_id, digest = (options.get(name) for name in (
        "model_run_id", "model_artifact_id", "model_sha256"))
    error = "FOREST_APPLY_MODEL_INVALID: select an unchanged, registered regression or binary forest result"
    training_operation = native_result_operation(artifact_id) if isinstance(artifact_id, str) else None
    if (not isinstance(run_id, str) or not _is_simple_run_id(run_id)
            or training_operation not in TRAINING_OPERATIONS
            or not isinstance(digest, str) or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)):
        raise ValueError(error)
    try:
        run_root = _resolve_run_root(str(project_root), run_id)
        entries = _read_artifacts_index(run_root)["artifacts"]
        if not isinstance(entries, list):
            raise ValueError(error)
        records = [entry for entry in entries if isinstance(entry, dict) and entry.get("artifact_id") == artifact_id]
        if len(records) != 1 or records[0].get("sha256") != digest:
            raise ValueError(error)
        entry = records[0]
        path = _resolve_artifact_path(run_root, entry)
        node_id = f"native-result:{artifact_id}"
        node = GraphStore(run_root.parent).read(run_id).nodes.get(node_id)
        if (node is None or node.kind != NodeKind.OPERATION or node.payload_ref != entry["path"]
                or node.node_hash != digest):
            raise ValueError(error)
        raw = read_native_result_bytes(run_root, entry, path, training_operation)
        if raw is None:
            raise ValueError(error)
        saved = json.loads(raw)
        source, request, result = saved["source"], saved["request"], saved["result"]
        if (saved.get("schema_version") != "workbench.workflow.capability/v1"
                or source.get("operation_id") != training_operation or source.get("run_id") != run_id
                or source.get("node_ref") != node.parent_stage_id
                or request.get("operation_id") != training_operation
                or result.get("operation_id") != training_operation
                or result.get("model_type") != training_operation.removeprefix("prediction.")):
            raise ValueError(error)
        basis = saved["local_detail"]["prediction_basis"]
        forest = forest_buffer(result, basis)
        pin = {"run_id": run_id, "node_id": node_id, "artifact_id": artifact_id, "sha256": digest,
               "training_source": {key: source[key] for key in ("run_id", "node_ref", "artifact_id", "sha256")}}
        return result, forest, pin
    except (WorkbenchAPIError, OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError(error) from exc


def preview_saved_forest(project_root, frame, options):
    result, forest, pin = load_saved_forest(project_root, options)
    columns = _output_columns(frame, options, result)
    validate_apply_frame(frame, forest[0], columns[0])
    return result, forest, pin


def _output_columns(frame, options, result):
    columns = apply_output_columns(options, classification=result["operation_id"] == CLASSIFICATION_OPERATION)
    if any(column in frame.columns for column in columns):
        raise ValueError("FOREST_APPLY_INVALID_OUTPUT: choose new output column names")
    return columns


def execute_saved_forest(project_root, frame, request):
    """The caller has entered the normal approved workflow execution boundary."""
    from ..agent.workflow_capability_adapters import WorkflowCapabilityExecution

    options = request["options"]
    result, forest, pin = load_saved_forest(project_root, options)
    columns = _output_columns(frame, options, result)
    column = columns[0]
    classification = result["operation_id"] == CLASSIFICATION_OPERATION
    predictions, receipt = score_saved_forest(frame, forest=forest, prediction_column=column, classification=classification)
    # Existing input blocks stay shared; only the new score vector is allocated.
    output = frame.copy(deep=False)
    output[column] = (predictions >= .5).astype(np.int64) if classification else predictions
    if classification:
        output[columns[1]] = predictions
    return WorkflowCapabilityExecution(
        payload={
            "schema_version": 1, "operation_id": OPERATION_ID, "dataset_kind": "derived_data",
            "input_rows": len(frame), "output_rows": len(output), "prediction_column": column,
            "model_type": result["model_type"], "engine": result["engine"],
            "predictors": list(result["predictors"]), "model_source": pin,
            "training_native_build": result["native_build"], "native_build": receipt,
            "assumptions": list(NATIVE_RESEARCH_OPERATIONS[OPERATION_ID].assumptions),
            "prediction_summary": {"minimum": float(np.min(predictions)), "maximum": float(np.max(predictions))},
            **({"probability_column": columns[1], "classification_threshold": .5,
                "prediction_summary": {"minimum": int(output[column].min()), "maximum": int(output[column].max())},
                "probability_summary": {"minimum": float(np.min(predictions)), "maximum": float(np.max(predictions))},
            } if classification else {}),
            "policy": {"scope": "offline_prediction", "refit": False, "row_order": "input_order",
                       "outcome_required": False, "evaluation_metrics": False},
        },
        output_frame=output, dataset_kind="derived_data", artifact_type="derived_data",
    )


def saved_forest_choices(project_root) -> list[dict]:
    """Publish at most 100 authenticated choices without exposing their trees."""
    runs = Path(project_root).expanduser().resolve() / "runs"
    if not runs.is_dir():
        return []
    choices = []
    for run_root in sorted(runs.iterdir(), key=lambda path: path.name, reverse=True):
        if not run_root.is_dir() or not _is_simple_run_id(run_root.name):
            continue
        try:
            run_root = _resolve_run_root(str(project_root), run_root.name)
            entries = _read_artifacts_index(run_root)["artifacts"]
        except (WorkbenchAPIError, OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if not isinstance(entries, list):
            continue
        for entry in reversed(entries):
            if (not isinstance(entry, dict) or entry.get("step") not in TRAINING_OPERATIONS
                    or entry.get("artifact_type") != "workflow_capability_result"):
                continue
            try:
                result, _, pin = load_saved_forest(project_root, {
                    "model_run_id": run_root.name, "model_artifact_id": entry.get("artifact_id"),
                    "model_sha256": entry.get("sha256"),
                })
            except (ValueError, OSError):
                continue
            choices.append({
                **{key: pin[key] for key in ("run_id", "node_id", "artifact_id", "sha256")},
                "label": (f"{result['outcome']} · {result['split']['train_rows']:,} training rows · "
                          f"{result['options']['n_trees']} trees · {pin['run_id']} / {pin['artifact_id'][-8:]}"),
                "predictors": list(result["predictors"]),
                "model_type": result["model_type"],
            })
            if len(choices) == 100:
                return choices
    return choices
