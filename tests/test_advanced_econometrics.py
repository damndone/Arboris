import numpy as np
import pandas as pd
import pytest

from workbench.econometrics import runner
from workbench.econometrics.normalize import normalize_statsmodels_result
from workbench.econometrics.runner import (
    run_glm,
    run_negative_binomial,
    run_probit,
)
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


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


class _FailingModel:
    def fit(self, **kwargs):
        raise RuntimeError("singular matrix")


@pytest.mark.parametrize(
    ("name", "fit_call"),
    [
        (
            "Probit",
            lambda frame: run_probit(frame, y="y", x=["x1"], model_id="probit_bad"),
        ),
        (
            "Negative Binomial",
            lambda frame: run_negative_binomial(frame, y="y", x=["x1"], model_id="nb_bad"),
        ),
        (
            "GLM",
            lambda frame: run_glm(
                frame,
                y="y",
                x=["x1"],
                model_id="glm_bad",
                family_name="poisson",
            ),
        ),
    ],
)
def test_advanced_model_fit_errors_include_root_cause(monkeypatch, name, fit_call):
    frame = pd.DataFrame({"y": [0, 1, 1, 2], "x1": [0.1, 0.2, 0.3, 0.4]})
    monkeypatch.setattr(runner.smf, name.lower().replace(" ", ""), lambda **kwargs: _FailingModel())

    with pytest.raises(ValueError, match="Root cause: singular matrix") as exc_info:
        fit_call(frame)

    assert name in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


class _GuardedValues:
    def __iter__(self):
        for _ in range(500):
            yield 1.0
        raise AssertionError("preview conversion should not consume beyond the cap")


class _FakeModel:
    exog_names = ["x1"]


class _FakeFitted:
    model = _FakeModel()
    params = [1.0]
    bse = [0.1]
    pvalues = [0.01]
    nobs = 1000
    fittedvalues = _GuardedValues()
    resid = _GuardedValues()


def test_normalize_statsmodels_result_caps_preview_conversion():
    result = normalize_statsmodels_result(_FakeFitted(), "ols_guard")

    assert len(result["fitted_values_preview"]) == 500
    assert len(result["residuals_preview"]) == 500


def test_run_workflow_explicit_probit_writes_model_result(tmp_path):
    rng = np.random.default_rng(45)
    n = 80
    x = rng.normal(size=n)
    y = (-0.1 + 0.8 * x + rng.normal(size=n) > 0).astype(int)
    source = tmp_path / "binary.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "explicit_probit")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="probit",
    )

    model_path = project.root / "runs" / result["run_id"] / "model_results" / "probit_1.json"
    model_result = read_json(model_path)
    assert model_result["model_type"] == "probit"
    assert model_result["engine"] == "statsmodels"


def test_run_workflow_auto_still_routes_binary_to_logit(tmp_path):
    rng = np.random.default_rng(46)
    n = 80
    x = rng.normal(size=n)
    y = (-0.1 + 0.8 * x + rng.normal(size=n) > 0).astype(int)
    source = tmp_path / "binary.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "auto_binary")

    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])

    model_dir = project.root / "runs" / result["run_id"] / "model_results"
    assert (model_dir / "logit_1.json").exists()
    assert not (model_dir / "probit_1.json").exists()
