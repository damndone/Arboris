"""Models service for workflow execution."""

from __future__ import annotations
import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping
import pandas as pd
from ...formula_terms import quote_column
from ...artifacts import read_json, sha256_file
from ...econometrics.runner import apply_ols_covariance, run_ols
from ...lineage.pipeline_drafts import (
    PipelineDraftStore,
    compute_executable_draft_hash,
    validate_draft_for_execution,
)
from ...lineage.upload_store import store_upload_bytes
from ...model_terms import (
    ModelTermError,
    dummy_column_name,
    expand_branch_terms,
    polynomial_column_name,
)
from ...repository.run_repository import _read_artifacts_index
from ...statistical_exploration import (
    ExplorationSpec,
    STATA_QUANTILE_METHOD,
    exploration_fingerprint,
    resolve_statistical_source,
)
from ...services.draft_materialization import create_genesis_draft
from ...services.draft_service import execute_genesis_draft
from ..workflow import WorkflowDraft, WorkflowExecutionError, WorkflowStepResult
from ..workflow_contracts import genesis_run_params
from ...contracts.model.family import family_context_columns, model_family_contract


def _execute_model_auto(
    *,
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    step: Any,
    frame: pd.DataFrame,
) -> WorkflowStepResult:
    from ...engine.packs.loader import bootstrap_builtin_packs
    from ...engine.registry import DEFAULT_BY_Y_TYPE
    from ...router import detect_y_kind
    outcomes = {
        str(branch["outcome"])
        for branch in step.spec.get("branches", [])
        if isinstance(branch, Mapping) and branch.get("outcome")
    }
    if len(outcomes) != 1:
        raise WorkflowExecutionError(
            "model.auto requires exactly one target column across its branches"
        )
    outcome = next(iter(outcomes))
    if outcome not in frame.columns:
        raise WorkflowExecutionError(
            f"model.auto target column is missing from the resolved frame: {outcome}"
        )
    bootstrap_builtin_packs()
    y_type = detect_y_kind(frame, outcome).value
    resolved_family = DEFAULT_BY_Y_TYPE.get(y_type)
    if not isinstance(resolved_family, str) or not resolved_family:
        raise WorkflowExecutionError(
            f"model.auto has no registered model family for target type {y_type!r}"
        )
    resolved_spec = {**step.spec, "model_family": resolved_family}
    resolved_step = replace(step, spec=resolved_spec)
    result = _execute_model_genesis_branches(
        root,
        draft,
        lineage,
        frame,
        resolved_step,
        raw_source_frame=frame,
    )
    return WorkflowStepResult(
        artifact_ids=list(result.artifact_ids),
        row_counts=dict(result.row_counts),
        empty_group_values=list(result.empty_group_values),
        result_fingerprint=result.result_fingerprint,
        payload={
            **result.payload,
            "resolved_model_family": resolved_family,
            "resolved_y_type": y_type,
        },
    )



