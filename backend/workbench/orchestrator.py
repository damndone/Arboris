from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .artifacts import read_json, register_artifact, write_json
from .cleaning import clean_frame, normalize_column_name
from .config import load_config
from .diagnostic_summary import build_diagnostic_summary
from .domain import GuardrailIssue, Severity
from .engine.context import DataHandle, ModelingContext, RunEnv
from .engine.stages.cleaning import CleaningStage
from .engine.stages.profile import ProfileStage
from .engine.stages.routing import RoutingStage
from .engine.stages.source import SourceStage
from .engine.stages.validation import ValidationStage
from .engine.stages.ytype import YTypeStage
from .engine.stages.pre_estimation_checks import PreEstimationChecksStage
from .engine.stages.roles import RoleInferenceStage
from .engine.stages.exposure import ExposureDetectionStage
from .engine.stages.statistical_tests import StatisticalTestsStage
from .engine.stages.imputation import ImputationStage
from .engine.stages.estimation import EstimationStage
from .engine.stages.recording import RecordingStage
from .engine.stages.diagnostics import DiagnosticsStage
from .engine.stages.reliability import ReliabilityStage
from .engine.stages.report import ReportStage
from .graph_recorder import GraphRecorder
from .graph_model import Stage
from .graph_store import GraphStore
from . import graph_decision_factory as dpf
from .econometrics.optional_deps import OptionalDependencyNotInstalled
from .econometrics.diagnostics import compute_diagnostics
from .econometrics.runner import (
    run_glm,
    run_logit,
    run_negative_binomial,
    run_ols,
    run_panel_ols,
    run_poisson,
    run_probit,
    run_time_series_diagnostics,
)
from .exports import export_pdf, export_xlsx
from .ingestion import ingest_files
from .imputation import run_mice_imputation
from .metadata import infer_schema
from .narrative import build_claims
from .profiling import profile_frame
from .prediction import run_prediction_model
from .projects import create_run
from .reporting import render_html_report
from .router import classify_dataset, detect_y_kind
from .statistical_tests import (
    run_statistical_tests,
    summarize_statistical_tests,
    write_statistical_test_artifacts,
)
from .validation import has_blockers, validate_profile
from .variable_roles import infer_variable_roles
from .visualization import create_figures

# ============================================================
# AUTO-DETECTION (computed from data, dataset-agnostic):
#   - Binary variable correlation: checks all binary X pairs
#   - Exposure candidates: matches column name patterns
#   - Suspicious dtype: datetime columns in X
#   - Binary/suspicious variable detection: based on data values
#
# HARDCODED THRESHOLDS (configurable defaults):
#   _BINARY_CORRELATION_WARN = 0.7
#   _BINARY_CORRELATION_INFO = 0.5
#   _EXPOSURE_NAME_PATTERNS = (...)
#   _SUSPICIOUS_NAME_PATTERNS = (...)
# ============================================================


