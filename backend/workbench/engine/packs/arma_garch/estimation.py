"""Explicit sequential ARMA-GARCH and joint AR-GARCH estimation semantics."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal
import warnings as runtime_warnings

import numpy as np
from arch.univariate import ARX, ConstantMean, ZeroMean

from workbench.contracts.common.envelope import freeze_json, thaw_json
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.arma import ArmaCandidateResult
from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError, diagnostic
from workbench.engine.packs.arma_garch.statistics import modelling_warnings
from workbench.engine.packs.arma_garch.volatility import (
    PersistenceResult,
    VarianceCandidateResult,
    VarianceCandidateSpec,
    build_distribution,
    build_volatility_process,
    calculate_persistence,
    convergence_details,
    finite_or_none,
    finite_parameters,
    fit_variance_candidate,
    json_finite_series,
    validate_variance_parameters,
)


ResolvedStrategy = Literal["sequential_arma_garch", "joint_ar_garch"]


@dataclass(frozen=True)
class SequentialArmaGarchResult:
    mean_order: tuple[int, int]
    variance_order: tuple[int, int]
    innovation_distribution: str
    hold_back: int
    mean_stage: Mapping[str, object]
    variance_stage: Mapping[str, object]
    conditional_series: Mapping[str, object]
    persistence: PersistenceResult
    warnings: tuple[str, ...]
    model_family: Literal["arma_garch"] = "arma_garch"
    estimation_strategy: Literal["sequential"] = "sequential"
    resolved_strategy: Literal["sequential_arma_garch"] = "sequential_arma_garch"
    joint_likelihood: Literal[False] = False

    def __post_init__(self) -> None:
        for field_name in ("mean_stage", "variance_stage", "conditional_series"):
            object.__setattr__(
                self,
                field_name,
                freeze_json(getattr(self, field_name), f"sequential_result.{field_name}"),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "display_name": (
                f"Sequential ARMA({self.mean_order[0]},{self.mean_order[1]})-"
                f"variance({self.variance_order[0]},{self.variance_order[1]}) two-stage"
            ),
            "model_family": self.model_family,
            "mean_order": list(self.mean_order),
            "variance_order": list(self.variance_order),
            "estimation_strategy": self.estimation_strategy,
            "resolved_strategy": self.resolved_strategy,
            "mean_backend": "statsmodels_arima",
            "variance_backend": "arch",
            "innovation_distribution": self.innovation_distribution,
            "joint_likelihood": self.joint_likelihood,
            "hold_back": self.hold_back,
            "mean_stage": thaw_json(self.mean_stage),
            "variance_stage": thaw_json(self.variance_stage),
            "conditional_series": thaw_json(self.conditional_series),
            "persistence": persistence_payload(self.persistence),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class JointArGarchResult:
    mean_order: tuple[int, Literal[0]]
    variance_order: tuple[int, int]
    innovation_distribution: str
    hold_back: int
    nobs: int
    converged: bool
    convergence_details: Mapping[str, object]
    parameters: Mapping[str, float]
    parameter_constraints: tuple[Mapping[str, object], ...]
    log_likelihood: float
    aic: float
    bic: float
    conditional_series: Mapping[str, object]
    persistence: PersistenceResult
    warnings: tuple[str, ...]
    model_family: Literal["ar_garch"] = "ar_garch"
    estimation_strategy: Literal["joint"] = "joint"
    resolved_strategy: Literal["joint_ar_garch"] = "joint_ar_garch"
    joint_likelihood: Literal[True] = True
    backend: Literal["arch"] = "arch"

    def __post_init__(self) -> None:
        for field_name in (
            "convergence_details",
            "parameters",
            "parameter_constraints",
            "conditional_series",
        ):
            object.__setattr__(
                self,
                field_name,
                freeze_json(getattr(self, field_name), f"joint_result.{field_name}"),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "display_name": (
                f"Joint AR({self.mean_order[0]})-"
                f"variance({self.variance_order[0]},{self.variance_order[1]})"
            ),
            "model_family": self.model_family,
            "mean_order": list(self.mean_order),
            "variance_order": list(self.variance_order),
            "estimation_strategy": self.estimation_strategy,
            "resolved_strategy": self.resolved_strategy,
            "backend": self.backend,
            "innovation_distribution": self.innovation_distribution,
            "joint_likelihood": self.joint_likelihood,
            "hold_back": self.hold_back,
            "nobs": self.nobs,
            "converged": self.converged,
            "convergence_details": thaw_json(self.convergence_details),
            "parameters": thaw_json(self.parameters),
            "parameter_constraints": thaw_json(self.parameter_constraints),
            "log_likelihood": self.log_likelihood,
            "aic": self.aic,
            "bic": self.bic,
            "conditional_series": thaw_json(self.conditional_series),
            "persistence": persistence_payload(self.persistence),
            "warnings": list(self.warnings),
        }


def resolve_estimation_strategy(
    requested_strategy: str,
    *,
    mean_q: int,
) -> ResolvedStrategy:
    if mean_q < 0:
        raise ValueError("mean_q cannot be negative")
    if requested_strategy == "auto":
        return "joint_ar_garch" if mean_q == 0 else "sequential_arma_garch"
    if requested_strategy == "sequential":
        return "sequential_arma_garch"
    if requested_strategy == "joint":
        if mean_q > 0:
            raise _unsupported_joint_error(mean_q)
        return "joint_ar_garch"
    raise ValueError(f"unsupported estimation strategy: {requested_strategy}")


def estimate_arma_garch(
    values: np.ndarray,
    contract: ArmaGarchAnalysisContract,
    *,
    mean_candidate: ArmaCandidateResult,
    variance_candidate: VarianceCandidateResult,
    frozen_hold_back: int,
    checkpoint: Callable[[], None] | None = None,
) -> SequentialArmaGarchResult | JointArGarchResult:
    """Execute one frozen specification without changing the selected orders."""

    if contract.estimation_strategy == "joint" and mean_candidate.q > 0:
        raise _unsupported_joint_error(mean_candidate.q)
    _validate_candidate_mean_binding(variance_candidate, mean_candidate)
    resolved = resolve_estimation_strategy(
        contract.estimation_strategy,
        mean_q=mean_candidate.q,
    )
    expected_candidate_strategy = (
        "sequential" if resolved == "sequential_arma_garch" else "joint"
    )
    if (
        variance_candidate.estimation_strategy != expected_candidate_strategy
        or variance_candidate.joint_likelihood
        != (expected_candidate_strategy == "joint")
    ):
        raise ValueError("variance candidate strategy does not match final estimation strategy")
    if variance_candidate.failure_code is not None:
        raise ValueError("final estimation requires an eligible variance candidate")
    if type(frozen_hold_back) is not int or frozen_hold_back < 0:
        raise ValueError("frozen_hold_back must be a non-negative integer")
    if variance_candidate.hold_back != frozen_hold_back:
        raise ValueError("frozen_hold_back must match the selected variance candidate")
    variance_spec = VarianceCandidateSpec.create(
        model=variance_candidate.model,
        p=variance_candidate.p,
        q=variance_candidate.q,
        distribution=variance_candidate.distribution,
    )
    if checkpoint is not None:
        checkpoint()
    if resolved == "sequential_arma_garch":
        return fit_sequential_arma_garch(
            values,
            mean_candidate,
            variance_spec,
            hold_back=frozen_hold_back,
            time_index_semantics=contract.time_index_semantics,
        )
    return fit_joint_ar_garch(
        values,
        mean_p=mean_candidate.p,
        include_constant=mean_candidate.constant,
        variance_spec=variance_spec,
        hold_back=frozen_hold_back,
        time_index_semantics=contract.time_index_semantics,
    )


def fit_sequential_arma_garch(
    values: np.ndarray,
    mean_candidate: ArmaCandidateResult,
    variance_spec: VarianceCandidateSpec,
    *,
    time_index_semantics: str,
    hold_back: int,
) -> SequentialArmaGarchResult:
    """Fit a zero-mean variance stage to frozen statsmodels ARMA residuals."""

    series = _finite_series(values)
    if not _eligible_mean_candidate(mean_candidate):
        raise ValueError("sequential estimation requires an eligible fitted ARMA candidate")
    residuals = np.asarray(mean_candidate.residuals, dtype=float)
    if len(residuals) != len(series) or not np.isfinite(residuals).all():
        raise ValueError("ARMA residuals must be finite and aligned to the input series")
    _validate_frozen_hold_back(
        hold_back,
        len(series),
        minimum=max(mean_candidate.p, variance_spec.p, variance_spec.q),
    )
    variance = fit_variance_candidate(
        residuals,
        variance_spec,
        hold_back=hold_back,
    )
    if variance.failure_code is not None:
        raise ValueError(
            "sequential variance stage failed: "
            f"{variance.failure_code}: {', '.join(variance.warnings)}"
        )
    aligned_series = _aligned_json_series(
        {
            "mean": series - residuals,
            "residual": residuals,
            "variance": variance.conditional_variance,
            "volatility": variance.conditional_volatility,
            "standardized_residual": variance.standardized_residuals,
            "squared_standardized_residual": variance.squared_standardized_residuals,
        },
        hold_back=hold_back,
    )
    conditional_series = {
        "alignment": {
            "total_observations": len(series),
            "hold_back": variance.hold_back,
            "effective_sample": variance.effective_sample,
        },
        **aligned_series,
    }
    persistence = calculate_persistence(
        model=variance.model,
        p=variance.p,
        q=variance.q,
        parameters=variance.parameters,
        time_index_semantics=time_index_semantics,
    )
    return SequentialArmaGarchResult(
        mean_order=(mean_candidate.p, mean_candidate.q),
        variance_order=(variance.p, variance.q),
        innovation_distribution=variance.distribution,
        hold_back=variance.hold_back,
        mean_stage={
            "backend": "statsmodels_arima",
            "candidate_id": mean_candidate.candidate_id,
            "nobs": mean_candidate.nobs,
            "effective_sample": mean_candidate.effective_sample,
            "parameter_count": mean_candidate.parameter_count,
            "log_likelihood": mean_candidate.log_likelihood,
            "aic": mean_candidate.aic,
            "aicc": mean_candidate.aicc,
            "bic": mean_candidate.bic,
        },
        variance_stage={
            "backend": "arch",
            "candidate_id": variance.candidate_id,
            "nobs": variance.nobs,
            "hold_back": variance.hold_back,
            "effective_sample": variance.effective_sample,
            "parameter_count": variance.parameter_count,
            "log_likelihood": variance.log_likelihood,
            "aic": variance.aic,
            "aicc": variance.aicc,
            "bic": variance.bic,
            "parameters": variance.parameters,
            "parameter_constraints": variance.parameter_constraints,
            "standardized_residual_diagnostics": (
                variance.standardized_residual_diagnostics
            ),
            "squared_standardized_residual_diagnostics": (
                variance.squared_standardized_residual_diagnostics
            ),
        },
        conditional_series=conditional_series,
        persistence=persistence,
        warnings=tuple((*variance.warnings, *persistence.warnings)),
    )


def fit_joint_ar_garch(
    values: np.ndarray,
    *,
    mean_p: int,
    include_constant: bool,
    variance_spec: VarianceCandidateSpec,
    hold_back: int,
    time_index_semantics: str,
) -> JointArGarchResult:
    """Jointly estimate an AR(q=0) mean and variance model using ``arch``."""

    series = _finite_series(values)
    if type(mean_p) is not int or mean_p < 0:
        raise ValueError("mean_p must be a non-negative integer")
    _validate_frozen_hold_back(
        hold_back,
        len(series),
        minimum=max(mean_p, variance_spec.p, variance_spec.q),
    )
    volatility = build_volatility_process(variance_spec)
    distribution = build_distribution(variance_spec.distribution)
    if mean_p > 0:
        model = ARX(
            series,
            lags=mean_p,
            constant=include_constant,
            hold_back=hold_back,
            volatility=volatility,
            distribution=distribution,
            rescale=False,
        )
    elif include_constant:
        model = ConstantMean(
            series,
            hold_back=hold_back,
            volatility=volatility,
            distribution=distribution,
            rescale=False,
        )
    else:
        model = ZeroMean(
            series,
            hold_back=hold_back,
            volatility=volatility,
            distribution=distribution,
            rescale=False,
        )

    captured: list[str] = []
    with runtime_warnings.catch_warnings(record=True) as caught:
        runtime_warnings.simplefilter("always")
        fitted = model.fit(disp="off", show_warning=False)
    captured.extend(modelling_warnings(caught))
    converged = fitted.convergence_flag == 0
    parameters = finite_parameters(fitted.params)
    validation = validate_variance_parameters(
        model=variance_spec.model,
        p=variance_spec.p,
        q=variance_spec.q,
        distribution=variance_spec.distribution,
        parameters=parameters,
    )
    if not converged:
        raise ValueError("joint AR-GARCH optimization did not converge")
    if not validation.valid:
        raise ValueError(
            "joint AR-GARCH variance parameters are invalid: "
            + (validation.failure_code or ", ".join(validation.failure_reasons))
        )

    log_likelihood = _required_finite(fitted.loglikelihood, "log_likelihood")
    aic = _required_finite(fitted.aic, "aic")
    bic = _required_finite(fitted.bic, "bic")
    residuals = np.asarray(fitted.resid, dtype=float)
    conditional_volatility = np.asarray(fitted.conditional_volatility, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        conditional_mean = series - residuals
        conditional_variance = np.square(conditional_volatility)
        standardized = residuals / conditional_volatility
        squared_standardized = np.square(standardized)
    aligned_series = _aligned_json_series(
        {
            "mean": conditional_mean,
            "residual": residuals,
            "variance": conditional_variance,
            "volatility": conditional_volatility,
            "standardized_residual": standardized,
            "squared_standardized_residual": squared_standardized,
        },
        hold_back=hold_back,
    )
    conditional_series = {
        "alignment": {
            "total_observations": len(series),
            "hold_back": hold_back,
            "effective_sample": int(fitted.nobs),
        },
        **aligned_series,
    }
    persistence = calculate_persistence(
        model=variance_spec.model,
        p=variance_spec.p,
        q=variance_spec.q,
        parameters=parameters,
        time_index_semantics=time_index_semantics,
    )
    return JointArGarchResult(
        mean_order=(mean_p, 0),
        variance_order=(variance_spec.p, variance_spec.q),
        innovation_distribution=variance_spec.distribution,
        hold_back=hold_back,
        nobs=int(fitted.nobs),
        converged=True,
        convergence_details=convergence_details(fitted),
        parameters=parameters,
        parameter_constraints=validation.constraints,
        log_likelihood=log_likelihood,
        aic=aic,
        bic=bic,
        conditional_series=conditional_series,
        persistence=persistence,
        warnings=tuple((*captured, *persistence.warnings)),
    )


def persistence_payload(value: PersistenceResult) -> dict[str, object]:
    return {
        "persistence": value.persistence,
        "half_life": value.half_life,
        "half_life_unit": value.half_life_unit,
        "warnings": list(value.warnings),
    }


def _eligible_mean_candidate(candidate: ArmaCandidateResult) -> bool:
    return (
        candidate.failure_code is None
        and candidate.converged
        and candidate.stationary
        and candidate.invertible
        and candidate.finite_parameters
        and candidate.aicc is not None
    )


def _finite_series(values: np.ndarray) -> np.ndarray:
    series = np.asarray(values, dtype=float)
    if series.ndim != 1 or len(series) == 0 or not np.isfinite(series).all():
        raise ValueError("estimation input must be a non-empty finite one-dimensional series")
    return series


def _validate_frozen_hold_back(
    hold_back: int,
    total_observations: int,
    *,
    minimum: int,
) -> None:
    if type(hold_back) is not int or hold_back < minimum:
        raise ValueError(f"frozen hold_back must be an integer >= {minimum}")
    if hold_back >= total_observations:
        raise ValueError("frozen hold_back must leave at least one effective observation")


def _validate_candidate_mean_binding(
    variance_candidate: VarianceCandidateResult,
    mean_candidate: ArmaCandidateResult,
) -> None:
    if (
        variance_candidate.mean_candidate_id is None
        or variance_candidate.mean_order is None
        or variance_candidate.mean_constant is None
    ):
        raise ValueError("final estimation requires a bound mean specification")
    expected = (
        mean_candidate.candidate_id,
        (mean_candidate.p, mean_candidate.q),
        mean_candidate.constant,
    )
    actual = (
        variance_candidate.mean_candidate_id,
        variance_candidate.mean_order,
        variance_candidate.mean_constant,
    )
    if actual != expected:
        raise ValueError("variance candidate mean binding does not match mean_candidate")


def _aligned_json_series(
    series_by_name: Mapping[str, object],
    *,
    hold_back: int,
) -> dict[str, tuple[float | None, ...]]:
    payloads = {
        name: list(json_finite_series(values))
        for name, values in series_by_name.items()
    }
    lengths = {len(payload) for payload in payloads.values()}
    if len(lengths) != 1:
        raise ValueError("conditional series must have equal lengths")
    total = next(iter(lengths), 0)
    common_mask = [
        index < hold_back
        or any(payload[index] is None for payload in payloads.values())
        for index in range(total)
    ]
    for payload in payloads.values():
        for index, masked in enumerate(common_mask):
            if masked:
                payload[index] = None
    return {name: tuple(payload) for name, payload in payloads.items()}


def _required_finite(value: object, name: str) -> float:
    numeric = finite_or_none(value)
    if numeric is None:
        raise ValueError(f"joint AR-GARCH produced non-finite {name}")
    return numeric


def _unsupported_joint_error(mean_q: int) -> ArmaGarchInputError:
    return ArmaGarchInputError(
        diagnostic(
            "UNSUPPORTED_JOINT_ARMA_GARCH",
            "v1.8 cannot jointly estimate a mean model containing MA terms.",
            evidence={"arma_q": mean_q, "requested_strategy": "joint"},
            impact="当前公共后端不能联合估计包含 MA 项的 ARMA-GARCH",
            recommended_actions=(
                {
                    "operation": "model.rerun",
                    "patch": {"estimation_strategy": "sequential"},
                },
                {
                    "operation": "model.rerun",
                    "patch": {"arma": {"q": 0}, "estimation_strategy": "joint"},
                },
            ),
        )
    )


__all__ = [
    "JointArGarchResult",
    "SequentialArmaGarchResult",
    "estimate_arma_garch",
    "fit_joint_ar_garch",
    "fit_sequential_arma_garch",
    "resolve_estimation_strategy",
]
