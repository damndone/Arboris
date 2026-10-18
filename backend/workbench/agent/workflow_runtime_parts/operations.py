"""Operations service for workflow execution."""

from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
import pandas as pd
from ...artifacts import read_json, sha256_file, write_json
from ...data_operations import (
    DataTransformSpecV1,
    FeatureRecipeOperationSpecV1,
    apply_data_transform,
    apply_feature_recipe_operation,
    preview_data_transform,
    preview_feature_recipe,
)
from ...predictive_research.contracts import FeatureRecipeV1
from ...repository.run_repository import _read_artifacts_index
from ...statistical_exploration import ExplorationSpec, execute_exploration
from ..workflow import WorkflowDraft, WorkflowExecutionError, WorkflowStepResult
from .artifacts import _ensure_runtime_artifact
from .datasets import _persist_workflow_dataset_frame, _persist_workflow_exploration
from .projection import _record_artifact_ids, _result_row_counts
from .constants import _PRODUCED_DATASET_SCHEMA


def _exploration_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    spec: ExplorationSpec,
    frame: pd.DataFrame | None = None,
) -> WorkflowStepResult:
    evaluated_frame = source_frame if frame is None else frame
    result = execute_exploration(evaluated_frame, spec)
    record, fingerprint = _persist_workflow_exploration(
        root, draft, lineage, spec=spec, result=result, frame=evaluated_frame
    )
    return WorkflowStepResult(
        artifact_ids=_record_artifact_ids(record),
        row_counts=_result_row_counts(result),
        empty_group_values=list(result.get("empty_group_values", [])),
        result_fingerprint=fingerprint,
        payload={"result": result, "record": record},
    )



def _persist_data_management_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
) -> WorkflowStepResult:
    """Execute every declared P4 data producer through one service adapter."""
    operation_id = str(step.operation_id)
    operation = operation_id.removeprefix("data.")
    source_run_id = str(draft.target["run_id"])
    source_node_id = str(lineage["node_ref"])
    source_artifact_id = str(lineage["artifact_id"])
    run_root = root / "runs" / source_run_id
    execution_key = f"exec_{step.fingerprint}"
    if operation == "feature_recipe":
        recipe = FeatureRecipeV1(
            recipe_id=str(step.spec["recipe_id"]),
            operation_id=str(step.spec["recipe_operation_id"]),
            operation_version=1,
            inputs=tuple(str(item) for item in step.spec["inputs"]),
            outputs=(str(step.spec["output"]),),
            output_types=(str(step.spec.get("output_type", "numeric")),),
            parameters=dict(step.spec["parameters"]),
            fit_scope=str(step.spec.get("fit_scope", "stateless")),
            source_artifact=source_artifact_id,
            lineage_parent=source_node_id,
            missing_policy=str(step.spec.get("missing_policy", "fail_closed")),
            outlier_policy=str(step.spec.get("outlier_policy", "preserve")),
        )
        typed_spec = FeatureRecipeOperationSpecV1(
            source_run_id=source_run_id,
            source_node_id=source_node_id,
            source_artifact_id=source_artifact_id,
            recipe=recipe,
        )
        preview = preview_feature_recipe(root, typed_spec)
        effect = apply_feature_recipe_operation(
            root, typed_spec, preview, execution_key_value=execution_key
        )
        output_columns = list(preview.output_columns)
        row_count_before = preview.row_count
        row_count_after = preview.row_count
        fingerprint = preview.fingerprint
    else:
        parameters = {
            key: value
            for key, value in step.spec.items()
            if key
            not in {
                "secondary_run_id",
                "secondary_node_id",
                "secondary_artifact_id",
                "source_artifact_fingerprint",
                "source",
            }
        }
        typed_spec = DataTransformSpecV1(
            source_run_id=source_run_id,
            source_node_id=source_node_id,
            source_artifact_id=source_artifact_id,
            operation=operation,
            parameters=parameters,
            secondary_run_id=step.spec.get("secondary_run_id"),
            secondary_node_id=step.spec.get("secondary_node_id"),
            secondary_artifact_id=step.spec.get("secondary_artifact_id"),
        )
        preview = preview_data_transform(root, typed_spec)
        effect = apply_data_transform(
            root, typed_spec, preview, execution_key_value=execution_key
        )
        output_columns = list(preview.output_columns)
        row_count_before = preview.row_count_before
        row_count_after = preview.row_count_after
        fingerprint = preview.fingerprint
    data_path = run_root / effect.artifact_path
    if not data_path.is_file():
        raise WorkflowExecutionError(
            f"{operation_id} service returned a missing persisted dataset: {effect.artifact_path}"
        )
    content_sha256 = sha256_file(data_path)
    return WorkflowStepResult(
        artifact_ids=[effect.artifact_id, effect.recipe_artifact_id],
        row_counts={"source": int(row_count_before), "output": int(row_count_after)},
        result_fingerprint=fingerprint,
        payload={
            "operation_id": operation_id,
            "output_columns": output_columns,
            "produced_dataset": {
                "schema_version": _PRODUCED_DATASET_SCHEMA,
                "run_id": source_run_id,
                "node_ref": effect.child_node_id,
                "artifact_id": effect.artifact_id,
                "content_sha256": content_sha256,
                "dataset_kind": "derived_data",
                "result_fingerprint": fingerprint,
            },
        },
    )



