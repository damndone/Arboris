"""Executable orchestration for the public ARMA-GARCH Model Pack."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import date, datetime
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from workbench import __version__
from workbench.artifacts import package_versions, register_artifact, sha256_file, write_json
from workbench.contracts.model.arma_garch import (
    ARMA_GARCH_PACK_ID,
    ArmaGarchAnalysisContract,
)
from workbench.engine.context import RunInterruptionRequested
from workbench.engine.packs.arma_garch.acceptance import assess_acceptance
from workbench.engine.packs.arma_garch.arma import (
    information_criterion_agreement,
    ArmaCandidateResult,
    ArmaSearchResult,
    search_arma_candidates,
)
from workbench.engine.packs.arma_garch.diagnostics import (
    MeanModelDiagnostics,
    build_mean_diagnostics,
)
from workbench.engine.packs.arma_garch.errors import (
    ArmaGarchInputError,
    diagnostic,
)
from workbench.engine.packs.arma_garch.estimation import estimate_arma_garch
from workbench.engine.packs.arma_garch.forecast import (
    RollingValidationResult,
    forecast_next_observation,
    run_rolling_validation,
)
from workbench.engine.packs.arma_garch.input import (
    PARSED_TIME_COLUMN,
    PARSED_VALUE_COLUMN,
    ROW_ID_COLUMN,
    PreparedArmaGarchInput,
    prepare_arma_garch_input,
)
from workbench.engine.packs.arma_garch.split import freeze_train_validation_split
from workbench.engine.packs.arma_garch.transforms import TRANSFORMED_VALUE_COLUMN
from workbench.engine.packs.arma_garch.volatility import (
    VarianceCandidateResult,
    VarianceSearchResult,
    search_joint_variance_candidates,
    search_variance_candidates,
)
from workbench.graph_model import Stage


MODEL_ID = "arma_garch_1"

_REQUIRED_LOGICAL_ARTIFACTS = {
    "ts.data_audit",
    "ts.analysis_contract",
    "ts.analysis_view_manifest",
    "ts.transform_profile",
    "ts.train_validation_split",
    "ts.arma_candidates",
    "ts.arma_selection",
    "ts.arma_diagnostics",
    "ts.volatility_candidates",
    "ts.volatility_selection",
    "ts.final_model",
    "ts.parameters",
    "ts.conditional_series",
    "ts.final_diagnostics",
    "ts.rolling_forecasts",
    "ts.forecast_metrics",
    "ts.next_forecast",
    "ts.arma_vs_garch_comparison",
    "ts.report",
    "ts.artifact_manifest",
    "ts.chart.series_transform",
    "ts.chart.acf",
    "ts.chart.pacf",
    "ts.chart.residual_series",
    "ts.chart.residual_acf",
    "ts.chart.squared_residual_acf",
    "ts.chart.qq",
    "ts.chart.conditional_volatility",
    "ts.chart.rolling_interval",
    "ts.chart.quantile_exceptions",
    "ts.chart.model_comparison",
}

_NODE_BY_ARTIFACT = {
    "ts.data_audit": "stage:ts-analysis-view",
    "ts.analysis_contract": "stage:ts-analysis-view",
    "ts.analysis_view_manifest": "stage:ts-analysis-view",
    "ts.transform_profile": "stage:ts-analysis-view",
    "ts.train_validation_split": "stage:ts-split",
    "ts.arma_candidates": "stage:ts-mean-selection",
    "ts.arma_selection": "stage:ts-mean-selection",
    "ts.arma_diagnostics": "stage:ts-mean-selection",
    "ts.volatility_candidates": "stage:ts-volatility-selection",
    "ts.volatility_selection": "stage:ts-volatility-selection",
    "ts.final_model": "stage:ts-volatility-selection",
    "ts.parameters": "stage:ts-volatility-selection",
    "ts.conditional_series": "stage:ts-volatility-selection",
    "ts.final_diagnostics": "stage:ts-volatility-selection",
    "ts.rolling_forecasts": "stage:ts-rolling-validation",
    "ts.forecast_metrics": "stage:ts-rolling-validation",
    "ts.arma_vs_garch_comparison": "stage:ts-rolling-validation",
    "ts.next_forecast": "stage:ts-full-sample-child",
    "ts.report": "stage:ts-full-sample-child",
    "ts.artifact_manifest": "stage:ts-full-sample-child",
    "ts.chart.series_transform": "stage:ts-analysis-view",
    "ts.chart.acf": "stage:ts-mean-selection",
    "ts.chart.pacf": "stage:ts-mean-selection",
    "ts.chart.residual_series": "stage:ts-mean-selection",
    "ts.chart.residual_acf": "stage:ts-mean-selection",
    "ts.chart.squared_residual_acf": "stage:ts-mean-selection",
    "ts.chart.qq": "stage:ts-volatility-selection",
    "ts.chart.conditional_volatility": "stage:ts-volatility-selection",
    "ts.chart.rolling_interval": "stage:ts-rolling-validation",
    "ts.chart.quantile_exceptions": "stage:ts-rolling-validation",
    "ts.chart.model_comparison": "stage:ts-rolling-validation",
}


def fit_from_context(ctx: Any, env: Any) -> tuple[str, dict[str, Any], None]:
    """Keep a truthful terminal artifact manifest on blocked/interrupted paths."""

    try:
        return _fit_from_context(ctx, env)
    except RunInterruptionRequested as exc:
        _persist_terminal_manifest_on_failure(
            ctx, env, status="interrupted", code=(
                "WORKFLOW_CANCELLED" if exc.reason == "cancelled" else "WORKFLOW_TIMEOUT"
            )
        )
        raise
    except ArmaGarchInputError as exc:
        _persist_terminal_manifest_on_failure(
            ctx, env, status="blocked", code=exc.code, diagnostic_payload=exc.to_dict()
        )
        raise
    except Exception as exc:
        _persist_terminal_manifest_on_failure(
            ctx, env, status="failed", code=type(exc).__name__
        )
        raise


def _fit_from_context(ctx: Any, env: Any) -> tuple[str, dict[str, Any], None]:
    """Run one immutable time/value analysis through the public engine seam."""

    options = ctx.artifacts.get("_model_options")
    if not isinstance(options, Mapping):
        raise ValueError("ARMA-GARCH model_options must be a mapping")
    contract = ArmaGarchAnalysisContract.from_dict(options)
    source = _raw_source_frame(ctx)
    raw_inputs = _raw_input_ids(ctx)
    ctx.artifacts["_primary_model_input_ids"] = raw_inputs

    env.progress("arma_garch", "Auditing immutable time-series input.")
    prepared = prepare_arma_garch_input(source, contract)
    transformed = prepared.transformed_view
    split = freeze_train_validation_split(transformed, contract)
    env.checkpoint("ARMA-GARCH split frozen")

    mean_search = search_arma_candidates(
        split, contract, checkpoint=lambda: env.checkpoint("ARMA candidate search")
    )
    mean_candidates = _eligible_mean_shortlist(mean_search, contract)
    if not mean_candidates:
        if mean_search.blocking_diagnostic is not None:
            raise ArmaGarchInputError(mean_search.blocking_diagnostic)
        raise ArmaGarchInputError(
            diagnostic(
                "NO_ARMA_CANDIDATE_CONVERGED",
                "No ARMA candidate is eligible for the requested estimation strategy.",
                evidence={
                    "requested_strategy": contract.estimation_strategy,
                    "candidate_count": len(mean_search.candidates),
                },
                impact="Volatility selection cannot start without one frozen mean specification.",
            )
        )

    training_values = split.training_view[TRANSFORMED_VALUE_COLUMN].to_numpy(
        dtype=float, copy=True
    )
    selected_mean = _selected_mean_candidate(mean_search, mean_candidates)
    variance_searches: list[dict[str, object]] = []
    env.checkpoint("Volatility candidate search")
    selected_variance_search = _search_variance(
        training_values, selected_mean, contract, env
    )
    variance_searches.append(
        {
            "mean_candidate_id": selected_mean.candidate_id,
            **selected_variance_search.to_dict(),
        }
    )
    variance_candidates = _variance_shortlist(selected_variance_search)
    if not variance_candidates:
        if selected_variance_search.blocking_diagnostic is not None:
            raise ArmaGarchInputError(selected_variance_search.blocking_diagnostic)
        raise ArmaGarchInputError(
            diagnostic(
                "NO_VOLATILITY_CANDIDATE_CONVERGED",
                "No volatility candidate passed the frozen training gates.",
                evidence={"mean_candidate_id": selected_mean.candidate_id},
                impact="A final volatility model and rolling validation cannot be produced.",
            )
        )

    selected_variance = _selected_variance_candidate(
        selected_variance_search, variance_candidates
    )
    rolling = run_rolling_validation(
        transformed,
        split,
        contract,
        mean_candidate=selected_mean,
        variance_candidate=selected_variance,
        checkpoint=lambda: env.checkpoint("Independent rolling evaluation"),
    )
    final_fit = estimate_arma_garch(
        training_values,
        contract,
        mean_candidate=selected_mean,
        variance_candidate=selected_variance,
        frozen_hold_back=selected_variance_search.common_hold_back,
        checkpoint=lambda: env.checkpoint("Final validation fit"),
    )
    final_model = final_fit.to_dict()
    mean_diagnostics = build_mean_diagnostics(
        training_values,
        np.asarray(selected_mean.residuals, dtype=float),
        model_df=selected_mean.p + selected_mean.q,
    )
    standardized = _finite_conditional_series(
        final_model["conditional_series"], "standardized_residual"
    )
    final_diagnostics = build_mean_diagnostics(
        training_values,
        standardized,
        model_df=selected_mean.p + selected_mean.q,
    )
    value_added = _volatility_value_added(rolling)
    acceptance = assess_acceptance(
        forecast_metrics=rolling.metrics,
        split_forecast_status=split.forecast_validation_status,
        estimation_converged=True,
        finite_parameters=True,
        variance_parameters_valid=selected_variance.parameters_valid,
        mean_residual_autocorrelation=_has_significant_p_value(
            mean_diagnostics.ljung_box
        ),
        squared_standardized_residual_arch=_has_significant_p_value(
            selected_variance.squared_standardized_residual_diagnostics
        ),
        normality_rejected=_normality_rejected(final_diagnostics),
        volatility_value_added=value_added,
    )

    next_forecast = forecast_next_observation(
        transformed,
        contract,
        mean_candidate=selected_mean,
        variance_candidate=selected_variance,
        next_timestamp=prepared.audited.time_index.next_timestamp,
        checkpoint=lambda: env.checkpoint("Full-sample production refit"),
    )
    next_payload = next_forecast.to_dict()
    production_child = {
        "result_id": f"{MODEL_ID}:production-final",
        "result_role": "production_final_child",
        "parent_result_id": MODEL_ID,
        "does_not_overwrite_parent": True,
        "fit_scope": "all_available_observations",
        "validation_metrics_recomputed": False,
        "refit_summary": next_payload["refit_summary"],
        "next_forecast": next_payload,
    }

    final_spec = dict(rolling.frozen_spec)
    artifact_payloads = _artifact_payloads(
        prepared=prepared,
        split=split,
        mean_search=mean_search,
        selected_mean=selected_mean,
        mean_diagnostics=mean_diagnostics,
        variance_searches=variance_searches,
        selected_variance=selected_variance,
        final_model=final_model,
        final_diagnostics=final_diagnostics,
        rolling=rolling,
        next_forecast=next_payload,
        production_child=production_child,
        acceptance=acceptance.to_dict(),
        final_spec=final_spec,
    )
    metadata_base = _metadata_base(
        ctx=ctx,
        env=env,
        contract=contract,
        analysis_view_hash=split.analysis_view_hash,
        model_spec=final_spec,
    )
    artifact_records = _persist_artifacts(
        env.run_root,
        artifact_payloads,
        metadata_base=metadata_base,
        inputs=raw_inputs,
    )
    _persist_artifact_manifest(
        env.run_root,
        artifact_records,
        metadata_base=metadata_base,
        inputs=raw_inputs,
    )
    _record_graph(env.recorder, artifact_records)

    result = {
        "model_type": ARMA_GARCH_PACK_ID,
        "model_id": MODEL_ID,
        "status": acceptance.overall_status,
        "nobs": split.n_train,
        "contract_hash": contract.contract_hash,
        "analysis_view_hash": split.analysis_view_hash,
        "split_hash": split.split_hash,
        "estimation_strategy": final_model["estimation_strategy"],
        "resolved_strategy": final_model["resolved_strategy"],
        "joint_likelihood": final_model["joint_likelihood"],
        "selection_repeated_during_validation": False,
        "selected_specification": final_spec,
        "validation": {
            "data_role": "independent_evaluation_after_selection",
            "candidate_selection_used_validation": False,
            "metrics": rolling.metrics.to_dict(),
            "acceptance": acceptance.to_dict(),
        },
        "production_child": production_child,
        "artifact_refs": {
            artifact_id: record["path"] for artifact_id, record in artifact_records.items()
        },
    }
    _require_finite_json(result, "model result")
    ctx.artifacts["_primary_model_parent_node_id"] = "stage:ts-full-sample-child"
    ctx.artifacts["_arma_garch_result"] = result
    env.progress("arma_garch", "ARMA-GARCH analysis and production forecast completed.")
    env.checkpoint()
    return MODEL_ID, result, None


def _persist_terminal_manifest_on_failure(
    ctx: Any,
    env: Any,
    *,
    status: str,
    code: str,
    diagnostic_payload: Mapping[str, object] | None = None,
) -> None:
    index_path = env.run_root / "artifacts_index.json"
    path = env.run_root / "artifacts" / "time_series" / "ts.artifact_manifest.json"
    if not index_path.exists():
        return
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        existing = {
            item.get("artifact_id")
            for item in index.get("artifacts", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("artifact_id"), str)
            and str(item.get("artifact_id")).startswith("ts.")
        }
        options = ctx.artifacts.get("_model_options")
        contract = (
            ArmaGarchAnalysisContract.from_dict(options)
            if isinstance(options, Mapping)
            else None
        )
        prior_metadata: Mapping[str, object] | None = None
        if path.exists():
            prior = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prior, Mapping) and isinstance(prior.get("metadata"), Mapping):
                prior_metadata = prior["metadata"]
        envelope = {
            "artifact_id": "ts.artifact_manifest",
            "metadata": dict(prior_metadata) if prior_metadata is not None else {
                "dataset_ref": None if contract is None else contract.dataset_ref,
                "dataset_hash": str(
                    ctx.artifacts.get("_upload_hash") or ctx.data.artifact_id
                ),
                "analysis_view_hash": None,
                "contract_hash": None if contract is None else contract.contract_hash,
                "run_id": env.run_id,
                "node_id": "stage:ts-analysis-view",
                "source_run_id": _source_run_id(env.run_root),
                "model_spec": {},
                "dependency_versions": package_versions(),
                "random_seed": None if contract is None else contract.random_seed,
                "code_version": __version__,
                "build_version": __version__,
            },
            "payload": {
                "status": status,
                "terminal_code": code,
                "complete": False,
                "persisted_artifact_ids": sorted(
                    item
                    for item in existing
                    if isinstance(item, str) and item != "ts.artifact_manifest"
                ),
                "missing_required_artifact_ids": sorted(
                    _REQUIRED_LOGICAL_ARTIFACTS - existing - {"ts.artifact_manifest"}
                ),
                "diagnostic": None if diagnostic_payload is None else dict(diagnostic_payload),
            },
        }
        _require_finite_json(envelope, "ts.artifact_manifest")
        write_json(path, envelope)
        manifest_record = next(
            (
                item
                for item in index.get("artifacts", [])
                if isinstance(item, dict)
                and item.get("artifact_id") == "ts.artifact_manifest"
            ),
            None,
        )
        if manifest_record is None:
            register_artifact(
                env.run_root,
                "ts.artifact_manifest",
                path,
                "time_series_manifest",
                "arma_garch",
                _raw_input_ids(ctx),
            )
        else:
            manifest_record["sha256"] = sha256_file(path)
            write_json(index_path, index)
    except Exception:
        # The original terminal condition remains authoritative. The shared
        # run lifecycle will still persist its manifest/errors contract.
        return


def _raw_source_frame(ctx: Any) -> pd.DataFrame:
    frames = ctx.artifacts.get("_frames")
    if not isinstance(frames, Mapping) or not frames:
        raise ValueError("ARMA-GARCH requires the immutable ingestion frames")
    if len(frames) != 1:
        raise ValueError("ARMA-GARCH v1.8 requires exactly one source table")
    frame = next(iter(frames.values()))
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("ARMA-GARCH ingestion frame must be a pandas DataFrame")
    return frame


def _raw_input_ids(ctx: Any) -> list[str]:
    value = ctx.artifacts.get("_raw_inputs")
    if isinstance(value, list) and value and all(
        isinstance(item, str) and item for item in value
    ):
        return list(value)
    return list(ctx.data.provenance) or [ctx.data.artifact_id]


def _eligible_mean_shortlist(
    search: ArmaSearchResult, contract: ArmaGarchAnalysisContract
) -> tuple[ArmaCandidateResult, ...]:
    by_id = {candidate.candidate_id: candidate for candidate in search.candidates}
    candidates = [
        by_id[candidate_id]
        for candidate_id in search.shortlist_candidate_ids
        if candidate_id in by_id
    ]
    if contract.estimation_strategy == "joint":
        candidates = [candidate for candidate in candidates if candidate.q == 0]
        if not candidates:
            candidates = [
                candidate
                for candidate in search.candidates
                if candidate.q == 0
                and candidate.failure_code is None
                and candidate.aicc is not None
            ]
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                math.inf if item.aicc is None else item.aicc,
                item.p + item.q,
                item.candidate_id,
            ),
        )
    )


def _selected_mean_candidate(
    search: ArmaSearchResult,
    eligible: Sequence[ArmaCandidateResult],
) -> ArmaCandidateResult:
    selected = next(
        (item for item in eligible if item.candidate_id == search.selected_candidate_id),
        None,
    )
    return selected if selected is not None else eligible[0]


def _selected_variance_candidate(
    search: VarianceSearchResult,
    eligible: Sequence[VarianceCandidateResult],
) -> VarianceCandidateResult:
    selected = next(
        (item for item in eligible if item.candidate_id == search.selected_candidate_id),
        None,
    )
    return selected if selected is not None else eligible[0]


def _search_variance(
    training_values: np.ndarray,
    mean_candidate: ArmaCandidateResult,
    contract: ArmaGarchAnalysisContract,
    env: Any,
) -> VarianceSearchResult:
    kwargs = {
        "mean_candidate_id": mean_candidate.candidate_id,
        "mean_order": (mean_candidate.p, mean_candidate.q),
        "mean_constant": mean_candidate.constant,
        "checkpoint": lambda: env.checkpoint("Volatility candidate fit"),
    }
    if contract.estimation_strategy == "joint" or (
        contract.estimation_strategy == "auto" and mean_candidate.q == 0
    ):
        return search_joint_variance_candidates(
            training_values.copy(), contract, **kwargs
        )
    return search_variance_candidates(
        np.asarray(mean_candidate.residuals, dtype=float), contract, **kwargs
    )


def _variance_shortlist(
    search: VarianceSearchResult,
) -> tuple[VarianceCandidateResult, ...]:
    by_id = {candidate.candidate_id: candidate for candidate in search.candidates}
    return tuple(
        by_id[candidate_id]
        for candidate_id in search.shortlist_candidate_ids
        if candidate_id in by_id and by_id[candidate_id].failure_code is None
    )


def _finite_conditional_series(
    conditional_series: object, name: str
) -> np.ndarray:
    if not isinstance(conditional_series, Mapping):
        return np.array([], dtype=float)
    values = conditional_series.get(name)
    if not isinstance(values, (list, tuple)):
        return np.array([], dtype=float)
    return np.asarray(
        [float(value) for value in values if value is not None and math.isfinite(float(value))],
        dtype=float,
    )


def _has_significant_p_value(
    diagnostics: Sequence[Mapping[str, object]],
) -> bool | None:
    values = [
        float(item["p_value"])
        for item in diagnostics
        if item.get("p_value") is not None
    ]
    return any(value < 0.05 for value in values) if values else None


def _normality_rejected(diagnostics: MeanModelDiagnostics) -> bool | None:
    value = diagnostics.normality.get("p_value")
    return None if value is None else float(value) < 0.05


def _volatility_value_added(validation: RollingValidationResult) -> bool | None:
    comparison = validation.comparison
    if int(comparison.get("comparison_validation_n", 0)) < 20:
        return None
    main = comparison.get("arma_garch")
    baseline = comparison.get("arma_only")
    if not isinstance(main, Mapping) or not isinstance(baseline, Mapping):
        return None
    improvements: list[bool] = []
    for key in ("rmse", "pinball_loss"):
        main_value = main.get(key)
        baseline_value = baseline.get(key)
        if main_value is not None and baseline_value is not None:
            improvements.append(float(main_value) < 0.98 * float(baseline_value))
    return any(improvements) if improvements else None


def _artifact_payloads(
    *,
    prepared: PreparedArmaGarchInput,
    split: Any,
    mean_search: ArmaSearchResult,
    selected_mean: ArmaCandidateResult,
    mean_diagnostics: MeanModelDiagnostics,
    variance_searches: list[dict[str, object]],
    selected_variance: VarianceCandidateResult,
    final_model: dict[str, object],
    final_diagnostics: MeanModelDiagnostics,
    rolling: RollingValidationResult,
    next_forecast: dict[str, object],
    production_child: dict[str, object],
    acceptance: dict[str, object],
    final_spec: dict[str, object],
) -> dict[str, object]:
    transformed = prepared.transformed_view
    audit = prepared.audited
    mean_payload = mean_diagnostics.to_dict()
    final_diag_payload = final_diagnostics.to_dict()
    rolling_payload = rolling.to_dict()
    conditional = final_model["conditional_series"]
    parameters = {
        "mean_candidate": dict(selected_mean.parameters),
        "selected_variance_candidate": dict(selected_variance.parameters),
        "final_fit": final_model.get("parameters")
        or (
            final_model.get("variance_stage", {}).get("parameters", {})
            if isinstance(final_model.get("variance_stage"), Mapping)
            else {}
        ),
    }
    report = {
        "answer": (
            f"Selected {selected_mean.candidate_id} with "
            f"{selected_variance.display_name}; acceptance is {acceptance['overall_status']}."
        ),
        "estimation_semantics": {
            "strategy": final_model["estimation_strategy"],
            "resolved_strategy": final_model["resolved_strategy"],
            "joint_likelihood": final_model["joint_likelihood"],
            "information_criteria_cross_strategy_comparable": False,
        },
        "sample": {
            "source_n": audit.time_index.original_row_count,
            "effective_n": len(transformed),
            "training_n": split.n_train,
            "validation_n": split.validation_n,
            "selection_data_role": "training_only",
            "validation_data_role": "independent_evaluation_after_selection",
        },
        "scale": {
            "transform": prepared.contract.transform,
            "lag_unit": audit.time_index.lag_unit,
            "original_scale_variance_claimed": False,
        },
        "forecast_limitations": {
            "horizon": 1,
            "predictive_interval": "plugin_conditional",
            "parameter_uncertainty_included": False,
        },
        "acceptance": acceptance,
        "warnings": list(
            dict.fromkeys(
                [
                    *(item.code for item in audit.diagnostics),
                    *mean_diagnostics.warnings,
                    *final_diagnostics.warnings,
                    *rolling.warnings,
                ]
            )
        ),
        "reproducibility": {
            "contract_hash": prepared.contract.contract_hash,
            "analysis_view_hash": split.analysis_view_hash,
            "split_hash": split.split_hash,
            "random_seed": prepared.contract.random_seed,
        },
    }
    payloads: dict[str, object] = {
        "ts.data_audit": {
            "time_index": _plain(audit.time_index),
            "data_quality": _plain(audit.data_quality),
            "diagnostics": [item.to_dict() for item in audit.diagnostics],
            "source_hash_before": audit.source_hash_before,
            "source_hash_after": audit.source_hash_after,
            "source_unchanged": audit.source_unchanged,
        },
        "ts.analysis_contract": prepared.contract.to_dict(),
        "ts.analysis_view_manifest": {
            "analysis_view_hash": split.analysis_view_hash,
            "columns": [str(column) for column in transformed.columns],
            "row_ids": transformed[ROW_ID_COLUMN].astype(str).tolist(),
            "row_count": len(transformed),
            "source_unchanged": audit.source_unchanged,
        },
        "ts.transform_profile": {
            "confirmed_transform": prepared.contract.transform,
            "user_confirmed": True,
            "profiles": {
                name: profile.to_dict()
                for name, profile in prepared.transform_profiles.items()
            },
        },
        "ts.train_validation_split": {
            **split.to_dict(),
            "training_data_role": "candidate_selection_and_estimation",
            "validation_data_role": "independent_evaluation_after_selection",
            "candidate_selection_used_validation": False,
        },
        "ts.arma_candidates": {
            "candidates": [item.to_dict() for item in mean_search.candidates],
            "selection_repeated_during_validation": False,
        },
        "ts.arma_selection": {
            "pre_validation_selected_candidate_id": mean_search.selected_candidate_id,
            "pre_validation_shortlist_candidate_ids": list(
                mean_search.shortlist_candidate_ids
            ),
            "final_selected_candidate_id": selected_mean.candidate_id,
            "final_selection_basis": "frozen_training_gates_aicc_bic_parsimony",
            "candidate_selection_used_validation": False,
            "validation_data_role": "independent_evaluation_after_selection",
            "information_criterion_agreement": information_criterion_agreement(
                [item.to_dict() for item in mean_search.candidates]
            ),
        },
        "ts.arma_diagnostics": mean_payload,
        "ts.volatility_candidates": {"searches": variance_searches},
        "ts.volatility_selection": {
            "selected_candidate_id": selected_variance.candidate_id,
            "selected_mean_candidate_id": selected_mean.candidate_id,
            "selection_basis": "frozen_training_gates_aicc_bic_parsimony",
            "candidate_selection_used_validation": False,
            "validation_data_role": "independent_evaluation_after_selection",
            "information_criteria_compared_across_strategies": False,
        },
        "ts.final_model": {
            "validation_fit": final_model,
            "acceptance": acceptance,
            "production_child": production_child,
        },
        "ts.parameters": parameters,
        "ts.conditional_series": conditional,
        "ts.final_diagnostics": final_diag_payload,
        "ts.rolling_forecasts": {
            key: value for key, value in rolling_payload.items() if key != "metrics"
        },
        "ts.forecast_metrics": rolling.metrics.to_dict(),
        "ts.next_forecast": {
            "result_role": "production_final_child",
            "parent_result_id": MODEL_ID,
            **next_forecast,
        },
        "ts.arma_vs_garch_comparison": dict(rolling.comparison),
        "ts.report": report,
    }
    payloads.update(
        _chart_payloads(
            transformed=transformed,
            split=split,
            mean_diagnostics=mean_payload,
            final_diagnostics=final_diag_payload,
            conditional_series=conditional,
            rolling=rolling_payload,
            comparison=dict(rolling.comparison),
            final_spec=final_spec,
        )
    )
    return payloads


def _chart_payloads(
    *,
    transformed: pd.DataFrame,
    split: Any,
    mean_diagnostics: Mapping[str, object],
    final_diagnostics: Mapping[str, object],
    conditional_series: object,
    rolling: Mapping[str, object],
    comparison: Mapping[str, object],
    final_spec: Mapping[str, object],
) -> dict[str, object]:
    series_rows = [
        {
            "row_id": str(row[ROW_ID_COLUMN]),
            "time": _time_text(row[PARSED_TIME_COLUMN]),
            "source_value": float(row[PARSED_VALUE_COLUMN]),
            "transformed_value": float(row[TRANSFORMED_VALUE_COLUMN]),
        }
        for _, row in transformed.iterrows()
    ]
    training = split.training_view
    conditional_rows: list[dict[str, object]] = []
    if isinstance(conditional_series, Mapping):
        volatility = conditional_series.get("volatility", [])
        if isinstance(volatility, (list, tuple)):
            conditional_rows = [
                {
                    "row_id": str(training.iloc[index][ROW_ID_COLUMN]),
                    "time": _time_text(training.iloc[index][PARSED_TIME_COLUMN]),
                    "conditional_volatility": value,
                }
                for index, value in enumerate(volatility)
                if index < len(training)
            ]
    rolling_rows = rolling.get("rows", [])
    if not isinstance(rolling_rows, list):
        rolling_rows = []
    return {
        "ts.chart.series_transform": {"rows": series_rows, "spec": dict(final_spec)},
        "ts.chart.acf": {"rows": mean_diagnostics.get("series_acf", [])},
        "ts.chart.pacf": {"rows": mean_diagnostics.get("series_pacf", [])},
        "ts.chart.residual_series": {
            "rows": mean_diagnostics.get("residual_series", [])
        },
        "ts.chart.residual_acf": {
            "rows": mean_diagnostics.get("residual_acf", [])
        },
        "ts.chart.squared_residual_acf": {
            "rows": mean_diagnostics.get("squared_residual_acf", [])
        },
        "ts.chart.qq": {"rows": final_diagnostics.get("qq_data", [])},
        "ts.chart.conditional_volatility": {"rows": conditional_rows},
        "ts.chart.rolling_interval": {"rows": rolling_rows},
        "ts.chart.quantile_exceptions": {
            "rows": [row for row in rolling_rows if row.get("quantile_exception")]
        },
        "ts.chart.model_comparison": {"comparison": dict(comparison)},
    }


def _metadata_base(
    *,
    ctx: Any,
    env: Any,
    contract: ArmaGarchAnalysisContract,
    analysis_view_hash: str,
    model_spec: Mapping[str, object],
) -> dict[str, object]:
    dataset_hash = str(ctx.artifacts.get("_upload_hash") or ctx.data.artifact_id)
    return {
        "dataset_ref": contract.dataset_ref,
        "dataset_hash": dataset_hash,
        "analysis_view_hash": analysis_view_hash,
        "contract_hash": contract.contract_hash,
        "run_id": env.run_id,
        "source_run_id": _source_run_id(env.run_root),
        "model_spec": dict(model_spec),
        "dependency_versions": package_versions(),
        "random_seed": contract.random_seed,
        "code_version": __version__,
        "build_version": __version__,
    }


def _persist_artifacts(
    run_root: Path,
    payloads: Mapping[str, object],
    *,
    metadata_base: Mapping[str, object],
    inputs: list[str],
) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for artifact_id, payload in payloads.items():
        node_id = _NODE_BY_ARTIFACT[artifact_id]
        path = run_root / "artifacts" / "time_series" / f"{artifact_id}.json"
        envelope = {
            "artifact_id": artifact_id,
            "metadata": {**metadata_base, "node_id": node_id},
            "payload": _plain(payload),
        }
        _require_finite_json(envelope, artifact_id)
        write_json(path, envelope)
        record = register_artifact(
            run_root,
            artifact_id,
            path,
            "time_series_json",
            "arma_garch",
            inputs,
        ).to_dict()
        records[artifact_id] = record
    return records


def _persist_artifact_manifest(
    run_root: Path,
    records: dict[str, dict[str, object]],
    *,
    metadata_base: Mapping[str, object],
    inputs: list[str],
) -> None:
    artifact_id = "ts.artifact_manifest"
    path = run_root / "artifacts" / "time_series" / f"{artifact_id}.json"
    envelope = {
        "artifact_id": artifact_id,
        "metadata": {
            **metadata_base,
            "node_id": _NODE_BY_ARTIFACT[artifact_id],
        },
        "payload": {
            "status": "complete",
            "complete": True,
            "artifact_count_before_manifest": len(records),
            "artifacts": [records[key] for key in sorted(records)],
        },
    }
    _require_finite_json(envelope, artifact_id)
    write_json(path, envelope)
    record = register_artifact(
        run_root,
        artifact_id,
        path,
        "time_series_manifest",
        "arma_garch",
        inputs,
    ).to_dict()
    records[artifact_id] = record


def _record_graph(
    recorder: Any, records: Mapping[str, Mapping[str, object]]
) -> None:
    stages = (
        (
            "stage:ts-analysis-view",
            "Time-series analysis view",
            "ts.analysis_view_manifest",
            Stage.TRANSFORM,
        ),
        ("stage:ts-split", "Frozen train/validation split", "ts.train_validation_split", Stage.TRANSFORM),
        ("stage:ts-mean-selection", "ARMA mean selection", "ts.arma_selection", Stage.MODEL),
        ("stage:ts-volatility-selection", "ARCH/GARCH selection", "ts.volatility_selection", Stage.MODEL),
        ("stage:ts-rolling-validation", "One-step rolling validation", "ts.forecast_metrics", Stage.DIAG),
        ("stage:ts-full-sample-child", "Full-sample production child", "ts.next_forecast", Stage.MODEL),
    )
    previous = "stage:raw"
    for node_id, label, artifact_id, stage in stages:
        record = records[artifact_id]
        recorder.record_stage(
            node_id=node_id,
            display_label=label,
            payload_ref=str(record["path"]),
            summary=label,
            stage=stage,
        )
        recorder.record_edge(
            edge_id=f"e:{previous.removeprefix('stage:')}:{node_id.removeprefix('stage:')}",
            source_id=previous,
            target_id=node_id,
            op=node_id.removeprefix("stage:ts-").replace("-", "_"),
        )
        previous = node_id


def _source_run_id(run_root: Path) -> str | None:
    path = run_root / "run_inputs.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("rerun_of")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


def _plain(value: object) -> object:
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, np.generic):
        return _plain(value.item())
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return _time_text(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _time_text(value: object) -> str:
    if isinstance(value, (int, float, np.integer, np.floating)):
        return f"{float(value):g}"
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _require_finite_json(value: object, label: str) -> None:
    try:
        json.dumps(_plain(value), allow_nan=False, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ArmaGarchInputError(
            diagnostic(
                "ARTIFACT_INCOMPLETE",
                f"{label} is not finite JSON and cannot be persisted safely.",
                evidence={"artifact": label, "error_type": type(exc).__name__},
                impact="The run cannot claim a complete reproducible artifact set.",
            )
        ) from exc


__all__ = ["MODEL_ID", "fit_from_context"]
