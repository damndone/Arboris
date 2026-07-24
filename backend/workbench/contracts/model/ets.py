"""v1.8.1 Contract Sprint — ETS model result contract (ADR-PD-001 §5, §8.2).

Integration-owned, read-only for the Model Pack Lane.

ETS (error/trend/seasonal exponential smoothing) is this wave's Model Pack
subject. It is deliberately a *forecasting alternative* to the existing
ARMA-GARCH pack rather than a new capability area: the Notebook's whole premise
is that an agent offers several defensible paths, and that is only testable when
at least two comparable models exist on the same data.

Statistical semantics locked here, before any implementation (ADR §8.2):

1. **Fit method.** Maximum likelihood via `statsmodels` `ETSModel`. No new
   dependency. `fit_method` is recorded and is part of result identity.
2. **Model specification.** `error` and `trend` in {add, mul, None as allowed by
   the component rules}, `seasonal` with an explicit `seasonal_periods`;
   `damped_trend` is explicit. The specification string is canonical and enters
   result identity — an ETS(A,A,N) and an ETS(A,Ad,N) are different models, not
   two fits of one.
3. **Information criteria are within-family only.** AIC/BIC may be compared
   across ETS specifications fitted to the *same* sample. Comparing an ETS AIC
   against an ARMA-GARCH AIC is prohibited: different likelihoods, different
   transformations. ComparePacket must return `comparability: restricted` with
   `reason_code: ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE`.
4. **Missing data and time-index semantics.** Complete-case on the modelled
   series, counted and reported. An interior gap in a `regular_calendar` series
   is blocking, because exponential smoothing over an implicit gap silently
   changes the time index.

   `time_index_semantics` (added in 1.1) mirrors the ARMA-GARCH vocabulary
   exactly, and for the same reason: a trading-day series such as VIXCLS has a
   weekend "gap" on every calendar week, which is not missing data at all. The
   1.0 contract had no such field, so ETS would have blocked on the very dataset
   v1.8.0 shipped with — making the Notebook's alternative model unusable
   precisely where an alternative is wanted. Under
   `business_or_trading_observations` or `observation_order`, spacing is the
   observation sequence and calendar gaps are not defects; interior *missing
   values* remain blocking under every setting.
5. **Convergence.** The optimizer status is mapped to a standardized code;
   non-convergence is a blocking diagnostic, not a warning with numbers shown.
6. **No volatility claims.** ETS models the conditional mean. It must never be
   reported as a volatility model, and must not emit VaR or conditional-variance
   fields — the v1.8.0 ledger already refuses composite IC and VaR labelling.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..common.envelope import ContractError, require_exact_keys

ETS_CONTRACT_VERSION = "1.1"
# §5.3: a minor bump must keep old consumer fixtures valid. A 1.0 packet is a
# 1.1 packet that omitted an optional field, so it is accepted and defaulted --
# refusing it would make "backward compatible" a claim rather than a property.
SUPPORTED_CONTRACT_VERSIONS = ("1.0", "1.1")
ETS_MODEL_TYPE = "time_series.ets"

ERROR_COMPONENTS = ("add", "mul")
TREND_COMPONENTS = ("add", "mul", None)
SEASONAL_COMPONENTS = ("add", "mul", None)

CONVERGENCE_CODES = ("converged", "max_iterations", "failed")

# Identical vocabulary to ArmaGarchAnalysisContract.time_index_semantics. Two
# models compared on one series must agree about what its index means, or the
# comparison is between different samples wearing the same name.
TIME_INDEX_SEMANTICS = (
    "regular_calendar",
    "business_or_trading_observations",
    "observation_order",
)
# 1.0 packets carry no such field. Defaulting to regular_calendar preserves
# their exact behaviour (ADR-PD-001 §5.3: a new optional field must define its
# missing-value behaviour and keep old consumer fixtures valid).
DEFAULT_TIME_INDEX_SEMANTICS = "regular_calendar"

# Reason codes a compare adapter may return for this model. Locked so the UI and
# the agent can render them without inventing text.
COMPARE_REASON_CODES = (
    "ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE",
    "ETS_SPECIFICATION_DIFFERS",
    "ETS_SAMPLE_DIFFERS",
)


class ETSContractError(ContractError):
    """An ETS packet violated its locked contract."""


def _require_str(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        raise ETSContractError(f"{field} must be a non-empty string")
    return value


def _require_number(value: Any, field: str) -> float:
    if type(value) not in (int, float) or value != value:  # NaN check
        raise ETSContractError(f"{field} must be a finite number")
    return float(value)


@dataclass(frozen=True)
class ETSSpecification:
    """The canonical model specification. Part of result identity."""

    error: str
    trend: str | None
    seasonal: str | None
    seasonal_periods: int | None
    damped_trend: bool

    def __post_init__(self) -> None:
        if self.error not in ERROR_COMPONENTS:
            raise ETSContractError(f"error must be one of {list(ERROR_COMPONENTS)}")
        if self.trend not in TREND_COMPONENTS:
            raise ETSContractError(f"trend must be one of {list(TREND_COMPONENTS)}")
        if self.seasonal not in SEASONAL_COMPONENTS:
            raise ETSContractError(f"seasonal must be one of {list(SEASONAL_COMPONENTS)}")
        if self.seasonal is not None and not self.seasonal_periods:
            raise ETSContractError("seasonal_periods is required when seasonal is set")
        if self.damped_trend and self.trend is None:
            raise ETSContractError("damped_trend requires a trend component")

    @property
    def canonical(self) -> str:
        """e.g. ETS(A,Ad,N) — the string a reader can compare at a glance."""

        letters = {"add": "A", "mul": "M", None: "N"}
        trend = letters[self.trend] + ("d" if self.damped_trend else "")
        return f"ETS({letters[self.error]},{trend},{letters[self.seasonal]})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.error,
            "trend": self.trend,
            "seasonal": self.seasonal,
            "seasonal_periods": self.seasonal_periods,
            "damped_trend": self.damped_trend,
            "canonical": self.canonical,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ETSSpecification":
        return cls(
            error=value["error"],
            trend=value["trend"],
            seasonal=value["seasonal"],
            seasonal_periods=value.get("seasonal_periods"),
            damped_trend=bool(value.get("damped_trend", False)),
        )


@dataclass(frozen=True)
class ETSResultContract:
    """The locked shape of an ETS estimation result."""

    model_type: str
    specification: ETSSpecification
    endog: str
    n_obs: int
    n_excluded: int
    exclusion_reasons: Mapping[str, int]
    params: Mapping[str, float]
    aic: float
    bic: float
    log_likelihood: float
    sigma2: float
    convergence_code: str
    fit_method: str
    result_identity: str
    time_index_semantics: str = DEFAULT_TIME_INDEX_SEMANTICS
    contract_version: str = ETS_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
            raise ETSContractError(
                f"contract_version must be one of {list(SUPPORTED_CONTRACT_VERSIONS)}"
            )
        if self.model_type != ETS_MODEL_TYPE:
            raise ETSContractError(f"model_type must be {ETS_MODEL_TYPE}")
        _require_str(self.endog, "endog")
        _require_str(self.result_identity, "result_identity")
        if self.time_index_semantics not in TIME_INDEX_SEMANTICS:
            raise ETSContractError(
                f"time_index_semantics must be one of {list(TIME_INDEX_SEMANTICS)}"
            )
        if self.convergence_code not in CONVERGENCE_CODES:
            raise ETSContractError(f"convergence_code must be one of {list(CONVERGENCE_CODES)}")
        if type(self.n_obs) is not int or self.n_obs <= 0:
            raise ETSContractError("n_obs must be a positive int")
        for field in ("aic", "bic", "log_likelihood", "sigma2"):
            _require_number(getattr(self, field), field)
        # Guard rail for point 6 of the module docstring: this is a mean model.
        forbidden = {"var", "value_at_risk", "conditional_variance", "volatility"}
        smuggled = sorted(forbidden & set(self.params))
        if smuggled:
            raise ETSContractError(
                f"ETS is a conditional-mean model; it must not report {smuggled}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "model_type": self.model_type,
            "specification": self.specification.to_dict(),
            "endog": self.endog,
            "n_obs": self.n_obs,
            "n_excluded": self.n_excluded,
            "exclusion_reasons": dict(self.exclusion_reasons),
            "params": dict(self.params),
            "aic": self.aic,
            "bic": self.bic,
            "log_likelihood": self.log_likelihood,
            "sigma2": self.sigma2,
            "convergence_code": self.convergence_code,
            "fit_method": self.fit_method,
            "result_identity": self.result_identity,
            "time_index_semantics": self.time_index_semantics,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ETSResultContract":
        # time_index_semantics is optional (1.0 packets predate it), so it is
        # stripped before the exact-key check rather than weakening that check.
        required_view = {k: v for k, v in value.items() if k != "time_index_semantics"}
        require_exact_keys(
            required_view,
            {
                "contract_version",
                "model_type",
                "specification",
                "endog",
                "n_obs",
                "n_excluded",
                "exclusion_reasons",
                "params",
                "aic",
                "bic",
                "log_likelihood",
                "sigma2",
                "convergence_code",
                "fit_method",
                "result_identity",
            },
            "ets_result",
        )
        return cls(
            model_type=value["model_type"],
            specification=ETSSpecification.from_dict(value["specification"]),
            endog=value["endog"],
            n_obs=value["n_obs"],
            n_excluded=value["n_excluded"],
            exclusion_reasons=value["exclusion_reasons"],
            params=value["params"],
            aic=value["aic"],
            bic=value["bic"],
            log_likelihood=value["log_likelihood"],
            sigma2=value["sigma2"],
            convergence_code=value["convergence_code"],
            fit_method=value["fit_method"],
            result_identity=value["result_identity"],
            time_index_semantics=value.get(
                "time_index_semantics", DEFAULT_TIME_INDEX_SEMANTICS
            ),
            contract_version=value["contract_version"],
        )


__all__ = [
    "COMPARE_REASON_CODES",
    "CONVERGENCE_CODES",
    "DEFAULT_TIME_INDEX_SEMANTICS",
    "SUPPORTED_CONTRACT_VERSIONS",
    "TIME_INDEX_SEMANTICS",
    "ETS_CONTRACT_VERSION",
    "ETS_MODEL_TYPE",
    "ETSContractError",
    "ETSResultContract",
    "ETSSpecification",
]
