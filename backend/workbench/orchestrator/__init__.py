from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from ..artifacts import read_json, register_artifact, write_json
from ..cleaning import clean_frame, normalize_column_name
from ..config import load_config
from ..diagnostic_summary import build_diagnostic_summary
from ..domain import GuardrailIssue, Severity
from ..engine.context import DataHandle, ModelingContext, RunEnv
from ..engine.stages.cleaning import CleaningStage
from ..engine.stages.profile import ProfileStage
from ..engine.stages.routing import RoutingStage
from ..engine.stages.source import SourceStage
from ..engine.stages.validation import ValidationStage
from ..engine.stages.ytype import YTypeStage
from ..engine.stages.pre_estimation_checks import PreEstimationChecksStage
from ..engine.stages.roles import RoleInferenceStage
from ..engine.stages.exposure import ExposureDetectionStage
from ..engine.stages.statistical_tests import StatisticalTestsStage
from ..engine.stages.imputation import ImputationStage
from ..engine.stages.estimation import EstimationStage
from ..engine.stages.recording import RecordingStage
from ..engine.stages.diagnostics import DiagnosticsStage
from ..engine.stages.reliability import ReliabilityStage
from ..engine.stages.report import ReportStage
from ..graph_recorder import GraphRecorder
from ..graph_model import Stage
from ..graph_store import GraphStore
from .. import graph_decision_factory as dpf
from ..econometrics.optional_deps import OptionalDependencyNotInstalled
from ..econometrics.diagnostics import compute_diagnostics
from ..econometrics.runner import (
    run_glm,
    run_iv_2sls,
    run_logit,
    run_negative_binomial,
    run_ols,
    run_panel_ols,
    run_poisson,
    run_probit,
    run_time_series_diagnostics,
)
from ..exports import export_pdf, export_xlsx
from ..ingestion import ingest_files
from ..imputation import run_mice_imputation
from ..metadata import infer_schema
from ..narrative import build_claims
from ..profiling import profile_frame
from ..prediction import run_prediction_model
from ..projects import create_run
from ..reporting import render_html_report
from ..router import classify_dataset, detect_y_kind
from ..statistical_tests import (
    run_statistical_tests,
    summarize_statistical_tests,
    write_statistical_test_artifacts,
)
from ..validation import has_blockers, validate_profile
from ..variable_roles import infer_variable_roles
from ..visualization import create_figures
from ._column_checks import (
    _CATEGORICAL_NAME_PATTERNS,
    _SUSPICIOUS_NAME_PATTERNS,
    _check_categorical_candidates,
    _check_dropped_variables,
    _check_suspicious_dtypes,
    _coerce_x_columns_to_numeric,
    _detect_categorical_x_vars,
    _detect_suspicious_vars,
    _model_column_issue,
    _normalized_existing,
)
from ._errors import WorkflowValidationError
from ._manifest import (
    _build_model_routing_summary,
    _lineage,
    _primary_model_summary,
    _safe_flush_recorder,
    _write_manifest,
)
from ._model_types import (
    _MODEL_METADATA,
    _MODEL_TYPE_MAP,
    _PREDICTION_MODEL_TYPES,
    _ROOT_CAUSE_MAX_LENGTH,
    _SUPPORTED_GLM_FAMILIES,
    _engine_for_type,
    _map_model_type,
    _model_failure_details,
    _model_id_for_type,
    _validate_requested_model_type,
)
from ._reliability_checks import (
    _BINARY_CORRELATION_INFO,
    _BINARY_CORRELATION_WARN,
    _EXPOSURE_NAME_PATTERNS,
    _TREATMENT_PROXY_CORRELATION_WARN,
    _check_binary_correlations,
    _check_model_validity,
    _check_overdispersion_issue,
    _check_rare_event,
    _check_treatment_proxy_correlations,
    _detect_binary_vars,
    _detect_exposure_candidates,
    _diagnostic_family,
    _select_valid_exposure_col,
)

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


# Map auto-detected y_type back to the model type actually attempted,
# so that failure evidence names the correct model (e.g. "logit",
# not "binary").
_Y_TYPE_TO_ATTEMPTED_MODEL: dict[str, str] = {
    "binary": "logit",
    "count": "poisson",
    "continuous": "ols",
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
    iv_endog: list[str] | None = None,
    iv_instruments: list[str] | None = None,
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
            iv_endog=iv_endog,
            iv_instruments=iv_instruments,
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
    iv_endog: list[str] | None = None,
    iv_instruments: list[str] | None = None,
) -> dict[str, str]:
    """Thin pipeline driver: build env+ctx, iterate PIPELINE, short-circuit on
    terminal_status. All per-stage work lives in ``backend/workbench/engine/stages/``
    — this function only assembles inputs, drives the loop, and returns the
    final status.
    """
    from ..engine.stages import PIPELINE

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
    ctx.artifacts["_iv_endog"] = [normalize_column_name(c) for c in (iv_endog or [])]
    ctx.artifacts["_iv_instruments"] = [normalize_column_name(c) for c in (iv_instruments or [])]

    for stage in PIPELINE:
        ctx = stage.run(ctx, env)
        if ctx.terminal_status in ("blocked", "failed"):
            return {"run_id": run_id, "status": ctx.terminal_status}

    return {"run_id": run_id, "status": ctx.terminal_status}


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
