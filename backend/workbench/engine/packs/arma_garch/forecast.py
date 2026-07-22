"""Frozen-spec expanding one-step forecasts and scale-aware evaluation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math
from time import perf_counter
from typing import Literal
import warnings as runtime_warnings

import numpy as np
import pandas as pd
from arch.univariate import ARX, ConstantMean, ZeroMean
from statsmodels.tsa.arima.model import ARIMA

from workbench.contracts.common.envelope import freeze_json, thaw_json
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.arma import (
    ArmaCandidateResult,
    enumerate_arma_candidates,
)
from workbench.engine.packs.arma_garch.estimation import resolve_estimation_strategy
from workbench.engine.packs.arma_garch.input import (
    PARSED_TIME_COLUMN,
    PARSED_VALUE_COLUMN,
    ROW_ID_COLUMN,
    dataframe_canonical_hash,
)
from workbench.engine.packs.arma_garch.split import FrozenTrainValidationSplit
from workbench.engine.packs.arma_garch.transforms import TRANSFORMED_VALUE_COLUMN
from workbench.engine.packs.arma_garch.volatility import (
    VarianceCandidateResult,
    VarianceCandidateSpec,
    build_distribution,
    build_volatility_process,
    common_hold_back,
    enumerate_variance_candidates,
)


FitMethod = Literal["refit", "fixed_parameters_update"]


@dataclass(frozen=True)
class ForecastRow:
    forecast_origin_row_id: str
    forecast_origin_time: str
    target_row_id: str
    target_time: str
    observed_value: float
    conditional_mean: float | None
    conditional_variance: float | None
    conditional_volatility: float | None
    lower_bound: float | None
    upper_bound: float | None
    lower_quantile: float | None
    interval_covered: bool | None
    quantile_exception: bool | None
    model_scale: str
    original_scale: Mapping[str, object]
    fit_status: Literal["ok", "failed"]
    fit_method: FitMethod
    warning: str | None
    predictive_interval: Literal["plugin_conditional"] = "plugin_conditional"
    parameter_uncertainty_included: Literal[False] = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.observed_value):
            raise ValueError("forecast observed_value must be finite")
        numeric = (
            self.conditional_mean,
            self.conditional_variance,
            self.conditional_volatility,
            self.lower_bound,
            self.upper_bound,
            self.lower_quantile,
        )
        if self.fit_status == "ok":
            if any(value is None or not math.isfinite(value) for value in numeric):
                raise ValueError("successful forecast fields must be finite")
            assert self.conditional_variance is not None
            if self.conditional_variance <= 0.0:
                raise ValueError("successful conditional variance must be positive")
        elif any(value is not None for value in numeric):
            raise ValueError("failed forecast numeric fields must be null")
        object.__setattr__(
            self,
            "original_scale",
            freeze_json(self.original_scale, "forecast_row.original_scale"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "forecast_origin": {
                "row_id": self.forecast_origin_row_id,
                "time": self.forecast_origin_time,
            },
            "target": {"row_id": self.target_row_id, "time": self.target_time},
            "observed_value": self.observed_value,
            "conditional_mean": self.conditional_mean,
            "conditional_variance": self.conditional_variance,
            "conditional_volatility": self.conditional_volatility,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "lower_quantile": self.lower_quantile,
            "interval_covered": self.interval_covered,
            "quantile_exception": self.quantile_exception,
            "model_scale": self.model_scale,
            "original_scale": thaw_json(self.original_scale),
            "fit_status": self.fit_status,
            "fit_method": self.fit_method,
            "warning": self.warning,
            "predictive_interval": self.predictive_interval,
            "parameter_uncertainty_included": self.parameter_uncertainty_included,
        }


@dataclass(frozen=True)
class ForecastMetrics:
    validation_n: int
    successful_forecast_n: int
    mae: float | None
    rmse: float | None
    mean_error: float | None
    interval_coverage: float | None
    average_interval_width: float | None
    coverage_count: int
    coverage_interval: tuple[float | None, float | None]
    exception_rate: float | None
    exception_count: int
    pinball_loss: float | None

    def __post_init__(self) -> None:
        if (
            type(self.validation_n) is not int
            or type(self.successful_forecast_n) is not int
            or not 0 <= self.successful_forecast_n <= self.validation_n
            or not 0 <= self.coverage_count <= self.successful_forecast_n
            or not 0 <= self.exception_count <= self.successful_forecast_n
        ):
            raise ValueError("forecast metric counts are inconsistent")
        optional = (
            self.mae,
            self.rmse,
            self.mean_error,
            self.interval_coverage,
            self.average_interval_width,
            *self.coverage_interval,
            self.exception_rate,
            self.pinball_loss,
        )
        if any(value is not None and not math.isfinite(value) for value in optional):
            raise ValueError("forecast metrics must be finite or null")
        for value in (self.interval_coverage, self.exception_rate):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError("forecast rates must be between zero and one")

    def to_dict(self) -> dict[str, object]:
        return {
            "validation_n": self.validation_n,
            "successful_forecast_n": self.successful_forecast_n,
            "mae": self.mae,
            "rmse": self.rmse,
            "mean_error": self.mean_error,
            "interval_coverage": self.interval_coverage,
            "average_interval_width": self.average_interval_width,
            "coverage_count": self.coverage_count,
            "coverage_uncertainty": {
                "method": "wilson_95pct",
                "lower": self.coverage_interval[0],
                "upper": self.coverage_interval[1],
            },
            "exception_rate": self.exception_rate,
            "exception_count": self.exception_count,
            "pinball_loss": self.pinball_loss,
        }


@dataclass(frozen=True)
class RollingValidationResult:
    rows: tuple[ForecastRow, ...]
    metrics: ForecastMetrics
    frozen_spec: Mapping[str, object]
    comparison: Mapping[str, object]
    warnings: tuple[str, ...]
    selection_repeated_during_validation: Literal[False] = False
    horizon: Literal[1] = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "frozen_spec", freeze_json(self.frozen_spec, "rolling.frozen_spec")
        )
        object.__setattr__(
            self, "comparison", freeze_json(self.comparison, "rolling.comparison")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "horizon": self.horizon,
            "selection_repeated_during_validation": self.selection_repeated_during_validation,
            "predictive_interval": "plugin_conditional",
            "parameter_uncertainty_included": False,
            "frozen_spec": thaw_json(self.frozen_spec),
            "rows": [row.to_dict() for row in self.rows],
            "metrics": self.metrics.to_dict(),
            "arma_vs_garch_comparison": thaw_json(self.comparison),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class NextObservationForecast:
    forecast_origin_row_id: str
    forecast_origin_time: str
    target_time: str | None
    conditional_mean: float
    conditional_variance: float
    conditional_volatility: float
    lower_bound: float
    upper_bound: float
    lower_quantile: float
    model_scale: str
    original_scale: Mapping[str, object]
    frozen_spec: Mapping[str, object]
    refit_summary: Mapping[str, object]
    warning: str | None
    target_label: Literal["next_observation"] = "next_observation"
    fit_method: Literal["full_sample_refit"] = "full_sample_refit"
    predictive_interval: Literal["plugin_conditional"] = "plugin_conditional"
    parameter_uncertainty_included: Literal[False] = False

    def __post_init__(self) -> None:
        numeric = (
            self.conditional_mean,
            self.conditional_variance,
            self.conditional_volatility,
            self.lower_bound,
            self.upper_bound,
            self.lower_quantile,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("next-observation forecast fields must be finite")
        if self.conditional_variance <= 0.0:
            raise ValueError("next-observation conditional variance must be positive")
        object.__setattr__(
            self,
            "original_scale",
            freeze_json(self.original_scale, "next_forecast.original_scale"),
        )
        object.__setattr__(
            self,
            "frozen_spec",
            freeze_json(self.frozen_spec, "next_forecast.frozen_spec"),
        )
        object.__setattr__(
            self,
            "refit_summary",
            freeze_json(self.refit_summary, "next_forecast.refit_summary"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "forecast_origin": {
                "row_id": self.forecast_origin_row_id,
                "time": self.forecast_origin_time,
            },
            "target_label": self.target_label,
            "target_time": self.target_time,
            "conditional_mean": self.conditional_mean,
            "conditional_variance": self.conditional_variance,
            "conditional_volatility": self.conditional_volatility,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "lower_quantile": self.lower_quantile,
            "model_scale": self.model_scale,
            "original_scale": thaw_json(self.original_scale),
            "frozen_spec": thaw_json(self.frozen_spec),
            "refit_summary": thaw_json(self.refit_summary),
            "fit_method": self.fit_method,
            "predictive_interval": self.predictive_interval,
            "parameter_uncertainty_included": self.parameter_uncertainty_included,
            "warning": self.warning,
        }


@dataclass
class _SequentialState:
    mean_parameters: np.ndarray | None = None
    variance_parameters: np.ndarray | None = None


@dataclass
class _JointState:
    parameters: np.ndarray | None = None


@dataclass(frozen=True)
class _PointForecast:
    mean: float
    variance: float
    distribution_parameters: Mapping[str, float]
    refit_summary: Mapping[str, object]
    warning: str | None


def innovation_quantiles(
    *,
    distribution: str,
    probabilities: Sequence[float],
    fitted_parameters: Mapping[str, float],
) -> tuple[float, ...]:
    """Use arch's standardized innovation definition for all quantiles."""

    if not probabilities or any(not 0.0 < float(value) < 1.0 for value in probabilities):
        raise ValueError("probabilities must be non-empty and strictly between zero and one")
    selected = build_distribution(distribution)
    names = tuple(selected.parameter_names())
    try:
        parameters = [float(fitted_parameters[name]) for name in names]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("fitted innovation distribution parameters are incomplete") from exc
    values = np.asarray(selected.ppf(tuple(probabilities), parameters or None), dtype=float)
    if values.shape != (len(probabilities),) or not np.isfinite(values).all():
        raise ValueError("innovation quantiles must be finite and aligned")
    return tuple(float(value) for value in values)


