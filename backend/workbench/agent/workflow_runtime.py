"""Native service adapter that executes one compiled workflow step."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from ..artifacts import read_json, register_artifact, write_json
from ..exports import export_pdf, export_xlsx
from ..lineage.pipeline_drafts import (
    PipelineDraftStore,
    compute_executable_draft_hash,
    validate_draft_for_execution,
)
from ..lineage.run_inputs import read_run_inputs
from ..lineage.upload_store import store_upload_bytes, verify_upload
from ..model_terms import ModelTermError, expand_branch_terms
from ..reporting import render_html_report
from ..repository.run_repository import _read_artifacts_index
from ..statistical_exploration import (
    ExplorationSpec,
    FilterSpec,
    STATA_QUANTILE_METHOD,
    StatisticalExplorationValidationError,
    execute_exploration,
    exploration_fingerprint,
    persist_exploration,
    resolve_statistical_source,
)
from ..services.draft_materialization import create_genesis_draft
from ..services.draft_service import execute_genesis_draft
from .workflow import WorkflowDraft, WorkflowExecutionError, WorkflowStepResult
from .workflow_contracts import workflow_dispatcher_key


def _exploration_spec(spec: Mapping[str, Any]) -> ExplorationSpec:
    return ExplorationSpec(
        operation=str(spec["operation"]),
        selected_columns=tuple(str(item) for item in spec.get("selected_columns", [])),
        filters=tuple(
            FilterSpec(
                column=str(item["column"]),
                operator=str(item["operator"]),
                value=item.get("value"),
            )
            for item in spec.get("filters", [])
        ),
        options=dict(spec.get("options") or {}),
        derived_definitions=tuple(spec.get("derived_definitions") or []),
    )


def _record_artifact_ids(record: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("artifact_id", "transcript_artifact_id"):
        value = record.get(key)
        if isinstance(value, str) and value:
            ids.append(value)
    for value in record.get("exports", []) or []:
        if isinstance(value, Mapping) and isinstance(value.get("artifact_id"), str):
            ids.append(value["artifact_id"])
    for key in ("derived", "plot"):
        value = record.get(key)
        if isinstance(value, Mapping):
            for nested_key in ("artifact_id", "recipe_artifact_id"):
                nested = value.get(nested_key)
                if isinstance(nested, str) and nested:
                    ids.append(nested)
    return list(dict.fromkeys(ids))


def _result_from_artifact_ids(run_root: Path, artifact_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
    index = _read_artifacts_index(run_root)
    wanted = set(artifact_ids)
    for item in index.get("artifacts", []):
        if item.get("artifact_id") not in wanted:
            continue
        path = run_root / str(item.get("path", ""))
        if path.is_file():
            payload = read_json(path)
            if isinstance(payload, Mapping) and isinstance(payload.get("result"), Mapping):
                return dict(payload["result"])
    raise WorkflowExecutionError("workflow dependency artifact is unavailable")


def _detail_result(
    previous: Mapping[str, WorkflowStepResult],
    run_root: Path,
    depends_on: tuple[str, ...] | list[str],
    dependency_graph: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Find the percentile evidence this step transitively depends on.

    Resolved through the dependency graph rather than a fixed step id. The
    search is transitive because a plan may legitimately route the evidence
    through an intermediate step — a live agent composed exactly that shape:
    the group comparison depended on the derivation, which depended on the
    detail statistics. Requiring a direct edge would reject a correct plan.
    """

    visited: set[str] = set()
    frontier = list(depends_on)
    while frontier:
        step_id = frontier.pop(0)
        if step_id in visited:
            continue
        visited.add(step_id)
        if dependency_graph is not None:
            frontier.extend(dependency_graph.get(step_id, ()))
        cached = previous.get(step_id)
        if cached is None:
            continue
        result = (
            dict(cached.payload["result"])
            if isinstance(cached.payload.get("result"), Mapping)
            else _result_from_artifact_ids(run_root, cached.artifact_ids)
        )
        variables = result.get("variables")
        if isinstance(variables, Mapping) and any(
            isinstance(entry, Mapping) and "percentiles" in entry
            for entry in variables.values()
        ):
            return result, step_id, cached.result_fingerprint or ""
    raise WorkflowExecutionError(
        "no dependency of this step provides percentile evidence: "
        + ", ".join(visited)
    )


