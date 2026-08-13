from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest

from workbench.engine.packs.glm_extensions import (
    GLMExtensionPackError,
    fit_beta,
    fit_hurdle_negative_binomial,
    fit_hurdle_poisson,
    fit_zero_inflated_negative_binomial,
    fit_zero_inflated_poisson,
    run_glm_extension,
)


FIXTURE = Path(__file__).parent / "fixtures" / "glm_extensions" / "reference_inputs.json"


def _config(name: str) -> dict[str, object]:
    return json.loads(FIXTURE.read_text())[name]


def _zip_data() -> tuple[np.ndarray, pd.DataFrame]:
    config = _config("zip")
    rng = np.random.default_rng(int(config["seed"]))
    x = rng.normal(size=int(config["n"]))
    zero_probability = 1.0 / (1.0 + np.exp(-float(config["zero_intercept"]) - float(config["zero_slope"]) * x))
    mean = np.exp(float(config["count_intercept"]) + float(config["count_slope"]) * x)
    structural_zero = rng.random(x.size) < zero_probability
    y = np.where(structural_zero, 0, rng.poisson(mean)).astype(float)
    return y, pd.DataFrame({"x": x})


def _zinb_data() -> tuple[np.ndarray, pd.DataFrame]:
    config = _config("zinb")
    rng = np.random.default_rng(int(config["seed"]))
    x = rng.normal(size=int(config["n"]))
    zero_probability = 1.0 / (1.0 + np.exp(-float(config["zero_intercept"]) - float(config["zero_slope"]) * x))
    mean = np.exp(float(config["count_intercept"]) + float(config["count_slope"]) * x)
    alpha = float(config["alpha"])
    shape = 1.0 / alpha
    gamma_mean = rng.gamma(shape=shape, scale=alpha * mean)
    structural_zero = rng.random(x.size) < zero_probability
    y = np.where(structural_zero, 0, rng.poisson(gamma_mean)).astype(float)
    return y, pd.DataFrame({"x": x})


def _hurdle_data(*, negative_binomial: bool) -> tuple[np.ndarray, pd.DataFrame]:
    config = _config("hurdle")
    rng = np.random.default_rng(int(config["seed"]) + int(negative_binomial))
    x = rng.normal(size=int(config["n"]))
    positive_probability = 1.0 / (1.0 + np.exp(-float(config["positive_intercept"]) - float(config["positive_slope"]) * x))
    positive = rng.random(x.size) < positive_probability
    mean = np.exp(float(config["count_intercept"]) + float(config["count_slope"]) * x)
    if negative_binomial:
        alpha = float(config["alpha"])
        gamma_mean = rng.gamma(shape=1.0 / alpha, scale=alpha * mean)
        counts = rng.poisson(gamma_mean)
    else:
        counts = rng.poisson(mean)
    while np.any(positive & (counts == 0)):
        redraw = positive & (counts == 0)
        if negative_binomial:
            gamma_mean = rng.gamma(shape=1.0 / float(config["alpha"]), scale=float(config["alpha"]) * mean[redraw])
            counts[redraw] = rng.poisson(gamma_mean)
        else:
            counts[redraw] = rng.poisson(mean[redraw])
    y = np.where(positive, counts, 0).astype(float)
    return y, pd.DataFrame({"x": x})


def _beta_data() -> tuple[np.ndarray, pd.DataFrame]:
    config = _config("beta")
    rng = np.random.default_rng(int(config["seed"]))
    x = rng.normal(size=int(config["n"]))
    mean = 1.0 / (1.0 + np.exp(-float(config["mean_intercept"]) - float(config["mean_slope"]) * x))
    precision = float(config["precision"])
    y = rng.beta(mean * precision, (1.0 - mean) * precision)
    return y, pd.DataFrame({"x": x})


@pytest.mark.parametrize(
    ("fitter", "data", "processes"),
    [
        (fit_zero_inflated_poisson, _zip_data, {"count", "zero"}),
        (fit_zero_inflated_negative_binomial, _zinb_data, {"count", "zero", "dispersion"}),
        (fit_hurdle_poisson, lambda: _hurdle_data(negative_binomial=False), {"zero", "positive_count"}),
        (fit_hurdle_negative_binomial, lambda: _hurdle_data(negative_binomial=True), {"zero", "positive_count", "dispersion"}),
    ],
)
def test_count_extensions_are_explicit_and_emit_bounded_estimand_layers(fitter, data, processes):
    y, X = data()
    packet = fitter(y, X, predictor_columns=["x"])
    result = packet["result"]

    assert packet["operation_id"].startswith("glm.")
    assert result["status"] == "completed"
    assert set(result["coefficient_estimands"]) == processes
    assert result["mean_estimands"]
    assert result["zero_probability_estimands"]
    assert result["scope"]["limitations"]
    assert result["scope"]["not_claimed"]
    assert result["diagnostics"]["covariance_finite"] is True
    json.dumps(packet)