def backtransform_forecast(
    *,
    transform: str,
    last_level: float,
    point: float,
    lower: float,
    upper: float,
    lower_quantile: float,
) -> dict[str, object]:
    """Back-transform a point/median and quantile boundaries, never a variance."""

    values = (last_level, point, lower, upper, lower_quantile)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("back-transform inputs must be finite")
    if transform == "level":
        converted = (point, lower, upper, lower_quantile)
        method = "identity"
        statistic = "conditional_mean"
    elif transform == "log_level":
        converted = tuple(math.exp(value) for value in (point, lower, upper, lower_quantile))
        method = "exp_quantiles"
        statistic = "conditional_median"
    elif transform == "diff_1":
        converted = tuple(last_level + value for value in (point, lower, upper, lower_quantile))
        method = "last_level_plus_quantile"
        statistic = "conditional_mean"
    elif transform == "log_return_pct":
        if last_level <= 0.0:
            raise ValueError("log-return back-transform requires a positive last level")
        converted = tuple(
            last_level * math.exp(value / 100.0)
            for value in (point, lower, upper, lower_quantile)
        )
        method = "last_level_times_exp_quantile_pct"
        statistic = "conditional_median"
    else:
        raise ValueError(f"unsupported transform: {transform}")
    if not all(math.isfinite(float(value)) for value in converted):
        raise ValueError("back-transformed quantiles must be finite")
    return {
        "transform": transform,
        "backtransform_method": method,
        "point_statistic": statistic,
        "point_or_median": float(converted[0]),
        "lower_bound": float(converted[1]),
        "upper_bound": float(converted[2]),
        "lower_quantile": float(converted[3]),
        "variance_available": False,
    }


