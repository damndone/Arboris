"""Continuous derivatives include every interaction and its covariance."""
import numpy as np
import pytest
from workbench.contracts.model.inference_kernel import build_inference_kernel
from workbench.postestimation.margins import marginal_effects
from workbench.postestimation.design import design_from_patsy
from patsy import dmatrix


def _case():
    group = "C(Q('arm'), Treatment(reference='a'))[T.b]"
    names = ["Intercept", group, "time", f"{group}:Q('time')", "x"]
    matrix = dmatrix("C(Q('arm'), Treatment(reference='a')) * Q('time') + Q('x')",
        {"arm": ["a", "b", "a", "b"], "time": np.arange(4.), "x": np.array([2., 3, 4, 5])})
    design = design_from_patsy(matrix, matrix.design_info)
    covariance = np.eye(5) * .04
    covariance[2, 3] = covariance[3, 2] = -.01
    kernel = build_inference_kernel(model_id="model", model_type="declared", param_names=names,
        params=[1, .3, .2, .4, .5], vcov=covariance, reference_distribution="z", df_resid=None,
        loglik=None, nobs=4, covariance_estimator="nonrobust")
    return kernel, design


@pytest.mark.parametrize("at", ["average", "means"])
def test_fixed_effect_time_derivative_and_covariance_include_interaction(at):
    kernel, design = _case()
    effect = marginal_effects(kernel, design, inverse_link="identity", variables=["time"], at=at)["effects"][0]
    assert effect["estimate"] == pytest.approx(.4)
    assert effect["std_error"] == pytest.approx(np.sqrt(.04 + .25 * .04 - .01))


def test_nonlinear_interaction_delta_gradient_matches_response_difference():
    kernel, design = _case()
    beta = np.array(kernel["params"])
    matrix = np.column_stack(list(design.values()))
    derivative = np.zeros_like(matrix)
    derivative[:, 2] = 1
    derivative[:, 3] = matrix[:, 1]
    def response(b):
        h = 1e-5
        logistic = lambda x: 1 / (1 + np.exp(-x))
        return np.mean((logistic((matrix+h*derivative)@b)-logistic((matrix-h*derivative)@b))/(2*h))
    actual = marginal_effects(kernel, design, inverse_link="logit", variables=["time"])["effects"][0]
    gradient = np.array([(response(beta + np.eye(5)[j]*1e-4)-response(beta - np.eye(5)[j]*1e-4))/2e-4 for j in range(5)])
    assert actual["estimate"] == pytest.approx(response(beta), rel=1e-6)
    assert actual["std_error"] == pytest.approx(np.sqrt(gradient@kernel["vcov"]@gradient), rel=1e-5)


@pytest.mark.parametrize("link", ["identity", "logit"])
def test_additive_colon_column_is_not_an_interaction(link):
    # These are three independent source columns, not a formula product.
    design = {"Intercept": np.ones(4), "x": np.array([.1, .2, .3, .4]),
              "z": np.array([1., 2, 3, 4]), "x:z": np.array([.4, .1, .3, .2])}
    kernel = build_inference_kernel(model_id="model", model_type="declared", param_names=list(design),
        params=[.1, .2, .3, .4], vcov=np.eye(4)*.01, reference_distribution="z", df_resid=None,
        loglik=None, nobs=4, covariance_estimator="nonrobust")
    result = marginal_effects(kernel, design, inverse_link=link, variables=["x", "x:z"])
    renamed = dict(kernel, param_names=["Intercept", "x", "z", "independent"])
    renamed_design = {("independent" if key == "x:z" else key): value for key, value in design.items()}
    reference = marginal_effects(renamed, renamed_design, inverse_link=link, variables=["x", "independent"])
    for actual, expected in zip(result["effects"], reference["effects"]):
        assert actual["estimate"] == pytest.approx(expected["estimate"], rel=1e-12)
        assert actual["std_error"] == pytest.approx(expected["std_error"], rel=1e-12)


def test_formula_metadata_distinguishes_same_public_name_from_true_product():
    data = {"x": np.array([1., 2, 3, 4]), "z": np.array([2., 3, 4, 5]),
            "x:z": np.array([9., 8, 7, 6])}
    additive = dmatrix("x + z + Q('x:z')", data)
    product = dmatrix("x * z", data)
    designs = [design_from_patsy(matrix, matrix.design_info) for matrix in (additive, product)]
    assert list(designs[0]) == list(designs[1]) == ["Intercept", "x", "z", "x:z"]
    assert not designs[0].product_factors
    assert designs[1].product_factors == {"x:z": ("x", "z")}
    kernel = build_inference_kernel(model_id="model", model_type="declared", param_names=list(designs[0]),
        params=[1, 2, 3, 4], vcov=np.eye(4)*.01, reference_distribution="z", df_resid=None,
        loglik=None, nobs=4, covariance_estimator="nonrobust")
    effects = [marginal_effects(kernel, design, inverse_link="identity", variables=["x"])["effects"][0] for design in designs]
    assert effects[0]["estimate"] == pytest.approx(2)
    assert effects[1]["estimate"] == pytest.approx(2 + 4 * data["z"].mean())
    assert effects[1]["std_error"] == pytest.approx(np.sqrt(.01 * (1 + data["z"].mean()**2)))


def test_quoted_colon_variable_in_a_real_formula_interaction():
    matrix = dmatrix("C(Q('arm'), Treatment(reference='a')) * Q('visit:time') + Q('x')",
        {"arm": ["a", "b", "a", "b"], "visit:time": np.arange(4.), "x": np.array([2., 3, 4, 5])})
    design = design_from_patsy(matrix, matrix.design_info, continuous_variables=["visit:time", "x"])
    kernel = build_inference_kernel(model_id="model", model_type="declared", param_names=list(design),
        params=[1, .3, .2, .4, .5], vcov=np.eye(5)*.04, reference_distribution="z", df_resid=None,
        loglik=None, nobs=4, covariance_estimator="nonrobust")
    effect = marginal_effects(kernel, design, inverse_link="identity", variables=["visit:time"])["effects"][0]
    assert effect["estimate"] == pytest.approx(.4)
    assert effect["std_error"] == pytest.approx(np.sqrt(.04 * 1.25))
