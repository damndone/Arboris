"""Native service adapter that executes one compiled workflow step."""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
from scipy import stats

from ..artifacts import read_json, register_artifact, sha256_file, write_json, write_text_durable
from ..econometrics.runner import run_ols
from ..exports import export_pdf, export_xlsx
from ..graph_model import BranchRef, Edge, Graph, Node, NodeKind, Stage, Trust
from ..graph_store import GraphStore
from ..lineage.pipeline_drafts import (
    PipelineDraftStore,
    compute_executable_draft_hash,
    validate_draft_for_execution,
)
from ..lineage.run_inputs import read_run_inputs
from ..lineage.upload_store import store_upload_bytes, verify_upload
from ..model_terms import (
    ModelTermError,
    dummy_column_name,
    expand_branch_terms,
    polynomial_column_name,
)
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


_NUMERIC_DERIVATION_SCHEMA = "workflow-derived-numeric.v1"


def _apply_numeric_recipes(
    frame: pd.DataFrame,
    recipes: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply the closed transform vocabulary to a copy of a source frame.

    Contract validation owns recipe shape; runtime validation owns actual data
    domain checks.  In particular, a log is never silently evaluated on zero,
    negative, or non-numeric values, and arithmetic cannot produce infinities.
    """

    derived = frame.copy()
    summaries: list[dict[str, Any]] = []
    for recipe in recipes:
        operator = str(recipe["operator"])
        inputs = [str(column) for column in recipe["input_columns"]]
        output_name = str(recipe["output_name"])
        if output_name in derived.columns:
            raise WorkflowExecutionError(
                f"numeric derivation output already exists: {output_name}"
            )
        missing = [column for column in inputs if column not in derived.columns]
        if missing:
            raise WorkflowExecutionError(
                "numeric derivation source column is unavailable: " + ", ".join(missing)
            )
        numeric_inputs: list[pd.Series] = []
        for column in inputs:
            original = derived[column]
            converted = pd.to_numeric(original, errors="coerce")
            if bool((original.notna() & converted.isna()).any()):
                raise WorkflowExecutionError(
                    f"numeric derivation input is not numeric: {column}"
                )
            numeric_inputs.append(converted.astype(float))
        if operator == "natural_log":
            value = numeric_inputs[0]
            if bool((value.dropna() <= 0).any()):
                raise WorkflowExecutionError(
                    f"natural_log requires strictly positive values: {inputs[0]}"
                )
            result = np.log(value)
        elif operator == "multiply":
            result = numeric_inputs[0] * numeric_inputs[1]
        else:  # contract validation should make this unreachable
            raise WorkflowExecutionError(f"numeric derivation operator is unsupported: {operator}")
        finite = result.notna()
        if bool((~np.isfinite(result[finite])).any()):
            raise WorkflowExecutionError(
                f"numeric derivation produced non-finite values: {output_name}"
            )
        derived[output_name] = result
        summaries.append(
            {
                "operator": operator,
                "input_columns": inputs,
                "output_name": output_name,
                "nonmissing_count": int(finite.sum()),
                "missing_count": int(result.isna().sum()),
            }
        )
    return derived, summaries


def _upstream_numeric_steps(
    draft: WorkflowDraft,
    step_id: str,
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> tuple[Any, ...]:
    """Return declared numeric ancestors in compiled topological order."""

    seen: set[str] = set()

    def visit(current: str) -> None:
        for dependency in dependency_graph.get(current, ()):
            if dependency in seen:
                continue
            seen.add(dependency)
            visit(dependency)

    visit(step_id)
    return tuple(
        item
        for item in draft.steps
        if item.step_id in seen and item.operation_id == "statistical.derive_numeric"
    )


def _workflow_input_frame(
    source_frame: pd.DataFrame,
    draft: WorkflowDraft,
    step: Any,
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> pd.DataFrame:
    """Rebuild the exact transformed input for a step from its declared DAG."""

    frame = source_frame
    for transform_step in _upstream_numeric_steps(draft, str(step.step_id), dependency_graph):
        frame, _ = _apply_numeric_recipes(frame, transform_step.spec["recipes"])
    return frame


def _ensure_runtime_artifact(
    run_root: Path,
    *,
    artifact_id: str,
    path: Path,
    artifact_type: str,
    step: str,
    inputs: list[str],
) -> None:
    index = _read_artifacts_index(run_root)
    matching = [item for item in index.get("artifacts", []) if item.get("artifact_id") == artifact_id]
    digest = sha256_file(path)
    if matching:
        if len(matching) != 1 or matching[0].get("sha256") != digest:
            raise WorkflowExecutionError("workflow-derived artifact binding is not deterministic")
        return
    register_artifact(run_root, artifact_id, path, artifact_type, step, inputs)


def _persist_numeric_derivation(
    *,
    root: Path,
    draft: WorkflowDraft,
    source_context: Mapping[str, Any],
    frame: pd.DataFrame,
    step: Any,
) -> WorkflowStepResult:
    """Persist a derived dataset + recipe and add one visible graph child."""

    derived, summaries = _apply_numeric_recipes(frame, step.spec["recipes"])
    source_run_id = str(draft.target["run_id"])
    run_root = root / "runs" / source_run_id
    fingerprint = str(step.fingerprint)
    relative_dir = Path("derived") / "workflow_numeric" / fingerprint
    data_rel = (relative_dir / "data.csv").as_posix()
    recipe_rel = (relative_dir / "recipe.json").as_posix()
    data_path = run_root / data_rel
    recipe_path = run_root / recipe_rel
    data_path.parent.mkdir(parents=True, exist_ok=True)
    recipe = {
        "schema_version": _NUMERIC_DERIVATION_SCHEMA,
        "workflow_id": draft.workflow_id,
        "workflow_step_id": str(step.step_id),
        "workflow_step_fingerprint": fingerprint,
        "source": {
            "artifact_id": str(draft.target["artifact_id"]),
            "sha256": str(source_context["source_sha256"]),
        },
        "recipes": [dict(recipe) for recipe in step.spec["recipes"]],
        "result": {"path": data_rel, "output_columns": summaries},
    }
    if recipe_path.exists():
        if read_json(recipe_path) != recipe:
            raise WorkflowExecutionError("numeric derivation recipe path is occupied")
    else:
        write_json(recipe_path, recipe)
    serialized_data = derived.to_csv(index=False)
    if data_path.exists():
        if data_path.read_text(encoding="utf-8") != serialized_data:
            raise WorkflowExecutionError("numeric derivation data path is occupied")
    else:
        write_text_durable(data_path, serialized_data)
    data_artifact_id = f"workflow_derived_numeric_{fingerprint[:24]}"
    recipe_artifact_id = f"workflow_derived_numeric_recipe_{fingerprint[:24]}"
    _ensure_runtime_artifact(
        run_root,
        artifact_id=data_artifact_id,
        path=data_path,
        artifact_type="derived_data",
        step="workflow.derive_numeric",
        inputs=[str(draft.target["artifact_id"])],
    )
    _ensure_runtime_artifact(
        run_root,
        artifact_id=recipe_artifact_id,
        path=recipe_path,
        artifact_type="metadata",
        step="workflow.derive_numeric",
        inputs=[str(draft.target["artifact_id"]), data_artifact_id],
    )
    child_node_id = f"data-derive-numeric:{fingerprint[:24]}"
    branch_id = f"workflow-numeric:{fingerprint[:20]}"
    source_node_id = str(draft.target["node_ref"])

    def add_child(graph: Graph) -> Graph:
        if child_node_id in graph.nodes:
            return graph
        child = Node(
            id=child_node_id,
            kind=NodeKind.DATASET_STAGE,
            display_label="Derived numeric columns",
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_stage_id=source_node_id,
            branch_id=branch_id,
            trust=Trust.OK,
            payload_ref=data_rel,
            summary=(
                f"{len(summaries)} declared numeric transform(s); "
                f"{len(derived)} rows"
            ),
            annotations=(
                {
                    "type": "workflow_numeric_derivation",
                    "workflow_id": draft.workflow_id,
                    "workflow_step_id": str(step.step_id),
                    "recipe_path": recipe_rel,
                },
            ),
            stage=Stage.TRANSFORM,
        )
        return Graph(
            schema_version=graph.schema_version,
            run_id=graph.run_id,
            nodes={**graph.nodes, child_node_id: child},
            edges={
                **graph.edges,
                f"edge:{child_node_id}": Edge(
                    id=f"edge:{child_node_id}",
                    source_id=source_node_id,
                    target_id=child_node_id,
                    op="workflow.derive_numeric",
                    params={"workflow_step_id": str(step.step_id)},
                ),
            },
            branches={
                **graph.branches,
                branch_id: BranchRef(
                    id=branch_id,
                    forked_from_node_id=source_node_id,
                    head_node_ids=(child_node_id,),
                ),
            },
            legacy=graph.legacy,
        )

    GraphStore(root / "runs").mutate(source_run_id, add_child)
    node_index_path = run_root / "node_index.json"
    if node_index_path.is_file():
        node_index = read_json(node_index_path)
        entry = {
            "node_hash": sha256_file(data_path),
            "producing_stage": "workflow.derive_numeric",
            "cas_ref": {"node_hash": sha256_file(data_path), "artifact": data_rel},
        }
        existing = node_index.get(child_node_id)
        if existing is not None and existing != entry:
            raise WorkflowExecutionError("numeric derivation node identity is not deterministic")
        if existing is None:
            write_json(node_index_path, {**node_index, child_node_id: entry})
    return WorkflowStepResult(
        artifact_ids=[data_artifact_id, recipe_artifact_id],
        row_counts={item["output_name"]: item["nonmissing_count"] for item in summaries},
        result_fingerprint=fingerprint,
        payload={"output_columns": summaries, "child_node_id": child_node_id},
    )


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


def build_workflow_step_executor(
    project_root: Path | str,
    draft: WorkflowDraft,
    *,
    custom_step_executor=None,
):
    """Return one callback that dispatches only the compiled step identities.

    ``model.custom`` is intentionally an injected gateway.  The default
    runtime has no authority to reserve, spawn, or dispatch it; the caller
    must supply a gateway that has already joined Proposal/Risk authorization,
    the exact binding, and the B1 broker.
    """

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
        step_frame = _workflow_input_frame(
            source_frame, draft, step, dependency_graph
        )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_explore" and "plots" not in step.spec:
            return _exploration_step(
                root=root,
                draft=draft,
                source_context=source_context,
                source_frame=step_frame,
                spec=_exploration_spec(step.spec),
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.statistical_derive_numeric":
            return _persist_numeric_derivation(
                root=root,
                draft=draft,
                source_context=source_context,
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
                    source_frame=step_frame,
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
                result = execute_exploration(step_frame, spec)
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
                    source_frame=step_frame,
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
            return _execute_model_genesis_branches(
                root,
                draft,
                source_context,
                step_frame,
                step,
                raw_source_frame=source_frame,
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.model_joint_f_test":
            return _execute_model_joint_f_test(
                root, draft, source_context, step_frame, step, previous
            )
        if dispatcher_key == "workbench.agent.workflow_runtime.model_white_test":
            return _execute_model_white_test(
                root, draft, source_context, step_frame, step, previous
            )
        if dispatcher_key == (
            "workbench.agent.workflow_runtime.model_quadratic_stationary_point"
        ):
            return _execute_model_quadratic_stationary_point(
                root, draft, source_context, step_frame, step, previous
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
            return _execute_workflow_report(root, draft, previous, step)
        raise WorkflowExecutionError(
            f"unsupported workflow operation: {step.operation_id}"
        )

    return execute


def _execute_model_genesis_branches(
    root: Path,
    draft: WorkflowDraft,
    source_context: Mapping[str, Any],
    source_frame: pd.DataFrame,
    step: Any = None,
    *,
    raw_source_frame: pd.DataFrame | None = None,
) -> WorkflowStepResult:
    source_run_id = str(draft.target["run_id"])
    source_run_root = root / "runs" / source_run_id
    inputs = read_run_inputs(source_run_root)
    upload = inputs.get("upload") or {}
    upload_sha = upload.get("sha256")
    filename = upload.get("filename") or "dataset.csv"
    if not isinstance(upload_sha, str) or not upload_sha:
        raise WorkflowExecutionError("raw source upload is unavailable for model genesis")
    upload_bytes = verify_upload(root, upload_sha).read_bytes()
    store = PipelineDraftStore(root)
    branch_outputs: list[dict[str, Any]] = []
    artifact_ids: list[str] = []
    # Read the branches off the step being executed. Indexing draft.steps[7]
    # tied the executor to one plan's length and ordering.
    branch_spec = step.spec if step is not None else draft.steps[7].spec
    model_family = str(branch_spec["model_family"])
    primary_model_artifact_id = f"{model_family}_1"
    workflow_step_id = str(step.step_id) if step is not None else "legacy-model-genesis"
    for branch in branch_spec["branches"]:
        branch_id = str(branch["branch_id"])
        branch_covariance = branch.get("covariance") or branch_spec.get("covariance") or "unadjusted"
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
        # A branch can have no branch-local dummy/polynomial expansion and
        # still depend on an upstream numeric derivation.  Reusing the original
        # upload in that case would silently discard a declared column before
        # Genesis runs.  Only retain the original upload when the final design
        # is exactly the immutable raw source; otherwise store the complete,
        # server-derived table for this branch.
        raw_frame = source_frame if raw_source_frame is None else raw_source_frame
        use_original_upload = (
            list(branch_frame.columns) == list(raw_frame.columns)
            and branch_frame.equals(raw_frame)
        )
        if use_original_upload:
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
            context_step = context.get("workflow_step_id")
            if (
                context_workflow == draft.workflow_id
                and context_branch == branch_id
                and context_step == workflow_step_id
            ):
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
                    or (
                        str(branch["outcome"]),
                        *[str(c) for c in branch["predictors"]],
                        *[
                            str(column)
                            for column in (branch_spec.get("entity_col"), branch_spec.get("time_col"))
                            if column
                        ],
                    )
                ),
                options={"quantile_method": STATA_QUANTILE_METHOD},
            )
            context = {
                "workflow_id": draft.workflow_id,
                "workflow_step_id": workflow_step_id,
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
                "model_family": model_family,
                "covariance": branch_covariance,
                "workflow_plan_fingerprint": draft.plan_fingerprint,
            }
            model_params: dict[str, Any] = {
                "model_type": model_family,
                "y": branch["outcome"],
                "x": list(branch_predictors),
                "covariance": branch_covariance,
            }
            if model_family == "ols":
                model_params["model_options"] = {"covariance": branch_covariance}
            else:
                model_params["entity_col"] = branch_spec.get("entity_col")
                model_params["time_col"] = branch_spec.get("time_col")
            stored = create_genesis_draft(
                root,
                upload_sha256=branch_upload_sha,
                filename=branch_filename,
                sheet_names=(),
                columns=tuple(str(column) for column in branch_frame.columns),
                model_params=model_params,
                exploration_context=context,
                notebook_provenance=(
                    dict(draft.bindings["notebook_provenance"])
                    if isinstance(draft.bindings.get("notebook_provenance"), Mapping)
                    else None
                ),
            )
        validation = validate_draft_for_execution(stored.draft, execution_mode="genesis")
        if not validation.get("executable"):
            raise WorkflowExecutionError(
                f"{model_family} Draft validation failed for {branch_id}: {validation.get('checks')}"
            )
        result = execute_genesis_draft(
            stored.draft["draft_id"],
            root,
            store,
            stored,
            validated_draft_hash=compute_executable_draft_hash(stored.draft),
            execution_mode="genesis",
            idempotency_key=f"{draft.workflow_id}:{workflow_step_id}:{branch_id}",
        )
        run_id = str(result["run_id"])
        _wait_for_run(root, run_id)
        run_root = root / "runs" / run_id
        manifest = read_json(run_root / "run_manifest.json")
        if manifest.get("status") != "completed":
            raise WorkflowExecutionError(f"{model_family} branch {branch_id} did not complete")
        run_artifacts = _read_artifacts_index(run_root).get("artifacts", [])
        ids = [str(item["artifact_id"]) for item in run_artifacts if item.get("artifact_id")]
        if primary_model_artifact_id not in ids:
            raise WorkflowExecutionError(
                f"{model_family} branch {branch_id} is missing model evidence"
            )
        if model_family == "ols" and "diagnostic_summary" not in ids:
            raise WorkflowExecutionError(f"OLS branch {branch_id} is missing diagnostics")
        model_result = read_json(
            run_root / "model_results" / f"{primary_model_artifact_id}.json"
        )
        if "ci_lower" not in json.dumps(model_result) or "ci_upper" not in json.dumps(model_result):
            raise WorkflowExecutionError(
                f"{model_family} branch {branch_id} is missing coefficient confidence intervals"
            )
        missing_figures = sorted(required_branch_figures(branch_predictors) - set(ids))
        if model_family == "ols" and missing_figures:
            raise WorkflowExecutionError(
                f"OLS branch {branch_id} is missing residual/fitted diagnostics: "
                + ", ".join(missing_figures)
            )
        artifact_ids.extend(f"{run_id}:{artifact_id}" for artifact_id in ids)
        branch_outputs.append(
            {
                "branch_id": branch_id,
                "run_id": run_id,
                "artifact_ids": ids,
                "branch_spec": {
                    "model_family": model_family,
                    "entity_col": branch_spec.get("entity_col"),
                    "time_col": branch_spec.get("time_col"),
                    "outcome": str(branch["outcome"]),
                    "predictors": [str(item) for item in branch["predictors"]],
                    "categorical": [str(item) for item in branch.get("categorical", []) or []],
                    "polynomials": [dict(item) for item in branch.get("polynomials", []) or []],
                },
                "predictor_columns": list(branch_predictors),
                "term_groups": _declared_branch_term_groups(
                    branch,
                    branch_frame,
                    branch_predictors,
                    references,
                ),
            }
        )
    return WorkflowStepResult(
        artifact_ids=artifact_ids,
        row_counts={"source": len(source_frame)},
        payload={"branches": branch_outputs},
    )


def _execute_ols_branches(
    root: Path,
    draft: WorkflowDraft,
    source_context: Mapping[str, Any],
    source_frame: pd.DataFrame,
    step: Any = None,
    *,
    raw_source_frame: pd.DataFrame | None = None,
) -> WorkflowStepResult:
    """Compatibility name for callers that historically imported the OLS-only executor."""

    return _execute_model_genesis_branches(
        root,
        draft,
        source_context,
        source_frame,
        step,
        raw_source_frame=raw_source_frame,
    )


def _declared_branch_term_groups(
    branch: Mapping[str, Any],
    branch_frame: pd.DataFrame,
    branch_predictors: list[str],
    references: Mapping[str, Any],
) -> dict[str, dict[str, list[str]]]:
    """Map only a branch's declared source terms to its fitted columns."""

    groups: dict[str, dict[str, list[str]]] = {
        "linear": {},
        "categorical": {},
        "polynomial": {},
    }
    available = set(branch_predictors)
    for column in [str(item) for item in branch.get("predictors", []) or []]:
        if column in available:
            groups["linear"][column] = [column]
    for column in [str(item) for item in branch.get("categorical", []) or []]:
        reference = references.get(column)
        if reference is None or column not in branch_frame.columns:
            continue
        levels = branch_frame[column].dropna().unique().tolist()
        levels.sort(key=lambda value: (str(type(value)), value))
        terms = [
            dummy_column_name(column, level)
            for level in levels
            if level != reference and dummy_column_name(column, level) in available
        ]
        if terms:
            groups["categorical"][column] = terms
    for entry in branch.get("polynomials", []) or []:
        if not isinstance(entry, Mapping):
            continue
        column = entry.get("column")
        degree = entry.get("degree")
        if not isinstance(column, str) or isinstance(degree, bool) or not isinstance(degree, int):
            continue
        terms = [
            polynomial_column_name(column, power)
            for power in range(2, degree + 1)
            if polynomial_column_name(column, power) in available
        ]
        if terms:
            groups["polynomial"][column] = terms
    return groups


def _dependent_model_branch(
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
) -> dict[str, Any]:
    """Resolve a branch only from a direct completed model dependency."""

    branch_id = str(step.spec["branch_id"])
    matches: list[dict[str, Any]] = []
    for dependency_id in step.depends_on:
        dependency = previous.get(dependency_id)
        branches = dependency.payload.get("branches") if dependency is not None else None
        if not isinstance(branches, list):
            continue
        for branch in branches:
            if isinstance(branch, Mapping) and branch.get("branch_id") == branch_id:
                matches.append(dict(branch))
    if not matches:
        raise WorkflowExecutionError(
            f"{step.step_id} must directly depend on a completed model branch: {branch_id}"
        )
    if len(matches) != 1:
        raise WorkflowExecutionError(
            f"{step.step_id} has an ambiguous completed model branch: {branch_id}"
        )
    branch = matches[0]
    if not isinstance(branch.get("branch_spec"), Mapping) or not isinstance(
        branch.get("term_groups"), Mapping
    ):
        raise WorkflowExecutionError(
            f"completed model branch {branch_id} lacks declared-term provenance"
        )
    return branch


def _refit_completed_ols_branch(
    source_frame: pd.DataFrame,
    branch: Mapping[str, Any],
) -> tuple[Any, list[str], pd.DataFrame]:
    """Reconstruct the exact unadjusted OLS design from immutable source data."""

    branch_spec = branch.get("branch_spec")
    if not isinstance(branch_spec, Mapping):
        raise WorkflowExecutionError("completed model branch lacks a branch specification")
    try:
        branch_frame, predictor_columns, _references = expand_branch_terms(
            source_frame,
            branch_spec,
        )
    except ModelTermError as exc:
        raise WorkflowExecutionError(
            f"completed model branch cannot be reconstructed: {exc}"
        ) from exc
    expected = branch.get("predictor_columns")
    if not isinstance(expected, list) or predictor_columns != [str(item) for item in expected]:
        raise WorkflowExecutionError(
            "completed model branch design no longer matches its declared provenance"
        )
    try:
        _normalized, fitted = run_ols(
            branch_frame,
            str(branch_spec["outcome"]),
            predictor_columns,
            robust=False,
            model_id="ols_1",
            covariance="unadjusted",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowExecutionError(
            f"completed model branch cannot be refit for post-estimation: {exc}"
        ) from exc
    model_frame = branch_frame.copy()
    if not model_frame.index.is_unique:
        model_frame.index = pd.RangeIndex(len(model_frame), name="__ols_position__")
    row_labels = getattr(fitted.model.data, "row_labels", None)
    if row_labels is None:
        raise WorkflowExecutionError("completed model does not expose its analysis sample")
    try:
        analysis_frame = model_frame.loc[row_labels].copy()
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowExecutionError(
            "completed model analysis sample cannot be recovered from immutable source data"
        ) from exc
    if len(analysis_frame) != int(fitted.nobs):
        raise WorkflowExecutionError(
            "completed model analysis sample does not match its fitted observation count"
        )
    return fitted, predictor_columns, analysis_frame


def _fitted_term_positions(fitted: Any, terms: list[str]) -> list[int]:
    names = [str(item) for item in getattr(fitted.model, "exog_names", [])]
    positions: list[int] = []
    for term in terms:
        fitted_name = f"Q({term!r})"
        try:
            positions.append(names.index(fitted_name))
        except ValueError as exc:
            raise WorkflowExecutionError(
                f"completed model is missing the declared coefficient term: {term}"
            ) from exc
    return positions


def _selected_model_terms(branch: Mapping[str, Any], selectors: list[Any]) -> list[str]:
    groups = branch.get("term_groups")
    if not isinstance(groups, Mapping):
        raise WorkflowExecutionError("completed model branch lacks declared term groups")
    selected: list[str] = []
    for selector in selectors:
        if not isinstance(selector, Mapping):
            raise WorkflowExecutionError("joint F test selector is invalid")
        kind = str(selector.get("kind"))
        column = str(selector.get("column"))
        by_column = groups.get(kind)
        terms = by_column.get(column) if isinstance(by_column, Mapping) else None
        if not isinstance(terms, list) or not terms:
            raise WorkflowExecutionError(
                "joint F test selector is not declared by the completed model branch: "
                f"{kind}:{column}"
            )
        selected.extend(str(item) for item in terms)
    return list(dict.fromkeys(selected))


def _persist_model_post_estimation_result(
    root: Path,
    draft: WorkflowDraft,
    step: Any,
    *,
    artifact_type: str,
    result: Mapping[str, Any],
    model_run_id: str,
    source_sha256: str,
) -> WorkflowStepResult:
    """Persist one durable, idempotent post-estimation artifact on the source run."""

    run_root = root / "runs" / str(draft.target["run_id"])
    token = str(step.fingerprint).removeprefix("sha256:")[:24]
    operation_token = str(step.operation_id).replace(".", "_")
    artifact_id = f"workflow_{operation_token}_{token}"
    artifact_path = run_root / "artifacts" / artifact_type / f"{artifact_id}.json"
    payload = {
        "schema_version": "workbench.workflow.post-estimation/v1",
        "source": {
            "run_id": str(draft.target["run_id"]),
            "node_ref": str(draft.target["node_ref"]),
            "artifact_id": str(draft.target["artifact_id"]),
            "sha256": source_sha256,
            "model_run_id": model_run_id,
            "model_artifact_id": "ols_1",
            "workflow_id": draft.workflow_id,
            "workflow_step_id": step.step_id,
            "workflow_step_fingerprint": step.fingerprint,
        },
        "result": dict(result),
    }
    if artifact_path.exists():
        if read_json(artifact_path) != payload:
            raise WorkflowExecutionError("post-estimation artifact path is occupied")
    else:
        write_json(artifact_path, payload)
    index = _read_artifacts_index(run_root)
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
            [str(draft.target["artifact_id"])],
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


def _execute_model_joint_f_test(
    root: Path,
    draft: WorkflowDraft,
    source_context: Mapping[str, Any],
    source_frame: pd.DataFrame,
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
) -> WorkflowStepResult:
    branch = _dependent_model_branch(step, previous)
    selectors = step.spec.get("term_selectors")
    if not isinstance(selectors, list):
        raise WorkflowExecutionError("joint F test term selectors are unavailable")
    terms = _selected_model_terms(branch, selectors)
    fitted, _predictor_columns, _analysis_frame = _refit_completed_ols_branch(
        source_frame, branch
    )
    positions = _fitted_term_positions(fitted, terms)
    restriction = np.zeros((len(positions), len(fitted.model.exog_names)))
    for row, position in enumerate(positions):
        restriction[row, position] = 1.0
    test = fitted.f_test(restriction)
    f_statistic = float(np.asarray(test.fvalue).squeeze())
    p_value = float(np.asarray(test.pvalue).squeeze())
    denominator_df = float(np.asarray(test.df_denom).squeeze())
    numerator_df = float(np.asarray(test.df_num).squeeze())
    if not all(math.isfinite(value) for value in (f_statistic, p_value, denominator_df, numerator_df)):
        raise WorkflowExecutionError("joint F test produced a non-finite result")
    result = {
        "schema_version": "workbench.model.joint-f-test/v1",
        "test": "joint_f_test",
        "branch_id": str(branch["branch_id"]),
        "term_selectors": [dict(item) for item in selectors if isinstance(item, Mapping)],
        "coefficient_terms": terms,
        "f_statistic": f_statistic,
        "p_value": p_value,
        "numerator_df": numerator_df,
        "denominator_df": denominator_df,
        "nobs": int(fitted.nobs),
        "covariance": "unadjusted",
    }
    return _persist_model_post_estimation_result(
        root,
        draft,
        step,
        artifact_type="statistical_test",
        result=result,
        model_run_id=str(branch["run_id"]),
        source_sha256=str(source_context["source_sha256"]),
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
    source_context: Mapping[str, Any],
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
        "covariance": "unadjusted",
    }
    return _persist_model_post_estimation_result(
        root,
        draft,
        step,
        artifact_type="statistical_test",
        result=result,
        model_run_id=str(branch["run_id"]),
        source_sha256=str(source_context["source_sha256"]),
    )


def _execute_model_quadratic_stationary_point(
    root: Path,
    draft: WorkflowDraft,
    source_context: Mapping[str, Any],
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
        "covariance": "unadjusted",
    }
    return _persist_model_post_estimation_result(
        root,
        draft,
        step,
        artifact_type="post_estimation",
        result=result,
        model_run_id=str(branch["run_id"]),
        source_sha256=str(source_context["source_sha256"]),
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
    step: Any | None = None,
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
    report_step_id = getattr(step, "step_id", None)
    if not isinstance(report_step_id, str) or not report_step_id:
        report_step_id = next(
            (
                candidate.step_id
                for candidate in draft.steps
                if candidate.operation_id == "report.compose"
            ),
            "report.compose",
        )
    steps[report_step_id] = {
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
            f"Workflow steps completed: {len(steps)}.",
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