def run_rolling_validation(
    transformed_view: pd.DataFrame,
    split: FrozenTrainValidationSplit,
    contract: ArmaGarchAnalysisContract,
    *,
    mean_candidate: ArmaCandidateResult,
    variance_candidate: VarianceCandidateResult,
    checkpoint: Callable[[], None] | None = None,
) -> RollingValidationResult:
    """Run expanding one-step validation without repeating candidate selection."""

    frame = _validate_rolling_inputs(
        transformed_view, split, contract, mean_candidate, variance_candidate
    )
    values = frame[TRANSFORMED_VALUE_COLUMN].to_numpy(dtype=float)
    split_index = split.split_index
    strategy = resolve_estimation_strategy(
        contract.estimation_strategy, mean_q=mean_candidate.q
    )
    main_state: _SequentialState | _JointState
    main_state = _SequentialState() if strategy == "sequential_arma_garch" else _JointState()
    baseline_state = _SequentialState()
    rows: list[ForecastRow] = []
    baseline_rows: list[ForecastRow] = []
    all_warnings: list[str] = []
    main_runtime_seconds = 0.0
    baseline_runtime_seconds = 0.0
    for offset, target_index in enumerate(range(split_index, len(frame))):
        if checkpoint is not None:
            checkpoint()
        history = values[:target_index].copy()
        scheduled_refit = offset % contract.validation.refit_every == 0
        main_refit = scheduled_refit or _state_empty(main_state)
        baseline_refit = scheduled_refit or _state_empty(baseline_state)
        origin = frame.iloc[target_index - 1]
        target = frame.iloc[target_index]
        main_started = perf_counter()
        try:
            if strategy == "sequential_arma_garch":
                assert isinstance(main_state, _SequentialState)
                point = _sequential_point_forecast(
                    history,
                    mean_candidate=mean_candidate,
                    variance_spec=_variance_spec(variance_candidate),
                    hold_back=variance_candidate.hold_back,
                    state=main_state,
                    refit=main_refit,
                )
            else:
                assert isinstance(main_state, _JointState)
                point = _joint_point_forecast(
                    history,
                    mean_candidate=mean_candidate,
                    variance_spec=_variance_spec(variance_candidate),
                    hold_back=variance_candidate.hold_back,
                    state=main_state,
                    refit=main_refit,
                )
            row = _build_row(
                origin,
                target,
                observed=float(values[target_index]),
                point=point,
                contract=contract,
                fit_method="refit" if main_refit else "fixed_parameters_update",
            )
            if point.warning:
                all_warnings.append(point.warning)
        except Exception as exc:
            row = _failed_row(
                origin,
                target,
                observed=float(values[target_index]),
                contract=contract,
                fit_method="refit" if main_refit else "fixed_parameters_update",
                warning=f"{type(exc).__name__}: {exc}",
            )
            all_warnings.append(row.warning or "rolling forecast failed")
        finally:
            main_runtime_seconds += perf_counter() - main_started
        rows.append(row)

        baseline_started = perf_counter()
        try:
            baseline = _sequential_point_forecast(
                history,
                mean_candidate=mean_candidate,
                variance_spec=VarianceCandidateSpec.create(
                    model="constant_variance",
                    p=0,
                    q=0,
                    distribution=variance_candidate.distribution,
                ),
                hold_back=variance_candidate.hold_back,
                state=baseline_state,
                refit=baseline_refit,
            )
            baseline_rows.append(
                _build_row(
                    origin,
                    target,
                    observed=float(values[target_index]),
                    point=baseline,
                    contract=contract,
                    fit_method="refit" if baseline_refit else "fixed_parameters_update",
                )
            )
        except Exception as exc:
            baseline_rows.append(
                _failed_row(
                    origin,
                    target,
                    observed=float(values[target_index]),
                    contract=contract,
                    fit_method="refit" if baseline_refit else "fixed_parameters_update",
                    warning=f"{type(exc).__name__}: {exc}",
                )
            )
        finally:
            baseline_runtime_seconds += perf_counter() - baseline_started

    metrics = calculate_forecast_metrics(rows, contract.forecast.lower_quantile)
    baseline_metrics = calculate_forecast_metrics(
        baseline_rows, contract.forecast.lower_quantile
    )
    comparable_pairs = tuple(
        (main_row, baseline_row)
        for main_row, baseline_row in zip(rows, baseline_rows, strict=True)
        if main_row.fit_status == "ok" and baseline_row.fit_status == "ok"
    )
    comparable_main = tuple(pair[0] for pair in comparable_pairs)
    comparable_baseline = tuple(pair[1] for pair in comparable_pairs)
    comparison_main_metrics = calculate_forecast_metrics(
        comparable_main, contract.forecast.lower_quantile
    )
    comparison_baseline_metrics = calculate_forecast_metrics(
        comparable_baseline, contract.forecast.lower_quantile
    )
    frozen_spec = {
        "split_hash": split.split_hash,
        "mean_candidate_id": mean_candidate.candidate_id,
        "mean_order": [mean_candidate.p, mean_candidate.q],
        "mean_constant": mean_candidate.constant,
        "variance_candidate_id": variance_candidate.candidate_id,
        "variance_model": variance_candidate.model,
        "variance_order": [variance_candidate.p, variance_candidate.q],
        "innovation_distribution": variance_candidate.distribution,
        "resolved_strategy": strategy,
        "hold_back": variance_candidate.hold_back,
        "transform": contract.transform,
        "refit_every": contract.validation.refit_every,
    }
    comparison = {
        "locked_transform": contract.transform,
        "locked_split_hash": split.split_hash,
        "locked_mean_order": [mean_candidate.p, mean_candidate.q],
        "locked_forecast_origin_row_ids": [row.forecast_origin_row_id for row in rows],
        "locked_target_row_ids": list(split.validation_row_ids),
        "locked_refit_every": contract.validation.refit_every,
        "selection_repeated_during_validation": False,
        "comparison_forecast_origin_row_ids": [
            row.forecast_origin_row_id for row in comparable_main
        ],
        "comparison_target_row_ids": [row.target_row_id for row in comparable_main],
        "comparison_validation_n": len(comparable_pairs),
        "arma_garch": comparison_main_metrics.to_dict(),
        "arma_only": comparison_baseline_metrics.to_dict(),
        "runtime_seconds": {
            "arma_garch": main_runtime_seconds,
            "arma_only": baseline_runtime_seconds,
        },
        "model_complexity": {
            "arma_garch_parameter_count": (
                mean_candidate.parameter_count + variance_candidate.parameter_count
                if strategy == "sequential_arma_garch"
                else variance_candidate.parameter_count
            ),
            "arma_only_parameter_count": (
                mean_candidate.parameter_count
                + 1
                + len(build_distribution(variance_candidate.distribution).parameter_names())
            ),
        },
        "convergence_stability": {
            "arma_garch_failed_origins": (
                metrics.validation_n - metrics.successful_forecast_n
            ),
            "arma_only_failed_origins": (
                baseline_metrics.validation_n
                - baseline_metrics.successful_forecast_n
            ),
        },
        "residual_arch_comparison_available": False,
        "information_criteria_compared_across_strategies": False,
    }
    return RollingValidationResult(
        rows=tuple(rows),
        metrics=metrics,
        frozen_spec=frozen_spec,
        comparison=comparison,
        warnings=tuple(dict.fromkeys(all_warnings)),
    )


