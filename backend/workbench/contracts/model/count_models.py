"""Owner-declared option contracts for count ML and fixed-dispersion GLMs."""
from collections.abc import Mapping
import math

from ...model_options import ModelOptionsContract
from ...engine.registry import ModelOptionsValidationError


def _options(options: Mapping[str, object], allowed: set[str]) -> None:
    unknown = set(options) - allowed
    if unknown:
        raise ModelOptionsValidationError("COUNT_MODEL_OPTIONS_UNKNOWN_FIELD",
            f"Unsupported count-model option fields: {', '.join(sorted(unknown))}.")
    alpha = options.get("alpha")
    try:
        valid_alpha = type(alpha) in (int, float) and math.isfinite(alpha) and alpha > 0
    except OverflowError:
        valid_alpha = False
    if alpha is not None and not valid_alpha:
        raise ModelOptionsValidationError("NB_ALPHA_INVALID",
            "Fixed alpha must be a finite, strictly positive number.")


def validate_negative_binomial_model_options(options: Mapping[str, object]) -> None:
    _options(options, {"dispersion", "alpha"})
    dispersion = options.get("dispersion", "mean")
    if dispersion not in ("mean", "constant"):
        raise ModelOptionsValidationError("NB_DISPERSION_INVALID",
            "dispersion must be mean (NB2) or constant (NB1).")
    if dispersion == "constant" and options.get("alpha") is not None:
        raise ModelOptionsValidationError("NB_FIXED_DISPERSION_UNSUPPORTED",
            "Fixed alpha requires NB2 dispersion='mean'.")


def validate_glm_model_options(options: Mapping[str, object]) -> None:
    _options(options, {"alpha"})


def validate_glm_family_options(options: Mapping[str, object], family: str) -> None:
    validate_glm_model_options(options)
    if family == "negative_binomial" and options.get("alpha") is None:
        raise ModelOptionsValidationError("GLM_NB_ALPHA_REQUIRED",
            "The negative binomial GLM requires explicit fixed alpha.")
    if family != "negative_binomial" and options.get("alpha") is not None:
        raise ModelOptionsValidationError("GLM_ALPHA_NOT_APPLICABLE",
            "alpha is only defined for the negative binomial GLM.")


NEGATIVE_BINOMIAL_MODEL_OPTIONS_CONTRACT = ModelOptionsContract(
    producer_version="negative_binomial@1.0", input_contract_version="count_model_options@1.0")
GLM_MODEL_OPTIONS_CONTRACT = ModelOptionsContract(
    producer_version="glm@1.0", input_contract_version="glm_model_options@1.0")
