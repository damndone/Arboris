"""Workflow orchestration package.

V1.5.4.5: orchestrator.py（1354 行）拆成包，行为冻结。本 __init__ 是薄驱动核心
（run_workflow / _run_workflow / run_batch_y_workflow / parse_imputation_request /
PIPELINE 装配 + run_* 再导出）+ 对外命名空间再导出枢纽。

维护者须知：
- helper 按消费者分簇在子模块：_manifest（清单/血缘）、_model_types（模型类型映射）、
  _errors（WorkflowValidationError）、_column_checks（列检查）、
  _reliability_checks（可靠性/相关性）、_report_build（报告构建）。
  新 helper 按用途放对应子模块；找不到归属再考虑新建子模块。
- 子模块**不得**反向 import 本包（`from . import ...`）—— 初始化期循环。
  子模块要用同级 helper，写 `from ._sibling import name`。
- 凡 stage / api / 测试以 `workbench.orchestrator.X` 形式引用的名字，必须在本文件 re-export；
  tests/test_orchestrator_namespace.py 钉死这份集合，漏导出即变红。
- run_* 再导出是测试 monkeypatch 的命名空间面，永远留在本文件。
"""
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
    run_cs_did,
    run_did,
    run_event_study,
    run_glm,
    run_iv_2sls,
    run_logit,
    run_negative_binomial,
    run_ols,
    run_panel_ols,
    run_poisson,
    run_probit,
    run_sa_did,
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
    did_mode: str = "",
    did_cohort_col: str = "",
    did_treat_col: str = "",
    did_post_col: str = "",
    did_status_col: str = "",
    cs_control_group: str = "",
    cs_est_method: str = "",
    cs_base_period: str = "",
    cs_anticipation: int = 0,
    cs_cluster_var: str = "",
    honest_did: bool = False,
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
            did_mode=did_mode,
            did_cohort_col=did_cohort_col,
            did_treat_col=did_treat_col,
            did_post_col=did_post_col,
            did_status_col=did_status_col,
            cs_control_group=cs_control_group,
            cs_est_method=cs_est_method,
            cs_base_period=cs_base_period,
            cs_anticipation=cs_anticipation,
            cs_cluster_var=cs_cluster_var,
            honest_did=honest_did,
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
    did_mode: str = "",
    did_cohort_col: str = "",
    did_treat_col: str = "",
    did_post_col: str = "",
    did_status_col: str = "",
    cs_control_group: str = "",
    cs_est_method: str = "",
    cs_base_period: str = "",
    cs_anticipation: int = 0,
    cs_cluster_var: str = "",
    honest_did: bool = False,
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
    ctx.artifacts["_did_mode"] = did_mode
    ctx.artifacts["_did_cohort_col"] = normalize_column_name(did_cohort_col) if did_cohort_col else ""
    ctx.artifacts["_did_treat_col"] = normalize_column_name(did_treat_col) if did_treat_col else ""
    ctx.artifacts["_did_post_col"] = normalize_column_name(did_post_col) if did_post_col else ""
    ctx.artifacts["_did_status_col"] = normalize_column_name(did_status_col) if did_status_col else ""
    ctx.artifacts["_cs_control_group"] = cs_control_group
    ctx.artifacts["_cs_est_method"] = cs_est_method
    ctx.artifacts["_cs_base_period"] = cs_base_period
    ctx.artifacts["_cs_anticipation"] = cs_anticipation
    ctx.artifacts["_cs_cluster_var"] = normalize_column_name(cs_cluster_var) if cs_cluster_var else ""
    ctx.artifacts["_honest_did"] = bool(honest_did)

    for stage in PIPELINE:
        ctx = stage.run(ctx, env)
        if ctx.terminal_status in ("blocked", "failed"):
            return {"run_id": run_id, "status": ctx.terminal_status}

    return {"run_id": run_id, "status": ctx.terminal_status}


from ._report_build import (
    _build_descriptive_stats,
    _build_variable_importance,
    _coefficient_rows,
    _coefficient_rows_for_models,
    _importance_sort_key,
    _mice_imputation_fact,
    _model_summary,
    _variable_summary,
    _write_model_result,
)