def test_beta_extension_rejects_boundaries_and_keeps_zero_probability_not_applicable():
    y, X = _beta_data()
    packet = fit_beta(y, X, predictor_columns=["x"])
    result = packet["result"]

    assert packet["operation_id"] == "glm.beta"
    assert result["status"] == "completed"
    assert set(result["coefficient_estimands"]) == {"mean", "precision"}
    assert "expected_response" in result["mean_estimands"]
    assert result["zero_probability_estimands"]["not_applicable"]["applicable"] is False

    with pytest.raises(GLMExtensionPackError, match="GLM_BETA_BOUNDARY_RESPONSE"):
        fit_beta(np.array([0.2, 0.4, 1.0, 0.6]), pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0]}), predictor_columns=["x"])


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="base R is required for the independent hurdle oracle")
def test_hurdle_positive_count_inference_is_labeled_and_matches_base_r(
    tmp_path: Path,
) -> None:
    """Approximate inference must be explicit and numerically anchored outside Python."""

    y, X = _hurdle_data(negative_binomial=False)
    packet = fit_hurdle_poisson(y, X, predictor_columns=["x"])
    result = packet["result"]
    inference = result["inference"]["positive_count"]

    assert inference == {
        "standard_error_method": "bfgs_inverse_hessian_approximation",
        "p_value_method": "normal_wald_approximation",
        "p_value_status": "approximate",
    }
    assert any(
        "approximate" in limitation.lower()
        for limitation in result["scope"]["limitations"]
    )

    source = tmp_path / "hurdle.csv"
    pd.DataFrame({"y": y, "x": X["x"]}).to_csv(source, index=False)
    completed = subprocess.run(
        [
            "Rscript",
            "--vanilla",
            str(FIXTURE.with_name("generate_hurdle_oracle.R")),
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    oracle = json.loads(completed.stdout)
    coefficients = result["coefficient_estimands"]["positive_count"]
    assert [coefficients[name]["estimate"] for name in ("const", "x")] == pytest.approx(
        oracle["estimate"], abs=1e-6
    )
    assert [coefficients[name]["standard_error"] for name in ("const", "x")] == pytest.approx(
        oracle["standard_error"], rel=0.005
    )


def test_hurdle_result_contract_rejects_unlabeled_approximate_inference() -> None:
    """Dropping the approximation label must fail at the public result boundary."""

    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.glm_extensions import GLMExtensionResultEnvelope

    y, X = _hurdle_data(negative_binomial=False)
    packet = fit_hurdle_poisson(y, X, predictor_columns=["x"])
    packet["result"]["inference"]["positive_count"].pop("p_value_status")

    with pytest.raises(ContractError, match="hurdle positive-count inference metadata"):
        GLMExtensionResultEnvelope.from_dict(packet)


def test_count_inputs_reject_non_integer_counts_and_nonfinite_values():
    X = pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0]})
    with pytest.raises(GLMExtensionPackError, match="GLM_INVALID_COUNT"):
        fit_zero_inflated_poisson(np.array([0.0, 1.5, 2.0, 1.0]), X, predictor_columns=["x"])
    with pytest.raises(GLMExtensionPackError, match="GLM_NONFINITE_INPUT"):
        fit_hurdle_poisson(np.array([0.0, 1.0, np.nan, 2.0]), X, predictor_columns=["x"])


def test_zero_inflated_and_hurdle_process_semantics_cannot_be_auto_selected():
    y, X = _zip_data()
    with pytest.raises(GLMExtensionPackError, match="GLM_ZERO_PROCESS_POLICY"):
        fit_hurdle_poisson(y, X, predictor_columns=["x"], zero_process_semantics="auto")


def test_dispatcher_returns_stable_rejection_without_executing_formula_or_callback():
    y, X = _zip_data()
    rejected = run_glm_extension(
        "glm.zero_inflated_poisson",
        y,
        "y ~ x",
        predictor_columns=["x"],
    )
    assert rejected["result"]["status"] == "rejected"
    assert rejected["result"]["reason_code"] == "GLM_BAD_INPUT"

    with pytest.raises(GLMExtensionPackError, match="GLM_BAD_INPUT"):
        fit_zero_inflated_poisson(y, X, predictor_columns=["x"], callback=lambda _: None)


def test_nonconvergence_is_not_reported_as_completed():
    y, X = _zip_data()
    rejected = run_glm_extension(
        "glm.zero_inflated_poisson",
        y,
        X,
        predictor_columns=["x"],
        maxiter=1,
    )
    assert rejected["result"]["status"] in {"rejected", "failed"}
    assert rejected["result"]["reason_code"] in {
        "GLM_NONCONVERGENCE",
        "GLM_NUMERICAL_FAILURE",
    }