def _execute_named_statistical_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
) -> WorkflowStepResult:
    from ...statistical_tests import run_named_statistical_test
    family = str(step.operation_id).removeprefix("test.")

    def run_one(rows: pd.DataFrame) -> dict[str, Any]:
        return run_named_statistical_test(
            rows,
            family=family,
            analysis_columns=list(step.spec["analysis_columns"]),
            dataset_sha256=str(lineage["sha256"]),
            lineage_parent=str(lineage["artifact_id"]),
            reference_means=step.spec.get("reference_means"),
            paired_columns=[tuple(pair) for pair in step.spec.get("paired_columns", []) or []],
        )

    by_group = step.spec.get("by_group")
    if by_group:
        result = _named_test_by_group(frame, str(by_group), str(step.operation_id), run_one)
    else:
        result = run_one(frame)
    run_root = root / "runs" / str(draft.target["run_id"])
    fingerprint = str(step.fingerprint).replace(":", "_")
    artifact_id = f"statistical_tests_named_{family}_{fingerprint[:24]}"
    relative = Path("statistical_tests") / f"{artifact_id}.json"
    path = run_root / relative
    envelope = {
        "payload_schema": "workbench.statistical_tests.named-family",
        "schema_version": 1,
        "artifact_id": artifact_id,
        "execution_mode": "named",
        "source": {
            "artifact_id": str(lineage["artifact_id"]),
            "node_ref": str(lineage["node_ref"]),
            "sha256": str(lineage["sha256"]),
        },
        "result": result,
    }
    if path.exists():
        if read_json(path) != envelope:
            raise WorkflowExecutionError(
                f"named statistical artifact {artifact_id} is not deterministic"
            )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, envelope)
    _ensure_runtime_artifact(
        run_root,
        artifact_id=artifact_id,
        path=path,
        artifact_type="statistical_test",
        step=f"test.{family}",
        inputs=[str(lineage["artifact_id"])],
    )
    row_counts = {"results": int(len(result.get("results", [])))}
    if isinstance(result.get("by_group"), Mapping):
        # One test per estimated group: the ledger counts each.
        row_counts["ledger_count"] = int(result["by_group"]["estimated_groups"])
    return WorkflowStepResult(
        artifact_ids=[artifact_id],
        row_counts=row_counts,
        result_fingerprint=str(step.fingerprint),
        payload={"result": result, "execution_mode": "named"},
    )



def _named_test_by_group(frame: pd.DataFrame, column: str, operation_id: str, run_one: Any) -> dict[str, Any]:
    """A named test run in every group, with p-values adjusted across groups."""
    from ...combinators.by_group import ByGroupRefusal, adjust_across_groups, run_by_group, semantics_for

    try:
        semantics_for(operation_id, design_declared=False)
        outcomes = run_by_group(frame, column, run_one)
    except ByGroupRefusal as refusal:
        raise WorkflowExecutionError(refusal.message) from refusal
    rows: list[dict[str, Any]] = []
    template: dict[str, Any] = {}
    for outcome in outcomes:
        if outcome["status"] != "estimated":
            continue
        group_result = outcome.pop("result")
        template = template or group_result
        for row in group_result.get("results", []):
            rows.append({**row, "group": outcome["key"], "group_column": column})
    adjust_across_groups(rows)
    groups = [{key: value for key, value in outcome.items() if key != "result"} for outcome in outcomes]
    return {
        **{key: value for key, value in template.items() if key != "results"},
        "results": rows,
        "by_group": {
            "column": column,
            "semantics": "subset",
            "groups": groups,
            "estimated_groups": sum(outcome["status"] == "estimated" for outcome in outcomes),
            "adjustment_across_groups": "holm and benjamini_hochberg per test_id",
            "comparing_groups": (
                "Results of separate groups side by side are not a test of a difference between groups."
            ),
        },
    }