def forecast_next_observation(
    transformed_view: pd.DataFrame,
    contract: ArmaGarchAnalysisContract,
    *,
    mean_candidate: ArmaCandidateResult,
    variance_candidate: VarianceCandidateResult,
    next_timestamp: str | None,
    checkpoint: Callable[[], None] | None = None,
) -> NextObservationForecast:
    """Refit one frozen specification on all available rows and forecast once."""

    required = {
        ROW_ID_COLUMN,
        PARSED_TIME_COLUMN,
        PARSED_VALUE_COLUMN,
        TRANSFORMED_VALUE_COLUMN,
    }
    if not isinstance(transformed_view, pd.DataFrame) or not required.issubset(
        transformed_view.columns
    ):
        raise ValueError("next forecast view is missing required lineage columns")
    frame = transformed_view.copy(deep=True).reset_index(drop=True)
    if frame.empty:
        raise ValueError("next forecast requires at least one observation")
    values = frame[TRANSFORMED_VALUE_COLUMN].to_numpy(dtype=float)
    levels = frame[PARSED_VALUE_COLUMN].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not np.isfinite(levels).all():
        raise ValueError("next forecast values and source levels must be finite")
    strategy = _validate_frozen_candidate_contract(
        contract, mean_candidate, variance_candidate
    )
    if checkpoint is not None:
        checkpoint()
    if strategy == "sequential_arma_garch":
        point = _sequential_point_forecast(
            values,
            mean_candidate=mean_candidate,
            variance_spec=_variance_spec(variance_candidate),
            hold_back=variance_candidate.hold_back,
            state=_SequentialState(),
            refit=True,
        )
    else:
        point = _joint_point_forecast(
            values,
            mean_candidate=mean_candidate,
            variance_spec=_variance_spec(variance_candidate),
            hold_back=variance_candidate.hold_back,
            state=_JointState(),
            refit=True,
        )
    interval_tail = (1.0 - contract.forecast.interval_level) / 2.0
    lower_z, q_z, upper_z = innovation_quantiles(
        distribution=contract.innovation_distribution,
        probabilities=(
            interval_tail,
            contract.forecast.lower_quantile,
            1.0 - interval_tail,
        ),
        fitted_parameters=point.distribution_parameters,
    )
    volatility = math.sqrt(point.variance)
    lower = point.mean + volatility * lower_z
    upper = point.mean + volatility * upper_z
    lower_quantile = point.mean + volatility * q_z
    origin = frame.iloc[-1]
    original_scale = backtransform_forecast(
        transform=contract.transform,
        last_level=float(origin[PARSED_VALUE_COLUMN]),
        point=point.mean,
        lower=lower,
        upper=upper,
        lower_quantile=lower_quantile,
    )
    frozen_spec = {
        "mean_candidate_id": mean_candidate.candidate_id,
        "mean_order": [mean_candidate.p, mean_candidate.q],
        "mean_constant": mean_candidate.constant,
        "variance_candidate_id": variance_candidate.candidate_id,
        "variance_model": variance_candidate.model,
        "variance_order": [variance_candidate.p, variance_candidate.q],
        "innovation_distribution": variance_candidate.distribution,
        "resolved_strategy": strategy,
        "hold_back": variance_candidate.hold_back,
        "transform": contract.transform,
    }
    return NextObservationForecast(
        forecast_origin_row_id=str(origin[ROW_ID_COLUMN]),
        forecast_origin_time=_time_text(origin[PARSED_TIME_COLUMN]),
        target_time=next_timestamp,
        conditional_mean=point.mean,
        conditional_variance=point.variance,
        conditional_volatility=volatility,
        lower_bound=lower,
        upper_bound=upper,
        lower_quantile=lower_quantile,
        model_scale=contract.transform,
        original_scale=original_scale,
        frozen_spec=frozen_spec,
        refit_summary=point.refit_summary,
        warning=point.warning,
    )


