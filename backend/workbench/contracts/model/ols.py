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
OLS_COVARIANCE_VALUES = ("robust", "clustered", "unadjusted", "hac")
#: The HAC (Newey-West) fields: the column that orders the observations in
#: time, and the lag truncation. Both belong to `covariance: "hac"` only.
OLS_HAC_FIELDS = ("time_order", "hac_lags")
_OLS_MODEL_OPTIONS_FIELDS = frozenset({"covariance", *OLS_HAC_FIELDS})
#: Families whose model options are validated here but which do not offer HAC
#: yet (v1.8.10 opens it for OLS only).
_HAC_NOT_OFFERED = frozenset({"panel_ols"})
#: Above this the lag is no longer a truncation of a time series' memory but a
#: sign of a mistyped value; Stata accepts any lag below the sample size.
MAX_HAC_LAGS = 1000
HAC_DEFAULT_LAG_RULE = "floor(4 * (T / 100) ** (2 / 9)) (Newey and West 1994)"


def hac_default_lags(nobs: int) -> int:
    """The Newey-West (1994) rule of thumb for the Bartlett kernel's lag."""
    return int(4 * (nobs / 100) ** (2 / 9))


class OLSModelOptionsError(ValueError):
    """A semantic OLS option error carrying a stable transport code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = code


def validate_ols_model_options(value: Mapping[str, Any], *, family: str = OLS_MODEL_TYPE) -> None:
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
    _validate_hac_fields(value, covariance, family)


def validate_panel_ols_model_options(value: Mapping[str, Any]) -> None:
    validate_ols_model_options(value, family="panel_ols")


def _validate_hac_fields(value: Mapping[str, Any], covariance: str, family: str) -> None:
    present = [field for field in OLS_HAC_FIELDS if field in value]
    if covariance != "hac":
        if present:
            raise OLSModelOptionsError(
                "OLS_MODEL_OPTIONS_HAC_FIELD_WITHOUT_HAC",
                f"{', '.join(present)} {'applies' if len(present) == 1 else 'apply'} only to "
                "covariance hac (Newey-West).",
            )
        return
    if family in _HAC_NOT_OFFERED:
        raise OLSModelOptionsError(
            "OLS_HAC_NOT_OFFERED",
            f"HAC (Newey-West) standard errors are offered for OLS only so far; {family} "
            "would need Driscoll-Kraay standard errors, which are not implemented yet.",
        )
    time_order = value.get("time_order")
    if not isinstance(time_order, str) or not time_order.strip():
        raise OLSModelOptionsError(
            "OLS_HAC_TIME_ORDER_MISSING",
            "HAC (Newey-West) standard errors need the data's time order: set time_order to "
            "the column that orders the observations in time (a year, period or date).",
        )
    lags = value.get("hac_lags")
    if lags is not None and (type(lags) is not int or not 0 <= lags <= MAX_HAC_LAGS):
        raise OLSModelOptionsError(
            "OLS_HAC_LAGS_INVALID",
            f"hac_lags must be an integer from 0 to {MAX_HAC_LAGS}; omit it to use "
            f"{HAC_DEFAULT_LAG_RULE}.",
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
    "HAC_DEFAULT_LAG_RULE",
    "MAX_HAC_LAGS",
    "OLS_COVARIANCE_VALUES",
    "OLS_HAC_FIELDS",
    "OLS_MODEL_ID",
    "OLS_MODEL_OPTIONS_CONTRACT",
    "OLS_MODEL_OPTIONS_CONTRACT_VERSION",
    "OLS_MODEL_OPTIONS_PRODUCER_VERSION",
    "OLS_MODEL_TYPE",
    "OLSModelOptionsError",
    "effective_ols_covariance",
    "hac_default_lags",
    "validate_ols_model_options",
    "validate_panel_ols_model_options",
]
