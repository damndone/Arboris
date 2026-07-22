"""Bounded ``arch`` variance candidates for frozen ARMA residuals.

This module deliberately owns only the pre-validation variance search.  Rolling
validation and final model choice belong to later slices.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math
from time import perf_counter
from typing import Literal
import warnings as runtime_warnings

import numpy as np
from arch.univariate import (
    ARCH,
    ARX,
    GARCH,
    ConstantMean,
    ConstantVariance,
    Normal,
    StudentsT,
    ZeroMean,
)

from workbench.contracts.common.envelope import freeze_json, thaw_json
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.errors import ArmaGarchDiagnostic, diagnostic
from workbench.engine.packs.arma_garch.statistics import (
    calculate_aicc,
    ljung_box_results,
    modelling_warnings,
)


VarianceModel = Literal["constant_variance", "arch", "garch"]
InnovationDistribution = Literal["normal", "student_t"]
TimeIndexSemantics = Literal[
    "regular_calendar",
    "business_or_trading_observations",
    "observation_order",
]


@dataclass(frozen=True)
class VarianceCandidateSpec:
    candidate_id: str
    model: VarianceModel
    p: int
    q: int
    distribution: InnovationDistribution
    display_name: str

    @classmethod
    def create(
        cls,
        *,
        model: str,
        p: int,
        q: int,
        distribution: str,
    ) -> "VarianceCandidateSpec":
        if model not in {"constant_variance", "arch", "garch"}:
            raise ValueError(f"unsupported variance model: {model}")
        if distribution not in {"normal", "student_t"}:
            raise ValueError(f"unsupported innovation distribution: {distribution}")
        if model == "constant_variance":
            if (p, q) != (0, 0):
                raise ValueError("constant_variance requires p=0 and q=0")
            display_name = "Constant Variance"
            order_token = "constant"
        elif model == "arch":
            if p < 1 or q != 0:
                raise ValueError("ARCH requires p>=1 and q=0")
            display_name = f"ARCH({p})"
            order_token = f"arch-p{p}"
        else:
            if p < 1 or q < 1:
                raise ValueError("GARCH requires p>=1 and q>=1")
            display_name = f"GARCH({p},{q})"
            order_token = f"garch-p{p}-q{q}"
        distribution_token = "normal" if distribution == "normal" else "student-t"
        return cls(
            candidate_id=f"variance-{order_token}-{distribution_token}",
            model=model,
            p=p,
            q=q,
            distribution=distribution,
            display_name=display_name,
        )


@dataclass(frozen=True)
class ParameterValidation:
    valid: bool
    constraints: tuple[Mapping[str, object], ...]
    failure_reasons: tuple[str, ...]
    failure_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "constraints",
            freeze_json(self.constraints, "variance_parameter_validation.constraints"),
        )


@dataclass(frozen=True)
class PersistenceResult:
    persistence: float | None
    half_life: float | None
    half_life_unit: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class VarianceCandidateResult:
    candidate_id: str
    display_name: str
    model: VarianceModel
    p: int
    q: int
    distribution: InnovationDistribution
    estimation_strategy: Literal["sequential", "joint"]
    joint_likelihood: bool
    mean_candidate_id: str | None
    mean_order: tuple[int, int] | None
    mean_constant: bool | None
    nobs: int
    hold_back: int
    effective_sample: int
    converged: bool
    convergence_details: Mapping[str, object]
    parameters: Mapping[str, float]
    parameter_constraints: tuple[Mapping[str, object], ...]
    parameters_valid: bool
    log_likelihood: float | None
    parameter_count: int
    aic: float | None
    aicc: float | None
    bic: float | None
    standardized_residual_diagnostics: tuple[Mapping[str, object], ...]
    squared_standardized_residual_diagnostics: tuple[Mapping[str, object], ...]
    conditional_variance: tuple[float | None, ...]
    conditional_volatility: tuple[float | None, ...]
    standardized_residuals: tuple[float | None, ...]
    squared_standardized_residuals: tuple[float | None, ...]
    warnings: tuple[str, ...]
    failure_code: str | None
    elapsed_seconds: float

    def __post_init__(self) -> None:
        mean_candidate_id, mean_order, mean_constant = _validated_mean_binding(
            mean_candidate_id=self.mean_candidate_id,
            mean_order=self.mean_order,
            mean_constant=self.mean_constant,
        )
        object.__setattr__(self, "mean_candidate_id", mean_candidate_id)
        object.__setattr__(self, "mean_order", mean_order)
        object.__setattr__(self, "mean_constant", mean_constant)
        for field_name in (
            "convergence_details",
            "parameters",
            "parameter_constraints",
            "standardized_residual_diagnostics",
            "squared_standardized_residual_diagnostics",
            "conditional_variance",
            "conditional_volatility",
            "standardized_residuals",
            "squared_standardized_residuals",
        ):
            object.__setattr__(
                self,
                field_name,
                freeze_json(getattr(self, field_name), f"variance_candidate.{field_name}"),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "display_name": self.display_name,
            "variance_model": self.model,
            "p": self.p,
            "q": self.q,
            "distribution": self.distribution,
            "estimation_strategy": self.estimation_strategy,
            "joint_likelihood": self.joint_likelihood,
            "mean_binding_status": (
                "bound" if self.mean_candidate_id is not None else "unbound"
            ),
            "mean_candidate_id": self.mean_candidate_id,
            "mean_order": None if self.mean_order is None else list(self.mean_order),
            "mean_constant": self.mean_constant,
            "nobs": self.nobs,
            "hold_back": self.hold_back,
            "effective_sample": self.effective_sample,
            "converged": self.converged,
            "convergence_details": thaw_json(self.convergence_details),
            "parameters": thaw_json(self.parameters),
            "parameter_constraints": thaw_json(self.parameter_constraints),
            "parameters_valid": self.parameters_valid,
            "log_likelihood": self.log_likelihood,
            "parameter_count": self.parameter_count,
            "aic": self.aic,
            "aicc": self.aicc,
            "bic": self.bic,
            "standardized_residual_diagnostics": thaw_json(
                self.standardized_residual_diagnostics
            ),
            "squared_standardized_residual_diagnostics": thaw_json(
                self.squared_standardized_residual_diagnostics
            ),
            "conditional_variance": list(self.conditional_variance),
            "conditional_volatility": list(self.conditional_volatility),
            "standardized_residuals": list(self.standardized_residuals),
            "squared_standardized_residuals": list(
                self.squared_standardized_residuals
            ),
            "warnings": list(self.warnings),
            "failure_code": self.failure_code,
            "elapsed_seconds": self.elapsed_seconds,
        }


@dataclass(frozen=True)
class VarianceSelection:
    selected_candidate_id: str | None
    shortlist_candidate_ids: tuple[str, ...]
    excluded_candidate_ids: tuple[str, ...]
    best_aicc: float | None
    delta_aicc_threshold: float
    selected_bic: float | None


@dataclass(frozen=True)
class VarianceSearchResult:
    candidates: tuple[VarianceCandidateResult, ...]
    selected_candidate_id: str | None
    shortlist_candidate_ids: tuple[str, ...]
    selection_status: Literal["provisional_pre_validation", "blocked"]
    common_hold_back: int
    blocking_diagnostic: ArmaGarchDiagnostic | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selected_candidate_id": self.selected_candidate_id,
            "shortlist_candidate_ids": list(self.shortlist_candidate_ids),
            "selection_status": self.selection_status,
            "common_hold_back": self.common_hold_back,
            "blocking_diagnostic": (
                None
                if self.blocking_diagnostic is None
                else self.blocking_diagnostic.to_dict()
            ),
        }


def enumerate_variance_candidates(
    contract: ArmaGarchAnalysisContract,
) -> tuple[VarianceCandidateSpec, ...]:
    """Return the approved bounded variance set in stable order."""

    distribution = contract.innovation_distribution
    if contract.selection_mode == "manual":
        options = contract.variance
        if options.model == "constant_variance":
            orders = (("constant_variance", 0, 0),)
        elif options.model == "arch":
            assert options.arch_p is not None
            orders = (("arch", options.arch_p, 0),)
        else:
            assert options.garch_p is not None and options.garch_q is not None
            orders = (("garch", options.garch_p, options.garch_q),)
    else:
        orders = (
            ("constant_variance", 0, 0),
            *(("arch", p, 0) for p in range(1, contract.variance.auto_arch_max_p + 1)),
            *(((("garch", 1, 1),) if contract.variance.include_garch_1_1 else ())),
        )
    return tuple(
        VarianceCandidateSpec.create(
            model=model,
            p=p,
            q=q,
            distribution=distribution,
        )
        for model, p, q in orders
    )


def common_hold_back(candidates: Sequence[VarianceCandidateSpec]) -> int:
    """Use one conservative burn-in across every comparable candidate."""

    return max((max(candidate.p, candidate.q) for candidate in candidates), default=0)


def fit_variance_candidate(
    residuals: np.ndarray,
    spec: VarianceCandidateSpec,
    *,
    hold_back: int,
    mean_candidate_id: str | None = None,
    mean_order: tuple[int, int] | None = None,
    mean_constant: bool | None = None,
) -> VarianceCandidateResult:
    """Fit one zero-mean variance candidate, isolating optimizer failures."""

    binding = _validated_mean_binding(
        mean_candidate_id=mean_candidate_id,
        mean_order=mean_order,
        mean_constant=mean_constant,
    )
    started = perf_counter()
    try:
        values = _finite_one_dimensional(residuals)
        _validate_hold_back(hold_back, len(values))
        model = ZeroMean(
            values,
            hold_back=hold_back,
            volatility=build_volatility_process(spec),
            distribution=build_distribution(spec.distribution),
            rescale=False,
        )
        return _fit_configured_arch_candidate(
            model,
            spec,
            total_observations=len(values),
            hold_back=hold_back,
            estimation_strategy="sequential",
            joint_likelihood=False,
            mean_candidate_id=binding[0],
            mean_order=binding[1],
            mean_constant=binding[2],
            started=started,
        )
    except Exception as exc:
        return failed_variance_candidate(
            spec,
            total_observations=(len(residuals) if np.ndim(residuals) == 1 else 0),
            hold_back=hold_back,
            warning=f"{type(exc).__name__}: {exc}",
            elapsed_seconds=perf_counter() - started,
            estimation_strategy="sequential",
            mean_candidate_id=binding[0],
            mean_order=binding[1],
            mean_constant=binding[2],
        )


def fit_joint_variance_candidate(
    values: np.ndarray,
    spec: VarianceCandidateSpec,
    *,
    mean_p: int,
    include_constant: bool,
    hold_back: int,
    mean_candidate_id: str | None = None,
    mean_order: tuple[int, int] | None = None,
    mean_constant: bool | None = None,
) -> VarianceCandidateResult:
    """Fit one variance candidate inside a direct joint AR likelihood."""

    binding = _validated_mean_binding(
        mean_candidate_id=mean_candidate_id,
        mean_order=mean_order,
        mean_constant=mean_constant,
    )
    if binding[0] is not None and (
        binding[1] != (mean_p, 0) or binding[2] is not include_constant
    ):
        raise ValueError("joint mean binding must match the fitted AR specification")
    started = perf_counter()
    try:
        series = _finite_one_dimensional(values)
        if type(mean_p) is not int or mean_p < 0:
            raise ValueError("mean_p must be a non-negative integer")
        _validate_hold_back(
            hold_back,
            len(series),
            minimum=max(mean_p, spec.p, spec.q),
        )
        model_kwargs = {
            "hold_back": hold_back,
            "volatility": build_volatility_process(spec),
            "distribution": build_distribution(spec.distribution),
            "rescale": False,
        }
        if mean_p > 0:
            model = ARX(
                series,
                lags=mean_p,
                constant=include_constant,
                **model_kwargs,
            )
        elif include_constant:
            model = ConstantMean(series, **model_kwargs)
        else:
            model = ZeroMean(series, **model_kwargs)
        return _fit_configured_arch_candidate(
            model,
            spec,
            total_observations=len(series),
            hold_back=hold_back,
            estimation_strategy="joint",
            joint_likelihood=True,
            mean_candidate_id=binding[0],
            mean_order=binding[1],
            mean_constant=binding[2],
            started=started,
        )
    except Exception as exc:
        return failed_variance_candidate(
            spec,
            total_observations=(len(values) if np.ndim(values) == 1 else 0),
            hold_back=hold_back,
            warning=f"{type(exc).__name__}: {exc}",
            elapsed_seconds=perf_counter() - started,
            estimation_strategy="joint",
            mean_candidate_id=binding[0],
            mean_order=binding[1],
            mean_constant=binding[2],
        )


def _fit_configured_arch_candidate(
    model: object,
    spec: VarianceCandidateSpec,
    *,
    total_observations: int,
    hold_back: int,
    estimation_strategy: Literal["sequential", "joint"],
    joint_likelihood: bool,
    mean_candidate_id: str | None,
    mean_order: tuple[int, int] | None,
    mean_constant: bool | None,
    started: float,
) -> VarianceCandidateResult:
    captured: list[str] = []
    with runtime_warnings.catch_warnings(record=True) as caught:
        runtime_warnings.simplefilter("always")
        fitted = model.fit(disp="off", show_warning=False)
    captured.extend(modelling_warnings(caught))

    convergence = convergence_details(fitted)
    converged = fitted.convergence_flag == 0
    parameters = finite_parameters(fitted.params)
    validation = validate_variance_parameters(
        model=spec.model,
        p=spec.p,
        q=spec.q,
        distribution=spec.distribution,
        parameters=parameters,
    )
    if not validation.valid:
        captured.extend(validation.failure_reasons)
    nobs = int(fitted.nobs)
    parameter_count = len(parameters)
    aic = finite_or_none(fitted.aic)
    aicc = (
        calculate_aicc(aic=aic, parameter_count=parameter_count, effective_sample=nobs)
        if aic is not None
        else None
    )
    if aicc is None:
        captured.append("AICC_UNDEFINED")

    volatility = json_finite_series(fitted.conditional_volatility)
    variance = tuple(None if value is None else float(value * value) for value in volatility)
    raw_residuals = np.asarray(fitted.resid, dtype=float)
    raw_volatility = np.asarray(fitted.conditional_volatility, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        standardized = raw_residuals / raw_volatility
        squared_standardized = np.square(standardized)
    standardized_payload = json_finite_series(standardized)
    squared_payload = json_finite_series(squared_standardized)
    finite_standardized = standardized[np.isfinite(standardized)]
    finite_squared = squared_standardized[np.isfinite(squared_standardized)]
    standardized_diagnostics = ljung_box_results(finite_standardized)
    squared_diagnostics = ljung_box_results(finite_squared)
    failure_code = None
    if not converged:
        failure_code = "VOLATILITY_NOT_CONVERGED"
    elif not validation.valid:
        failure_code = validation.failure_code or "GARCH_INVALID_VARIANCE_PARAMETERS"
    elif any(
        value is None
        for value in (
            finite_or_none(fitted.loglikelihood),
            aic,
            aicc,
            finite_or_none(fitted.bic),
        )
    ):
        failure_code = "VOLATILITY_NONFINITE_FIT"
    return VarianceCandidateResult(
        candidate_id=spec.candidate_id,
        display_name=spec.display_name,
        model=spec.model,
        p=spec.p,
        q=spec.q,
        distribution=spec.distribution,
        estimation_strategy=estimation_strategy,
        joint_likelihood=joint_likelihood,
        mean_candidate_id=mean_candidate_id,
        mean_order=mean_order,
        mean_constant=mean_constant,
        nobs=nobs,
        hold_back=hold_back,
        effective_sample=nobs,
        converged=converged,
        convergence_details=convergence,
        parameters=parameters,
        parameter_constraints=validation.constraints,
        parameters_valid=validation.valid,
        log_likelihood=finite_or_none(fitted.loglikelihood),
        parameter_count=parameter_count,
        aic=aic,
        aicc=aicc,
        bic=finite_or_none(fitted.bic),
        standardized_residual_diagnostics=standardized_diagnostics,
        squared_standardized_residual_diagnostics=squared_diagnostics,
        conditional_variance=variance,
        conditional_volatility=volatility,
        standardized_residuals=standardized_payload,
        squared_standardized_residuals=squared_payload,
        warnings=tuple(captured),
        failure_code=failure_code,
        elapsed_seconds=perf_counter() - started,
    )


def failed_variance_candidate(
    spec: VarianceCandidateSpec,
    *,
    total_observations: int,
    hold_back: int,
    warning: str,
    elapsed_seconds: float = 0.0,
    estimation_strategy: Literal["sequential", "joint"] = "sequential",
    mean_candidate_id: str | None = None,
    mean_order: tuple[int, int] | None = None,
    mean_constant: bool | None = None,
) -> VarianceCandidateResult:
    safe_hold_back = max(0, hold_back)
    return VarianceCandidateResult(
        candidate_id=spec.candidate_id,
        display_name=spec.display_name,
        model=spec.model,
        p=spec.p,
        q=spec.q,
        distribution=spec.distribution,
        estimation_strategy=estimation_strategy,
        joint_likelihood=estimation_strategy == "joint",
        mean_candidate_id=mean_candidate_id,
        mean_order=mean_order,
        mean_constant=mean_constant,
        nobs=max(0, total_observations - safe_hold_back),
        hold_back=safe_hold_back,
        effective_sample=max(0, total_observations - safe_hold_back),
        converged=False,
        convergence_details={"convergence_flag": None, "status": None, "message": warning},
        parameters={},
        parameter_constraints=(),
        parameters_valid=False,
        log_likelihood=None,
        parameter_count=0,
        aic=None,
        aicc=None,
        bic=None,
        standardized_residual_diagnostics=(),
        squared_standardized_residual_diagnostics=(),
        conditional_variance=(None,) * total_observations,
        conditional_volatility=(None,) * total_observations,
        standardized_residuals=(None,) * total_observations,
        squared_standardized_residuals=(None,) * total_observations,
        warnings=(warning,),
        failure_code="VOLATILITY_FIT_FAILED",
        elapsed_seconds=elapsed_seconds,
    )


def search_variance_candidates(
    residuals: np.ndarray,
    contract: ArmaGarchAnalysisContract,
    *,
    mean_candidate_id: str,
    mean_order: tuple[int, int],
    mean_constant: bool,
    checkpoint: Callable[[], None] | None = None,
) -> VarianceSearchResult:
    """Fit the variance set once and return an explicitly provisional choice."""

    values = _finite_one_dimensional(residuals)
    binding = _validated_mean_binding(
        mean_candidate_id=mean_candidate_id,
        mean_order=mean_order,
        mean_constant=mean_constant,
    )
    assert binding[1] is not None
    specs = enumerate_variance_candidates(contract)
    hold_back = max(binding[1][0], common_hold_back(specs))
    candidates: list[VarianceCandidateResult] = []
    for spec in specs:
        if checkpoint is not None:
            checkpoint()
        try:
            candidate = fit_variance_candidate(
                values.copy(),
                spec,
                hold_back=hold_back,
                mean_candidate_id=binding[0],
                mean_order=binding[1],
                mean_constant=binding[2],
            )
        except Exception as exc:
            candidate = failed_variance_candidate(
                spec,
                total_observations=len(values),
                hold_back=hold_back,
                warning=f"{type(exc).__name__}: {exc}",
                mean_candidate_id=binding[0],
                mean_order=binding[1],
                mean_constant=binding[2],
            )
        candidates.append(candidate)
    selection = select_variance_candidate(tuple(candidates))
    blocked = selection.selected_candidate_id is None
    blocking_diagnostic = (
        no_variance_candidate_diagnostic(tuple(candidates), hold_back=hold_back)
        if blocked
        else None
    )
    return VarianceSearchResult(
        candidates=tuple(candidates),
        selected_candidate_id=selection.selected_candidate_id,
        shortlist_candidate_ids=selection.shortlist_candidate_ids,
        selection_status="blocked" if blocked else "provisional_pre_validation",
        common_hold_back=hold_back,
        blocking_diagnostic=blocking_diagnostic,
    )


def search_joint_variance_candidates(
    values: np.ndarray,
    contract: ArmaGarchAnalysisContract,
    *,
    mean_candidate_id: str,
    mean_order: tuple[int, int],
    mean_constant: bool,
    checkpoint: Callable[[], None] | None = None,
) -> VarianceSearchResult:
    """Search variance forms directly under one frozen joint AR likelihood."""

    series = _finite_one_dimensional(values)
    binding = _validated_mean_binding(
        mean_candidate_id=mean_candidate_id,
        mean_order=mean_order,
        mean_constant=mean_constant,
    )
    assert binding[1] is not None and binding[2] is not None
    if binding[1][1] != 0:
        raise ValueError("joint variance search requires mean_order q=0")
    specs = enumerate_variance_candidates(contract)
    hold_back = max(binding[1][0], common_hold_back(specs))
    candidates: list[VarianceCandidateResult] = []
    for spec in specs:
        if checkpoint is not None:
            checkpoint()
        try:
            candidate = fit_joint_variance_candidate(
                series.copy(),
                spec,
                mean_p=binding[1][0],
                include_constant=binding[2],
                hold_back=hold_back,
                mean_candidate_id=binding[0],
                mean_order=binding[1],
                mean_constant=binding[2],
            )
        except Exception as exc:
            candidate = failed_variance_candidate(
                spec,
                total_observations=len(series),
                hold_back=hold_back,
                warning=f"{type(exc).__name__}: {exc}",
                estimation_strategy="joint",
                mean_candidate_id=binding[0],
                mean_order=binding[1],
                mean_constant=binding[2],
            )
        candidates.append(candidate)
    selection = select_variance_candidate(tuple(candidates))
    blocked = selection.selected_candidate_id is None
    blocking_diagnostic = (
        no_variance_candidate_diagnostic(tuple(candidates), hold_back=hold_back)
        if blocked
        else None
    )
    return VarianceSearchResult(
        candidates=tuple(candidates),
        selected_candidate_id=selection.selected_candidate_id,
        shortlist_candidate_ids=selection.shortlist_candidate_ids,
        selection_status="blocked" if blocked else "provisional_pre_validation",
        common_hold_back=hold_back,
        blocking_diagnostic=blocking_diagnostic,
    )


def select_variance_candidate(
    candidates: Sequence[VarianceCandidateResult],
    *,
    delta_aicc_threshold: float = 2.0,
) -> VarianceSelection:
    """Apply fit/parameter gates, then AICc shortlist and parsimony evidence."""

    eligible = [candidate for candidate in candidates if candidate_eligible(candidate)]
    excluded = tuple(
        sorted(
            candidate.candidate_id
            for candidate in candidates
            if not candidate_eligible(candidate)
        )
    )
    if not eligible:
        return VarianceSelection(None, (), excluded, None, delta_aicc_threshold, None)
    best_aicc = min(float(candidate.aicc) for candidate in eligible if candidate.aicc is not None)
    shortlist = [
        candidate
        for candidate in eligible
        if candidate.aicc is not None
        and candidate.aicc <= best_aicc + delta_aicc_threshold
    ]
    selected = min(
        shortlist,
        key=lambda item: (
            variance_complexity(item),
            item.parameter_count,
            math.inf if item.bic is None else item.bic,
            float(item.aicc),
            item.candidate_id,
        ),
    )
    return VarianceSelection(
        selected_candidate_id=selected.candidate_id,
        shortlist_candidate_ids=tuple(
            item.candidate_id
            for item in sorted(
                shortlist,
                key=lambda item: (float(item.aicc), item.candidate_id),
            )
        ),
        excluded_candidate_ids=excluded,
        best_aicc=best_aicc,
        delta_aicc_threshold=delta_aicc_threshold,
        selected_bic=selected.bic,
    )


def candidate_eligible(candidate: VarianceCandidateResult) -> bool:
    return (
        candidate.failure_code is None
        and candidate.converged
        and candidate.parameters_valid
        and candidate.aicc is not None
    )


def variance_complexity(candidate: VarianceCandidateResult) -> int:
    if candidate.model == "constant_variance":
        return 0
    if candidate.model == "arch":
        return candidate.p
    return candidate.p + candidate.q


def validate_variance_parameters(
    *,
    model: str,
    p: int,
    q: int,
    distribution: str,
    parameters: Mapping[str, float],
) -> ParameterValidation:
    """Apply the public variance and innovation parameter constraints."""

    checks: list[tuple[str, str, float | None, bool]] = []
    aggregate_persistence: float | None = None
    if model == "constant_variance":
        value = _mapping_number(parameters, "sigma2")
        checks.append(("sigma2", "> 0", value, value is not None and value > 0.0))
    else:
        omega = _mapping_number(parameters, "omega")
        checks.append(("omega", "> 0", omega, omega is not None and omega > 0.0))
        alpha_values: list[float | None] = []
        for index in range(1, p + 1):
            name = f"alpha[{index}]"
            value = _mapping_number(parameters, name)
            alpha_values.append(value)
            checks.append((name, ">= 0", value, value is not None and value >= 0.0))
        beta_values: list[float | None] = []
        if model == "garch":
            for index in range(1, q + 1):
                name = f"beta[{index}]"
                value = _mapping_number(parameters, name)
                beta_values.append(value)
                checks.append((name, ">= 0", value, value is not None and value >= 0.0))
        persistence_terms = (*alpha_values, *beta_values)
        if persistence_terms and all(value is not None for value in persistence_terms):
            aggregate_persistence = sum(float(value) for value in persistence_terms)
        checks.append(
            (
                "aggregate_persistence",
                "< 1",
                aggregate_persistence,
                aggregate_persistence is not None and aggregate_persistence < 1.0,
            )
        )
    if distribution == "student_t":
        nu = _mapping_number(parameters, "nu")
        checks.append(("nu", "> 2", nu, nu is not None and nu > 2.0))

    constraints = tuple(
        {
            "parameter": name,
            "constraint": condition,
            "value": value,
            "satisfied": satisfied,
        }
        for name, condition, value, satisfied in checks
    )
    reasons = tuple(
        f"INVALID_PARAMETER:{name}:{condition}"
        for name, condition, _, satisfied in checks
        if not satisfied
    )
    nonstationary = (
        aggregate_persistence is not None and aggregate_persistence >= 1.0
    )
    return ParameterValidation(
        not reasons,
        constraints,
        reasons,
        "GARCH_NONSTATIONARY_PERSISTENCE" if nonstationary else None,
    )


def calculate_persistence(
    *,
    model: str,
    p: int,
    q: int,
    parameters: Mapping[str, float],
    time_index_semantics: str,
) -> PersistenceResult:
    """Report exact GARCH(1,1) persistence only, with semantic period units."""

    if model != "garch":
        return PersistenceResult(None, None, None, ())
    if (p, q) != (1, 1):
        return PersistenceResult(
            None,
            None,
            _half_life_unit(time_index_semantics),
            ("HIGH_ORDER_PERSISTENCE_NOT_REPORTED",),
        )
    alpha = _mapping_number(parameters, "alpha[1]")
    beta = _mapping_number(parameters, "beta[1]")
    if alpha is None or beta is None:
        return PersistenceResult(
            None,
            None,
            _half_life_unit(time_index_semantics),
            ("GARCH_INVALID_VARIANCE_PARAMETERS",),
        )
    persistence = alpha + beta
    if alpha < 0.0 or beta < 0.0:
        return PersistenceResult(
            persistence=finite_or_none(persistence),
            half_life=None,
            half_life_unit=_half_life_unit(time_index_semantics),
            warnings=("GARCH_INVALID_VARIANCE_PARAMETERS",),
        )
    warnings: list[str] = []
    half_life = None
    if 0.0 < persistence < 1.0:
        half_life = math.log(0.5) / math.log(persistence)
        if persistence >= 0.99:
            warnings.append("GARCH_HIGH_PERSISTENCE")
    elif persistence >= 1.0:
        warnings.append("GARCH_NONSTATIONARY_PERSISTENCE")
    elif persistence < 0.0:
        warnings.append("GARCH_INVALID_VARIANCE_PARAMETERS")
    return PersistenceResult(
        persistence=finite_or_none(persistence),
        half_life=finite_or_none(half_life),
        half_life_unit=_half_life_unit(time_index_semantics),
        warnings=tuple(warnings),
    )


def build_volatility_process(spec: VarianceCandidateSpec):
    if spec.model == "constant_variance":
        return ConstantVariance()
    if spec.model == "arch":
        return ARCH(p=spec.p)
    return GARCH(p=spec.p, o=0, q=spec.q)


def build_distribution(distribution: str):
    if distribution == "normal":
        return Normal(seed=0)
    if distribution == "student_t":
        return StudentsT(seed=0)
    raise ValueError(f"unsupported innovation distribution: {distribution}")


def convergence_details(fitted: object) -> dict[str, object]:
    optimization = getattr(fitted, "optimization_result", None)
    status = getattr(optimization, "status", None)
    return {
        "convergence_flag": _int_or_none(getattr(fitted, "convergence_flag", None)),
        "status": _int_or_none(status),
        "success": _bool_or_none(getattr(optimization, "success", None)),
        "message": str(getattr(optimization, "message", "")),
        "iterations": _int_or_none(getattr(optimization, "nit", None)),
        "function_evaluations": _int_or_none(getattr(optimization, "nfev", None)),
    }


def finite_parameters(values: object) -> dict[str, float]:
    items = values.items() if hasattr(values, "items") else ()
    result: dict[str, float] = {}
    for name, value in items:
        numeric = finite_or_none(value)
        if numeric is None:
            raise ValueError(f"non-finite fitted parameter: {name}")
        result[str(name)] = numeric
    return result


def json_finite_series(values: object) -> tuple[float | None, ...]:
    array = np.asarray(values, dtype=float).reshape(-1)
    return tuple(finite_or_none(value) for value in array)


def finite_or_none(value: object) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def no_variance_candidate_diagnostic(
    candidates: tuple[VarianceCandidateResult, ...],
    *,
    hold_back: int,
) -> ArmaGarchDiagnostic:
    failure_counts = Counter(
        candidate.failure_code or "AICC_UNDEFINED_OR_INELIGIBLE"
        for candidate in candidates
    )
    return diagnostic(
        "NO_VOLATILITY_CANDIDATE_CONVERGED",
        "No variance candidate passed the frozen residual acceptance gates.",
        evidence={
            "candidate_count": len(candidates),
            "common_hold_back": hold_back,
            "failure_counts": dict(sorted(failure_counts.items())),
        },
        impact="Volatility model selection cannot proceed to rolling validation.",
        recommended_actions=(
            {
                "operation": "model.rerun",
                "purpose": "review_mean_model_or_variance_specification",
                "required_confirmation": True,
            },
        ),
    )


def _finite_one_dimensional(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or len(array) == 0 or not np.isfinite(array).all():
        raise ValueError("variance input must be a non-empty finite one-dimensional series")
    return array


def _validate_hold_back(
    hold_back: int,
    total_observations: int,
    *,
    minimum: int = 0,
) -> None:
    if type(hold_back) is not int or hold_back < minimum:
        raise ValueError(f"hold_back must be an integer >= {minimum}")
    if hold_back >= total_observations:
        raise ValueError("hold_back must leave at least one effective observation")


def _validated_mean_binding(
    *,
    mean_candidate_id: str | None,
    mean_order: tuple[int, int] | None,
    mean_constant: bool | None,
) -> tuple[str | None, tuple[int, int] | None, bool | None]:
    fields = (mean_candidate_id, mean_order, mean_constant)
    if all(value is None for value in fields):
        return None, None, None
    if any(value is None for value in fields):
        raise ValueError("mean binding must be either complete or explicitly unbound")
    if not isinstance(mean_candidate_id, str) or not mean_candidate_id.strip():
        raise ValueError("mean_candidate_id must be a non-empty stable identifier")
    if not isinstance(mean_order, (tuple, list)) or len(mean_order) != 2:
        raise ValueError("mean_order must contain [p, q]")
    normalized_order = tuple(mean_order)
    if any(type(value) is not int or value < 0 for value in normalized_order):
        raise ValueError("mean_order values must be non-negative integers")
    if type(mean_constant) is not bool:
        raise ValueError("mean_constant must be boolean")
    return mean_candidate_id, normalized_order, mean_constant


def _mapping_number(values: Mapping[str, float], key: str) -> float | None:
    if key not in values:
        return None
    return finite_or_none(values[key])


def _half_life_unit(time_index_semantics: str) -> str:
    units = {
        "observation_order": "observation_periods",
        "business_or_trading_observations": "business_or_trading_observation_periods",
        "regular_calendar": "regular_calendar_observation_periods",
    }
    if time_index_semantics not in units:
        raise ValueError(f"unsupported time index semantics: {time_index_semantics}")
    return units[time_index_semantics]


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _bool_or_none(value: object) -> bool | None:
    return bool(value) if type(value) in {bool, np.bool_} else None


__all__ = [
    "ParameterValidation",
    "PersistenceResult",
    "VarianceCandidateResult",
    "VarianceCandidateSpec",
    "VarianceSearchResult",
    "build_distribution",
    "build_volatility_process",
    "calculate_persistence",
    "common_hold_back",
    "enumerate_variance_candidates",
    "failed_variance_candidate",
    "fit_joint_variance_candidate",
    "fit_variance_candidate",
    "search_joint_variance_candidates",
    "search_variance_candidates",
    "select_variance_candidate",
    "validate_variance_parameters",
]
