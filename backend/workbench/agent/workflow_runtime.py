"""Stable entry point for compiled workflow execution.

Services live in workflow_runtime_parts; dispatcher identity strings remain stable.
"""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from ..checks.ar_cancellation import check_cancellation
from ..events import get_event_manager
from ..statistical_exploration import (
    ExplorationSpec,
    FilterSpec,
    STATA_QUANTILE_METHOD,
    execute_exploration,
    resolve_statistical_source,
)
from .workflow import WorkflowDraft, WorkflowExecutionError, WorkflowStep, WorkflowStepResult
from .workflow_contracts import workflow_dispatcher_key
from .workflow_runtime_parts.datasets import (
    _exploration_spec,
    _persist_numeric_derivation,
    _persist_workflow_exploration,
)
from .workflow_runtime_parts.inputs import _lineage_source, _workflow_input_frame
from .workflow_runtime_parts.models import _execute_model_auto, _execute_model_genesis_branches
from .workflow_runtime_parts.operations import (
    _execute_imputation_step,
    _execute_named_statistical_step,
    _execute_prediction_step,
    _execute_resampling_step,
    _execute_time_series_recipe,
    _exploration_step,
    _persist_data_management_step,
    _persist_exploration_result,
)
from .workflow_runtime_parts.postestimation import (
    _execute_model_joint_f_test,
    _execute_model_quadratic_stationary_point,
    _execute_model_white_test,
    _persist_model_post_estimation_result,
    _persist_p7_pack_result,
    _persist_workflow_capability_result,
)
from .workflow_runtime_parts.projection import (
    _detail_result,
    _p7_result_status,
    _record_artifact_ids,
)
from .workflow_runtime_parts.reports import _execute_workflow_report


from .workflow_runtime_parts.inputs import (
    _apply_numeric_recipes,
    _committed_source_binding,
    _require_binding_shape,
    _resolve_committed_source_frame,
    _upstream_numeric_steps,
)
from .workflow_runtime_parts.projection import (
    _read_post_estimation_artifact_records,
    _read_post_estimation_entry,
    _result_from_artifact_ids,
    _result_row_counts,
    collect_post_estimation_results,
    count_post_estimation_results,
)
from .workflow_runtime_parts.artifacts import _ensure_runtime_artifact
from .workflow_runtime_parts.datasets import _persist_workflow_dataset_frame
from .workflow_runtime_parts.operations import _WorkflowPackRecorder, _named_test_by_group
from .workflow_runtime_parts.models import (
    _branch_covariance,
    _branch_kernel,
    _declared_branch_term_groups,
    _dependent_model_branch,
    _execute_ols_branches,
    _fitted_term_positions,
    _refit_completed_ols_branch,
    _selected_model_terms,
    _wait_for_run,
    required_branch_figures,
)
from .workflow_runtime_parts.postestimation import (
    _white_test_statistics,
    _workflow_request_fingerprint,
)
from .workflow_runtime_parts.constants import (
    MAX_PROJECTED_POST_ESTIMATION_RESULTS,
    POST_ESTIMATION_ARTIFACT_TYPES,
    _NUMERIC_DERIVATION_SCHEMA,
    _PRODUCED_DATASET_FIELDS,
    _PRODUCED_DATASET_SCHEMA,
)

__all__ = ["build_workflow_step_executor"]

_PARALLEL_EXPLORATION_OPERATIONS = frozenset({"summarize", "summarize_detail", "misstable"})
_PARALLEL_EXPLORATION_MAX_ROWS = 8192
_PARALLEL_EXPLORATION_MAX_COLUMNS = 8


