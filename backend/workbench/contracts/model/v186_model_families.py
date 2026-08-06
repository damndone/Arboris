"""Typed, fail-closed packets for the v1.8.6 model-family slice.

These contracts deliberately keep the external-oracle boundary explicit.  The
runtime can prove internal consistency and packet shape here, but it must not
turn that evidence into a Stata/R equivalence claim.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..common.envelope import ContractError, require_exact_keys
from .survival import SurvivalEvidenceContract
from .validation_levels import (
    INTERNAL_ONLY,
    NOT_VERIFIED,
    VALIDATION_LEVELS,
    ExternalOracle,
    check_validation,
)


V186_MODEL_FAMILY_CONTRACT_VERSION = "1"
V186_VALIDATION_LEVEL = "internal_consistency_only"
V186_EXTERNAL_ORACLE_STATUS = "not_verified"

_VALIDATION_FIELDS = {"level", "external_oracle"}

#: One entry per family. Adding a family without one leaves it at
#: `internal_consistency_only`, which is the truthful default for something
#: nothing has checked from the outside.
EXTERNAL_ORACLES: dict[str, ExternalOracle] = {
    "survival_cox": ExternalOracle(
        level="external_oracle_exact",
        reference="R survival::coxph (Efron ties)",
        tolerance="1e-10 relative",
        note="Coefficients, standard errors and hazard ratios agree to machine precision.",
    ),
    "quantile_regression": ExternalOracle(
        level="external_oracle_within_tolerance",
        reference="R quantreg::rq (Barrodale-Roberts simplex)",
        tolerance="1e-5 absolute",
        note=(
            "quantreg solves the linear program exactly; statsmodels fits iteratively, "
            "so the two differ in the sixth decimal."
        ),
    ),
    "ordinal_logit": ExternalOracle(
        level="external_oracle_within_tolerance",
        reference="R MASS::polr (proportional odds)",
        tolerance="1e-4 absolute",
        note=(
            "The same likelihood optimised by different solvers. Cutpoints are "
            "comparable only after undoing statsmodels' log-increment parameterisation."
        ),
    ),
    "multinomial_logit": ExternalOracle(
        level="external_oracle_within_tolerance",
        reference="R nnet::multinom",
        tolerance="1e-4 absolute",
        note=(
            "nnet optimises a neural-net objective by BFGS against statsmodels' Newton "
            "method. Comparable only once the baseline category is pinned on both sides."
        ),
    ),
}


def validation_payload(model_type: str) -> dict[str, str]:
    """The validation block a result of this family should carry."""
    oracle = EXTERNAL_ORACLES.get(model_type)
    if oracle is None:
        return {
            "level": V186_VALIDATION_LEVEL,
            "external_oracle": V186_EXTERNAL_ORACLE_STATUS,
        }
    return {"level": oracle.level, "external_oracle": oracle.statement}


def _require_string(value: Any, field_name: str) -> str:
    if type(value) is not str or not value:
        raise ContractError(f"{field_name} must be a non-empty string")
    return value


def _require_positive_int(value: Any, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ContractError(f"{field_name} must be a positive int")
    return value


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field_name} must be a mapping")
    if any(type(key) is not str for key in value):
        raise ContractError(f"{field_name} mapping keys must be strings")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{field_name} must be an array")
    return value


def _require_validation(value: Any) -> Mapping[str, str]:
    validation = _require_mapping(value, "validation")
    require_exact_keys(validation, _VALIDATION_FIELDS, "validation")
    check_validation(dict(validation), "validation")
    return validation  # type: ignore[return-value]


def _require_identity(
    value: Mapping[str, Any],
    *,
    packet_name: str,
    expected_contract: str,
    expected_model_type: str,
) -> None:
    """For packets that share identity but not the result envelope.

    The ordinal diagnostics packet carries contract, model_type, parallel_lines,
    nobs and validation -- no coefficients, no model_id, no engine. Pushing it
    through the result envelope would be forcing a fit, the same mistake in the
    opposite direction from letting each family restate the core.
    """
    from .result_envelope import ResultEnvelopeError, validate_result_identity

    try:
        validate_result_identity(
            value,
            packet_name=packet_name,
            expected_contract=expected_contract,
            expected_model_type=expected_model_type,
        )
    except ResultEnvelopeError as exc:
        raise ContractError(str(exc)) from exc


def _require_common(
    value: Mapping[str, Any],
    *,
    packet_name: str,
    expected_contract: str,
    expected_model_type: str,
) -> None:
    """Delegate the shared core to its single definition.

    This used to check two of the eight shared fields itself, leaving the other
    six restated per family with nothing keeping them in step.
    """
    from .result_envelope import ResultEnvelopeError, validate_result_envelope

    try:
        validate_result_envelope(
            value,
            packet_name=packet_name,
            expected_contract=expected_contract,
            expected_model_type=expected_model_type,
        )
    except ResultEnvelopeError as exc:
        raise ContractError(str(exc)) from exc


@dataclass(frozen=True)
class OrdinalResultContract:
    """Primary ordered-logit/probit result packet."""

    contract: str
    schema_version: int
    model_id: str
    model_type: Literal["ordinal_logit"]
    engine: str
    nobs: int
    outcome_levels: list[str]
    link: Literal["logit", "probit"]
    coefficients: Mapping[str, Any]
    odds_ratios: Mapping[str, Any] | None
    predicted_probabilities: list[Mapping[str, Any]]
    marginal_effects: list[Mapping[str, Any]]
    diagnostic_artifacts: list[str]
    validation: Mapping[str, str]

    def __post_init__(self) -> None:
        _require_common(
            self.to_dict(),
            packet_name="ordinal_result",
            expected_contract="workbench.ordinal_logit.result.v1",
            expected_model_type="ordinal_logit",
        )
        if self.schema_version != 1:
            raise ContractError("ordinal_result.schema_version must be 1")
        _require_string(self.model_id, "ordinal_result.model_id")
        _require_string(self.engine, "ordinal_result.engine")
        _require_positive_int(self.nobs, "ordinal_result.nobs")
        if len(self.outcome_levels) < 3 or len(set(self.outcome_levels)) != len(self.outcome_levels):
            raise ContractError("ordinal_result.outcome_levels must contain at least three unique levels")
        if self.link not in {"logit", "probit"}:
            raise ContractError("ordinal_result.link must be logit or probit")
        _require_mapping(self.coefficients, "ordinal_result.coefficients")
        if self.odds_ratios is not None:
            _require_mapping(self.odds_ratios, "ordinal_result.odds_ratios")
        _require_list(self.predicted_probabilities, "ordinal_result.predicted_probabilities")
        _require_list(self.marginal_effects, "ordinal_result.marginal_effects")
        _require_validation(self.validation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "model_type": self.model_type,
            "engine": self.engine,
            "nobs": self.nobs,
            "outcome_levels": list(self.outcome_levels),
            "link": self.link,
            "coefficients": dict(self.coefficients),
            "odds_ratios": dict(self.odds_ratios) if self.odds_ratios is not None else None,
            "predicted_probabilities": list(self.predicted_probabilities),
            "marginal_effects": list(self.marginal_effects),
            "diagnostic_artifacts": list(self.diagnostic_artifacts),
            "validation": dict(self.validation),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OrdinalResultContract":
        require_exact_keys(
            value,
            {
                "contract", "schema_version", "model_id", "model_type", "engine", "nobs",
                "outcome_levels", "link", "coefficients", "odds_ratios",
                "predicted_probabilities", "marginal_effects", "diagnostic_artifacts", "validation",
            },
            "ordinal_result",
        )
        return cls(**value)


@dataclass(frozen=True)
class OrdinalDiagnosticsContract:
    """Independent ordered-model parallel-lines diagnostic packet."""

    contract: str
    model_type: Literal["ordinal_logit"]
    parallel_lines: Mapping[str, Any]
    nobs: int
    validation: Mapping[str, str]

    def __post_init__(self) -> None:
        _require_identity(
            self.to_dict(),
            packet_name="ordinal_diagnostics",
            expected_contract="workbench.ordinal_logit.diagnostics.v1",
            expected_model_type="ordinal_logit",
        )
        _require_mapping(self.parallel_lines, "ordinal_diagnostics.parallel_lines")
        _require_positive_int(self.nobs, "ordinal_diagnostics.nobs")
        _require_validation(self.validation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "model_type": self.model_type,
            "parallel_lines": dict(self.parallel_lines),
            "nobs": self.nobs,
            "validation": dict(self.validation),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OrdinalDiagnosticsContract":
        require_exact_keys(
            value,
            {"contract", "model_type", "parallel_lines", "nobs", "validation"},
            "ordinal_diagnostics",
        )
        return cls(**value)


@dataclass(frozen=True)
class MultinomialResultContract:
    """Primary nominal MNLogit result packet."""

    contract: str
    schema_version: int
    model_id: str
    model_type: Literal["multinomial_logit"]
    engine: str
    nobs: int
    outcome_levels: list[str]
    base_category: str
    coefficients: Mapping[str, Any]
    relative_risk_ratios: Mapping[str, Any]
    predicted_probabilities: Mapping[str, list[Any]]
    marginal_effects: list[Mapping[str, Any]]
    diagnostic_artifacts: list[str]
    validation: Mapping[str, str]

    def __post_init__(self) -> None:
        _require_common(
            self.to_dict(),
            packet_name="multinomial_result",
            expected_contract="workbench.multinomial_logit.result.v1",
            expected_model_type="multinomial_logit",
        )
        if self.schema_version != 1:
            raise ContractError("multinomial_result.schema_version must be 1")
        _require_string(self.model_id, "multinomial_result.model_id")
        _require_string(self.engine, "multinomial_result.engine")
        _require_positive_int(self.nobs, "multinomial_result.nobs")
        if len(self.outcome_levels) < 3 or len(set(self.outcome_levels)) != len(self.outcome_levels):
            raise ContractError("multinomial_result.outcome_levels must contain at least three unique levels")
        if self.base_category not in self.outcome_levels:
            raise ContractError("multinomial_result.base_category must be an outcome level")
        for field_name in ("coefficients", "relative_risk_ratios"):
            _require_mapping(getattr(self, field_name), f"multinomial_result.{field_name}")
        probabilities = _require_mapping(
            self.predicted_probabilities, "multinomial_result.predicted_probabilities"
        )
        if set(probabilities) != set(self.outcome_levels):
            raise ContractError("multinomial_result probabilities must cover every outcome level")
        _require_list(self.marginal_effects, "multinomial_result.marginal_effects")
        _require_validation(self.validation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "model_type": self.model_type,
            "engine": self.engine,
            "nobs": self.nobs,
            "outcome_levels": list(self.outcome_levels),
            "base_category": self.base_category,
            "coefficients": dict(self.coefficients),
            "relative_risk_ratios": dict(self.relative_risk_ratios),
            "predicted_probabilities": dict(self.predicted_probabilities),
            "marginal_effects": list(self.marginal_effects),
            "diagnostic_artifacts": list(self.diagnostic_artifacts),
            "validation": dict(self.validation),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MultinomialResultContract":
        require_exact_keys(
            value,
            {
                "contract", "schema_version", "model_id", "model_type", "engine", "nobs",
                "outcome_levels", "base_category", "coefficients", "relative_risk_ratios",
                "predicted_probabilities", "marginal_effects", "diagnostic_artifacts", "validation",
            },
            "multinomial_result",
        )
        return cls(**value)


@dataclass(frozen=True)
class QuantileRegressionResultContract:
    """Primary multi-quantile regression packet."""

    contract: str
    schema_version: int
    model_id: str
    model_type: Literal["quantile_regression"]
    engine: str
    nobs: int
    quantiles: list[float]
    fits: Mapping[str, Any]
    coefficients: Mapping[str, Any]
    reference_quantile: float
    confidence_intervals: Mapping[str, Any]
    bootstrap: Mapping[str, Any]
    cross_quantile_comparisons: list[Mapping[str, Any]]
    validation: Mapping[str, str]

    def __post_init__(self) -> None:
        _require_common(
            self.to_dict(),
            packet_name="quantile_result",
            expected_contract="workbench.quantile_regression.result.v1",
            expected_model_type="quantile_regression",
        )
        if self.schema_version != 1:
            raise ContractError("quantile_result.schema_version must be 1")
        _require_string(self.model_id, "quantile_result.model_id")
        _require_string(self.engine, "quantile_result.engine")
        _require_positive_int(self.nobs, "quantile_result.nobs")
        if not self.quantiles or any(not 0 < float(q) < 1 for q in self.quantiles):
            raise ContractError("quantile_result.quantiles must be strictly between zero and one")
        if len(set(self.quantiles)) != len(self.quantiles):
            raise ContractError("quantile_result.quantiles must be unique")
        if self.reference_quantile not in self.quantiles:
            raise ContractError("quantile_result.reference_quantile must be one of quantiles")
        for field_name in ("fits", "coefficients", "confidence_intervals", "bootstrap"):
            _require_mapping(getattr(self, field_name), f"quantile_result.{field_name}")
        _require_list(
            self.cross_quantile_comparisons,
            "quantile_result.cross_quantile_comparisons",
        )
        _require_validation(self.validation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "model_type": self.model_type,
            "engine": self.engine,
            "nobs": self.nobs,
            "quantiles": list(self.quantiles),
            "fits": dict(self.fits),
            "coefficients": dict(self.coefficients),
            "reference_quantile": self.reference_quantile,
            "confidence_intervals": dict(self.confidence_intervals),
            "bootstrap": dict(self.bootstrap),
            "cross_quantile_comparisons": list(self.cross_quantile_comparisons),
            "validation": dict(self.validation),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QuantileRegressionResultContract":
        require_exact_keys(
            value,
            {
                "contract", "schema_version", "model_id", "model_type", "engine", "nobs",
                "quantiles", "fits", "coefficients", "reference_quantile",
                "confidence_intervals", "bootstrap", "cross_quantile_comparisons", "validation",
            },
            "quantile_result",
        )
        return cls(**value)


__all__ = [
    "MultinomialResultContract",
    "OrdinalDiagnosticsContract",
    "OrdinalResultContract",
    "QuantileRegressionResultContract",
    "SurvivalEvidenceContract",
    "V186_EXTERNAL_ORACLE_STATUS",
    "V186_MODEL_FAMILY_CONTRACT_VERSION",
    "V186_VALIDATION_LEVEL",
]
