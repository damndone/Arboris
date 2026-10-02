"""v1.8.10 step 2a: post-estimation reads the kernel and agrees with R.

Each family is fitted once through the real pipeline on the committed oracle
frame; the kernels those runs persisted are what the operations read. The
oracle (tests/fixtures/postestimation/oracle.json) is R: car::linearHypothesis,
car::deltaMethod (symbolic derivatives) and lmtest::lrtest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.postestimation import PostestimationRefusal, lincom, lr_test, nlcom, wald_test
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "postestimation"
ORACLE = json.loads((FIXTURES / "oracle.json").read_text())

# family -> (model_type, outcome, extra run arguments)
FAMILIES = {
    "ols": ("ols", "y", {"covariance": "unadjusted"}),
    "ols_robust": ("ols", "y", {}),
    "logit": ("logit", "yb", {}),
    "probit": ("probit", "yb", {}),
    "poisson": ("poisson", "yc", {}),
}
WITH_LR = ("ols", "logit", "probit", "poisson")

JOINT = [{"terms": {"x1": 1}, "value": 0}, {"terms": {"x2": 1}, "value": 0}]
SHIFTED = [{"terms": {"x1": 1, "x2": -1}, "value": 1}]
REL = 1e-6


def _fit(root: Path, name: str, model_type: str, y: str, x: list[str], extra: dict) -> dict:
    project = create_project(root, name)
    outcome = run_workflow(
        project.root, [FIXTURES / "data.csv"], mode="auto", model_type=model_type, y=y, x=x, **extra
    )
    assert outcome["status"] == "completed", outcome
    run_root = project.root / "runs" / outcome["run_id"]
    return read_json(run_root / kernel_relative_path(f"{model_type}_1"))


@pytest.fixture(scope="module")
def kernels(tmp_path_factory) -> dict[str, dict]:
    root = tmp_path_factory.mktemp("postestimation")
    out = {}
    for family, (model_type, y, extra) in FAMILIES.items():
        out[family] = _fit(root, family, model_type, y, ["x1", "x2", "x3"], extra)
        if family in WITH_LR:
            out[f"{family}_restricted"] = _fit(root, f"{family}_r", model_type, y, ["x1"], extra)
    return out


@pytest.mark.parametrize("family", list(FAMILIES))
def test_the_kernel_reproduces_rs_estimates(kernels, family) -> None:
    kernel = kernels[family]
    expected = ORACLE["families"][family]["params"]
    params = dict(zip(kernel["param_names"], kernel["params"]))
    for name in ("x1", "x2", "x3"):
        assert params[name] == pytest.approx(expected[name], rel=REL)


@pytest.mark.parametrize("family", list(FAMILIES))
@pytest.mark.parametrize(("case", "constraints"), [("wald_joint", JOINT), ("wald_shifted", SHIFTED)])
def test_wald_agrees_with_car_linear_hypothesis(kernels, family, case, constraints) -> None:
    result = wald_test(kernels[family], constraints)
    expected = ORACLE["families"][family][case]
    assert result["distribution"] == expected["distribution"]
    assert result["df_num"] == expected["df_num"]
    if expected["distribution"] == "F":
        assert result["df_den"] == expected["df_den"]
    assert result["statistic"] == pytest.approx(expected["statistic"], rel=REL)
    assert result["p_value"] == pytest.approx(expected["p_value"], rel=1e-5)


@pytest.mark.parametrize("family", list(FAMILIES))
def test_lincom_agrees_with_car_delta_method(kernels, family) -> None:
    result = lincom(kernels[family], {"x1": 1, "x2": 2}, constant=-0.5)
    expected = ORACLE["families"][family]["lincom"]
    assert result["estimate"] == pytest.approx(expected["estimate"], rel=REL)
    assert result["std_error"] == pytest.approx(expected["std_error"], rel=REL)
    assert result["ci"][0] < result["estimate"] < result["ci"][1]


@pytest.mark.parametrize("family", list(FAMILIES))
def test_nlcom_agrees_with_symbolic_differentiation(kernels, family) -> None:
    result = nlcom(kernels[family], "x1 / x2")
    expected = ORACLE["families"][family]["nlcom"]
    assert result["estimate"] == pytest.approx(expected["estimate"], rel=REL)
    assert result["std_error"] == pytest.approx(expected["std_error"], rel=1e-6)


@pytest.mark.parametrize("family", WITH_LR)
def test_lr_agrees_with_lmtest(kernels, family) -> None:
    result = lr_test(kernels[family], kernels[f"{family}_restricted"])
    expected = ORACLE["families"][family]["lr_drop_x2_x3"]
    assert result["df"] == expected["df"]
    assert result["loglik_full"] == pytest.approx(expected["loglik_full"], rel=REL)
    assert result["statistic"] == pytest.approx(expected["statistic"], rel=1e-5)
    assert result["p_value"] == pytest.approx(expected["p_value"], rel=1e-4)
    assert result["dropped_parameters"] == ["x2", "x3"]


def test_the_reference_distribution_follows_the_kernel(kernels) -> None:
    """Same data, same hypothesis: F for the classical OLS fit, chi2 for the
    HC1 fit that reports z p-values -- each matches the model's own p-values."""
    assert wald_test(kernels["ols"], JOINT)["distribution"] == "F"
    assert wald_test(kernels["ols_robust"], JOINT)["distribution"] == "chi2"
    assert lincom(kernels["ols"], {"x1": 1})["distribution"] == "t"
    assert lincom(kernels["logit"], {"x1": 1})["distribution"] == "z"