def _bounded_exploration_spec(frame: pd.DataFrame, step: WorkflowStep) -> ExplorationSpec | None:
    spec = step.spec
    if (
        step.operation_id != "statistical.explore"
        or step.operation_version != "v1"
        or spec.get("operation") not in _PARALLEL_EXPLORATION_OPERATIONS
        or "plots" in spec
        or "source" in spec
        or spec.get("filters", []) != []
    ):
        return None
    options = spec.get("options")
    if options and (spec["operation"] != "summarize_detail"
                    or options != {"quantile_method": STATA_QUANTILE_METHOD}):
        return None
    columns = spec.get("selected_columns") or ()
    if not 0 < len(columns) <= _PARALLEL_EXPLORATION_MAX_COLUMNS or not frame.columns.is_unique:
        return None
    for column in columns:
        if not isinstance(column, str) or column not in frame.columns:
            return None
        series = frame[column]
        dtype = series.dtype
        if (not isinstance(dtype, np.dtype) or dtype.kind not in "iuf" or dtype.itemsize > 8
                or not series.to_numpy(copy=False).flags.c_contiguous):
            return None
    return _exploration_spec(spec)


def build_workflow_step_executor(
    project_root: Path | str,
    draft: WorkflowDraft,
    *,
    custom_step_executor=None,
    on_source_resolved: Callable[[Mapping[str, Any]], None] | None = None,
):
    """Return one callback that dispatches only the compiled step identities.

    ``model.custom`` is intentionally an injected gateway.  The default
    runtime has no authority to reserve, spawn, or dispatch it; the caller
    must supply a gateway that has already joined Proposal/Risk authorization,
    the exact binding, and the B1 broker.
    """
    execute, _ = _build_workflow_runtime(
        project_root, draft, custom_step_executor=custom_step_executor,
        on_source_resolved=on_source_resolved,
    )
    return execute


