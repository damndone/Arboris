"""Dimension-level acceptance aggregation for ARMA-GARCH results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from workbench.contracts.common.envelope import freeze_json, thaw_json
from workbench.engine.packs.arma_garch.forecast import ForecastMetrics


AcceptanceStatus = Literal[
    "accepted", "accepted_with_warnings", "rejected", "inconclusive"
]


@dataclass(frozen=True)
class AcceptanceDimension:
    status: AcceptanceStatus
    reasons: tuple[str, ...]
    evidence: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence", freeze_json(self.evidence, "acceptance_dimension.evidence")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reasons": list(self.reasons),
            "evidence": thaw_json(self.evidence),
        }


@dataclass(frozen=True)
class AcceptanceResult:
    dimensions: Mapping[str, AcceptanceDimension]
    overall_status: AcceptanceStatus
    model_fit_succeeded: bool

    def __post_init__(self) -> None:
        if set(self.dimensions) != {
            "data_readiness",
            "mean_adequacy",
            "volatility_adequacy",
            "distribution_adequacy",
            "forecast_validation",
            "volatility_value_added",
        } or not all(
            isinstance(value, AcceptanceDimension)
            for value in self.dimensions.values()
        ):
            raise ValueError("acceptance dimensions are incomplete")
        object.__setattr__(
            self, "dimensions", MappingProxyType(dict(self.dimensions))
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "overall_status": self.overall_status,
            "model_fit_succeeded": self.model_fit_succeeded,
            "dimensions": {
                name: value.to_dict() if isinstance(value, AcceptanceDimension) else value
                for name, value in self.dimensions.items()
            },
        }


def assess_acceptance(
    *,
    forecast_metrics: ForecastMetrics,
    split_forecast_status: str,
    estimation_converged: bool,
    finite_parameters: bool,
    variance_parameters_valid: bool,
    mean_residual_autocorrelation: bool | None,
    squared_standardized_residual_arch: bool | None,
    normality_rejected: bool | None,
    volatility_value_added: bool | None,
) -> AcceptanceResult:
    """Apply the approved hard failures without collapsing all evidence to pass/fail."""

    fit_succeeded = bool(
        estimation_converged and finite_parameters and variance_parameters_valid
    )
    short_validation = (
        split_forecast_status == "inconclusive" or forecast_metrics.validation_n < 20
    )
    data_readiness = _dimension(
        "inconclusive" if short_validation else "accepted",
        "validation sample is too short for a stable acceptance conclusion"
        if short_validation
        else "frozen train and validation intervals are adequate",
        {
            "validation_n": forecast_metrics.validation_n,
            "split_forecast_status": split_forecast_status,
        },
    )
    if not estimation_converged or not finite_parameters:
        mean_adequacy = _dimension(
            "rejected",
            "estimation did not converge with finite parameters",
            {
                "estimation_converged": estimation_converged,
                "finite_parameters": finite_parameters,
            },
        )
    elif mean_residual_autocorrelation is None:
        mean_adequacy = _dimension(
            "inconclusive", "mean residual autocorrelation was not evaluated", {}
        )
    elif mean_residual_autocorrelation:
        mean_adequacy = _dimension(
            "accepted_with_warnings",
            "mean residual autocorrelation remains",
            {"mean_residual_autocorrelation": True},
        )
    else:
        mean_adequacy = _dimension(
            "accepted", "no material mean residual autocorrelation remains", {}
        )

    if not estimation_converged or not finite_parameters or not variance_parameters_valid:
        volatility_adequacy = _dimension(
            "rejected",
            "variance estimation did not produce converged finite legal parameters",
            {
                "estimation_converged": estimation_converged,
                "finite_parameters": finite_parameters,
                "variance_parameters_valid": variance_parameters_valid,
            },
        )
    elif squared_standardized_residual_arch is None:
        volatility_adequacy = _dimension(
            "inconclusive", "standardized squared residual ARCH was not evaluated", {}
        )
    elif squared_standardized_residual_arch:
        volatility_adequacy = _dimension(
            "accepted_with_warnings",
            "standardized squared residuals retain ARCH structure",
            {"squared_standardized_residual_arch": True},
        )
    else:
        volatility_adequacy = _dimension(
            "accepted", "no material ARCH remains in standardized squared residuals", {}
        )

    if normality_rejected is None:
        distribution_adequacy = _dimension(
            "inconclusive", "innovation distribution diagnostics were not evaluated", {}
        )
    elif normality_rejected:
        distribution_adequacy = _dimension(
            "accepted_with_warnings",
            "normality rejection is distribution evidence, not an automatic model failure",
            {"normality_rejected": True},
        )
    else:
        distribution_adequacy = _dimension(
            "accepted", "innovation distribution diagnostics are adequate", {}
        )

    failed_count = (
        forecast_metrics.validation_n - forecast_metrics.successful_forecast_n
    )
    if forecast_metrics.successful_forecast_n == 0:
        forecast_validation = _dimension(
            "rejected",
            "no rolling forecast origin succeeded",
            {"failed_forecast_count": failed_count},
        )
    elif short_validation:
        forecast_validation = _dimension(
            "inconclusive",
            "rolling metrics are reported but the validation sample is too short",
            forecast_metrics.to_dict(),
        )
    elif failed_count:
        forecast_validation = _dimension(
            "accepted_with_warnings",
            "some rolling origins failed",
            {**forecast_metrics.to_dict(), "failed_forecast_count": failed_count},
        )
    else:
        forecast_validation = _dimension(
            "accepted",
            "all frozen validation origins produced one-step forecasts",
            forecast_metrics.to_dict(),
        )

    if short_validation or volatility_value_added is None:
        value_added = _dimension(
            "inconclusive",
            "validation evidence is insufficient to establish incremental volatility value",
            {"volatility_value_added": volatility_value_added},
        )
    elif volatility_value_added:
        value_added = _dimension(
            "accepted", "GARCH adds value on the locked ARMA-only comparison", {}
        )
    else:
        value_added = _dimension(
            "rejected",
            "GARCH did not add practical value over the locked ARMA-only comparison",
            {"model_fit_succeeded": fit_succeeded},
        )

    dimensions = {
        "data_readiness": data_readiness,
        "mean_adequacy": mean_adequacy,
        "volatility_adequacy": volatility_adequacy,
        "distribution_adequacy": distribution_adequacy,
        "forecast_validation": forecast_validation,
        "volatility_value_added": value_added,
    }
    hard_dimensions = (
        data_readiness,
        mean_adequacy,
        volatility_adequacy,
        forecast_validation,
    )
    if any(item.status == "rejected" for item in hard_dimensions):
        overall: AcceptanceStatus = "rejected"
    elif any(item.status == "inconclusive" for item in dimensions.values()):
        overall = "inconclusive"
    elif any(
        item.status in {"accepted_with_warnings", "rejected"}
        for item in dimensions.values()
    ):
        overall = "accepted_with_warnings"
    else:
        overall = "accepted"
    return AcceptanceResult(
        dimensions=dimensions,
        overall_status=overall,
        model_fit_succeeded=fit_succeeded,
    )


def _dimension(
    status: AcceptanceStatus, reason: str, evidence: Mapping[str, object]
) -> AcceptanceDimension:
    return AcceptanceDimension(status=status, reasons=(reason,), evidence=evidence)


__all__ = [
    "AcceptanceDimension",
    "AcceptanceResult",
    "AcceptanceStatus",
    "assess_acceptance",
]