def _execute_imputation_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
) -> WorkflowStepResult:
    if step.operation_id != "imputation.mice":
        raise WorkflowExecutionError(
            f"{step.operation_id} has no registered imputation owner"
        )
    from ...imputation import run_mice_imputation
    run_root = root / "runs" / str(draft.target["run_id"])
    summary = run_mice_imputation(
        frame,
        run_root,
        list(step.spec["columns"]),
        m=int(step.spec.get("m", 1)),
        max_iter=int(step.spec.get("max_iter", 10)),
        random_seed=int(step.spec.get("random_seed", 20260429)),
        max_missing_rate=float(step.spec.get("max_missing_rate", 0.4)),
    )
    skipped = list(summary.get("skipped_columns", []))
    if skipped:
        raise WorkflowExecutionError(
            "imputation.mice refused to silently drop declared column(s): "
            + ", ".join(str(column) for column in skipped)
        )
    if summary.get("status") != "completed":
        raise WorkflowExecutionError(
            "imputation.mice did not produce a changed dataset; inspect the "
            "persisted MICE summary before retrying"
        )
    imputed_path = run_root / "processed" / "imputed_dataset.parquet"
    if not imputed_path.is_file():
        raise WorkflowExecutionError(
            "imputation.mice reported completion without its imputed_dataset artifact"
        )
    imputed = pd.read_parquet(imputed_path)
    return _persist_workflow_dataset_frame(
        root=root,
        draft=draft,
        lineage=lineage,
        step=step,
        frame=imputed,
        dataset_label="imputation_mice",
        producer_step="imputation.mice",
        summary=summary,
    )



def _execute_resampling_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
) -> WorkflowStepResult:
    method = str(step.operation_id).removeprefix("resample.")
    from ...prediction import build_sampler
    target = str(step.spec["target_column"])
    features = [str(column) for column in step.spec["feature_columns"]]
    missing = [column for column in [target, *features] if column not in frame.columns]
    if missing:
        raise WorkflowExecutionError(
            f"{step.operation_id} source columns are missing: " + ", ".join(missing)
        )
    selected = frame[[*features, target]].copy()
    if selected.isna().any().any():
        raise WorkflowExecutionError(
            f"{step.operation_id} refuses missing target/features; impute first"
        )
    sampler = build_sampler(
        method,
        model_type="prediction_resampling",
        random_seed=int(step.spec.get("random_seed", 0)),
    )
    if sampler is None:
        raise WorkflowExecutionError(
            f"{step.operation_id} did not resolve a sampler; no-op resampling is forbidden"
        )
    x_resampled, y_resampled = sampler.fit_resample(
        selected[features], selected[target]
    )
    output = pd.DataFrame(x_resampled, columns=features)
    output[target] = y_resampled
    if output.empty:
        raise WorkflowExecutionError(f"{step.operation_id} produced an empty training dataset")
    return _persist_workflow_dataset_frame(
        root=root,
        draft=draft,
        lineage=lineage,
        step=step,
        frame=output,
        dataset_label=f"resample_{method}",
        producer_step=step.operation_id,
        summary={
            "method": method,
            "source_row_count": int(len(frame)),
            "output_row_count": int(len(output)),
            "target_column": target,
            "feature_columns": features,
        },
    )



def _execute_prediction_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
) -> WorkflowStepResult:
    from ...prediction import run_prediction_model_v186
    from ...predictive_research.contracts import SamplingSpecV1
    model_type = str(step.operation_id).removeprefix("prediction.")
    sampling_value = step.spec.get("sampling")
    sampling = None
    if sampling_value is not None:
        try:
            sampling = SamplingSpecV1(**dict(sampling_value))
        except (TypeError, ValueError) as exc:
            raise WorkflowExecutionError(
                f"{step.operation_id} sampling does not match SamplingSpecV1"
            ) from exc
    fingerprint = str(step.fingerprint).replace(":", "_")
    model_id = f"workflow_{model_type}_{fingerprint[:24]}"
    run_root = root / "runs" / str(draft.target["run_id"])
    result = run_prediction_model_v186(
        frame,
        run_root,
        y=str(step.spec["y"]),
        x=[str(column) for column in step.spec["x"]],
        model_type=model_type,
        model_id=model_id,
        final_holdout_fraction=float(step.spec["final_holdout_fraction"]),
        cv_folds=int(step.spec["cv_folds"]),
        shuffle=bool(step.spec["shuffle"]),
        random_seed=int(step.spec["random_seed"]),
        data_structure=str(step.spec["data_structure"]),
        entity_column=step.spec.get("entity_column"),
        group_column=step.spec.get("group_column"),
        time_column=step.spec.get("time_column"),
        sampling=sampling,
        inputs=[str(lineage["artifact_id"])],
        imputation_method=step.spec.get("imputation_method"),
        imputation_max_iter=int(step.spec.get("imputation_max_iter", 10)),
        imputation_max_missing_rate=float(
            step.spec.get("imputation_max_missing_rate", 0.4)
        ),
    )
    records = _read_artifacts_index(run_root).get("artifacts", [])
    artifact_ids = [
        str(item["artifact_id"])
        for item in records
        if isinstance(item.get("artifact_id"), str)
        and (
            item["artifact_id"] == model_id
            or item["artifact_id"].startswith(f"{model_id}_")
        )
    ]
    if not artifact_ids:
        raise WorkflowExecutionError(
            f"{step.operation_id} completed without registered prediction artifacts"
        )
    return WorkflowStepResult(
        artifact_ids=artifact_ids,
        row_counts={"source": int(len(frame))},
        result_fingerprint=str(step.fingerprint),
        payload={"result": result, "model_type": model_type, "source": dict(lineage)},
    )



