"""Derived model terms: dummy expansion and polynomial powers."""
from __future__ import annotations

import pandas as pd
import pytest
import statsmodels.api as sm

from workbench.model_terms import (
    MAX_CATEGORICAL_LEVELS,
    ModelTermError,
    branch_source_columns,
    expand_branch_terms,
    validate_branch_terms,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "y": [10.0 + index for index in range(24)],
            "x": [float(index % 7) for index in range(24)],
            "size": [100 + index * 5 for index in range(24)],
            "wave": [1998, 2002, 2006] * 8,
            "region": ["north", "south"] * 12,
        }
    )


def _branch(**overrides):
    return {"branch_id": "m", "outcome": "y", "predictors": ["x"], **overrides}


def test_categorical_expands_to_dummies_with_one_dropped_reference() -> None:
    """Keeping every level alongside the intercept is exact collinearity."""
    frame, predictors, references = expand_branch_terms(
        _frame(), _branch(categorical=["wave"])
    )

    assert predictors == ["x", "wave_2002", "wave_2006"]
    assert references == {"wave": 1998}
    # The dropped level is recoverable: a row is the reference iff every
    # indicator is zero.
    is_reference = (frame["wave_2002"] == 0) & (frame["wave_2006"] == 0)
    assert list(frame.loc[is_reference, "wave"].unique()) == [1998]
    assert set(frame["wave_2002"].unique()) == {0, 1}


def test_categorical_reuses_an_equivalent_persisted_indicator() -> None:
    """A verified source indicator is the same term, not a name collision."""

    source = _frame()
    source["wave_2002"] = (source["wave"] == 2002).astype(int)

    frame, predictors, references = expand_branch_terms(
        source, _branch(categorical=["wave"])
    )

    assert predictors == ["x", "wave_2002", "wave_2006"]
    assert references == {"wave": 1998}
    assert frame["wave_2002"].equals(source["wave_2002"])


def test_polynomial_adds_powers_without_implying_the_linear_term() -> None:
    frame, predictors, _ = expand_branch_terms(
        _frame(), _branch(polynomials=[{"column": "size", "degree": 3}])
    )

    assert predictors == ["x", "size_pow2", "size_pow3"]
    assert frame["size_pow2"].tolist() == [value**2 for value in _frame()["size"]]
    assert frame["size_pow3"].tolist() == [value**3 for value in _frame()["size"]]
    # `size` itself is absent because it was not listed as a predictor; the
    # caller decides whether the linear term belongs in the model.
    assert "size" not in predictors


def test_expansion_reproduces_the_equivalent_formula_fit() -> None:
    """The design must be the one a formula-based fit would produce."""
    import statsmodels.formula.api as smf

    frame = _frame()
    expanded, predictors, _ = expand_branch_terms(
        frame,
        _branch(
            predictors=["x", "size"],
            categorical=["wave", "region"],
            polynomials=[{"column": "size", "degree": 2}],
        ),
    )
    design = sm.add_constant(expanded[predictors])
    fitted = sm.OLS(expanded["y"], design).fit()
    reference = smf.ols(
        "y ~ x + size + I(size**2) + C(wave) + C(region)", frame
    ).fit()

    assert fitted.params["x"] == pytest.approx(reference.params["x"])
    assert fitted.rsquared == pytest.approx(reference.rsquared)
    assert int(fitted.df_model) == int(reference.df_model)


def test_a_column_cannot_be_both_a_linear_predictor_and_a_dummy_set() -> None:
    """These are different models, so the ambiguity must be refused."""
    with pytest.raises(ModelTermError, match="both a linear predictor"):
        validate_branch_terms(_branch(predictors=["x", "wave"], categorical=["wave"]))


@pytest.mark.parametrize(
    "branch, message",
    [
        (_branch(categorical=["wave", "wave"]), "duplicate"),
        (_branch(categorical=["y"]), "outcome"),
        (_branch(polynomials=[{"column": "size", "degree": 1}]), "between 2 and"),
        (_branch(polynomials=[{"column": "size", "degree": 9}]), "between 2 and"),
        (_branch(polynomials=[{"column": "size", "degree": 2.0}]), "whole number"),
        (_branch(polynomials=[{"column": "size", "degree": True}]), "whole number"),
        (_branch(polynomials=[{"degree": 2}]), "requires a column"),
        (_branch(polynomials=[{"column": "y", "degree": 2}]), "outcome"),
        (_branch(categorical=["wave"], polynomials=[{"column": "wave", "degree": 2}]), "both categorical"),
        (_branch(categorical="wave"), "list of column names"),
    ],
)
def test_malformed_terms_fail_closed(branch, message) -> None:
    with pytest.raises(ModelTermError, match=message):
        validate_branch_terms(branch)


def test_a_high_cardinality_column_is_refused_rather_than_exploded() -> None:
    """An id-like column would add one regressor per row."""
    frame = pd.DataFrame(
        {
            "y": range(MAX_CATEGORICAL_LEVELS + 5),
            "x": range(MAX_CATEGORICAL_LEVELS + 5),
            "school_id": range(MAX_CATEGORICAL_LEVELS + 5),
        }
    )
    with pytest.raises(ModelTermError, match="above the limit"):
        expand_branch_terms(frame, _branch(categorical=["school_id"]))


def test_a_constant_column_carries_no_information_to_expand() -> None:
    frame = _frame().assign(only_one=1)
    with pytest.raises(ModelTermError, match="fewer than two observed levels"):
        expand_branch_terms(frame, _branch(categorical=["only_one"]))


def test_a_derived_name_that_collides_with_real_data_is_refused() -> None:
    """Silently overwriting a real column would corrupt the model."""
    frame = _frame().assign(size_pow2=0.0)
    with pytest.raises(ModelTermError, match="collides"):
        expand_branch_terms(frame, _branch(polynomials=[{"column": "size", "degree": 2}]))


def test_a_categorical_collision_with_different_values_is_refused() -> None:
    """A similarly named real column cannot silently change a fixed effect."""

    frame = _frame().assign(wave_2002=1)
    with pytest.raises(ModelTermError, match="collides"):
        expand_branch_terms(frame, _branch(categorical=["wave"]))


def test_a_branch_without_derived_terms_is_left_exactly_as_it_was() -> None:
    frame = _frame()
    returned, predictors, references = expand_branch_terms(frame, _branch())

    assert returned is frame
    assert predictors == ["x"]
    assert references == {}


def test_branch_source_columns_include_derived_term_sources() -> None:
    """A typo in a dummy column must be caught by the schema check."""
    assert branch_source_columns(
        _branch(categorical=["region"], polynomials=[{"column": "size", "degree": 2}])
    ) == {"y", "x", "region", "size"}
