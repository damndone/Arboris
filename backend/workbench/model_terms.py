"""Derived model terms: dummy expansion and polynomial powers.

`predictors` is a flat list of columns that enter linearly. Anything else a
model needs — a categorical expanded into indicators, a squared term — has to
be built as a real column before estimation, because the estimator reads a
dataset, not a formula.

One module owns those names and rules so the proposal validator and the
executor cannot disagree about what a branch means. A validator that accepted
a spec the executor then built differently would be worse than no validator.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import pandas as pd


class ModelTermError(ValueError):
    """Raised when a branch's derived terms cannot be built as specified."""


# A dummy set replaces one column with one column per level, so an id-like
# column would silently produce thousands of regressors. Refuse instead: at
# that width the model is a mistake, not a choice.
MAX_CATEGORICAL_LEVELS = 50

# Powers above this stop being a polynomial fit and start being a numerical
# accident, and a high power of a large count overflows float range.
MAX_POLYNOMIAL_DEGREE = 4

_SAFE_NAME = re.compile(r"[^0-9A-Za-z]+")


def polynomial_column_name(column: str, power: int) -> str:
    return f"{column}_pow{power}"


def dummy_column_name(column: str, level: Any) -> str:
    """Stable, readable name for one indicator column."""

    if isinstance(level, bool):
        token = "true" if level else "false"
    elif isinstance(level, float) and level.is_integer():
        token = str(int(level))
    else:
        token = str(level)
    token = _SAFE_NAME.sub("_", token).strip("_")
    return f"{column}_{token}" if token else f"{column}_level"


def _as_mappings(entries: Any, *, field: str) -> list[Mapping[str, Any]]:
    if entries is None:
        return []
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise ModelTermError(f"{field} must be a list")
    result: list[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ModelTermError(f"each {field} entry must be an object")
        result.append(entry)
    return result


def _as_names(entries: Any, *, field: str) -> list[str]:
    if entries is None:
        return []
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise ModelTermError(f"{field} must be a list of column names")
    return [str(item) for item in entries]


def validate_branch_terms(branch: Mapping[str, Any]) -> None:
    """Check a branch's derived terms without needing the data.

    Shape and coherence only; whether a categorical column is narrow enough to
    expand is a fact about the data, and is enforced at expansion time.
    """

    predictors = [str(item) for item in branch.get("predictors") or []]
    categorical = _as_names(branch.get("categorical"), field="categorical")
    polynomials = _as_mappings(branch.get("polynomials"), field="polynomials")

    duplicated = sorted(set(categorical) & set(predictors))
    if duplicated:
        raise ModelTermError(
            "a column cannot be both a linear predictor and a categorical "
            "expansion: " + ", ".join(duplicated)
            + ". Listing it in `categorical` alone gives the dummy set; listing "
            "it in `predictors` alone gives the linear effect on the code."
        )
    if len(set(categorical)) != len(categorical):
        raise ModelTermError("categorical contains a duplicate column")

    outcome = branch.get("outcome")
    if outcome is not None and str(outcome) in categorical:
        raise ModelTermError(f"the outcome {outcome} cannot also be expanded as categorical")

    seen_polynomial: set[str] = set()
    for entry in polynomials:
        column = entry.get("column")
        if not isinstance(column, str) or not column:
            raise ModelTermError("each polynomials entry requires a column")
        if column in seen_polynomial:
            raise ModelTermError(f"polynomials contains a duplicate column: {column}")
        seen_polynomial.add(column)
        if column in categorical:
            raise ModelTermError(
                f"{column} cannot be both categorical and polynomial"
            )
        if outcome is not None and column == str(outcome):
            raise ModelTermError(f"the outcome {column} cannot carry a polynomial term")
        degree = entry.get("degree")
        if isinstance(degree, bool) or not isinstance(degree, int):
            raise ModelTermError(
                f"polynomial degree for {column} must be a whole number "
                f"(got: {degree!r})"
            )
        if degree < 2 or degree > MAX_POLYNOMIAL_DEGREE:
            raise ModelTermError(
                f"polynomial degree for {column} must be between 2 and "
                f"{MAX_POLYNOMIAL_DEGREE}; degree 1 is just the linear term, so "
                "list the column in predictors instead"
            )


def branch_source_columns(branch: Mapping[str, Any]) -> set[str]:
    """Every source column the branch reads, derived terms included."""

    columns = {str(item) for item in branch.get("predictors") or []}
    columns.update(_as_names(branch.get("categorical"), field="categorical"))
    for entry in _as_mappings(branch.get("polynomials"), field="polynomials"):
        if entry.get("column"):
            columns.add(str(entry["column"]))
    if branch.get("outcome"):
        columns.add(str(branch["outcome"]))
    return columns


def expand_branch_terms(
    frame: pd.DataFrame,
    branch: Mapping[str, Any],
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    """Return (frame with derived columns, expanded predictor list, references).

    The returned predictor list is the model's actual design: linear predictors
    first, in the order given, then each derived term. `references` records the
    dropped level per categorical column so a reader can interpret the
    coefficients.
    """

    validate_branch_terms(branch)
    predictors = [str(item) for item in branch.get("predictors") or []]
    categorical = _as_names(branch.get("categorical"), field="categorical")
    polynomials = _as_mappings(branch.get("polynomials"), field="polynomials")

    if not categorical and not polynomials:
        return frame, list(predictors), {}

    augmented = frame.copy()
    expanded = list(predictors)
    references: dict[str, Any] = {}

    for column in categorical:
        if column not in augmented.columns:
            raise ModelTermError(f"categorical column is not in the data: {column}")
        levels = augmented[column].dropna().unique().tolist()
        levels.sort(key=lambda value: (str(type(value)), value))
        if len(levels) < 2:
            raise ModelTermError(
                f"categorical column {column} has fewer than two observed levels, "
                "so it carries no information to expand"
            )
        if len(levels) > MAX_CATEGORICAL_LEVELS:
            raise ModelTermError(
                f"categorical column {column} has {len(levels)} levels, above the "
                f"limit of {MAX_CATEGORICAL_LEVELS}; expanding it would add one "
                "regressor per level"
            )
        # Drop the first level as the reference category. Keeping every level
        # alongside the intercept is exact collinearity, which is the mistake
        # the assignment language ("one will be dropped") is describing.
        references[column] = levels[0]
        for level in levels[1:]:
            name = dummy_column_name(column, level)
            if name in augmented.columns:
                raise ModelTermError(
                    f"derived dummy column {name} collides with an existing column"
                )
            augmented[name] = (augmented[column] == level).astype(int)
            expanded.append(name)

    for entry in polynomials:
        column = str(entry["column"])
        if column not in augmented.columns:
            raise ModelTermError(f"polynomial column is not in the data: {column}")
        numeric = pd.to_numeric(augmented[column], errors="coerce")
        if numeric.isna().all():
            raise ModelTermError(f"polynomial column {column} is not numeric")
        for power in range(2, int(entry["degree"]) + 1):
            name = polynomial_column_name(column, power)
            if name in augmented.columns:
                raise ModelTermError(
                    f"derived polynomial column {name} collides with an existing column"
                )
            augmented[name] = numeric**power
            expanded.append(name)

    if len(set(expanded)) != len(expanded):
        raise ModelTermError("the expanded design contains a duplicate column")
    return augmented, expanded, references