def _result_row_counts(result: Mapping[str, Any]) -> dict[str, int]:
    counts = {
        "source": int(result.get("source_row_count", 0) or 0),
        "filtered": int(result.get("filtered_row_count", 0) or 0),
    }
    if isinstance(result.get("groups"), list):
        counts["groups"] = len(result["groups"])
    if result.get("correlation_n") is not None:
        counts["correlation_n"] = int(result["correlation_n"])
    return counts


def _exploration_step(
    *,
    root: Path,
    draft: WorkflowDraft,
    source_context: Mapping[str, Any],
    source_frame: pd.DataFrame,
    spec: ExplorationSpec,
    frame: pd.DataFrame | None = None,
) -> WorkflowStepResult:
    evaluated_frame = source_frame if frame is None else frame
    result = execute_exploration(evaluated_frame, spec)
    source_run_id = str(draft.target["run_id"])
    source_sha = str(source_context["source_sha256"])
    fingerprint = exploration_fingerprint(source_sha, spec)
    record = persist_exploration(
        root,
        source_run_id=source_run_id,
        source_node_id=str(draft.target["node_ref"]),
        source_artifact_id=str(draft.target["artifact_id"]),
        source_sha256=source_sha,
        spec=spec,
        result=result,
        fingerprint=fingerprint,
        source_frame=evaluated_frame,
    )
    return WorkflowStepResult(
        artifact_ids=_record_artifact_ids(record),
        row_counts=_result_row_counts(result),
        empty_group_values=list(result.get("empty_group_values", [])),
        result_fingerprint=fingerprint,
        payload={"result": result, "record": record},
    )