def calculate_forecast_metrics(
    rows: Sequence[ForecastRow], lower_quantile_probability: float
) -> ForecastMetrics:
    successful = [row for row in rows if row.fit_status == "ok"]
    if not successful:
        return ForecastMetrics(
            validation_n=len(rows),
            successful_forecast_n=0,
            mae=None,
            rmse=None,
            mean_error=None,
            interval_coverage=None,
            average_interval_width=None,
            coverage_count=0,
            coverage_interval=(None, None),
            exception_rate=None,
            exception_count=0,
            pinball_loss=None,
        )
    errors = np.asarray(
        [row.observed_value - float(row.conditional_mean) for row in successful],
        dtype=float,
    )
    covered = sum(row.interval_covered is True for row in successful)
    exceptions = sum(row.quantile_exception is True for row in successful)
    widths = np.asarray(
        [float(row.upper_bound) - float(row.lower_bound) for row in successful],
        dtype=float,
    )
    losses = []
    for row in successful:
        difference = row.observed_value - float(row.lower_quantile)
        losses.append(
            lower_quantile_probability * difference
            if difference >= 0.0
            else (lower_quantile_probability - 1.0) * difference
        )
    coverage = covered / len(successful)
    return ForecastMetrics(
        validation_n=len(rows),
        successful_forecast_n=len(successful),
        mae=float(np.mean(np.abs(errors))),
        rmse=float(math.sqrt(float(np.mean(np.square(errors))))),
        mean_error=float(np.mean(errors)),
        interval_coverage=coverage,
        average_interval_width=float(np.mean(widths)),
        coverage_count=covered,
        coverage_interval=_wilson_interval(covered, len(successful)),
        exception_rate=exceptions / len(successful),
        exception_count=exceptions,
        pinball_loss=float(np.mean(losses)),
    )