def _execute_model_genesis_branches(
    root: Path,
    draft: WorkflowDraft,
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    step: Any = None,
    *,
    raw_source_frame: pd.DataFrame | None = None,
) -> WorkflowStepResult:
    source_run_id = str(lineage.get("run_id", draft.target["run_id"]))
    source, selected_frame = resolve_statistical_source(
        root,
        source_run_id=source_run_id,
        source_node_id=str(lineage["node_ref"]),
        source_artifact_id=str(lineage["artifact_id"]),
    )
    if source["source_sha256"] != lineage["sha256"]:
        raise WorkflowExecutionError("model genesis selected source fingerprint changed")
    source_path = root / "runs" / source_run_id / source["source_artifact_path"]
    selected_bytes = source_path.read_bytes()
    if hashlib.sha256(selected_bytes).hexdigest() != source["source_sha256"]:
        raise WorkflowExecutionError("model genesis selected source changed during read")
    filename = source_path.name
    dataset_source = {
        "source_run_id": source_run_id,
        "op_node_id": str(lineage["node_ref"]),
        "source_artifact_id": str(lineage["artifact_id"]),
        "source_sha256": source["source_sha256"],
    }
    store = PipelineDraftStore(root)
    branch_outputs: list[dict[str, Any]] = []
    artifact_ids: list[str] = []
    # Read the branches off the step being executed. Indexing draft.steps[7]
    # tied the executor to one plan's length and ordering.
    branch_spec = step.spec if step is not None else draft.steps[7].spec
    model_family = str(branch_spec["model_family"])
    family_contract = model_family_contract(model_family)
    family_source_columns = family_context_columns(family_contract, branch_spec)
    primary_model_artifact_id = family_contract.expected_artifacts[0]
    workflow_step_id = str(step.step_id) if step is not None else "legacy-model-genesis"
    for branch in branch_spec["branches"]:
        branch_id = str(branch["branch_id"])
        branch_covariance = (
            branch.get("covariance") or branch_spec.get("covariance")
            or family_contract.default_covariance
        )
        # Expand branch terms from the selected, verified dataset.
        try:
            branch_frame, branch_predictors, references = expand_branch_terms(
                source_frame, branch
            )
        except ModelTermError as exc:
            raise WorkflowExecutionError(
                f"{model_family} branch {branch_id} derived terms: {exc}"
            ) from exc
        if family_contract.validate_branch_frame is not None:
            family_contract.validate_branch_frame(branch_frame, {
                **branch, "model_options": dict(branch_spec.get("model_options") or {}),
            })
        # Preserve the exact registered bytes whenever no branch expansion
        # changes the selected table. The original run upload is not authority
        # for a transformed target; comparing that target to itself cannot
        # establish that it is the original upload.
        if branch_frame.equals(selected_frame):
            branch_upload_sha = store_upload_bytes(root, selected_bytes, filename=filename)
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
                        *family_source_columns,
                    )
                ),
                options={"quantile_method": STATA_QUANTILE_METHOD},
            )
            context = {
                "workflow_id": draft.workflow_id,
                "workflow_step_id": workflow_step_id,
                "branch_id": branch_id,
                "source_run_id": source_run_id,
                # The dataset this branch was actually built from. A branch
                # reading an upstream step's output is estimated on that table;
                # naming the workflow target here would hand every reader of
                # this draft -- resume, comparison, the report -- a digest that
                # belongs to data the model never saw.
                "source_node_id": str(lineage["node_ref"]),
                "source_artifact_id": str(lineage["artifact_id"]),
                "source_sha256": str(lineage["sha256"]),
                "exploration_fingerprint": exploration_fingerprint(str(lineage["sha256"]), spec),
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
            model_params = family_contract.build_model_params(
                branch_spec, branch, list(branch_predictors), branch_covariance
            )
            # Run-level declarations belong to the data, not to the family, so
            # they are merged once here instead of in eighteen parameter
            # builders -- which is where they were being dropped.
            model_params.update(genesis_run_params(branch_spec))
            # An optional column the spec leaves unset (one-way panel effects) is
            # absent from the draft, not None: the draft validator reads a present
            # None as a malformed column name and failed the step after the
            # person had confirmed it (paid fix2 round, panel_fe.specific).
            for field in family_contract.column_spec_fields:
                if field in model_params and model_params[field] is None:
                    del model_params[field]
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
            dataset_source=dataset_source,
        )
        run_id = str(result["run_id"])
        _wait_for_run(root, run_id)
        run_root = root / "runs" / run_id
        manifest = read_json(run_root / "run_manifest.json")
        if manifest.get("status") != "completed":
            raise WorkflowExecutionError(f"{model_family} branch {branch_id} did not complete")
        run_artifacts = _read_artifacts_index(run_root).get("artifacts", [])
        ids = [str(item["artifact_id"]) for item in run_artifacts if item.get("artifact_id")]
        by_group = branch_spec.get("by_group")
        # A by-group run writes one result per group (ols_1_g01, ...) and the
        # collection that lists them, not the family's single primary result.
        expected = (
            {"by_group_collection", *family_contract.expected_artifacts[1:]}
            if by_group else set(family_contract.expected_artifacts)
        )
        missing_artifacts = sorted(expected - set(ids))
        if missing_artifacts:
            raise WorkflowExecutionError(
                f"{model_family} branch {branch_id} is missing required evidence: "
                + ", ".join(missing_artifacts)
            )
        if by_group:
            collection = read_json(run_root / "model_results" / "collections" / "by_group.json")
            first = next(m for m in collection["members"] if m["status"] == "estimated")
            model_result = read_json(run_root / first["result_ref"])
        else:
            model_result = read_json(
                run_root / "model_results" / f"{primary_model_artifact_id}.json"
            )
        if (
            family_contract.result_shape == "coefficient_intervals"
            and ("ci_lower" not in json.dumps(model_result) or "ci_upper" not in json.dumps(model_result))
        ):
            raise WorkflowExecutionError(
                f"{model_family} branch {branch_id} is missing coefficient confidence intervals"
            )
        missing_figures = sorted(required_branch_figures(branch_predictors) - set(ids))
        if family_contract.requires_branch_figures and missing_figures:
            raise WorkflowExecutionError(
                f"{model_family} branch {branch_id} is missing required diagnostics: "
                + ", ".join(missing_figures)
            )
        artifact_ids.extend(f"{run_id}:{artifact_id}" for artifact_id in ids)
        from ...contracts.model.inference_kernel import kernel_relative_path

        kernel_path = run_root / kernel_relative_path(primary_model_artifact_id)
        branch_outputs.append(
            {
                "branch_id": branch_id,
                "run_id": run_id,
                "model_id": primary_model_artifact_id if not by_group else None,
                "inference_kernel_sha256": (
                    sha256_file(kernel_path) if not by_group and kernel_path.is_file()
                    else None
                ),
                "artifact_ids": ids,
                "branch_spec": {
                    "model_family": model_family,
                    # Post-estimation refits this branch, and the covariance
                    # estimator changes what a joint test answers. Without it
                    # recorded here the refit could only guess, and would
                    # report inference for a model nobody estimated.
                    "covariance": branch_covariance,
                    **({"by_group": str(by_group)} if by_group else {}),
                    **{
                        field_name: branch_spec.get(field_name)
                        for field_name in family_contract.context_spec_fields
                    },
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
    lineage: Mapping[str, str],
    source_frame: pd.DataFrame,
    step: Any = None,
    *,
    raw_source_frame: pd.DataFrame | None = None,
) -> WorkflowStepResult:
    """Compatibility name for callers that historically imported the OLS-only executor."""

    return _execute_model_genesis_branches(
        root,
        draft,
        lineage,
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



def _branch_covariance(branch_spec: Mapping[str, Any]) -> str:
    """The covariance estimator the completed branch was actually fitted under.

    Fails closed rather than defaulting. Silently refitting under `unadjusted`
    is what produced a joint test whose p-value belonged to a model the user
    never estimated, while carrying that model's provenance.
    """

    covariance = branch_spec.get("covariance")
    if not isinstance(covariance, str) or not covariance:
        raise WorkflowExecutionError(
            "completed model branch does not record its covariance estimator, so "
            "post-estimation inference cannot reproduce it"
        )
    if covariance not in {"unadjusted", "robust", "clustered"}:
        raise WorkflowExecutionError(
            f"completed model branch has an unsupported covariance estimator: {covariance}"
        )
    return covariance



def _refit_completed_ols_branch(
    source_frame: pd.DataFrame,
    branch: Mapping[str, Any],
) -> tuple[Any, list[str], pd.DataFrame]:
    """Reconstruct the completed OLS design and covariance from source data."""

    branch_spec = branch.get("branch_spec")
    if not isinstance(branch_spec, Mapping):
        raise WorkflowExecutionError("completed model branch lacks a branch specification")
    # Every caller refits by OLS. On a GLM/panel/IV branch that would report
    # OLS inference under that model's provenance, so refuse instead.
    model_family = branch_spec.get("model_family")
    if model_family != "ols":
        raise WorkflowExecutionError(
            f"this post-estimation step is defined for OLS models only; branch "
            f"{branch.get('branch_id')} was estimated as {model_family or 'an undeclared family'}"
        )
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
    covariance = _branch_covariance(branch_spec)
    if branch_spec.get("by_group"):
        raise WorkflowExecutionError(
            "this post-estimation step refits one model, but the branch was estimated separately by "
            f"{branch_spec['by_group']}; its group-difference tests are already in the result"
        )
    if covariance == "hac":
        # These steps refit the model; reproducing Newey-West here would need the
        # time order and lag, and the refit has not been extended to them.
        raise WorkflowExecutionError(
            "this post-estimation step refits the model and does not support HAC (Newey-West) "
            "standard errors yet; joint tests on the fitted model's inference kernel do"
        )
    cluster_col: str | None = None
    if covariance == "clustered":
        entity_col = branch_spec.get("entity_col")
        if not isinstance(entity_col, str) or not entity_col:
            raise WorkflowExecutionError(
                "clustered post-estimation requires the branch's cluster column"
            )
        cluster_col = entity_col
    try:
        # run_ols returns the *plain* fit, so the declared estimator is applied
        # here through the shared helper. Reading `fitted` straight from
        # run_ols would silently do post-estimation inference under nonrobust.
        _normalized, plain_fit = run_ols(
            branch_frame,
            str(branch_spec["outcome"]),
            predictor_columns,
            robust=covariance == "robust",
            model_id="ols_1",
            cluster_col=cluster_col,
            covariance=covariance,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowExecutionError(
            f"completed model branch cannot be refit for post-estimation: {exc}"
        ) from exc
    model_frame = branch_frame.copy()
    if not model_frame.index.is_unique:
        model_frame.index = pd.RangeIndex(len(model_frame), name="__ols_position__")
    row_labels = getattr(plain_fit.model.data, "row_labels", None)
    if row_labels is None:
        raise WorkflowExecutionError("completed model does not expose its analysis sample")
    try:
        analysis_frame = model_frame.loc[row_labels].copy()
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkflowExecutionError(
            "completed model analysis sample cannot be recovered from immutable source data"
        ) from exc
    if len(analysis_frame) != int(plain_fit.nobs):
        raise WorkflowExecutionError(
            "completed model analysis sample does not match its fitted observation count"
        )
    groups = (
        analysis_frame[cluster_col].to_numpy(copy=True) if cluster_col is not None else None
    )
    try:
        fitted = apply_ols_covariance(plain_fit, covariance, groups=groups)
    except ValueError as exc:
        raise WorkflowExecutionError(
            f"completed model covariance cannot be reproduced: {exc}"
        ) from exc
    return fitted, predictor_columns, analysis_frame



def _fitted_term_positions(fitted: Any, terms: list[str]) -> list[int]:
    names = [str(item) for item in getattr(fitted.model, "exog_names", [])]
    positions: list[int] = []
    for term in terms:
        fitted_name = quote_column(term)
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



def _branch_kernel(root: Path, branch: Mapping[str, Any]) -> dict[str, Any]:
    """The inference kernel the completed model branch's run persisted."""
    from ...contracts.model.inference_kernel import InferenceKernelError, validate_inference_kernel

    spec = branch.get("branch_spec") if isinstance(branch.get("branch_spec"), Mapping) else {}
    if spec.get("by_group"):
        raise WorkflowExecutionError(
            f"the branch was estimated separately by {spec['by_group']}, one result per group; its "
            "group-difference tests are in the result, and a test within one group names that group's model"
        )
    directory = root / "runs" / str(branch["run_id"]) / "model_results" / "inference_kernels"
    paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if len(paths) != 1:
        raise WorkflowExecutionError(
            "the completed model branch has no single inference kernel; rerun the branch to test it"
        )
    kernel = read_json(paths[0])
    try:
        validate_inference_kernel(kernel)
        if kernel.get("model_id") != branch.get("model_id") or paths[0].stem != branch.get("model_id"):
            raise InferenceKernelError("the branch kernel identity does not match its model owner")
    except InferenceKernelError as exc:
        raise WorkflowExecutionError(f"the branch's inference kernel is not usable: {exc}") from exc
    from ...postestimation.comparison_data import assert_completed_kernel

    try:
        assert_completed_kernel(root / "runs" / str(branch["run_id"]), kernel)
    except (OSError, ValueError, KeyError) as exc:
        raise WorkflowExecutionError(f"the branch's completed kernel binding is not usable: {exc}") from exc
    return kernel



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
