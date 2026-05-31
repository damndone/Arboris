import numpy as np
import pandas as pd

from workbench.econometrics.runner import (
    run_glm,
    run_negative_binomial,
    run_probit,
)


def test_run_probit_binary_y_returns_normalized_result():
    rng = np.random.default_rng(42)
    n = 80
    x1 = rng.normal(size=n)
    latent = -0.2 + 0.9 * x1 + rng.normal(size=n)
    y = (latent > 0).astype(int)
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_probit(frame, y="y", x=["x1"], model_id="probit_1")

    assert result["schema_version"] == 1
    assert result["model_id"] == "probit_1"
    assert result["model_type"] == "probit"
    assert result["engine"] == "statsmodels"
    assert result["nobs"] == n
    assert "x1" in result["coefficients"]
    assert len(result["fitted_values_preview"]) <= 500
    assert "fitted_values" not in result


def test_run_negative_binomial_count_y_returns_irr():
    rng = np.random.default_rng(43)
    n = 120
    x1 = rng.uniform(0, 3, n)
    mu = np.exp(0.2 + 0.4 * x1)
    y = rng.negative_binomial(n=2, p=2 / (2 + mu))
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_negative_binomial(frame, y="y", x=["x1"], model_id="nb_1")

    assert result["model_type"] == "negative_binomial"
    assert result["engine"] == "statsmodels"
    assert "irr" in result
    assert "x1" in result["coefficients"]


def test_run_glm_poisson_returns_requested_family():
    rng = np.random.default_rng(44)
    n = 60
    x1 = rng.uniform(0, 2, n)
    y = rng.poisson(np.exp(0.1 + 0.3 * x1))
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_glm(
        frame,
        y="y",
        x=["x1"],
        model_id="glm_1",
        family_name="poisson",
    )

    assert result["model_type"] == "glm"
    assert result["glm_family"] == "poisson"
    assert result["engine"] == "statsmodels"