def _validate_rolling_inputs(
    frame: pd.DataFrame,
    split: FrozenTrainValidationSplit,
    contract: ArmaGarchAnalysisContract,
    mean: ArmaCandidateResult,
    variance: VarianceCandidateResult,
) -> pd.DataFrame:
    if split.contract_hash != contract.contract_hash:
        raise ValueError("split contract hash does not match the rolling contract")
    required = {
        ROW_ID_COLUMN,
        PARSED_TIME_COLUMN,
        PARSED_VALUE_COLUMN,
        TRANSFORMED_VALUE_COLUMN,
    }
    if not isinstance(frame, pd.DataFrame) or not required.issubset(frame.columns):
        raise ValueError("rolling view is missing required transformed lineage columns")
    copied = frame.copy(deep=True).reset_index(drop=True)
    expected_ids = (*split.training_row_ids, *split.validation_row_ids)
    actual_ids = tuple(copied[ROW_ID_COLUMN].astype(str))
    if actual_ids != expected_ids or split.split_index != len(split.training_row_ids):
        raise ValueError("rolling row membership does not match the frozen split")
    if dataframe_canonical_hash(copied) != split.analysis_view_hash:
        raise ValueError("rolling view hash does not match the frozen split")
    values = copied[TRANSFORMED_VALUE_COLUMN].to_numpy(dtype=float)
    levels = copied[PARSED_VALUE_COLUMN].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not np.isfinite(levels).all():
        raise ValueError("rolling values and source levels must be finite")
    _validate_frozen_candidate_contract(contract, mean, variance)
    return copied


def _validate_frozen_candidate_contract(
    contract: ArmaGarchAnalysisContract,
    mean: ArmaCandidateResult,
    variance: VarianceCandidateResult,
) -> str:
    binding = (variance.mean_candidate_id, variance.mean_order, variance.mean_constant)
    expected = (mean.candidate_id, (mean.p, mean.q), mean.constant)
    if binding != expected:
        raise ValueError("variance candidate mean binding does not match the frozen mean candidate")
    if variance.distribution != contract.innovation_distribution:
        raise ValueError("variance candidate distribution does not match the frozen contract")
    if mean.candidate_id not in {
        item.candidate_id for item in enumerate_arma_candidates(contract)
    }:
        raise ValueError("mean candidate is outside the frozen contract candidate set")
    variance_specs = enumerate_variance_candidates(contract)
    if variance.candidate_id not in {item.candidate_id for item in variance_specs}:
        raise ValueError("variance candidate is outside the frozen contract candidate set")
    expected_hold_back = max(mean.p, common_hold_back(variance_specs))
    if variance.hold_back != expected_hold_back:
        raise ValueError("variance candidate hold_back does not match the frozen search")
    if mean.failure_code is not None or not (
        mean.converged and mean.finite_parameters and mean.stationary and mean.invertible
    ):
        raise ValueError("rolling validation requires an eligible mean candidate")
    if variance.failure_code is not None or not (
        variance.converged and variance.parameters_valid
    ):
        raise ValueError("rolling validation requires an eligible variance candidate")
    resolved = resolve_estimation_strategy(contract.estimation_strategy, mean_q=mean.q)
    expected_strategy = "joint" if resolved == "joint_ar_garch" else "sequential"
    if variance.estimation_strategy != expected_strategy:
        raise ValueError("variance candidate strategy does not match the rolling strategy")
    return resolved


