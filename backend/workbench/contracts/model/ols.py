"""Server-owned OLS model-options contract.

The legacy OLS form exposes ``covariance`` at the top level.  Notebook Agent
patches use the generic ``model_options`` envelope instead, so this module is
the single semantic owner for the nested representation and its projection
back to the legacy execution field.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...model_options import ModelOptionsContract


OLS_MODEL_TYPE = "ols"
OLS_MODEL_ID = "ols_1"
OLS_MODEL_OPTIONS_PRODUCER_VERSION = "ols@1.0"
OLS_MODEL_OPTIONS_CONTRACT_VERSION = "ols_model_options@1.0"
OLS_MODEL_OPTIONS_CONTRACT = ModelOptionsContract(
    producer_version=OLS_MODEL_OPTIONS_PRODUCER_VERSION,
    input_contract_version=OLS_MODEL_OPTIONS_CONTRACT_VERSION,
)
OLS_COVARIANCE_VALUES = ("robust", "clustered", "unadjusted")
_OLS_MODEL_OPTIONS_FIELDS = frozenset({"covariance"})


class OLSModelOptionsError(ValueError):
    """A semantic OLS option error carrying a stable transport code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = code


def validate_ols_model_options(value: Mapping[str, Any]) -> None:
    """Validate the exact nested OLS option payload.

    Clustered covariance is accepted here because it is a valid OLS inference
    choice.  Its required ``entity_col`` is a sibling model parameter and is
    therefore checked by the execution estimator, where the complete input is
    available; it must never be silently downgraded to robust covariance.
    """

    if not isinstance(value, Mapping):
        raise OLSModelOptionsError(
            "OLS_MODEL_OPTIONS_NOT_OBJECT",
            "OLS model_options must be an object.",
        )
    unknown = sorted(set(value) - _OLS_MODEL_OPTIONS_FIELDS)
    if unknown:
        raise OLSModelOptionsError(
            "OLS_MODEL_OPTIONS_UNKNOWN_FIELD",
            "OLS model_options contains unsupported field(s): "
            + ", ".join(str(item) for item in unknown),
        )
    covariance = value.get("covariance")
    if not isinstance(covariance, str) or covariance not in OLS_COVARIANCE_VALUES:
        raise OLSModelOptionsError(
            "OLS_MODEL_OPTIONS_INVALID_COVARIANCE",
            "OLS model_options.covariance must be one of: "
            + ", ".join(OLS_COVARIANCE_VALUES),
        )


def effective_ols_covariance(
    top_level_covariance: object,
    model_options: Mapping[str, Any] | None,
) -> str:
    """Resolve the covariance actually used by an OLS fit.

    A validated nested Agent option intentionally wins over the historical
    top-level default.  This is what prevents a rerun patch such as
    ``{"model_options": {"covariance": "unadjusted"}}`` from binding
    successfully while still fitting HC1 robust standard errors.
    """

    if model_options:
        validate_ols_model_options(model_options)
        return str(model_options["covariance"])
    value = str(top_level_covariance or "").strip().lower() or "robust"
    if value not in OLS_COVARIANCE_VALUES:
        raise OLSModelOptionsError(
            "OLS_MODEL_OPTIONS_INVALID_COVARIANCE",
            "OLS covariance must be one of: " + ", ".join(OLS_COVARIANCE_VALUES),
        )
    return value


__all__ = [
    "OLS_COVARIANCE_VALUES",
    "OLS_MODEL_ID",
    "OLS_MODEL_OPTIONS_CONTRACT",
    "OLS_MODEL_OPTIONS_CONTRACT_VERSION",
    "OLS_MODEL_OPTIONS_PRODUCER_VERSION",
    "OLS_MODEL_TYPE",
    "OLSModelOptionsError",
    "effective_ols_covariance",
    "validate_ols_model_options",
]