class WorkflowValidationError(ValueError):
    """Structured validation error with error code and evidence context.

    Raised when a workflow cannot proceed due to a known, diagnosable
    configuration or input issue (unsupported model, bad GLM family,
    etc.).  The error code and evidence are used to write a structured
    ``errors.json`` entry so the failure is machine-readable, not a
    generic ``WORKFLOW_FAILED``.
    """

    def __init__(
        self,
        error_code: str,
        message: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.evidence = evidence or {}


# ---------------------------------------------------------------------------
# Per-model-type metadata used to build structured failure details.
# ---------------------------------------------------------------------------
_MODEL_METADATA: dict[str, dict[str, str]] = {
    "ols":               {"model_id": "ols_1",               "engine": "statsmodels"},
    "logit":             {"model_id": "logit_1",             "engine": "statsmodels"},
    "probit":            {"model_id": "probit_1",            "engine": "statsmodels"},
    "poisson":           {"model_id": "poisson_1",           "engine": "statsmodels"},
    "negative_binomial": {"model_id": "negative_binomial_1", "engine": "statsmodels"},
    "panel_ols":         {"model_id": "panel_ols_1",         "engine": "linearmodels"},
    "prediction_lasso":          {"model_id": "prediction_lasso_1",          "engine": "scikit-learn"},
    "prediction_ridge":          {"model_id": "prediction_ridge_1",          "engine": "scikit-learn"},
    "prediction_random_forest":  {"model_id": "prediction_random_forest_1",  "engine": "scikit-learn"},
}

# Map auto-detected y_type back to the model type actually attempted,
# so that failure evidence names the correct model (e.g. "logit",
# not "binary").
_Y_TYPE_TO_ATTEMPTED_MODEL: dict[str, str] = {
    "binary": "logit",
    "count": "poisson",
    "continuous": "ols",
}

# Maximum length of root_cause string in failure evidence to avoid
# leaking verbose stack traces into errors.json.
_ROOT_CAUSE_MAX_LENGTH = 300


def _model_id_for_type(model_type: str) -> str:
    """Return the canonical model_id for a given model_type string."""
    meta = _MODEL_METADATA.get(model_type)
    if meta is not None:
        return meta["model_id"]
    if model_type.startswith("glm:"):
        return "glm_1"
    return f"{model_type}_1"


def _engine_for_type(model_type: str) -> str:
    """Return the engine string for a given model_type."""
    meta = _MODEL_METADATA.get(model_type)
    if meta is not None:
        return meta["engine"]
    if model_type.startswith("glm:"):
        return "statsmodels"
    return "unknown"


def _model_failure_details(
    *,
    model_type: str,
    y: str,
    x: list[str],
    root_cause: str,
    step: str = "estimation",
) -> dict[str, Any]:
    """Build a consistent evidence dict for model-failure issues.

    Every ``MODEL_FIT_FAILED``, ``UNSUPPORTED_MODEL_TYPE``, etc. issue
    must include at least ``model_type``, ``model_id``, ``engine``,
    ``step``, ``y``, ``x``, and ``root_cause`` so that downstream
    consumers (diagnostic summary, report view-model) can render the
    failure without guessing context.
    """
    return {
        "model_type": model_type,
        "model_id": _model_id_for_type(model_type),
        "engine": _engine_for_type(model_type),
        "step": step,
        "y": y,
        "x": list(x),
        "root_cause": root_cause[:_ROOT_CAUSE_MAX_LENGTH],
    }


def run_workflow(
    project_root: Path,
    input_files: list[Path],
    *,
    mode: str,
    y: str,
    x: list[str],
    model_type: str = "auto",
    imputation: dict | None = None,
    entity_col: str = "",
    time_col: str = "",
    covariance: str = "",
    prediction_model_type: str = "",
    prediction_cv_folds: int = 0,
    prediction_sampling_method: str = "",
) -> dict[str, str]:
    project_root = Path(project_root)
    config = load_config(project_root / "config.yml")
    run = create_run(project_root, mode=mode)
    started_at = datetime.now(timezone.utc).isoformat()
    _write_manifest(
        run.root,
        run.run_id,
        mode,
        "running",
        _lineage(input_files),
        started_at=started_at,
        y=y,
        x=x,
        requested_model_type=model_type,
    )

    try:
        return _run_workflow(
            run.root,
            run.run_id,
            input_files,
            mode,
            y,
            x,
            config,
            started_at,
            model_type=model_type,
            imputation=imputation,
            entity_col=entity_col,
            time_col=time_col,
            covariance=covariance,
            prediction_model_type=prediction_model_type,
            prediction_cv_folds=prediction_cv_folds,
            prediction_sampling_method=prediction_sampling_method,
        )
    except OptionalDependencyNotInstalled as exc:
        details = exc.to_issue_details()
        issue = GuardrailIssue(
            Severity.BLOCKER,
            details["error_code"],
            details["message"],
            {
                "step": details["step"],
                "engine": details["engine"],
                "model_type": details["model_type"],
                **details["details"],
            },
        )
        write_json(run.root / "errors.json", {"issues": [issue.to_dict()]})
        _write_manifest(
            run.root,
            run.run_id,
            mode,
            "failed",
            _lineage(input_files),
            started_at=started_at,
            y=y,
            x=x,
            requested_model_type=model_type,
        )
        raise
    except WorkflowValidationError as exc:
        evidence = dict(exc.evidence)
        # Only fill model_id/engine when the model_type is known and not
        # "auto" (which would produce meaningless "auto_1" / "unknown").
        if model_type != "auto":
            evidence.setdefault("model_type", model_type)
            evidence.setdefault("model_id", _model_id_for_type(model_type))
            evidence.setdefault("engine", _engine_for_type(model_type))
        issue = GuardrailIssue(
            Severity.BLOCKER,
            exc.error_code,
            str(exc),
            evidence,
        )
        # Merge with existing validation issues instead of overwriting.
        # Validation may have already written INFO/WARNING issues before
        # this blocker was raised.
        errors_path = run.root / "errors.json"
        existing_issues: list[dict[str, Any]] = []
        if errors_path.exists():
            existing = read_json(errors_path)
            if isinstance(existing, dict):
                existing_issues = existing.get("issues", [])
        write_json(errors_path, {"issues": [*existing_issues, issue.to_dict()]})
        _write_manifest(
            run.root,
            run.run_id,
            mode,
            "failed",
            _lineage(input_files),
            started_at=started_at,
            y=y,
            x=x,
            requested_model_type=model_type,
        )
        raise
    except Exception as exc:
        issue = GuardrailIssue(
            Severity.BLOCKER,
            "WORKFLOW_FAILED",
            "Workflow failed before completion.",
            {"error": str(exc)},
        )
        write_json(run.root / "errors.json", {"issues": [issue.to_dict()]})
        _write_manifest(
            run.root,
            run.run_id,
            mode,
            "failed",
            _lineage(input_files),
            started_at=started_at,
            y=y,
            x=x,
            requested_model_type=model_type,
        )
        raise


def parse_imputation_request(raw: str | dict | None) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if raw.strip() == "":
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("imputation must be a JSON object")
    return parsed


def run_batch_y_workflow(
    project_root: Path,
    input_files: list[Path],
    *,
    mode: str,
    y_list: list[str],
    x: list[str],
) -> dict[str, Any]:
    runs: list[dict[str, str | None]] = []
    for y in y_list:
        result = run_workflow(project_root, input_files, mode=mode, y=y, x=x)
        run_id = result["run_id"]
        run_root = Path(project_root) / "runs" / run_id
        model_summary = _primary_model_summary(run_root)
        runs.append(
            {
                "y": y,
                "run_id": run_id,
                "status": result["status"],
                "model_id": model_summary.get("model_id"),
                "model_type": model_summary.get("model_type"),
            }
        )
    status = "completed" if all(item["status"] == "completed" for item in runs) else "partial"
    return {"status": status, "runs": runs}


def _safe_flush_recorder(recorder: GraphRecorder, *, context: str) -> None:
    """Persist lineage best-effort. Lineage is observability, not correctness —
    a write failure must not promote a blocked run to errored."""
    try:
        recorder.flush()
    except Exception as exc:  # noqa: BLE001
        import warnings as _warnings
        _warnings.warn(
            f"Failed to flush lineage graph ({context}): {exc!r}",
            RuntimeWarning, stacklevel=2,
        )


def _primary_model_summary(run_root: Path) -> dict[str, str | None]:
    model_dir = run_root / "model_results"
    if not model_dir.is_dir():
        return {"model_id": None, "model_type": None}
    for model_file in ("ols_1.json", "logit_1.json", "poisson_1.json"):
        path = model_dir / model_file
        if path.is_file():
            data = read_json(path)
            return {
                "model_id": data.get("model_id"),
                "model_type": data.get("model_type"),
            }
    return {"model_id": None, "model_type": None}


def _variable_summary(cat_dp: Any, coer_dp: Any) -> str:
    if cat_dp is not None:
        params = cat_dp.reason.chosen_params if cat_dp.reason else {}
        n_levels = params.get("n_unique", "?")
        ref = params.get("reference_level", "?")
        return f"Dummy-encoded ({n_levels} levels, ref={ref!r})"
    if coer_dp is not None:
        params = coer_dp.reason.chosen_params if coer_dp.reason else {}
        conversion_rate = float(params.get("conversion_rate", 0))
        return f"Coerced to numeric ({conversion_rate:.0%} convertible)"
    return "Kept as numeric"


def _model_summary(
    model_type: str,
    result: dict[str, Any],
    *,
    robust_se_dp: Any,
    exposure_col: str | None,
    fallback_n: int,
) -> str | None:
    n = int(result.get("nobs", fallback_n))
    if model_type in ("ols", "ols_robust"):
        if robust_se_dp is not None and robust_se_dp.reason is not None:
            se_type = robust_se_dp.reason.chosen_params.get("variant", robust_se_dp.selected)
        elif robust_se_dp is not None:
            se_type = robust_se_dp.selected
        else:
            se_type = "HC1"
        return f"OLS ({se_type}, n={n})"
    if model_type == "logit":
        return f"Logit (n={n})"
    if model_type == "poisson_rate":
        exp = result.get("exposure_col") or exposure_col
        return f"Poisson rate (exposure={exp}, n={n})" if exp else f"Poisson (n={n})"
    if model_type == "poisson":
        return f"Poisson (n={n})"
    return None


def _run_workflow(
    run_root: Path,
    run_id: str,
    input_files: list[Path],
    mode: str,
    y: str,
    x: list[str],
    config: Any,
    started_at: str,
    on_step: Callable[[str, str, str], None] | None = None,
    model_type: str = "auto",
    sheet_name: str | None = None,
    transpose: bool = False,
    imputation: dict | None = None,
    entity_col: str = "",
    time_col: str = "",
    covariance: str = "",
    prediction_model_type: str = "",
    prediction_cv_folds: int = 0,
    prediction_sampling_method: str = "",
) -> dict[str, str]:
    """Thin pipeline driver: build env+ctx, iterate PIPELINE, short-circuit on
    terminal_status. All per-stage work lives in ``backend/workbench/engine/stages/``
    — this function only assembles inputs, drives the loop, and returns the
    final status.
    """
    from .engine.stages import PIPELINE

    _graph_store = GraphStore(runs_root=run_root.parent)
    _recorder = GraphRecorder(run_id=run_id, store=_graph_store)

    env = RunEnv(run_root=run_root, run_id=run_id, recorder=_recorder, on_step=on_step)
    ctx = ModelingContext(
        data=DataHandle(
            frame=pd.DataFrame(),
            artifact_id="raw",
            provenance=tuple(f"raw_{p.name}" for p in input_files),
        ),
        y_col=y,
        x_cols=list(x),
        requested_model_type=model_type,
    )
    ctx.artifacts["_input_files"] = input_files
    ctx.artifacts["_config"] = config
    ctx.artifacts["_sheet_name"] = sheet_name
    ctx.artifacts["_transpose"] = transpose
    ctx.artifacts["_mode"] = mode
    ctx.artifacts["_y"] = y
    ctx.artifacts["_x"] = x
    ctx.artifacts["_model_type"] = model_type
    ctx.artifacts["_started_at"] = started_at
    ctx.artifacts["_imputation_request"] = imputation
    ctx.artifacts["_entity_col"] = entity_col
    ctx.artifacts["_time_col"] = time_col
    ctx.artifacts["_covariance"] = covariance
    ctx.artifacts["_prediction_model_type"] = prediction_model_type
    ctx.artifacts["_prediction_cv_folds"] = prediction_cv_folds
    ctx.artifacts["_prediction_sampling_method"] = prediction_sampling_method

    for stage in PIPELINE:
        ctx = stage.run(ctx, env)
        if ctx.terminal_status in ("blocked", "failed"):
            return {"run_id": run_id, "status": ctx.terminal_status}

    return {"run_id": run_id, "status": ctx.terminal_status}


def _normalized_existing(candidates: tuple[str, ...], frame: pd.DataFrame) -> list[str]:
    columns = set(frame.columns)
    return [
        normalized
        for candidate in candidates
        if (normalized := normalize_column_name(candidate)) in columns
    ]


def _write_model_result(
    run_root: Path,
    model_id: str,
    model_result: dict[str, Any],
    *,
    inputs: list[str] | None = None,
) -> None:
    model_path = run_root / "model_results" / f"{model_id}.json"
    write_json(model_path, model_result)
    register_artifact(
        run_root,
        model_id,
        model_path,
        "model_result",
        "econometrics",
        inputs or ["cleaned_dataset"],
    )


def _mice_imputation_fact(imputation: dict[str, Any]) -> str:
    columns = imputation.get("imputed_columns", [])
    columns_text = ", ".join(str(column) for column in columns) if columns else "none"
    persisted = imputation.get("persisted_datasets", 0)
    persisted_text = "one" if persisted == 1 else str(persisted)
    pooled = "were produced" if imputation.get("pooled_estimates") else "were not produced"
    return (
        f"MICE imputation: {persisted_text} persisted imputed dataset; "
        f"imputed columns: {columns_text}; pooled estimates {pooled}."
    )


def _coefficient_rows(model_result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    coefficients = model_result.get("coefficients", {})
    irr_dict = model_result.get("irr", {})
    if not isinstance(coefficients, dict):
        return rows
    for term, values in coefficients.items():
        if isinstance(values, dict):
            row: dict[str, Any] = {"term": term, **values}
            if isinstance(irr_dict, dict) and term in irr_dict:
                term_irr = irr_dict[term]
                if isinstance(term_irr, dict):
                    row.setdefault("irr", term_irr.get("irr"))
                    row.setdefault("irr_ci_lower", term_irr.get("irr_ci_lower"))
                    row.setdefault("irr_ci_upper", term_irr.get("irr_ci_upper"))
            rows.append(row)
    return rows


def _coefficient_rows_for_models(
    model_results: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id, model_result in model_results:
        for row in _coefficient_rows(model_result):
            rows.append({"model_id": model_id, **row})
    return rows


def _model_column_issue(
    frame: pd.DataFrame,
    normalized_y: str,
    normalized_x: list[str],
    requested_y: str,
    requested_x: list[str],
) -> GuardrailIssue | None:
    columns = set(frame.columns)
    requested = [normalized_y, *normalized_x]
    missing = [column for column in requested if column not in columns]
    if not missing:
        return None
    return GuardrailIssue(
        Severity.BLOCKER,
        "MODEL_COLUMNS_NOT_FOUND",
        "Requested model columns are not available after cleaning.",
        {
            "missing_columns": missing,
            "available_columns": sorted(str(column) for column in frame.columns),
            "requested_y": requested_y,
            "requested_x": requested_x,
        },
    )


def _lineage(input_files: list[Path]) -> list[dict[str, str]]:
    return [
        {"source": str(path), "artifact_id": f"raw_{Path(path).name}"}
        for path in input_files
    ]


def _build_model_routing_summary(
    frame: pd.DataFrame,
    y: str,
    *,
    requested_model_type: str,
    data_detected_y_type: str,
    effective_y_type: str,
    model_results: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    series = frame[y].dropna() if y in frame.columns else pd.Series(dtype="float64")
    numeric = pd.to_numeric(series, errors="coerce")
    numeric_present = numeric.dropna()
    integer_like = False
    if not numeric_present.empty:
        integer_like = bool((numeric_present == numeric_present.astype(int)).all())
    effective_model_id = model_results[0][0] if model_results else None
    effective_model_type = (
        model_results[0][1].get("model_type") if model_results else None
    )
    return {
        "requested_model_type": requested_model_type,
        "current_y": y,
        "dtype": str(series.dtype),
        "min": float(numeric_present.min()) if not numeric_present.empty else None,
        "max": float(numeric_present.max()) if not numeric_present.empty else None,
        "unique": int(series.nunique()),
        "integer_like": integer_like,
        "data_detected_y_type": data_detected_y_type,
        "effective_y_type": effective_y_type,
        "effective_model_id": effective_model_id,
        "effective_model_type": effective_model_type,
    }


def _write_manifest(
    run_root: Path,
    run_id: str,
    mode: str,
    status: str,
    lineage: list[dict[str, str]],
    *,
    started_at: str,
    y: str,
    x: list[str],
    requested_model_type: str | None = None,
    model_routing: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "status": status,
        "started_at": started_at,
        "y": y,
        "x": list(x),
        "lineage": lineage,
    }
    if requested_model_type is not None:
        payload["requested_model_type"] = requested_model_type
    if model_routing is not None:
        payload["model_routing"] = model_routing
    write_json(
        run_root / "run_manifest.json",
        payload,
    )


_BINARY_CORRELATION_WARN = 0.7  # |r| > 0.7 > Severity.WARNING
_BINARY_CORRELATION_INFO = 0.5  # 0.5 < |r| <= 0.7 > Severity.INFO
_TREATMENT_PROXY_CORRELATION_WARN = 0.7
_MODEL_TYPE_MAP = {
    "ols": "continuous",
    "logit": "binary",
    "probit": "binary",
    "poisson": "count",
    "negative_binomial": "count",
    "panel_ols": "continuous",
}
_SUPPORTED_GLM_FAMILIES = {"binomial", "poisson", "negative_binomial"}
_PREDICTION_MODEL_TYPES = {
    "prediction_lasso",
    "prediction_ridge",
    "prediction_random_forest",
}


def _map_model_type(model_type: str) -> str | None:
    return _MODEL_TYPE_MAP.get(model_type)


def _validate_requested_model_type(model_type: str) -> str | None:
    if model_type == "auto" or model_type in _MODEL_TYPE_MAP or model_type in _PREDICTION_MODEL_TYPES:
        return None
    if not model_type.startswith("glm:"):
        raise WorkflowValidationError(
            "UNSUPPORTED_MODEL_TYPE",
            f"Unsupported model type: {model_type}",
            {
                "model_type": model_type,
                "supported_types": sorted(
                    list(_MODEL_TYPE_MAP.keys())
                    + list(_PREDICTION_MODEL_TYPES)
                    + ["glm:<family>"]
                ),
            },
        )
    family_name = model_type.split(":", 1)[1]
    if family_name not in _SUPPORTED_GLM_FAMILIES:
        raise WorkflowValidationError(
            "UNSUPPORTED_GLM_FAMILY",
            f"Unsupported GLM family: {family_name}",
            {
                "model_type": model_type,
                "glm_family": family_name,
                "supported_families": sorted(_SUPPORTED_GLM_FAMILIES),
            },
        )
    return family_name


def _diagnostic_family(model_result: dict[str, Any]) -> str:
    model_type = model_result.get("model_type", "ols")
    if model_type == "glm":
        family = model_result.get("glm_family")
        return str(family) if family else "glm"
    if model_type == "poisson_rate":
        return "poisson"
    if model_type in ("ols", "ols_robust", "fixed_effects", "panel_ols"):
        return "ols"
    return str(model_type)


def _build_variable_importance(
    statistical_tests: dict[str, dict[str, Any]],
    y: str,
    x_vars: list[str],
    model_results: list[tuple[str, dict[str, Any]]] | None = None,
    frame: pd.DataFrame | None = None,
    primary_type: str = "ols",
    exposure_col: str | None = None,
    categorical_vars: set[str] | None = None,
) -> list[dict[str, Any]]:
    cat_set = categorical_vars or set()
    importance: dict[str, dict[str, Any]] = {}
    for var in x_vars:
        if var == exposure_col:
            continue
        importance[var] = {
            "variable": var, "correlation": None, "best_p_value": None, "test_type": None
        }
    if frame is not None:
        cols = [y] + [v for v in x_vars if v in frame.columns]
        if len(cols) >= 2:
            corr = frame[cols].corr(numeric_only=True)
            if y in corr.columns:
                for var in x_vars:
                    if var == exposure_col:
                        continue
                    if var in corr.columns:
                        c = corr[y].get(var)
                        if pd.notna(c):
                            importance[var]["correlation"] = round(float(c), 3)
                            if var in cat_set:
                                importance[var]["correlation_note"] = "Pearson r on categorical codes — prefer ANOVA"
    for row in statistical_tests.get("correlations", {}).get("results", []):
        variables = row.get("variables", [])
        if isinstance(variables, list) and y in variables:
            for var in variables:
                if var != y and var in importance:
                    importance[var]["correlation"] = row.get("effect", {}).get("r")
                    p = row.get("p_value")
                    if p is not None:
                        importance[var]["best_p_value"] = p
                        importance[var]["test_type"] = "correlation"
    for family in ("t_tests", "anova"):
        for row in statistical_tests.get(family, {}).get("results", []):
            outcome = row.get("outcome")
            if outcome != y:
                continue
            group = row.get("group", "")
            if group in importance:
                p = row.get("p_value")
                existing = importance[group]["best_p_value"]
                if p is not None and (existing is None or p < existing):
                    importance[group]["best_p_value"] = p
                    importance[group]["test_type"] = family
    if model_results:
        primary = model_results[0][1] if model_results else {}
        coefficients = primary.get("coefficients", {})
        for var in x_vars:
            if var not in importance:
                continue
            imp = importance[var]
            if imp["best_p_value"] is not None:
                continue
            coeff = coefficients.get(var)
            if isinstance(coeff, dict) and coeff.get("p_value") is not None:
                imp["best_p_value"] = coeff["p_value"]
                imp["test_type"] = f"{primary_type}_coefficient" if primary_type else "model_coefficient"
    for var in x_vars:
        if var not in importance:
            continue
        imp = importance[var]
        corr = imp["correlation"]
        p = imp["best_p_value"]
        if corr is not None and abs(corr) >= 0.3:
            imp["strength"] = "strong"
        elif corr is not None and abs(corr) >= 0.1:
            imp["strength"] = "moderate"
        elif corr is not None:
            imp["strength"] = "weak"
        elif p is not None and p < 0.05:
            imp["strength"] = "significant (no correlation data)"
        else:
            imp["strength"] = ""
    return sorted(importance.values(), key=_importance_sort_key)


def _check_model_validity(
    diag: dict[str, Any],
    model_id: str,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    cd = diag.get("cooks_distance", {})
    if isinstance(cd, dict):
        if cd.get("max") is None and cd.get("leverage_max") is not None:
            issue = GuardrailIssue(
                Severity.WARNING,
                "MODEL_DIAGNOSTIC_ANOMALY",
                f"Model {model_id}: Cook's distance could not be computed. "
                f"Derived results (influence diagnostics) may be unreliable.",
                {"model_id": model_id, "leverage_max": cd.get("leverage_max")},
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
        if cd.get("leverage_max") is not None and float(cd["leverage_max"]) >= 1.0:
            issue = GuardrailIssue(
                Severity.WARNING,
                "MODEL_OVERPARAMETERIZED",
                f"Model {model_id}: max leverage is {cd['leverage_max']:.4f}. "
                f"Model may be over-parameterized or contain near-singular design matrix.",
                {"model_id": model_id, "leverage_max": cd["leverage_max"]},
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})


def _check_overdispersion_issue(
    diag: dict[str, Any],
    model_id: str,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    od = diag.get("overdispersion", {})
    if not isinstance(od, dict):
        return
    od_ratio = od.get("overdispersion_ratio")
    if od_ratio is not None and float(od_ratio) > 2.0:
        warning = od.get(
            "warning",
            f"Severe overdispersion detected (ratio={float(od_ratio):.2f}). "
            f"Poisson model is unreliable.",
        )
        issue_dicts.append(GuardrailIssue(
            Severity.WARNING,
            "OVERDISPERSION_DETECTED",
            warning,
            {
                "model_id": model_id,
                "overdispersion_ratio": float(od_ratio),
                "recommended_action": (
                    "Switch to Negative Binomial regression or use "
                    "robust standard errors."
                ),
            },
        ).to_dict())
        write_json(run_root / "errors.json", {"issues": issue_dicts})
    zero_rate = od.get("zero_rate")
    if zero_rate is not None and float(zero_rate) > 0.5:
        od["zero_inflation_hint"] = (
            f"Outcome has {float(zero_rate):.0%} zeros. Consider comparing with "
            f"zero-inflated Poisson or hurdle model if zeros may arise from a separate process."
        )


_EXPOSURE_NAME_PATTERNS = (
    "exposure", "exposure_months", "policy_months", "person_years",
    "risk_time", "offset", "time_at_risk", "months", "years_at_risk",
)


def _detect_exposure_candidates(x_vars: list[str]) -> list[str]:
    """Detect column names that look like exposure/offset variables."""
    detected: list[str] = []
    for var in x_vars:
        var_lower = var.lower()
        if any(pat == var_lower or var_lower.endswith(f"_{pat}") or var_lower.startswith(f"{pat}_")
               for pat in _EXPOSURE_NAME_PATTERNS):
            detected.append(var)
    return detected


def _select_valid_exposure_col(
    frame: pd.DataFrame,
    exposure_candidates: list[str],
) -> str | None:
    """Return the first candidate that can validly be used as a GLM exposure."""
    for candidate in exposure_candidates:
        if candidate not in frame.columns:
            continue
        values = pd.to_numeric(frame[candidate], errors="coerce").dropna()
        if values.empty:
            continue
        if (values > 0).all():
            return candidate
    return None


_SUSPICIOUS_NAME_PATTERNS = {"noise", "random", "placebo", "check", "fake", "test"}


def _check_rare_event(
    frame: pd.DataFrame,
    y: str,
    model_type: str,
    n_predictors: int,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> dict[str, Any] | None:
    if model_type not in ("logit",):
        return None
    if y not in frame.columns:
        return None
    series = frame[y].dropna()
    if len(series) == 0:
        return None
    positive_rate = float(series.astype(float).mean())
    n_positive = int(positive_rate * len(series))
    epv = n_positive / max(n_predictors, 1)
    if positive_rate >= 0.05 and epv >= 5:
        return None
    reliability = "Low / exploratory only" if (positive_rate < 0.05 or epv < 5) else "Caution advised"
    issue_dicts.append(GuardrailIssue(
        Severity.WARNING if reliability.startswith("Low") else Severity.INFO,
        "RARE_EVENT_WARNING",
        f"The positive class for '{y}' accounts for {positive_rate:.1%} ({n_positive} of {len(series)}). "
        f"Events per predictor: {epv:.1f}. "
        f"Standard MLE Logit reliability is reduced. "
        f"Consider Firth penalized likelihood or exact logistic regression (not yet available in this MVP).",
        {"positive_rate": positive_rate, "n_positive": n_positive, "n_total": int(len(series)), "events_per_predictor": round(epv, 1)},
    ).to_dict())
    write_json(run_root / "errors.json", {"issues": issue_dicts})
    return {"reliability": reliability, "events_per_predictor": round(epv, 1), "positive_rate": positive_rate}


def _detect_binary_vars(frame: pd.DataFrame, x_vars: list[str]) -> set[str]:
    binary: set[str] = set()
    for var in x_vars:
        if var not in frame.columns:
            continue
        unique = sorted(frame[var].dropna().unique())
        if len(unique) == 2:
            try:
                if set(unique) <= {0, 1, 0.0, 1.0, True, False}:
                    binary.add(var)
            except Exception:
                pass
    return binary


def _check_binary_correlations(
    frame: pd.DataFrame,
    binary_vars: set[str],
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    """Check for highly correlated binary X variables and add INFO/WARNING issues."""
    binary_list = sorted(binary_vars)
    for i in range(len(binary_list)):
        for j in range(i + 1, len(binary_list)):
            var1, var2 = binary_list[i], binary_list[j]
            if var1 not in frame.columns or var2 not in frame.columns:
                continue
            col1 = frame[var1].astype(float)
            col2 = frame[var2].astype(float)
            r = col1.corr(col2)
            abs_r = abs(r)
            if pd.isna(r):
                continue
            evidence: dict[str, Any] = {
                "var1": var1, "var2": var2, "correlation": round(float(r), 4),
            }
            if abs_r > _BINARY_CORRELATION_WARN:
                severity = Severity.WARNING
                message = (
                    f"{var1} and {var2} are strongly correlated (r={r:.2f}). "
                    f"This may inflate standard errors. "
                    f"Consider removing or combining one."
                )
                evidence["action_suggestions"] = [
                    "Keep both if they represent distinct concepts in your domain.",
                    "Compare models with each variable individually vs. both together.",
                    "If redundant, consider combining into a single indicator.",
                ]
            elif abs_r > _BINARY_CORRELATION_INFO:
                severity = Severity.INFO
                message = (
                    f"{var1} and {var2} are moderately correlated (r={r:.2f}). "
                    f"The model can still be used, but be cautious when interpreting "
                    f"individual binary coefficients."
                )
                evidence["action_suggestions"] = [
                    "Keep both if they represent distinct concepts in your domain.",
                    "Compare models with each variable individually vs. both together.",
                    "If redundant, consider combining into a single indicator.",
                ]
            else:
                continue
            issue = GuardrailIssue(severity, "BINARY_CORRELATION", message, evidence)
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})


def _check_treatment_proxy_correlations(
    frame: pd.DataFrame,
    x_vars: list[str],
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    treatment_vars = [
        var for var in x_vars
        if var in frame.columns and "treatment" in var.lower()
    ]
    proxy_vars = [
        var for var in x_vars
        if var in frame.columns
        and any(token in var.lower() for token in ("proxy", "interaction"))
    ]
    for treatment in treatment_vars:
        for proxy in proxy_vars:
            if treatment == proxy:
                continue
            pair = frame[[treatment, proxy]].apply(pd.to_numeric, errors="coerce").dropna()
            if len(pair) < 3:
                continue
            r = pair[treatment].corr(pair[proxy])
            if pd.isna(r) or abs(r) <= _TREATMENT_PROXY_CORRELATION_WARN:
                continue
            issue = GuardrailIssue(
                Severity.WARNING,
                "TREATMENT_PROXY_CORRELATION",
                f"{treatment} and {proxy} are highly correlated (r={r:.3f}). "
                "Interpret their coefficients jointly; individual treatment-effect "
                "interpretation may be unstable.",
                {
                    "treatment": treatment,
                    "proxy": proxy,
                    "correlation": round(float(r), 4),
                    "action_suggestions": [
                        "Compare models with and without the proxy term.",
                        "Interpret treatment and proxy coefficients jointly.",
                    ],
                },
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})


def _detect_suspicious_vars(x_vars: list[str]) -> set[str]:
    suspicious: set[str] = set()
    for var in x_vars:
        name_lower = var.lower()
        for pattern in _SUSPICIOUS_NAME_PATTERNS:
            if pattern in name_lower:
                suspicious.add(var)
                break
    return suspicious


def _coerce_x_columns_to_numeric(
    frame: pd.DataFrame,
    x_vars: list[str],
    run_root: Path,
) -> list[dict[str, Any]]:
    """Coerce X columns from datetime/object to numeric if appropriate.

    Returns a list of coercion action dicts and writes a summary artifact.
    """
    heuristics = {
        "year", "month", "age", "miles", "density", "score", "count",
        "claims", "days", "number", "num", "amount", "rate", "price",
        "cost", "value", "size", "weight", "volume", "sum",
    }
    actions: list[dict[str, Any]] = []
    for var in x_vars:
        if var not in frame.columns:
            continue
        if pd.api.types.is_numeric_dtype(frame[var]):
            continue
        is_likely_numeric = any(pat in var.lower() for pat in heuristics)
        threshold = 0.80 if is_likely_numeric else 0.90
        numeric = pd.to_numeric(frame[var], errors="coerce")
        good = numeric.notna().sum()
        total = len(numeric)
        if total > 0 and (good / total) >= threshold:
            original_dtype = str(frame[var].dtype)
            frame[var] = numeric
            actions.append({
                "column": var,
                "original_dtype": original_dtype,
                "conversion_rate": round(good / total, 4),
            })
    if actions:
        path = run_root / "staged" / "x_coercion_summary.json"
        write_json(path, {"coerced_columns": actions})
        try:
            register_artifact(
                run_root,
                "x_coercion_summary",
                path,
                "metadata",
                "cleaning",
                ["cleaned_dataset"],
            )
        except Exception:
            pass
    return actions


def _check_suspicious_dtypes(
    frame: pd.DataFrame,
    x_vars: list[str],
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    x_set = set(x_vars)
    for col in frame.columns:
        if not pd.api.types.is_datetime64_any_dtype(frame[col]):
            continue
        nunique = int(frame[col].nunique())
        is_x = col in x_set
        severity = Severity.WARNING if is_x else Severity.INFO
        if nunique <= 5:
            issue = GuardrailIssue(
                severity,
                "SUSPICIOUS_DTYPE",
                f"Column '{col}' has datetime dtype with only {nunique} unique value(s). "
                f"It may be a binary/categorical variable misread as datetime. "
                f"{'It is used as a predictor — verify its dtype.' if is_x else 'Verify before using it as a predictor.'}",
                {"column": col, "dtype": str(frame[col].dtype), "nunique": nunique, "is_x": is_x},
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
        elif is_x and nunique > 5:
            numeric = pd.to_numeric(frame[col], errors="coerce")
            good = numeric.notna().sum()
            total = len(numeric)
            if total > 0 and (good / total) >= 0.9:
                frame[col] = numeric
                issue = GuardrailIssue(
                    Severity.INFO,
                    "COERCED_X_DTYPE",
                    f"Column '{col}' was datetime dtype with {nunique} unique values; "
                    f"auto-coerced to numeric ({good}/{total}, {good/total:.0%} conversion rate).",
                    {"column": col, "dtype": str(frame[col].dtype), "nunique": nunique},
                )
                issue_dicts.append(issue.to_dict())
                write_json(run_root / "errors.json", {"issues": issue_dicts})


_CATEGORICAL_NAME_PATTERNS = {"code", "region", "category", "group", "type", "class", "level", "tier", "rank"}


def _detect_categorical_x_vars(frame: pd.DataFrame, x_vars: list[str]) -> set[str]:
    """Detect X variables that should use C() encoding in the model formula.

    Name-suggestive numeric columns with 3-20 unique values and non-numeric
    columns with 2-20 unique values are flagged as categorical. Binary 0/1
    columns are excluded since they are handled by _detect_binary_vars.
    """
    categorical: set[str] = set()
    for var in x_vars:
        if var not in frame.columns:
            continue
        series = frame[var].dropna()
        if len(series) < 2:
            continue
        nunique = int(series.nunique())
        if nunique > 20 or nunique >= len(series):
            continue
        name_lower = str(var).lower()
        name_suggests_category = any(
            pat in name_lower for pat in _CATEGORICAL_NAME_PATTERNS
        )
        if pd.api.types.is_numeric_dtype(series):
            if nunique >= 3 and name_suggests_category:
                categorical.add(var)
        else:
            if nunique >= 2:
                categorical.add(var)
    return categorical


def _check_categorical_candidates(
    frame: pd.DataFrame,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
    encoded_categorical_vars: set[str] | None = None,
) -> None:
    """Report categorical handling using the final model preprocessing state."""
    encoded = encoded_categorical_vars or set()
    for col in sorted(encoded):
        col_str = str(col)
        if col_str not in frame.columns:
            continue
        issue_dicts.append(
            GuardrailIssue(
                Severity.INFO,
                "CATEGORICAL_AUTO_DUMMY_CODED",
                f"Column '{col_str}' was detected as categorical and automatically dummy-coded.",
                {"column": col_str, "preprocessing": "dummy_coded"},
            ).to_dict()
        )
        write_json(run_root / "errors.json", {"issues": issue_dicts})

    for col in frame.columns:
        col_str = str(col)
        if col_str in encoded:
            continue
        name_lower = col_str.lower()
        if not any(pat in name_lower for pat in _CATEGORICAL_NAME_PATTERNS):
            continue
        nunique = int(frame[col].nunique())
        if 1 < nunique <= 10:
            issue_dicts.append(
                GuardrailIssue(
                    Severity.INFO,
                    "CATEGORICAL_CANDIDATE",
                    f"Column '{col_str}' may be categorical ({nunique} unique values). Consider one-hot encoding.",
                    {"column": col_str, "nunique": nunique},
                ).to_dict()
            )
            write_json(run_root / "errors.json", {"issues": issue_dicts})


def _importance_sort_key(item: dict[str, Any]) -> float:
    p = item.get("best_p_value")
    if p is None:
        return 2.0
    return float(p)


def _build_descriptive_stats(frame: pd.DataFrame, *, categorical_vars: set[str] | None = None) -> list[dict[str, Any]]:
    cat_set = categorical_vars or set()
    stats: list[dict[str, Any]] = []
    for column in frame.columns:
        col_str = str(column)
        series = frame[column]
        present = int(series.notna().sum())
        total = len(series)
        row: dict[str, Any] = {
            "column": col_str,
            "dtype": str(series.dtype),
            "count": present,
            "missing": total - present,
            "missing_rate": round((total - present) / total, 4) if total > 0 else 0.0,
            "unique_count": int(series.nunique()),
        }
        is_categorical = col_str in cat_set
        if pd.api.types.is_numeric_dtype(series) and not is_categorical:
            row["mean"] = round(float(series.mean()), 4)
            row["std"] = round(float(series.std()), 4)
            row["min"] = round(float(series.min()), 4)
            row["max"] = round(float(series.max()), 4)
        else:
            row["mean"] = None
            row["std"] = None
            row["min"] = None
            row["max"] = None
            if is_categorical:
                row["note"] = "categorical — mean/std not meaningful"
        stats.append(row)
    return stats


def _check_dropped_variables(
    x_vars: list[str],
    model_results: list[tuple[str, dict[str, Any]]],
    frame: pd.DataFrame,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
    categorical_vars: set[str] | None = None,
) -> list[dict[str, str]]:
    """Check for user-specified X variables dropped from the model silently.

    Returns structured entries: {"variable", "reason" (normalized id),
    "reason_display" (human string)}. Respects C()-encoded categoricals.
    """
    if categorical_vars is None:
        categorical_vars = set()

    if not model_results:
        return []

    primary_result = model_results[0][1]
    coefficients = primary_result.get("coefficients", {})
    if not isinstance(coefficients, dict):
        return []

    def _in_coefficients(var: str) -> bool:
        if var in coefficients:
            return True
        if var in categorical_vars:
            sq = f"C(Q('{var}'))[T."
            dq = f'C(Q("{var}"))[T.'
            for cterm in coefficients:
                if isinstance(cterm, str) and (sq in cterm or dq in cterm):
                    return True
        return False

    dropped: list[dict[str, str]] = []
    for var in x_vars:
        if _in_coefficients(var):
            continue
        if var not in frame.columns or frame[var].isna().all():
            reason_id = "all_missing_after_cleaning"
            reason_display = "dropped due to all-missing after cleaning"
        elif frame[var].nunique() <= 1:
            reason_id = "zero_variance"
            reason_display = "dropped due to zero variance"
        elif var in categorical_vars:
            reason_id = "perfect_collinearity_categorical"
            reason_display = "dropped due to perfect collinearity (categories may overlap with other predictors)"
        else:
            reason_id = "perfect_collinearity"
            reason_display = "dropped due to perfect collinearity"

        dropped.append({
            "variable": var,
            "reason": reason_id,
            "reason_display": reason_display,
        })
        issue_dicts.append(
            GuardrailIssue(
                Severity.INFO,
                "VARIABLE_DROPPED",
                f"Variable '{var}' was {reason_display}.",
                {"variable": var, "reason": reason_display},
            ).to_dict()
        )

    if dropped:
        write_json(run_root / "errors.json", {"issues": issue_dicts})

    return dropped