class _WorkflowPackRecorder:
    """No-op recorder for pack-owned evidence; workflow lineage is separate."""
    def __getattr__(self, _name: str):
        return lambda *args, **kwargs: None



def _execute_time_series_recipe(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
) -> WorkflowStepResult:
    recipe_id = str(step.operation_id).removeprefix("model.")
    options = dict(step.spec["model_options"])
    if recipe_id == "time_series.arma_garch":
        options["dataset_ref"] = str(lineage["artifact_id"])
        from ...engine.packs.arma_garch.runner import fit_from_context
    elif recipe_id == "time_series.ets":
        from ...engine.packs.ets.runner import fit_from_context
    else:
        raise WorkflowExecutionError(f"{step.operation_id} has no registered Recipe owner")
    from ...engine.context import DataHandle, ModelingContext, RunEnv
    source_artifact = str(lineage["artifact_id"])
    context = ModelingContext(
        data=DataHandle.of(
            frame,
            artifact_id=source_artifact,
            provenance=(source_artifact,),
        ),
        y_col=str(options.get("value_column", "")),
        x_cols=[],
        requested_model_type=recipe_id,
        artifacts={
            "_model_options": options,
            "_frames": {source_artifact: frame},
            "_raw_inputs": [source_artifact],
            "_upload_hash": str(lineage["sha256"]),
        },
    )
    run_root = root / "runs" / str(draft.target["run_id"])
    env = RunEnv(
        run_root=run_root,
        run_id=str(draft.target["run_id"]),
        recorder=_WorkflowPackRecorder(),
    )
    model_id, result, _fitted = fit_from_context(context, env)
    artifact_ids: list[str]
    if recipe_id == "time_series.ets":
        fingerprint = str(step.fingerprint).replace(":", "_")
        artifact_id = f"workflow_{recipe_id.replace('.', '_')}_{fingerprint[:24]}"
        relative = Path("artifacts") / "time_series" / f"{artifact_id}.json"
        path = run_root / relative
        envelope = {
            "artifact_id": artifact_id,
            "payload_schema": "workbench.recipe.time_series.ets",
            "schema_version": 1,
            "model_id": model_id,
            "source": dict(lineage),
            "result": result,
        }
        if path.exists():
            if read_json(path) != envelope:
                raise WorkflowExecutionError(
                    f"{step.operation_id} result artifact is not deterministic"
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, envelope)
        _ensure_runtime_artifact(
            run_root,
            artifact_id=artifact_id,
            path=path,
            artifact_type="model_result",
            step=step.operation_id,
            inputs=[source_artifact],
        )
        artifact_ids = [artifact_id]
    else:
        records = _read_artifacts_index(run_root).get("artifacts", [])
        artifact_ids = [
            str(item["artifact_id"])
            for item in records
            if isinstance(item.get("artifact_id"), str)
            and item["artifact_id"].startswith("ts.")
            and item.get("step") == "arma_garch"
        ]
        if "ts.artifact_manifest" not in artifact_ids:
            raise WorkflowExecutionError(
                "time_series.arma_garch owner returned without ts.artifact_manifest"
            )
    return WorkflowStepResult(
        artifact_ids=artifact_ids,
        row_counts={"source": int(len(frame))},
        result_fingerprint=str(step.fingerprint),
        payload={
            "recipe_id": recipe_id,
            "model_id": model_id,
            "result": result,
            "source": dict(lineage),
        },
    )