def build_workflow_step_executor(project_root: Path | str, draft: WorkflowDraft):
    """Return one callback that dispatches only the compiled step identities."""

    root = Path(project_root).expanduser().resolve()
    source_context, source_frame = resolve_statistical_source(
        root,
        source_run_id=str(draft.target["run_id"]),
        source_node_id=str(draft.target["node_ref"]),
        source_artifact_id=str(draft.target["artifact_id"]),
    )
    source_run_root = root / "runs" / str(draft.target["run_id"])
    dependency_graph = {item.step_id: item.depends_on for item in draft.steps}

    def execute(step, previous: Mapping[str, WorkflowStepResult]) -> WorkflowStepResult:
        # Dispatch on the declared operation identity, never on a step number:
        # a plan with a different shape or length must run on the same runtime.
        operation_id = step.operation_id
        dispatcher_key = workflow_dispatcher_key(operation_id)
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_explore" and "plots" not in step.spec:
            return _exploration_step(
                root=root,
                draft=draft,
                source_context=source_context,
                source_frame=source_frame,
                spec=_exploration_spec(step.spec),
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
                result = execute_exploration(source_frame, spec)
                actual = result.get("derived", {}).get("threshold")
                if actual is None or abs(float(actual) - float(expected)) > 1e-12:
                    raise WorkflowExecutionError(
                        f"{step.step_id} threshold for {recipe['output_name']} "
                        f"is not sourced from {detail_step_id}"
                    )
                fingerprint = exploration_fingerprint(str(source_context["source_sha256"]), spec)
                record = persist_exploration(
                    root,
                    source_run_id=str(draft.target["run_id"]),
                    source_node_id=str(draft.target["node_ref"]),
                    source_artifact_id=str(draft.target["artifact_id"]),
                    source_sha256=str(source_context["source_sha256"]),
                    spec=spec,
                    result=result,
                    fingerprint=fingerprint,
                    source_frame=source_frame,
                )
                artifact_ids.extend(_record_artifact_ids(record))
                row_counts[recipe["output_name"]] = int(
                    result.get("source_row_count", len(source_frame))
                )
            return WorkflowStepResult(
                artifact_ids=list(dict.fromkeys(artifact_ids)),
                row_counts=row_counts,
                result_fingerprint=step.fingerprint,
                payload={
                    "detail": detail,
                    "threshold_source": {
                        "step_id": "step-4",
                        "artifact_role": "result",
                        "result_fingerprint": detail_fingerprint,
                    },
                },
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_derived_group_summarize":
            detail, detail_step_id, _detail_fp = _detail_result(
                previous, source_run_root, step.depends_on, dependency_graph
            )
            grouped = source_frame.copy()
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
                fingerprint = exploration_fingerprint(str(source_context["source_sha256"]), spec)
                record = persist_exploration(
                    root,
                    source_run_id=str(draft.target["run_id"]),
                    source_node_id=str(draft.target["node_ref"]),
                    source_artifact_id=str(draft.target["artifact_id"]),
                    source_sha256=str(source_context["source_sha256"]),
                    spec=spec,
                    result=result,
                    fingerprint=fingerprint,
                    source_frame=grouped,
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
                result = execute_exploration(source_frame, spec)
                fingerprint = exploration_fingerprint(str(source_context["source_sha256"]), spec)
                record = persist_exploration(
                    root,
                    source_run_id=str(draft.target["run_id"]),
                    source_node_id=str(draft.target["node_ref"]),
                    source_artifact_id=str(draft.target["artifact_id"]),
                    source_sha256=str(source_context["source_sha256"]),
                    spec=spec,
                    result=result,
                    fingerprint=fingerprint,
                    source_frame=source_frame,
                )
                artifact_ids.extend(_record_artifact_ids(record))
                row_counts[f"{plot['x_column']}->{plot['y_column']}"] = int(
                    result.get("plot", {}).get("plotted_row_count", 0)
                )
            return WorkflowStepResult(
                artifact_ids=list(dict.fromkeys(artifact_ids)),
                row_counts=row_counts,
            )
        if dispatcher_key == "workbench.services.genesis":
            return _execute_ols_branches(
                root, draft, source_context, source_frame, step
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.report":
            return _execute_workflow_report(root, draft, previous)
        raise WorkflowExecutionError(
            f"unsupported workflow operation: {step.operation_id}"
        )

    return execute


def _execute_ols_branches(
    root: Path,
    draft: WorkflowDraft,
    source_context: Mapping[str, Any],
    source_frame: pd.DataFrame,
    step: Any = None,
) -> WorkflowStepResult:
    source_run_id = str(draft.target["run_id"])
    source_run_root = root / "runs" / source_run_id
    inputs = read_run_inputs(source_run_root)
    upload = inputs.get("upload") or {}
    upload_sha = upload.get("sha256")
    filename = upload.get("filename") or "dataset.csv"
    if not isinstance(upload_sha, str) or not upload_sha:
        raise WorkflowExecutionError("raw source upload is unavailable for OLS genesis")
    upload_bytes = verify_upload(root, upload_sha).read_bytes()
    store = PipelineDraftStore(root)
    branch_outputs: list[dict[str, Any]] = []
    artifact_ids: list[str] = []
    # Read the branches off the step being executed. Indexing draft.steps[7]
    # tied the executor to one plan's length and ordering.
    branch_spec = step.spec if step is not None else draft.steps[7].spec
    for branch in branch_spec["branches"]:
        branch_id = str(branch["branch_id"])
        # Genesis estimates from an uploaded dataset, not from a formula, so a
        # dummy set or a squared term has to exist as a real column first. When
        # a branch declares derived terms, materialize an augmented upload and
        # point this branch at it; branches without them keep the original
        # upload untouched, so their lineage is unchanged.
        try:
            branch_frame, branch_predictors, references = expand_branch_terms(
                source_frame, branch
            )
        except ModelTermError as exc:
            raise WorkflowExecutionError(
                f"OLS branch {branch_id} derived terms: {exc}"
            ) from exc
        if branch_predictors == [str(item) for item in branch["predictors"]]:
            branch_upload_sha = upload_sha
            branch_filename = filename
        else:
            branch_upload_sha = store_upload_bytes(
                root,
                branch_frame.to_csv(index=False).encode(),
                filename=f"{Path(filename).stem}__{branch_id}.csv",
            )
            branch_filename = f"{Path(filename).stem}__{branch_id}.csv"
        stored = None
        for summary in store.list():
            candidate = store.get(summary["draft_id"])
            context = candidate.draft.get("exploration_context") or {}
            # Legacy keys are still read so a draft created before the rename
            # still resumes instead of re-estimating under a new identity.
            context_workflow = context.get("workflow_id", context.get("class3_workflow_id"))  # legacy-compat
            context_branch = context.get("branch_id", context.get("class3_branch_id"))  # legacy-compat
            if context_workflow == draft.workflow_id and context_branch == branch_id:
                stored = candidate
                break
        if stored is None:
            spec = ExplorationSpec(
                operation="summarize_detail",
                # Source columns only: this describes the variables the model is
                # built from, and it is evaluated against the original data
                # where a derived dummy or power column does not exist.
                selected_columns=tuple(
                    branch_spec.get("context_columns")
                    or (str(branch["outcome"]), *[str(c) for c in branch["predictors"]])
                ),
                options={"quantile_method": STATA_QUANTILE_METHOD},
            )
            context = {
                "workflow_id": draft.workflow_id,
                "branch_id": branch_id,
                "source_run_id": source_run_id,
                "source_node_id": str(draft.target["node_ref"]),
                "source_artifact_id": str(draft.target["artifact_id"]),
                "source_sha256": source_context["source_sha256"],
                "exploration_fingerprint": exploration_fingerprint(str(source_context["source_sha256"]), spec),
                "filters": [],
                "spec": spec.to_dict(),
                "outcome_column": branch["outcome"],
                # The design actually estimated, so a reader can tell a dummy
                # set from a linear effect on the same source column.
                "predictor_columns": list(branch_predictors),
                "source_predictor_columns": [str(item) for item in branch["predictors"]],
                "categorical_reference_levels": references,
                "covariance": "unadjusted",
                "workflow_plan_fingerprint": draft.plan_fingerprint,
            }
            stored = create_genesis_draft(
                root,
                upload_sha256=branch_upload_sha,
                filename=branch_filename,
                sheet_names=(),
                columns=tuple(str(column) for column in branch_frame.columns),
                model_params={
                    "model_type": "ols",
                    "y": branch["outcome"],
                    "x": list(branch_predictors),
                    "covariance": "unadjusted",
                    "model_options": {"covariance": "unadjusted"},
                },
                exploration_context=context,
            )
        validation = validate_draft_for_execution(stored.draft, execution_mode="genesis")
        if not validation.get("executable"):
            raise WorkflowExecutionError(
                f"OLS Draft validation failed for {branch_id}: {validation.get('checks')}"
            )
        result = execute_genesis_draft(
            stored.draft["draft_id"],
            root,
            store,
            stored,
            validated_draft_hash=compute_executable_draft_hash(stored.draft),
            execution_mode="genesis",
            idempotency_key=f"{draft.workflow_id}:{branch_id}",
        )
        run_id = str(result["run_id"])
        _wait_for_run(root, run_id)
        run_root = root / "runs" / run_id
        manifest = read_json(run_root / "run_manifest.json")
        if manifest.get("status") != "completed":
            raise WorkflowExecutionError(f"OLS branch {branch_id} did not complete")
        run_artifacts = _read_artifacts_index(run_root).get("artifacts", [])
        ids = [str(item["artifact_id"]) for item in run_artifacts if item.get("artifact_id")]
        if "ols_1" not in ids or "diagnostic_summary" not in ids:
            raise WorkflowExecutionError(f"OLS branch {branch_id} is missing model evidence")
        model_result = read_json(run_root / "model_results" / "ols_1.json")
        if "ci_lower" not in json.dumps(model_result) or "ci_upper" not in json.dumps(model_result):
            raise WorkflowExecutionError(f"OLS branch {branch_id} is missing coefficient confidence intervals")
        missing_figures = sorted(required_branch_figures(branch_predictors) - set(ids))
        if missing_figures:
            raise WorkflowExecutionError(
                f"OLS branch {branch_id} is missing residual/fitted diagnostics: "
                + ", ".join(missing_figures)
            )
        artifact_ids.extend(f"{run_id}:{artifact_id}" for artifact_id in ids)
        branch_outputs.append({"branch_id": branch_id, "run_id": run_id, "artifact_ids": ids})
    return WorkflowStepResult(
        artifact_ids=artifact_ids,
        row_counts={"source": len(source_frame)},
        payload={"branches": branch_outputs},
    )


def required_branch_figures(predictors: Iterable[str]) -> set[str]:
    """Residual and fitted plots the branch's own predictors imply.

    This gate used to name one exercise's columns and special-case one of
    its branch ids, so a correct single-predictor branch under any other
    name was rejected for "missing diagnostics".
    """

    figures: set[str] = set()
    for predictor in predictors:
        figures.add(f"residuals_vs_{predictor}")
        figures.add(f"fitted_vs_{predictor}")
    return figures


def _wait_for_run(root: Path, run_id: str, *, timeout_seconds: float = 1800.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    path = root / "runs" / run_id / "run_manifest.json"
    while time.monotonic() < deadline:
        if path.is_file():
            manifest = read_json(path)
            if manifest.get("status") in {"completed", "failed", "blocked", "interrupted", "cancelled"}:
                return
        time.sleep(0.1)
    raise WorkflowExecutionError(f"run did not reach a terminal state: {run_id}")


def _execute_workflow_report(
    root: Path,
    draft: WorkflowDraft,
    previous: Mapping[str, WorkflowStepResult],
) -> WorkflowStepResult:
    run_root = root / "runs" / str(draft.target["run_id"])
    log_path = root / "workbench" / "exploration" / f"{draft.workflow_id}.jsonl"
    events = []
    if log_path.is_file():
        from ..agent.storage import read_jsonl

        events = read_jsonl(log_path)
    steps = {
        step_id: {
            "status": "completed",
            "artifact_ids": list(result.artifact_ids),
        }
        for step_id, result in previous.items()
    }
    collection_id = f"workflow_report_collection_{draft.workflow_id}"
    html_id = f"workflow_report_{draft.workflow_id}_html"
    pdf_id = f"workflow_report_{draft.workflow_id}_pdf"
    xlsx_id = f"workflow_report_{draft.workflow_id}_xlsx"
    steps["step-9"] = {
        "status": "completed",
        "artifact_ids": [collection_id, html_id, pdf_id, xlsx_id],
    }
    collection = {
        "schema_version": "workflow-report-collection.v1",
        "workflow_id": draft.workflow_id,
        "workflow_plan_fingerprint": draft.plan_fingerprint,
        "status": "completed",
        "steps": steps,
        "exploration_log": events,
    }
    collection_path = run_root / "artifacts" / "statistical_exploration" / f"{draft.workflow_id}.json"
    collection_path.parent.mkdir(parents=True, exist_ok=True)
    if collection_path.exists() and read_json(collection_path) != collection:
        raise WorkflowExecutionError("workflow report collection path is occupied")
    if not collection_path.exists():
        write_json(collection_path, collection)
    register_artifact(run_root, collection_id, collection_path, "report_collection", "report.compose", [])
    view_model = {
        "title": "Statistical workflow report",
        "facts": [
            "Nine server-defined workflow steps completed.",
            f"Workflow id: {draft.workflow_id}",
            f"Source rows: {next(iter(previous.values())).row_counts.get('source', 0) if previous else 0}",
        ],
        "claims": [],
        "warnings": [],
        "descriptive_stats": [],
        "exploration": collection,
    }
    render_html_report(view_model, run_root, filename=f"{draft.workflow_id}.html", artifact_id=html_id, inputs=[collection_id])
    export_pdf(view_model, run_root, filename=f"{draft.workflow_id}.pdf", artifact_id=pdf_id, inputs=[collection_id])
    export_xlsx(
        {
            "workflow_steps": [
                {
                    "step_id": key,
                    "status": value["status"],
                    "artifact_ids": ", ".join(value["artifact_ids"]),
                }
                for key, value in steps.items()
            ]
        },
        run_root,
        filename=f"{draft.workflow_id}.xlsx",
        artifact_id=xlsx_id,
        inputs=[collection_id],
    )
    return WorkflowStepResult(
        artifact_ids=[collection_id, html_id, pdf_id, xlsx_id],
        row_counts={"steps": len(steps)},
        payload={"collection_id": collection_id},
    )


__all__ = ["build_workflow_step_executor"]