def test_lincom_of_one_coefficient_is_that_coefficient(kernels) -> None:
    kernel = kernels["logit"]
    params = dict(zip(kernel["param_names"], kernel["params"]))
    result = lincom(kernel, {"x1": 1})
    assert result["estimate"] == pytest.approx(params["x1"], rel=1e-12)


# --- refusals: each names the property that is missing -------------------------


def _refusal(call) -> PostestimationRefusal:
    with pytest.raises(PostestimationRefusal) as caught:
        call()
    return caught.value


def test_lr_refuses_a_robust_covariance(kernels) -> None:
    refusal = _refusal(lambda: lr_test(kernels["ols_robust"], kernels["ols_restricted"]))
    assert refusal.code == "NOT_MODEL_BASED_VARIANCE"
    assert "HC1" in refusal.message and "Wald" in refusal.message


def test_lr_refuses_models_estimated_on_different_samples(kernels) -> None:
    restricted = dict(kernels["logit_restricted"], estimation_sample_fingerprint="rows-sha256:other")
    assert _refusal(lambda: lr_test(kernels["logit"], restricted)).code == "DIFFERENT_SAMPLES"


def test_lr_refuses_sampling_weights(kernels) -> None:
    full = dict(kernels["logit"], weights="sampling")
    assert _refusal(lambda: lr_test(full, kernels["logit_restricted"])).code == "SAMPLING_WEIGHTS"


def test_lr_refuses_models_that_are_not_nested(kernels) -> None:
    assert _refusal(lambda: lr_test(kernels["logit_restricted"], kernels["logit"])).code == "NOT_NESTED"


def test_lr_refuses_different_families(kernels) -> None:
    assert _refusal(lambda: lr_test(kernels["logit"], kernels["probit_restricted"])).code == "DIFFERENT_MODELS"


def test_a_model_without_a_likelihood_is_refused_with_its_own_reason(kernels) -> None:
    full = dict(kernels["logit"], interfaces=["coef_vcov"],
                unavailable={"loglik": "Instrumental-variables estimates have no likelihood."})
    refusal = _refusal(lambda: lr_test(full, kernels["logit_restricted"]))
    assert refusal.code == "INTERFACE_UNAVAILABLE" and "no likelihood" in refusal.message


def test_dependent_constraints_are_refused_not_silently_reduced(kernels) -> None:
    doubled = [{"terms": {"x1": 1}, "value": 0}, {"terms": {"x1": 2}, "value": 0}]
    assert _refusal(lambda: wald_test(kernels["ols"], doubled)).code == "DEPENDENT_CONSTRAINTS"


def test_an_unknown_parameter_lists_the_real_ones(kernels) -> None:
    refusal = _refusal(lambda: lincom(kernels["ols"], {"education": 1}))
    assert refusal.code == "UNKNOWN_PARAMETER" and "x1" in refusal.message


def test_parameters_outside_the_stored_covariance_are_refused(kernels) -> None:
    kernel = dict(kernels["ols"])
    kernel["vcov"] = [[kernel["vcov"][1][1]]]
    kernel["vcov_param_names"] = ["x1"]
    kernel["vcov_scope"] = "focal"
    assert lincom(kernel, {"x1": 1})["std_error"] > 0
    assert _refusal(lambda: lincom(kernel, {"x2": 1})).code == "COVARIANCE_NOT_STORED"


@pytest.mark.parametrize(
    "expression",
    ["__import__('os').system('true')", "x1.real", "[x1]", "x1 if x2 else x3", "open('f')", "lambda: 1"],
)
def test_nlcom_never_evaluates_anything_but_arithmetic(kernels, expression) -> None:
    assert _refusal(lambda: nlcom(kernels["ols"], expression)).code in {"INVALID_EXPRESSION", "UNKNOWN_PARAMETER"}


def test_nlcom_accepts_quoted_parameter_names(kernels) -> None:
    kernel = kernels["ols"]
    bare = nlcom(kernel, "exp(x1) - x2")
    quoted = nlcom(kernel, 'exp(b["x1"]) - b["x2"]')
    assert quoted["estimate"] == bare["estimate"] and quoted["std_error"] == bare["std_error"]


def test_nlcom_warns_when_the_delta_method_is_unreliable(kernels) -> None:
    """x3 is small relative to its standard error, so 1/x3 bends sharply."""
    assert nlcom(kernels["ols"], "1 / x3")["warnings"]
    assert not nlcom(kernels["ols"], "x1 + x2")["warnings"]


def test_a_joint_test_over_300_parameters_stays_within_budget() -> None:
    """Budget: Wald, lincom and LR read the kernel and finish within 0.5 s."""
    import time

    import numpy as np

    from workbench.contracts.model.inference_kernel import build_inference_kernel

    k = 300
    rng = np.random.default_rng(3)
    factor = rng.normal(size=(k, k))
    names = [f"b{i}" for i in range(k)]
    kernel = build_inference_kernel(
        model_id="ols_1", model_type="ols", param_names=names, params=rng.normal(size=k),
        vcov=factor @ factor.T / k + np.eye(k), reference_distribution="t", df_resid=5000.0,
        loglik=-1.0, nobs=5301, covariance_estimator="nonrobust",
    )
    constraints = [{"terms": {name: 1}, "value": 0} for name in names]
    started = time.perf_counter()
    result = wald_test(kernel, constraints)
    lincom(kernel, dict.fromkeys(names, 1.0))
    assert time.perf_counter() - started < 0.5
    assert result["df_num"] == k