def _sequential_point_forecast(
    history: np.ndarray,
    *,
    mean_candidate: ArmaCandidateResult,
    variance_spec: VarianceCandidateSpec,
    hold_back: int,
    state: _SequentialState,
    refit: bool,
) -> _PointForecast:
    mean_model = ARIMA(
        history,
        order=(mean_candidate.p, 0, mean_candidate.q),
        trend="c" if mean_candidate.constant else "n",
    )
    captured: list[str] = []
    with runtime_warnings.catch_warnings(record=True) as caught:
        runtime_warnings.simplefilter("always")
        mean_fit = (
            mean_model.fit()
            if refit or state.mean_parameters is None
            else mean_model.filter(state.mean_parameters)
        )
    captured.extend(str(item.message) for item in caught)
    state.mean_parameters = np.asarray(mean_fit.params, dtype=float).copy()
    residuals = np.asarray(mean_fit.resid, dtype=float)
    if not np.isfinite(residuals).all():
        raise ValueError("ARMA residual update produced non-finite values")
    variance_model = ZeroMean(
        residuals,
        hold_back=hold_back,
        volatility=build_volatility_process(variance_spec),
        distribution=build_distribution(variance_spec.distribution),
        rescale=False,
    )
    with runtime_warnings.catch_warnings(record=True) as caught:
        runtime_warnings.simplefilter("always")
        variance_fit = (
            variance_model.fit(disp="off", show_warning=False)
            if refit or state.variance_parameters is None
            else variance_model.fix(state.variance_parameters)
        )
        variance_forecast = variance_fit.forecast(horizon=1, reindex=False)
    captured.extend(str(item.message) for item in caught)
    state.variance_parameters = np.asarray(variance_fit.params, dtype=float).copy()
    return _point_payload(
        mean=float(np.asarray(mean_fit.forecast(1), dtype=float)[0]),
        variance=float(variance_forecast.variance.values[-1, 0]),
        fitted_parameters=variance_fit.params,
        distribution=variance_spec.distribution,
        warnings=captured,
        refit_summary={
            "fit_scope": "all_available_observations",
            "nobs": len(history),
            "effective_sample": max(0, len(history) - hold_back),
            "converged": bool(
                getattr(mean_fit, "mle_retvals", {}).get("converged", True)
            )
            and int(getattr(variance_fit, "convergence_flag", 0)) == 0,
            "finite_parameters": bool(
                np.isfinite(np.asarray(mean_fit.params, dtype=float)).all()
                and np.isfinite(np.asarray(variance_fit.params, dtype=float)).all()
            ),
            "parameters": {
                "mean": {
                    str(name): float(value)
                    for name, value in zip(mean_fit.param_names, mean_fit.params, strict=True)
                },
                "variance": {
                    str(name): float(value) for name, value in variance_fit.params.items()
                },
            },
            "convergence_details": {
                "mean": _statsmodels_convergence_summary(mean_fit),
                "variance_flag": int(getattr(variance_fit, "convergence_flag", 0)),
            },
            "fit_statistics": {
                "mean_log_likelihood": float(mean_fit.llf),
                "mean_aic": float(mean_fit.aic),
                "mean_bic": float(mean_fit.bic),
                "variance_log_likelihood": float(variance_fit.loglikelihood),
                "variance_aic": float(variance_fit.aic),
                "variance_bic": float(variance_fit.bic),
            },
        },
    )


def _statsmodels_convergence_summary(fitted: object) -> dict[str, object]:
    details = getattr(fitted, "mle_retvals", {})
    if not isinstance(details, Mapping):
        return {"converged": True}
    summary: dict[str, object] = {"converged": bool(details.get("converged", True))}
    for source_key, target_key in (("warnflag", "warning_flag"), ("iterations", "iterations")):
        value = details.get(source_key)
        if isinstance(value, (int, np.integer)):
            summary[target_key] = int(value)
    return summary


def _joint_point_forecast(
    history: np.ndarray,
    *,
    mean_candidate: ArmaCandidateResult,
    variance_spec: VarianceCandidateSpec,
    hold_back: int,
    state: _JointState,
    refit: bool,
) -> _PointForecast:
    kwargs = {
        "hold_back": hold_back,
        "volatility": build_volatility_process(variance_spec),
        "distribution": build_distribution(variance_spec.distribution),
        "rescale": False,
    }
    if mean_candidate.p > 0:
        model = ARX(
            history,
            lags=mean_candidate.p,
            constant=mean_candidate.constant,
            **kwargs,
        )
    elif mean_candidate.constant:
        model = ConstantMean(history, **kwargs)
    else:
        model = ZeroMean(history, **kwargs)
    captured: list[str] = []
    with runtime_warnings.catch_warnings(record=True) as caught:
        runtime_warnings.simplefilter("always")
        fitted = (
            model.fit(disp="off", show_warning=False)
            if refit or state.parameters is None
            else model.fix(state.parameters)
        )
        forecast = fitted.forecast(horizon=1, reindex=False)
    captured.extend(str(item.message) for item in caught)
    state.parameters = np.asarray(fitted.params, dtype=float).copy()
    return _point_payload(
        mean=float(forecast.mean.values[-1, 0]),
        variance=float(forecast.variance.values[-1, 0]),
        fitted_parameters=fitted.params,
        distribution=variance_spec.distribution,
        warnings=captured,
        refit_summary={
            "fit_scope": "all_available_observations",
            "nobs": len(history),
            "effective_sample": max(0, len(history) - hold_back),
            "converged": int(getattr(fitted, "convergence_flag", 0)) == 0,
            "finite_parameters": bool(
                np.isfinite(np.asarray(fitted.params, dtype=float)).all()
            ),
            "parameters": {
                str(name): float(value) for name, value in fitted.params.items()
            },
            "convergence_details": {
                "optimization_flag": int(getattr(fitted, "convergence_flag", 0)),
                "optimization_message": str(
                    getattr(getattr(fitted, "optimization_result", None), "message", "")
                ),
            },
            "fit_statistics": {
                "log_likelihood": float(fitted.loglikelihood),
                "aic": float(fitted.aic),
                "bic": float(fitted.bic),
            },
        },
    )


