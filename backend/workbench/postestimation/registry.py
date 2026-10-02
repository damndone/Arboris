"""Which post-estimation operations are offered for which model families.

An operation needs two things before it is offered for a family: the model
must provide the interfaces it reads (checked from the kernel at run time),
and the pair must have been validated against a reference implementation. The
second is recorded here, pair by pair, with the oracle case that validates it;
tests/test_postestimation_registry.py fails when a listed pair has no passing
oracle case. Coverage grows by adding oracle data, not by writing code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

from .core import PostestimationRefusal, lincom, lr_test, nlcom, wald_test

ORACLE_FIXTURE = "tests/fixtures/postestimation/oracle.json"


@dataclass(frozen=True)
class OperationSpec:
    operation: str
    #: How many kernels the operation reads (LR compares two models).
    kernels: int
    run: Callable[..., dict[str, Any]]


def _run_wald(kernels: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]) -> dict[str, Any]:
    return wald_test(kernels[0], spec.get("constraints"))


def _run_lincom(kernels: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]) -> dict[str, Any]:
    return lincom(kernels[0], spec.get("terms"), constant=spec.get("constant", 0.0), level=spec.get("level", 0.95))


def _run_nlcom(kernels: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]) -> dict[str, Any]:
    return nlcom(kernels[0], spec.get("expression"), level=spec.get("level", 0.95))


def _run_lr(kernels: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]) -> dict[str, Any]:
    return lr_test(kernels[0], kernels[1])


OPERATIONS: Mapping[str, OperationSpec] = {
    "wald": OperationSpec("wald", 1, _run_wald),
    "lincom": OperationSpec("lincom", 1, _run_lincom),
    "nlcom": OperationSpec("nlcom", 1, _run_nlcom),
    "lr": OperationSpec("lr", 2, _run_lr),
}

#: (model_type, operation) -> oracle cases in ORACLE_FIXTURE that validate it.
#: A case is "<family key>.<result key>"; `ols_robust` is the OLS fit with
#: HC1 covariance, validated separately because its reference distribution
#: differs.
VALIDATED: Mapping[tuple[str, str], tuple[str, ...]] = {
    ("ols", "wald"): ("ols.wald_joint", "ols.wald_shifted", "ols_robust.wald_joint", "ols_robust.wald_shifted"),
    ("ols", "lincom"): ("ols.lincom", "ols_robust.lincom"),
    ("ols", "nlcom"): ("ols.nlcom", "ols_robust.nlcom"),
    ("ols", "lr"): ("ols.lr_drop_x2_x3",),
    ("logit", "wald"): ("logit.wald_joint", "logit.wald_shifted"),
    ("logit", "lincom"): ("logit.lincom",),
    ("logit", "nlcom"): ("logit.nlcom",),
    ("logit", "lr"): ("logit.lr_drop_x2_x3",),
    ("probit", "wald"): ("probit.wald_joint", "probit.wald_shifted"),
    ("probit", "lincom"): ("probit.lincom",),
    ("probit", "nlcom"): ("probit.nlcom",),
    ("probit", "lr"): ("probit.lr_drop_x2_x3",),
    ("poisson", "wald"): ("poisson.wald_joint", "poisson.wald_shifted"),
    ("poisson", "lincom"): ("poisson.lincom",),
    ("poisson", "nlcom"): ("poisson.nlcom",),
    ("poisson", "lr"): ("poisson.lr_drop_x2_x3",),
    ("negative_binomial", "wald"): ("negative_binomial.wald_joint", "negative_binomial.wald_shifted"),
    ("negative_binomial", "lincom"): ("negative_binomial.lincom",),
    ("ordinal_logit", "wald"): ("ordinal_logit.wald_joint",),
    ("ordinal_logit", "lincom"): ("ordinal_logit.lincom",),
    ("multinomial_logit", "wald"): ("multinomial_logit.wald_joint",),
    ("multinomial_logit", "lincom"): ("multinomial_logit.lincom",),
}


def validated_operations(model_type: str) -> list[str]:
    return [operation for (family, operation) in VALIDATED if family == model_type]


def require_validated(model_type: str, operation: str) -> None:
    if operation not in OPERATIONS:
        raise PostestimationRefusal(
            "UNKNOWN_OPERATION", f"{operation} is not a post-estimation operation; use one of {', '.join(OPERATIONS)}"
        )
    if (model_type, operation) not in VALIDATED:
        offered = validated_operations(model_type)
        raise PostestimationRefusal(
            "NOT_YET_VALIDATED",
            f"{operation} has not yet been checked against a reference implementation for "
            f"{model_type} models, so it is not offered yet. What is missing is that check, not "
            "the model's ability: "
            + (f"for this model, {', '.join(offered)} are available." if offered
               else "no post-estimation operation has been validated for this model yet."),
        )


def run_operation(operation: str, kernels: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]) -> dict[str, Any]:
    """Run one operation after the validation gate; the kernels decide the rest."""
    spec_def = OPERATIONS.get(operation)
    if spec_def is None:
        require_validated("", operation)
    if len(kernels) != spec_def.kernels:
        raise PostestimationRefusal(
            "WRONG_MODEL_COUNT", f"{operation} compares {spec_def.kernels} model(s), got {len(kernels)}"
        )
    for kernel in kernels:
        require_validated(str(kernel.get("model_type")), operation)
    return spec_def.run(kernels, spec)
