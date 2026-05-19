import pytest
from workbench.narrative.render import render_template


def test_render_known_template():
    result = render_template("cook_distance_screening", {
        "n_exceed": "34",
        "threshold": "0.0057",
        "max_d": "0.0172",
    })
    assert "34 observations" in result
    assert "conservative screening threshold" in result
    assert "0.0057" in result
    assert "0.0172" in result
    assert "not a model failure" in result


def test_render_unknown_template_raises_keyerror():
    with pytest.raises(KeyError, match="Unknown template_key"):
        render_template("nonexistent_key", {})


def test_render_missing_params_raises_valueerror():
    with pytest.raises(ValueError, match="Missing template params"):
        render_template("cook_distance_screening", {})


def test_render_missing_params_error_lists_missing_names():
    with pytest.raises(ValueError, match="n_exceed"):
        render_template("cook_distance_screening", {"threshold": "0.1"})


def test_render_causal_caution_with_treatment():
    result = render_template("causal_caution_with_treatment", {})
    assert "treatment-like variable" in result
    assert "causal interpretation" in result