def _point_payload(
    *,
    mean: float,
    variance: float,
    fitted_parameters: object,
    distribution: str,
    warnings: Sequence[str],
    refit_summary: Mapping[str, object],
) -> _PointForecast:
    if not math.isfinite(mean) or not math.isfinite(variance) or variance <= 0.0:
        raise ValueError("one-step forecast mean and variance must be finite with positive variance")
    names = build_distribution(distribution).parameter_names()
    parameters = {
        name: float(fitted_parameters[name])
        for name in names
    }
    if not all(math.isfinite(value) for value in parameters.values()):
        raise ValueError("innovation distribution parameters must be finite")
    return _PointForecast(
        mean=mean,
        variance=variance,
        distribution_parameters=parameters,
        refit_summary=refit_summary,
        warning="; ".join(dict.fromkeys(warnings)) or None,
    )


def _build_row(
    origin: pd.Series,
    target: pd.Series,
    *,
    observed: float,
    point: _PointForecast,
    contract: ArmaGarchAnalysisContract,
    fit_method: FitMethod,
) -> ForecastRow:
    interval_tail = (1.0 - contract.forecast.interval_level) / 2.0
    lower_z, q_z, upper_z = innovation_quantiles(
        distribution=contract.innovation_distribution,
        probabilities=(interval_tail, contract.forecast.lower_quantile, 1.0 - interval_tail),
        fitted_parameters=point.distribution_parameters,
    )
    volatility = math.sqrt(point.variance)
    lower = point.mean + volatility * lower_z
    upper = point.mean + volatility * upper_z
    q_value = point.mean + volatility * q_z
    original_scale = backtransform_forecast(
        transform=contract.transform,
        last_level=float(origin[PARSED_VALUE_COLUMN]),
        point=point.mean,
        lower=lower,
        upper=upper,
        lower_quantile=q_value,
    )
    original_scale["observed_value"] = float(target[PARSED_VALUE_COLUMN])
    return ForecastRow(
        forecast_origin_row_id=str(origin[ROW_ID_COLUMN]),
        forecast_origin_time=_time_text(origin[PARSED_TIME_COLUMN]),
        target_row_id=str(target[ROW_ID_COLUMN]),
        target_time=_time_text(target[PARSED_TIME_COLUMN]),
        observed_value=observed,
        conditional_mean=point.mean,
        conditional_variance=point.variance,
        conditional_volatility=volatility,
        lower_bound=lower,
        upper_bound=upper,
        lower_quantile=q_value,
        interval_covered=lower <= observed <= upper,
        quantile_exception=observed < q_value,
        model_scale=contract.transform,
        original_scale=original_scale,
        fit_status="ok",
        fit_method=fit_method,
        warning=point.warning,
    )


def _failed_row(
    origin: pd.Series,
    target: pd.Series,
    *,
    observed: float,
    contract: ArmaGarchAnalysisContract,
    fit_method: FitMethod,
    warning: str,
) -> ForecastRow:
    return ForecastRow(
        forecast_origin_row_id=str(origin[ROW_ID_COLUMN]),
        forecast_origin_time=_time_text(origin[PARSED_TIME_COLUMN]),
        target_row_id=str(target[ROW_ID_COLUMN]),
        target_time=_time_text(target[PARSED_TIME_COLUMN]),
        observed_value=observed,
        conditional_mean=None,
        conditional_variance=None,
        conditional_volatility=None,
        lower_bound=None,
        upper_bound=None,
        lower_quantile=None,
        interval_covered=None,
        quantile_exception=None,
        model_scale=contract.transform,
        original_scale={
            "transform": contract.transform,
            "observed_value": float(target[PARSED_VALUE_COLUMN]),
            "variance_available": False,
        },
        fit_status="failed",
        fit_method=fit_method,
        warning=warning,
    )


def _variance_spec(candidate: VarianceCandidateResult) -> VarianceCandidateSpec:
    return VarianceCandidateSpec.create(
        model=candidate.model,
        p=candidate.p,
        q=candidate.q,
        distribution=candidate.distribution,
    )


def _state_empty(state: _SequentialState | _JointState) -> bool:
    if isinstance(state, _JointState):
        return state.parameters is None
    return state.mean_parameters is None or state.variance_parameters is None


def _wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total <= 0:
        raise ValueError("Wilson interval requires a positive sample size")
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = (proportion + z * z / (2.0 * total)) / denominator
    spread = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return max(0.0, centre - spread), min(1.0, centre + spread)


def _time_text(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


__all__ = [
    "ForecastMetrics",
    "ForecastRow",
    "NextObservationForecast",
    "RollingValidationResult",
    "backtransform_forecast",
    "calculate_forecast_metrics",
    "forecast_next_observation",
    "innovation_quantiles",
    "run_rolling_validation",
]
