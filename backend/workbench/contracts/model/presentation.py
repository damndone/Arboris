"""Presentation policies for persisted model result types, including legacy aliases.

Result aliases are deliberately distinct from executable workflow families. These
policies preserve the historical report and claim semantics of those results.
"""
from dataclasses import dataclass
from typing import Any, Callable, Mapping

SummaryBuilder = Callable[[Mapping[str, Any], Any, str | None, int], str]


def _ols_summary(result, decision, exposure, n):
    if decision is not None and decision.reason is not None:
        variant = decision.reason.chosen_params.get("variant", decision.selected)
    elif decision is not None:
        variant = decision.selected
    else:
        variant = "HC1"
    return f"OLS ({variant}, n={n})"


def _logit_summary(result, decision, exposure, n):
    return f"Logit (n={n})"


def _poisson_summary(result, decision, exposure, n):
    return f"Poisson (n={n})"


def _rate_summary(result, decision, exposure, n):
    exposure = result.get("exposure_col") or exposure
    return f"Poisson rate (exposure={exposure}, n={n})" if exposure else f"Poisson (n={n})"


@dataclass(frozen=True)
class ResultPresentation:
    label: str | None = None
    diagnostic_family: str | None = None
    diagnostic_family_field: str | None = None
    coefficient_interpretation: str = "difference"
    rare_event_check: bool = False
    summary: SummaryBuilder | None = None
    overdispersion_artifact: str | None = None
    uses_exposure: bool = False


RESULT_PRESENTATIONS = {
    "ols": ResultPresentation("OLS", "ols", summary=_ols_summary),
    "ols_robust": ResultPresentation("OLS (robust SE)", "ols", summary=_ols_summary),
    "ols_hac": ResultPresentation("OLS (Newey-West SE)", "ols", summary=_ols_summary),
    "fixed_effects": ResultPresentation(diagnostic_family="ols"),
    "panel_ols": ResultPresentation("Panel OLS", "ols"),
    "glm": ResultPresentation(diagnostic_family_field="glm_family"),
    "logit": ResultPresentation("Logit", coefficient_interpretation="log_odds", rare_event_check=True, summary=_logit_summary),
    "poisson": ResultPresentation("Poisson", coefficient_interpretation="log_count", summary=_poisson_summary, overdispersion_artifact="poisson_1"),
    "poisson_rate": ResultPresentation("Poisson (rate model)", "poisson", coefficient_interpretation="log_count", summary=_rate_summary, overdispersion_artifact="poisson_1", uses_exposure=True),
    "ordinal_logit": ResultPresentation("Ordinal logit"),
    "multinomial_logit": ResultPresentation("Multinomial logit"),
    "survival_cox": ResultPresentation("Survival / Cox"),
    "quantile_regression": ResultPresentation("Quantile regression"),
}
_DEFAULT = ResultPresentation()


def result_presentation(model_type: str) -> ResultPresentation:
    return RESULT_PRESENTATIONS.get(model_type, _DEFAULT)


def diagnostic_family(result: Mapping[str, Any]) -> str:
    model_type = result.get("model_type", "ols")
    policy = result_presentation(model_type)
    if policy.diagnostic_family_field:
        return str(result.get(policy.diagnostic_family_field) or model_type)
    return policy.diagnostic_family or str(model_type)


def model_summary(model_type, result, *, robust_se_dp, exposure_col, fallback_n):
    n = int(result.get("nobs", fallback_n))
    builder = result_presentation(model_type).summary
    return builder(result, robust_se_dp, exposure_col, n) if builder else None
