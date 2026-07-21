"""Bounded statsmodels ARMA candidate search on the frozen training interval."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from collections import Counter
from dataclasses import dataclass, field
import math
from time import perf_counter
import warnings as runtime_warnings

import numpy as np
from statsmodels.tsa.arima.model import ARIMA

from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.contracts.common.envelope import freeze_json
from workbench.engine.packs.arma_garch.split import FrozenTrainValidationSplit
from workbench.engine.packs.arma_garch.errors import ArmaGarchDiagnostic, diagnostic
from workbench.engine.packs.arma_garch.statistics import (
    calculate_aicc,
    ljung_box_results,
)
from workbench.engine.packs.arma_garch.transforms import TRANSFORMED_VALUE_COLUMN


@dataclass(frozen=True)
class ArmaCandidateSpec:
    candidate_id: str
    p: int
    q: int
    constant: bool

    @property
    def trend(self) -> str:
        return "c" if self.constant else "n"


@dataclass(frozen=True)
class ArmaCandidateResult:
    candidate_id: str
    p: int
    q: int
    constant: bool
    nobs: int
    effective_sample: int
    converged: bool
    convergence_details: Mapping[str, object]
    stationary: bool
    invertible: bool
    ar_roots: tuple[Mapping[str, float | None], ...]
    ma_roots: tuple[Mapping[str, float | None], ...]
    finite_parameters: bool
    log_likelihood: float | None
    parameter_count: int
    aic: float | None
    aicc: float | None
    bic: float | None
    residual_variance: float | None
    ljung_box_results: tuple[Mapping[str, float | int | None], ...]
    warnings: tuple[str, ...]
    failure_code: str | None
    elapsed_seconds: float
    residuals: tuple[float, ...]
    parameters: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "convergence_details",
            "ar_roots",
            "ma_roots",
            "ljung_box_results",
            "parameters",
        ):
            object.__setattr__(
                self,
                field_name,
                freeze_json(getattr(self, field_name), f"arma_candidate.{field_name}"),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "p": self.p,
            "q": self.q,
            "constant": self.constant,
            "nobs": self.nobs,
            "effective_sample": self.effective_sample,
            "converged": self.converged,
            "convergence_details": dict(self.convergence_details),
            "stationary": self.stationary,
            "invertible": self.invertible,
            "ar_roots": [dict(root) for root in self.ar_roots],
            "ma_roots": [dict(root) for root in self.ma_roots],
            "finite_parameters": self.finite_parameters,
            "log_likelihood": self.log_likelihood,
            "parameter_count": self.parameter_count,
            "aic": self.aic,
            "aicc": self.aicc,
            "aicc_minus_aic": (
                self.aicc - self.aic
                if isinstance(self.aicc, (int, float)) and isinstance(self.aic, (int, float))
                else None
            ),
            "bic": self.bic,
            "residual_variance": self.residual_variance,
            "ljung_box_results": [dict(item) for item in self.ljung_box_results],
            "warnings": list(self.warnings),
            "failure_code": self.failure_code,
            "elapsed_seconds": self.elapsed_seconds,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class ArmaSelection:
    selected_candidate_id: str | None
    shortlist_candidate_ids: tuple[str, ...]
    excluded_candidate_ids: tuple[str, ...]
    best_aicc: float | None
    delta_aicc_threshold: float
    selected_bic: float | None


@dataclass(frozen=True)
class ArmaSearchResult:
    split_hash: str
    training_row_ids: tuple[str, ...]
    candidates: tuple[ArmaCandidateResult, ...]
    selected_candidate_id: str | None
    shortlist_candidate_ids: tuple[str, ...]
    blocking_diagnostic: ArmaGarchDiagnostic | None = None
    selection_repeated_during_validation: bool = False


def enumerate_arma_candidates(
    contract: ArmaGarchAnalysisContract,
) -> tuple[ArmaCandidateSpec, ...]:
    """Enumerate only the bounded orders already accepted by the public contract."""

    if contract.selection_mode == "manual":
        assert contract.arma.p is not None and contract.arma.q is not None
        orders = ((contract.arma.p, contract.arma.q),)
    else:
        orders = tuple(
            (p, q)
            for p in range(contract.arma.auto_max_p + 1)
            for q in range(contract.arma.auto_max_q + 1)
            if p + q <= contract.arma.auto_max_total_order
        )
    constants = {
        "auto": (False, True),
        "include": (True,),
        "exclude": (False,),
    }[contract.arma.constant_mode]
    return tuple(
        ArmaCandidateSpec(
            candidate_id=_candidate_id(p, q, constant),
            p=p,
            q=q,
            constant=constant,
        )
        for p, q in orders
        for constant in constants
    )


def fit_arma_candidate(
    values: np.ndarray,
    spec: ArmaCandidateSpec,
) -> ArmaCandidateResult:
    """Fit one ARMA candidate; optimizer failures become table rows."""

    started = perf_counter()
    captured: list[str] = []
    try:
        series = np.asarray(values, dtype=float)
        if series.ndim != 1 or len(series) == 0 or not np.isfinite(series).all():
            raise ValueError("ARMA input must be a non-empty finite one-dimensional series")
        with runtime_warnings.catch_warnings(record=True) as caught:
            runtime_warnings.simplefilter("always")
            fitted = ARIMA(
                series,
                order=(spec.p, 0, spec.q),
                trend=spec.trend,
            ).fit()
            raw_ar_roots = fitted.arroots
            raw_ma_roots = fitted.maroots
        captured.extend(str(item.message) for item in caught)

        convergence = _convergence_details(fitted.mle_retvals)
        converged = bool(convergence.get("converged", True))
        ar_roots = _roots_payload(raw_ar_roots)
        ma_roots = _roots_payload(raw_ma_roots)
        stationary = _roots_outside_unit_circle(ar_roots)
        invertible = _roots_outside_unit_circle(ma_roots)
        if any(root["modulus"] is None for root in (*ar_roots, *ma_roots)):
            captured.append("NONFINITE_CHARACTERISTIC_ROOT")
        parameter_values = np.asarray(fitted.params, dtype=float)
        parameter_names = tuple(str(name) for name in fitted.param_names)
        parameters = {
            name: float(value)
            for name, value in zip(parameter_names, parameter_values, strict=True)
        }
        finite_parameters = bool(np.isfinite(parameter_values).all())
        residuals = np.asarray(fitted.resid, dtype=float)
        residuals = residuals[np.isfinite(residuals)]
        nobs = int(fitted.nobs)
        effective_sample = int(getattr(fitted, "nobs_effective", len(residuals)))
        parameter_count = int(len(parameter_values))
        aic = _finite_or_none(fitted.aic)
        aicc = (
            calculate_aicc(
                aic=aic,
                parameter_count=parameter_count,
                effective_sample=effective_sample,
            )
            if aic is not None
            else None
        )
        if aicc is None:
            captured.append("AICC_UNDEFINED")
        ljung_box = ljung_box_results(
            residuals,
            model_df=spec.p + spec.q,
        )
        failure_code = _candidate_failure_code(
            converged=converged,
            finite_parameters=finite_parameters,
            stationary=stationary,
            invertible=invertible,
            ljung_box=ljung_box,
        )
        return ArmaCandidateResult(
            candidate_id=spec.candidate_id,
            p=spec.p,
            q=spec.q,
            constant=spec.constant,
            nobs=nobs,
            effective_sample=effective_sample,
            converged=converged,
            convergence_details=convergence,
            stationary=stationary,
            invertible=invertible,
            ar_roots=ar_roots,
            ma_roots=ma_roots,
            finite_parameters=finite_parameters,
            log_likelihood=_finite_or_none(fitted.llf),
            parameter_count=parameter_count,
            aic=aic,
            aicc=aicc,
            bic=_finite_or_none(fitted.bic),
            residual_variance=_finite_or_none(np.var(residuals)),
            ljung_box_results=ljung_box,
            warnings=tuple(captured),
            failure_code=failure_code,
            elapsed_seconds=perf_counter() - started,
            residuals=tuple(float(value) for value in residuals),
            parameters=parameters,
        )
    except Exception as exc:
        captured.append(f"{type(exc).__name__}: {exc}")
        return _failed_candidate(
            spec,
            nobs=len(values) if np.ndim(values) == 1 else 0,
            warnings=tuple(captured),
            elapsed_seconds=perf_counter() - started,
        )


def search_arma_candidates(
    split: FrozenTrainValidationSplit,
    contract: ArmaGarchAnalysisContract,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> ArmaSearchResult:
    """Fit the bounded grid once using only the frozen training values."""

    training = split.training_view
    values = training[TRANSFORMED_VALUE_COLUMN].to_numpy(dtype=float, copy=True)
    results: list[ArmaCandidateResult] = []
    for spec in enumerate_arma_candidates(contract):
        if checkpoint is not None:
            checkpoint()
        try:
            result = fit_arma_candidate(values.copy(), spec)
        except Exception as exc:
            result = _failed_candidate(
                spec,
                nobs=len(values),
                warnings=(f"{type(exc).__name__}: {exc}",),
                elapsed_seconds=0.0,
            )
        results.append(result)
    selection = select_arma_candidate(tuple(results))
    blocking_diagnostic = (
        None
        if selection.selected_candidate_id is not None
        else _no_candidate_diagnostic(
            tuple(results), split_hash=split.split_hash, n_train=len(values)
        )
    )
    return ArmaSearchResult(
        split_hash=split.split_hash,
        training_row_ids=split.training_row_ids,
        candidates=tuple(results),
        selected_candidate_id=selection.selected_candidate_id,
        shortlist_candidate_ids=selection.shortlist_candidate_ids,
        blocking_diagnostic=blocking_diagnostic,
        selection_repeated_during_validation=False,
    )


def select_arma_candidate(
    candidates: Sequence[ArmaCandidateResult],
    *,
    delta_aicc_threshold: float = 2.0,
) -> ArmaSelection:
    """Apply validity gates, then AICc shortlist and parsimony selection."""

    eligible = [candidate for candidate in candidates if _eligible(candidate)]
    excluded = tuple(
        sorted(
            candidate.candidate_id
            for candidate in candidates
            if candidate not in eligible
        )
    )
    if not eligible:
        return ArmaSelection(None, (), excluded, None, delta_aicc_threshold, None)

    best_aicc = min(float(candidate.aicc) for candidate in eligible if candidate.aicc is not None)
    shortlist = [
        candidate
        for candidate in eligible
        if candidate.aicc is not None
        and candidate.aicc <= best_aicc + delta_aicc_threshold
    ]
    shortlist_by_aicc = tuple(
        candidate.candidate_id
        for candidate in sorted(
            shortlist,
            key=lambda item: (float(item.aicc), item.candidate_id),
        )
    )
    selected = min(
        shortlist,
        key=lambda item: (
            item.p + item.q,
            item.parameter_count,
            math.inf if item.bic is None else item.bic,
            float(item.aicc),
            item.candidate_id,
        ),
    )
    return ArmaSelection(
        selected_candidate_id=selected.candidate_id,
        shortlist_candidate_ids=shortlist_by_aicc,
        excluded_candidate_ids=excluded,
        best_aicc=best_aicc,
        delta_aicc_threshold=delta_aicc_threshold,
        selected_bic=selected.bic,
    )


def _candidate_id(p: int, q: int, constant: bool) -> str:
    return f"arma-p{p}-q{q}-{'c' if constant else 'n'}"


def _no_candidate_diagnostic(
    candidates: tuple[ArmaCandidateResult, ...],
    *,
    split_hash: str,
    n_train: int,
) -> ArmaGarchDiagnostic:
    failure_counts = Counter(
        candidate.failure_code or "AICC_UNDEFINED_OR_INELIGIBLE"
        for candidate in candidates
    )
    return diagnostic(
        "NO_ARMA_CANDIDATE_CONVERGED",
        "No ARMA candidate passed the frozen training-set acceptance gates.",
        evidence={
            "candidate_count": len(candidates),
            "failure_counts": dict(sorted(failure_counts.items())),
            "n_train": n_train,
            "split_hash": split_hash,
        },
        impact="Mean-model selection cannot continue to volatility estimation.",
        recommended_actions=(
            {
                "operation": "graph.fork",
                "purpose": "review_and_confirm_alternative_transform",
                "required_confirmation": True,
                "reason": (
                    "All bounded ARMA candidates were already evaluated; review an "
                    "eligible alternative transform instead of repeating a failed order."
                ),
            },
        ),
    )


def _convergence_details(value: object) -> dict[str, object]:
    details = value if isinstance(value, Mapping) else {}
    return {
        "converged": bool(details.get("converged", True)),
        "warnflag": _int_or_none(details.get("warnflag")),
        "iterations": _int_or_none(details.get("iterations")),
        "function_calls": _int_or_none(details.get("fcalls")),
    }


def _roots_payload(
    values: object,
) -> tuple[Mapping[str, float | None], ...]:
    roots = np.asarray(values, dtype=complex)
    return tuple(
        {
            "real": _finite_or_none(root.real),
            "imaginary": _finite_or_none(root.imag),
            "modulus": _finite_or_none(abs(root)),
        }
        for root in roots
    )


def _roots_outside_unit_circle(
    roots: tuple[Mapping[str, float | None], ...],
) -> bool:
    return all(
        root["modulus"] is not None and float(root["modulus"]) > 1.0
        for root in roots
    )


def _candidate_failure_code(
    *,
    converged: bool,
    finite_parameters: bool,
    stationary: bool,
    invertible: bool,
    ljung_box: tuple[Mapping[str, float | int | None], ...],
) -> str | None:
    if not converged:
        return "ARMA_NOT_CONVERGED"
    if not finite_parameters:
        return "ARMA_NONFINITE_PARAMETERS"
    if not stationary:
        return "ARMA_NONSTATIONARY"
    if not invertible:
        return "ARMA_NONINVERTIBLE"
    if any(
        item["p_value"] is not None and float(item["p_value"]) < 0.01
        for item in ljung_box
    ):
        return "ARMA_RESIDUAL_AUTOCORRELATION"
    return None


def _eligible(candidate: ArmaCandidateResult) -> bool:
    return bool(
        candidate.failure_code is None
        and candidate.converged
        and candidate.finite_parameters
        and candidate.stationary
        and candidate.invertible
        and candidate.aicc is not None
        and math.isfinite(candidate.aicc)
        and not any(
            item["p_value"] is not None and float(item["p_value"]) < 0.01
            for item in candidate.ljung_box_results
        )
    )


def _failed_candidate(
    spec: ArmaCandidateSpec,
    *,
    nobs: int,
    warnings: tuple[str, ...],
    elapsed_seconds: float,
) -> ArmaCandidateResult:
    return ArmaCandidateResult(
        candidate_id=spec.candidate_id,
        p=spec.p,
        q=spec.q,
        constant=spec.constant,
        nobs=nobs,
        effective_sample=0,
        converged=False,
        convergence_details={"converged": False},
        stationary=False,
        invertible=False,
        ar_roots=(),
        ma_roots=(),
        finite_parameters=False,
        log_likelihood=None,
        parameter_count=0,
        aic=None,
        aicc=None,
        bic=None,
        residual_variance=None,
        ljung_box_results=(),
        warnings=warnings,
        failure_code="ARMA_FIT_FAILED",
        elapsed_seconds=elapsed_seconds,
        residuals=(),
    )


def _finite_or_none(value: object) -> float | None:
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _int_or_none(value: object) -> int | None:
    return int(value) if value is not None else None


__all__ = [
    "ArmaCandidateResult",
    "ArmaCandidateSpec",
    "ArmaSearchResult",
    "ArmaSelection",
    "enumerate_arma_candidates",
    "fit_arma_candidate",
    "search_arma_candidates",
    "select_arma_candidate",
]


def information_criterion_agreement(
    candidates: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """The reference's explicit "is AICc close to AIC?" evidence.

    Summarizes `delta = aicc - aic` and reports whether ranking by AIC agrees
    with ranking by AICc (Spearman rho plus an exact-order flag). Candidates
    without both finite criteria are excluded rather than coerced.
    """

    rows = [
        item
        for item in candidates
        if isinstance(item.get("aic"), (int, float))
        and isinstance(item.get("aicc"), (int, float))
        and math.isfinite(float(item["aic"]))
        and math.isfinite(float(item["aicc"]))
    ]
    if not rows:
        return {
            "n": 0,
            "delta_max": None,
            "delta_mean": None,
            "rank_agreement_spearman": None,
            "rank_agreement_identical": None,
        }
    deltas = [float(item["aicc"]) - float(item["aic"]) for item in rows]
    aic_order = [
        index for index, _ in sorted(enumerate(rows), key=lambda pair: float(pair[1]["aic"]))
    ]
    aicc_order = [
        index for index, _ in sorted(enumerate(rows), key=lambda pair: float(pair[1]["aicc"]))
    ]
    spearman: float | None = None
    if len(rows) > 1:
        aic_rank = _ranks([float(item["aic"]) for item in rows])
        aicc_rank = _ranks([float(item["aicc"]) for item in rows])
        spearman = _pearson(aic_rank, aicc_rank)
    return {
        "n": len(rows),
        "delta_max": max(deltas),
        "delta_mean": sum(deltas) / len(deltas),
        "rank_agreement_spearman": spearman,
        "rank_agreement_identical": aic_order == aicc_order,
    }


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks (ties share the mean rank), matching Stata's rank handling."""

    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            ranks[order[index]] = shared
        position = end + 1
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    left_ss = sum((a - mean_left) ** 2 for a in left)
    right_ss = sum((b - mean_right) ** 2 for b in right)
    if left_ss <= 0.0 or right_ss <= 0.0:
        return None
    return numerator / math.sqrt(left_ss * right_ss)
