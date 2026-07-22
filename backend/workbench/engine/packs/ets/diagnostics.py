"""Convergence classification and recommended-action candidates.

Point 5 of the locked contract is implemented here: the optimizer status is
mapped to one of the contract's standardized codes, and anything other than
`converged` is a *blocking* diagnostic. The pack never returns estimated
numbers alongside a "did not converge" warning.

The pack only states what is statistically permissible. Turning a candidate
into a user-visible, confirmation-required proposal belongs to the Agent Lane
(ADR-PD-001 §7B).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from workbench.contracts.model.ets import CONVERGENCE_CODES, ETSSpecification

from .errors import ETSDiagnostic, ETSEstimationError, diagnostic


NON_CONVERGENCE_CODE = "ETS_OPTIMIZER_DID_NOT_CONVERGE"


def classify_convergence(mle_retvals: Mapping[str, Any] | None) -> str:
    """Map a statsmodels optimizer return record onto a contract code."""

    if not isinstance(mle_retvals, Mapping):
        return "failed"
    if bool(mle_retvals.get("converged")) is True:
        return "converged"
    warnflag = mle_retvals.get("warnflag")
    if warnflag in (1, "1"):
        return "max_iterations"
    return "failed"


def simplification_candidates(
    specification: ETSSpecification,
) -> tuple[dict[str, object], ...]:
    """Statistically permissible simplifications of a failed specification."""

    candidates: list[dict[str, object]] = []
    if specification.damped_trend:
        candidates.append(
            {
                "action_id": "ets.drop_damping",
                "patch": {"damped_trend": False},
                "rationale_code": "ETS_DAMPING_ADDS_A_WEAKLY_IDENTIFIED_PARAMETER",
                "required_confirmation": True,
            }
        )
    if specification.seasonal is not None:
        candidates.append(
            {
                "action_id": "ets.drop_seasonal",
                "patch": {"seasonal": None, "seasonal_periods": None},
                "rationale_code": "ETS_SEASONAL_COMPONENT_MAY_BE_UNSUPPORTED_BY_SAMPLE",
                "required_confirmation": True,
            }
        )
    if specification.trend is not None:
        candidates.append(
            {
                "action_id": "ets.drop_trend",
                "patch": {"trend": None, "damped_trend": False},
                "rationale_code": "ETS_TREND_COMPONENT_MAY_BE_UNSUPPORTED_BY_SAMPLE",
                "required_confirmation": True,
            }
        )
    return tuple(candidates)


def non_convergence_diagnostic(
    *, convergence_code: str, specification: ETSSpecification, n_obs: int
) -> ETSDiagnostic:
    """Build the blocking diagnostic for any non-converged optimizer status."""

    if convergence_code not in CONVERGENCE_CODES:
        raise ValueError(f"unknown convergence code: {convergence_code}")
    if convergence_code == "converged":
        raise ValueError("converged is not a failure")
    return diagnostic(
        NON_CONVERGENCE_CODE,
        f"the ETS optimizer terminated with status {convergence_code!r}",
        evidence={
            "convergence_code": convergence_code,
            "specification": specification.canonical,
            "n_obs": int(n_obs),
        },
        impact=(
            "Parameter estimates from a non-converged optimizer are not "
            "reportable, so no ETS result is produced."
        ),
        severity="blocking",
        recommended_actions=simplification_candidates(specification),
    )


def raise_non_convergence(
    *, convergence_code: str, specification: ETSSpecification, n_obs: int
) -> None:
    raise ETSEstimationError(
        non_convergence_diagnostic(
            convergence_code=convergence_code,
            specification=specification,
            n_obs=n_obs,
        )
    )


__all__ = [
    "NON_CONVERGENCE_CODE",
    "classify_convergence",
    "non_convergence_diagnostic",
    "raise_non_convergence",
    "simplification_candidates",
]
