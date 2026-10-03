"""What a check can read about one fitted model.

Traits are the family's declared traits plus facts of this fit read from its
inference kernel (a clustered covariance adds `vce.cluster`). The design is the
estimation sample's regressor matrix grouped into terms, so a factor with three
levels is one term of two columns.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..contracts.model.result_envelope_registry import declaration_for

_FACTOR = re.compile(r"^C\((?P<name>.+?)(?:,[^()]*)?\)$")
_QUOTED = re.compile(r"^Q\(['\"](?P<name>.+)['\"]\)$")


def term_label(term: str) -> str:
    """`region` from `C(region)`, `education` from `Q('education')`."""
    match = _QUOTED.match(term)
    if match:
        return match.group("name").strip()
    match = _FACTOR.match(term)
    if match:
        return term_label(match.group("name").strip())
    return term


_LEVEL = re.compile(r"^(?P<term>C\(.+\))\[T\.(?P<level>[^\]]+)\]$")


def public_column(name: str) -> str:
    """`x1` for `Q('x1')`, `region[West]` for `C(region)[T.West]`."""
    match = _LEVEL.match(name)
    if match:
        return f"{term_label(match.group('term'))}[{match.group('level')}]"
    return term_label(name)


@dataclass(frozen=True)
class Design:
    matrix: np.ndarray
    column_names: tuple[str, ...]
    #: term label -> column positions (the intercept is not a term)
    terms: Mapping[str, tuple[int, ...]]
    intercept: int | None

    @property
    def regressor_columns(self) -> list[int]:
        return [index for index in range(self.matrix.shape[1]) if index != self.intercept]


@dataclass
class CheckContext:
    model_id: str
    model_type: str
    traits: frozenset[str]
    nobs: int | None
    design: Design | None = None
    outcome: np.ndarray | None = None
    fitted: Any = None
    kernel: Mapping[str, Any] | None = None
    facts: dict[str, Any] = field(default_factory=dict)


def fit_traits(kernel: Mapping[str, Any] | None) -> frozenset[str]:
    """Facts of this fit that checks can require."""
    if not kernel:
        return frozenset()
    traits = set()
    estimator = kernel.get("covariance_estimator")
    if estimator == "cluster":
        traits.add("vce.cluster")
    if kernel.get("weights") == "sampling":
        traits.add("weights.sampling")
    return frozenset(traits)


def design_from_fitted(fitted: Any) -> Design | None:
    """The design matrix and its terms, from a formula-fitted statsmodels model."""
    model = getattr(fitted, "model", None)
    exog = getattr(model, "exog", None)
    names = getattr(model, "exog_names", None)
    if exog is None or names is None:
        return None
    matrix = np.asarray(exog, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != len(names):
        return None
    design_info = getattr(getattr(model, "data", None), "design_info", None)
    terms: dict[str, tuple[int, ...]] = {}
    intercept = None
    slices = getattr(design_info, "term_name_slices", None)
    if slices:
        for term, span in slices.items():
            positions = tuple(range(span.start, span.stop))
            if term == "Intercept":
                intercept = positions[0] if positions else None
                continue
            terms[term_label(term)] = positions
    else:
        for index, name in enumerate(names):
            if str(name) in {"Intercept", "const"}:
                intercept = index
            else:
                terms[term_label(str(name))] = (index,)
    return Design(matrix=matrix, column_names=tuple(str(name) for name in names), terms=terms, intercept=intercept)


def build_context(
    *, model_id: str, model_type: str, fitted: Any, kernel: Mapping[str, Any] | None, nobs: int | None,
    facts: Mapping[str, Any] | None = None,
) -> CheckContext:
    declaration = declaration_for(model_type)
    family_traits = declaration.traits if declaration is not None else frozenset()
    # Estimators expose their data differently (linearmodels wraps it); one
    # that does not expose a plain design or outcome gets "not checked" from
    # the checks that need them, and never fails the run here.
    try:
        design = design_from_fitted(fitted) if fitted is not None else None
    except Exception:  # noqa: BLE001
        design = None
    try:
        endog = getattr(getattr(fitted, "model", None), "endog", None)
        outcome = np.asarray(endog, dtype=float).reshape(-1) if endog is not None else None
    except Exception:  # noqa: BLE001
        outcome = None
    return CheckContext(
        model_id=model_id,
        model_type=model_type,
        traits=family_traits | fit_traits(kernel),
        nobs=nobs,
        design=design,
        outcome=outcome,
        fitted=fitted,
        kernel=kernel,
        facts=dict(facts or {}),
    )
