"""Which fits may answer an outcome: the registry's family declarations, read through each fit's checks.

The check library writes beside each fit whether its family is declared for the
outcome's type (``outcome.type_served``). The delivery gate reads that record: a
fit whose family does not serve its outcome is never bound as the primary answer.
In the binary_logit retest (2026-11-07) the gate bound the imported OLS as
``ols:primary`` for a 0/1 outcome and asked for OLS sensitivity fits after the
Agent had fitted a Logit, because no playbook owned Logit.

The ``outcome_family`` playbook takes its families from the same declarations:
every registered family declared for an outcome type whose default family no
design playbook owns (binary and count outcomes today), so a new family that
declares its outcome types needs no edit here.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..checks.fit_checks import OUTCOME_TYPE_SERVED

OUTCOME_FAMILY = "outcome_family"
NOT_SERVED = "outcome:family_not_served"
CHECKS_ARTIFACT_TYPE = "model_checks"


def outcome_family_types(owned: Iterable[str]) -> tuple[str, ...]:
    from ..engine.registry import DEFAULT_BY_Y_TYPE, MODEL_REGISTRY

    owned = set(owned)
    kinds = {kind for kind, default in DEFAULT_BY_Y_TYPE.items() if default not in owned}
    return tuple(sorted(name for name, handler in MODEL_REGISTRY.items()
                        if name not in owned and kinds.intersection(handler.serves_y_types)))


def checks_ref(ref: Mapping[str, Any], model: Mapping[str, Any]) -> dict[str, str]:
    return {"run_id": ref["run_id"], "artifact_id": f"checks_{model.get('model_id')}"}


def fit_checks(products, ref, model) -> list[dict[str, Any]] | None:
    artifact = products.load(checks_ref(ref, model))
    if artifact is None or artifact.artifact_type != CHECKS_ARTIFACT_TYPE:
        return None
    payload = artifact.payload or {}
    if payload.get("model_id") != model.get("model_id"):
        return None
    return [item for item in payload.get("checks") or [] if isinstance(item, dict)]


def unserved(products, ref, model) -> dict[str, Any] | None:
    """The fit's own record that its family does not serve its outcome, or None."""
    for item in fit_checks(products, ref, model) or ():
        if item.get("check_id") == OUTCOME_TYPE_SERVED.check_id and item.get("status") == "caution":
            return dict(item.get("evidence") or {})
    return None


def checks_hold(values: Iterable[Mapping[str, Any]]) -> bool:
    """The outcome_family diagnostics: the fit's check library ran and no check fails."""
    for value in values:
        checks = [item for item in value.get("checks") or [] if isinstance(item, dict)]
        if checks and all(item.get("status") != "fails" for item in checks):
            return True
    return False


def not_served_step(evidence: Mapping[str, Any]) -> str:
    serving = ", ".join(evidence.get("families_serving_outcome_type") or ()) or "a family declared for it"
    return (f"The only fit for this outcome is {evidence.get('family')}, which is not declared for "
            f"{evidence.get('outcome_type')} outcomes, so it cannot be the answer. Refit with {serving}: "
            "model.rerun on the same model node with model_type set to one of them keeps its data, outcome and "
            "predictors (a change of estimator, not a new specification). Bind that fit as primary under the "
            f"{OUTCOME_FAMILY} playbook; the earlier fit may stay as a comparison.")


def comparison_families(model_type: str | None) -> list[str]:
    """Other outcome_family members declared for an outcome type the primary's family serves."""
    from ..engine.registry import MODEL_REGISTRY

    handler = MODEL_REGISTRY.get(model_type or "")
    kinds = set(handler.serves_y_types) - {"continuous"} if handler else set()
    return [name for name in outcome_family_types(()) if name != model_type
            and kinds.intersection(MODEL_REGISTRY[name].serves_y_types)]


def comparison_step(model_type: str | None) -> str:
    """The outcome_family sensitivity repair. binary_logit.open.r1 (501cdda6): the generic step pointed at
    prepared options that are new specifications (model.genesis), refused there, and the Agent concluded nothing remained."""
    others = ", ".join(comparison_families(model_type)) or "another family declared for this outcome"
    return ("No distinct comparison fit is bound. The direct comparison for this outcome is model.rerun on the primary's "
            f"model node with model_type set to one of {others}: the same data, outcome and predictors under another "
            "estimator is a distinct point estimation, and the Workbench binds it as sensitivity. A sensitivity_options "
            "entry, where one is offered and permitted, is an alternative; never drop the variable the question is about. "
            "Compose the report after it.")