def _build_workflow_runtime(
    project_root: Path | str,
    draft: WorkflowDraft,
    *,
    custom_step_executor=None,
    on_source_resolved: Callable[[Mapping[str, Any]], None] | None = None,
):
    root = Path(project_root).expanduser().resolve()
    source_context, source_frame = resolve_statistical_source(
        root,
        source_run_id=str(draft.target["run_id"]),
        source_node_id=str(draft.target["node_ref"]),
        source_artifact_id=str(draft.target["artifact_id"]),
    )
    if on_source_resolved is not None:
        on_source_resolved(source_context)
    source_run_root = root / "runs" / str(draft.target["run_id"])
    dependency_graph = {item.step_id: item.depends_on for item in draft.steps}

    def compute_exploration(frame, spec):
        check_cancellation()
        result = execute_exploration(frame, spec)
        check_cancellation()
        return result

    def publish_exploration(step, spec, future):
        check_cancellation()
        return _persist_exploration_result(
            root=root, draft=draft, lineage=_lineage_source(draft, step, source_context, {}),
            frame=source_frame, spec=spec, result=future.result(),
        )

    def prepare_pair(left, right):
        left_spec = _bounded_exploration_spec(source_frame, left)
        right_spec = _bounded_exploration_spec(source_frame, right)
        if left_spec is None or right_spec is None:
            return {}
        if (_upstream_numeric_steps(draft, left.step_id, dependency_graph)
                or _upstream_numeric_steps(draft, right.step_id, dependency_graph)):
            return {}
        events = get_event_manager()
        if not events.try_acquire_slot():
            return {}
        try:
            check_cancellation()
            prepared = {}
            with ThreadPoolExecutor(max_workers=2) as workers:
                for step, spec in ((left, left_spec), (right, right_spec)):
                    # Own each small numeric snapshot before giving it to pandas in a worker.
                    frame = source_frame[list(spec.selected_columns)].copy(deep=True)
                    future = workers.submit(copy_context().run, compute_exploration, frame, spec)
                    prepared[step.step_id] = partial(publish_exploration, step, spec, future)
            # The coordinator consumes errors and any output in the original plan order.
            return prepared
        finally:
            events.release_slot(None)

    def execute(step, previous: Mapping[str, WorkflowStepResult]) -> WorkflowStepResult:
        # Dispatch on the declared operation identity, never on a step number:
        # a plan with a different shape or length must run on the same runtime.
        operation_id = step.operation_id
        dispatcher_key = workflow_dispatcher_key(operation_id)
        if dispatcher_key == "workbench.agent.extension_runtime.external_query":
            from .extension_runtime import external_workflow_step
            return external_workflow_step(root, draft, step)
        step_frame = _workflow_input_frame(
            source_frame, draft, step, dependency_graph, previous, root
        )
        # Resolved here, beside the frame, so the data a step reads and the
        # source its output claims come from one decision. `source_context` is
        # deliberately not forwarded past this point: every branch below
        # receives `lineage` and nothing else that could name the target.
        lineage = _lineage_source(draft, step, source_context, previous)
        if dispatcher_key == "workbench.agent.workflow_runtime.p7_pack":
            from .p7_pack_registry import p7_pack_registry

            operation = p7_pack_registry.get(operation_id)
            request = {
                "operation_id": operation_id,
                "input_mode": step.spec.get("input_mode"),
                "column_bindings": step.spec.get("column_bindings"),
                "options": step.spec.get("options"),
            }
            try:
                operation.preflight(step_frame, request)
                result = operation.execute(step_frame, request)
                operation.validate_result(result)
                result_status, result_details = _p7_result_status(result)
                if result_status is not None and result_status != "completed":
                    reason_code = result_details.get("reason_code")
                    message = result_details.get("message")
                    detail_parts = [
                        str(value)
                        for value in (reason_code, message)
                        if value is not None
                    ]
                    if len(detail_parts) == 2 and detail_parts[1].startswith(
                        detail_parts[0] + ": "
                    ):
                        detail_parts[1] = detail_parts[1][len(detail_parts[0]) + 2 :]
                    detail = ": ".join(detail_parts)
                    raise WorkflowExecutionError(
                        f"P7 pack {operation_id} returned non-completed result "
                        f"status {result_status!r}"
                        + (f" ({detail})" if detail else "")
                    )
            except Exception as exc:
                raise WorkflowExecutionError(
                    f"P7 pack {operation_id} failed closed: {exc}"
                ) from exc
            return _persist_p7_pack_result(
                root,
                draft,
                step,
                result=result,
                lineage=lineage,
                pack_family=operation.pack_family,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.workflow_capability":
            from .workflow_capability_registry import workflow_capability_registry

            operation = workflow_capability_registry().require(operation_id)
            request = {
                "operation_id": operation_id,
                "input_mode": step.spec.get("input_mode"),
                "column_bindings": step.spec.get("column_bindings"),
                "options": step.spec.get("options"),
            }
            try:
                normalized_request, execution = operation.execute_with_context(
                    step_frame, request, project_root=root,
                )
            except Exception as exc:
                from ..econometrics.optional_deps import OptionalDependencyNotInstalled

                if isinstance(exc, OptionalDependencyNotInstalled):
                    raise WorkflowExecutionError(
                        f"workflow capability {operation_id} blocked/optional_dependency: {exc}"
                    ) from exc
                raise WorkflowExecutionError(
                    f"workflow capability {operation_id} failed closed: {exc}"
                ) from exc
            return _persist_workflow_capability_result(
                root,
                draft,
                step,
                lineage=lineage,
                request=normalized_request,
                execution=execution,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.data_operation":
            return _persist_data_management_step(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_explore" and "plots" not in step.spec:
            return _exploration_step(
                root=root,
                draft=draft,
                lineage=lineage,
                source_frame=step_frame,
                spec=_exploration_spec(step.spec),
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_derive_numeric":
            return _persist_numeric_derivation(
                root=root,
                draft=draft,
                lineage=lineage,
                frame=step_frame,
                step=step,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_derive_boolean":
            detail, detail_step_id, detail_fingerprint = _detail_result(
                previous, source_run_root, step.depends_on, dependency_graph
            )
            if not detail_fingerprint:
                raise WorkflowExecutionError(
                    f"{detail_step_id} detail result fingerprint is unavailable"
                )
            artifact_ids: list[str] = []
            row_counts: dict[str, int] = {}
            for recipe in step.spec["recipes"]:
                variable = detail.get("variables", {}).get(recipe["source_column"], {})
                expected = variable.get("percentiles", {}).get(f"p{recipe['percentile']}")
                if expected is None:
                    raise WorkflowExecutionError(
                        f"{detail_step_id} has no p{recipe['percentile']} "
                        f"for {recipe['source_column']}"
                    )
                spec = ExplorationSpec(
                    operation="derive_boolean",
                    selected_columns=(recipe["source_column"],),
                    options={
                        "source_column": recipe["source_column"],
                        "percentile": recipe["percentile"],
                        "comparison": recipe["comparison"],
                        "output_name": recipe["output_name"],
                        "quantile_method": step.spec.get(
                            "quantile_method", STATA_QUANTILE_METHOD
                        ),
                    },
                )
                result = execute_exploration(step_frame, spec)
                actual = result.get("derived", {}).get("threshold")
                if actual is None or abs(float(actual) - float(expected)) > 1e-12:
                    raise WorkflowExecutionError(
                        f"{step.step_id} threshold for {recipe['output_name']} "
                        f"is not sourced from {detail_step_id}"
                    )
                record, _fingerprint = _persist_workflow_exploration(
                    root, draft, lineage, spec=spec, result=result, frame=step_frame
                )
                artifact_ids.extend(_record_artifact_ids(record))
                row_counts[recipe["output_name"]] = int(
                    result.get("source_row_count", len(step_frame))
                )
            return WorkflowStepResult(
                artifact_ids=list(dict.fromkeys(artifact_ids)),
                row_counts=row_counts,
                result_fingerprint=step.fingerprint,
                payload={
                    "detail": detail,
                    "threshold_source": {
                        "step_id": detail_step_id,
                        "artifact_role": "result",
                        "result_fingerprint": detail_fingerprint,
                    },
                },
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_derived_group_summarize":
            detail, detail_step_id, _detail_fp = _detail_result(
                previous, source_run_root, step.depends_on, dependency_graph
            )
            grouped = step_frame.copy()
            artifact_ids: list[str] = []
            row_counts: dict[str, int] = {}
            summarize_columns = tuple(
                str(column) for column in step.spec["summarize_columns"]
            )
            for recipe in step.spec["groups"]:
                threshold = detail["variables"][recipe["source_column"]]["percentiles"][f"p{recipe['percentile']}"]
                series = grouped[recipe["source_column"]]
                values = pd.Series(pd.NA, index=grouped.index, dtype="boolean")
                if recipe["comparison"] == "lte":
                    values.loc[series.notna()] = series.loc[series.notna()] <= threshold
                else:
                    values.loc[series.notna()] = series.loc[series.notna()] >= threshold
                grouped[recipe["output_name"]] = values
                spec = ExplorationSpec(
                    operation="summarize",
                    selected_columns=summarize_columns,
                    filters=(FilterSpec(column=recipe["output_name"], operator="eq", value=True),),
                )
                result = execute_exploration(grouped, spec)
                if int(result.get("filtered_row_count", 0)) == 0:
                    raise WorkflowExecutionError(
                        f"{step.step_id} empty derived group: {recipe['output_name']}"
                    )
                record, _fingerprint = _persist_workflow_exploration(
                    root, draft, lineage, spec=spec, result=result, frame=grouped
                )
                artifact_ids.extend(_record_artifact_ids(record))
                row_counts[recipe["output_name"]] = int(result["filtered_row_count"])
            return WorkflowStepResult(
                artifact_ids=list(dict.fromkeys(artifact_ids)),
                row_counts=row_counts,
                payload={"groups": row_counts},
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_explore" and "plots" in step.spec:
            artifact_ids: list[str] = []
            row_counts: dict[str, int] = {}
            for plot in step.spec["plots"]:
                spec = ExplorationSpec(
                    operation="scatter",
                    selected_columns=(plot["x_column"], plot["y_column"]),
                    options={"x_column": plot["x_column"], "y_column": plot["y_column"]},
                )
                result = execute_exploration(step_frame, spec)
                record, _fingerprint = _persist_workflow_exploration(
                    root, draft, lineage, spec=spec, result=result, frame=step_frame
                )
                artifact_ids.extend(_record_artifact_ids(record))
                row_counts[f"{plot['x_column']}->{plot['y_column']}"] = int(
                    result.get("plot", {}).get("plotted_row_count", 0)
                )
            return WorkflowStepResult(
                artifact_ids=list(dict.fromkeys(artifact_ids)),
                row_counts=row_counts,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_named_test":
            return _execute_named_statistical_step(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.imputation":
            return _execute_imputation_step(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.resampling":
            return _execute_resampling_step(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.prediction_model":
            return _execute_prediction_step(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.time_series_recipe":
            return _execute_time_series_recipe(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.model_auto":
            return _execute_model_auto(
                root=root,
                draft=draft,
                lineage=lineage,
                step=step,
                frame=step_frame,
            )
        if dispatcher_key == "workbench.services.genesis":
            return _execute_model_genesis_branches(
                root,
                draft,
                lineage,
                step_frame,
                step,
                raw_source_frame=source_frame,
            )
        if dispatcher_key == 'workbench.agent.workflow_runtime.iv_ar':
            from .postestimation_steps import _resolve_model_binding, _load_kernel
            from ..services.iv_ar import compute_ar
            check_cancellation()
            model_root, model_id = _resolve_model_binding(root, str(draft.target['run_id']), step, 'model_ref', previous)
            _load_kernel(model_root, model_id)
            result = compute_ar(model_root, model_id, {
                'run_id': str(lineage.get('run_id', draft.target['run_id'])),
                'artifact_id': lineage['artifact_id'], 'sha256': lineage['sha256']}, step_frame)
            check_cancellation()
            return _persist_model_post_estimation_result(root, draft, step, artifact_type='post_estimation',
                result=result, model_run_id=model_root.name, model_artifact_id=model_id, lineage=lineage)
        if dispatcher_key == "workbench.agent.workflow_runtime.postestimation":
            from .postestimation_steps import execute_postestimation_step

            result, model_run_id, model_id = execute_postestimation_step(
                root, str(draft.target["run_id"]), step, previous=previous
            )
            return _persist_model_post_estimation_result(
                root,
                draft,
                step,
                artifact_type="post_estimation",
                result=result,
                model_run_id=model_run_id,
                model_artifact_id=model_id,
                lineage=lineage,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.model_joint_f_test":
            return _execute_model_joint_f_test(
                root, draft, lineage, step_frame, step, previous
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.model_white_test":
            return _execute_model_white_test(
                root, draft, lineage, step_frame, step, previous
            )
        if dispatcher_key == (
            "workbench.agent.workflow_runtime.model_quadratic_stationary_point"
        ):
            return _execute_model_quadratic_stationary_point(
                root, draft, lineage, step_frame, step, previous
            )
        if dispatcher_key == "capability_factory.custom_dispatcher":
            if not callable(custom_step_executor):
                raise WorkflowExecutionError(
                    "model.custom requires an authorized custom capability gateway"
                )
            result = custom_step_executor(
                project_root=root,
                draft=draft,
                step=step,
                previous=previous,
            )
            if not isinstance(result, WorkflowStepResult):
                raise WorkflowExecutionError(
                    "authorized custom capability gateway returned an invalid result"
                )
            return result
        if dispatcher_key == "workbench.agent.workflow_runtime.report":
            return _execute_workflow_report(root, draft, previous, step, source_rows=len(source_frame))
        raise WorkflowExecutionError(
            f"unsupported workflow operation: {step.operation_id}"
        )

    can_prepare_pair = (
        custom_step_executor is None
        and len(draft.steps) >= 2
        and len(source_frame) <= _PARALLEL_EXPLORATION_MAX_ROWS
        and isinstance(source_frame.index, pd.RangeIndex)
    )
    return execute, prepare_pair if can_prepare_pair else None
