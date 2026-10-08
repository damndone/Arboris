"""Count-family options must reach the actual owner and inference core."""
from pathlib import Path
import json

import pytest

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.model_options import ModelOptionsError, bind_new_model_options
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

REFERENCE = Path(__file__).parent / "fixtures/count_models/reference-v3"


@pytest.mark.parametrize("options", [{"dispersion": "mean"}, {"dispersion": "constant"},
                                      {"alpha": .7}, {"alpha": None}])
def test_negative_binomial_options_have_a_bound_owner(options):
    bound = bind_new_model_options("negative_binomial", options)
    assert bound.payload == options
    assert bound.binding.owner_model_id == "negative_binomial_1"


@pytest.mark.parametrize("options", [{"dispersion": "other"}, {"alpha": True},
    {"alpha": "0.7"}, {"alpha": 0}, {"alpha": -1}, {"alpha": float("inf")},
    {"future": 1}, {"dispersion": "constant", "alpha": .7}])
def test_negative_binomial_options_reject_invalid_or_unimplemented_values(options):
    with pytest.raises(ModelOptionsError):
        bind_new_model_options("negative_binomial", options)


def test_glm_fixed_alpha_has_a_bound_owner():
    bound = bind_new_model_options("glm:negative_binomial", {"alpha": 1.})
    assert bound.payload == {"alpha": 1.}
    assert bound.binding.owner_model_id == "glm_1"


@pytest.mark.parametrize("dispersion,data,key", [("mean", "nb2.csv", "nb2"),
                                                   ("constant", "nb1.csv", "nb1")])
def test_nb_option_changes_actual_fit_and_kernel_has_only_regression_coefficients(
    tmp_path, dispersion, data, key,
):
    project = create_project(tmp_path, key)
    outcome = run_workflow(project.root, [REFERENCE/data], mode="auto", model_type="negative_binomial",
        y="y", x=["x1", "x2"], model_options={"dispersion": dispersion})
    root = project.root/"runs"/outcome["run_id"]
    assert outcome["status"] == "completed", read_json(root/"errors.json")
    packet = read_json(root/"model_results/negative_binomial_1.json")
    kernel = read_json(root/kernel_relative_path("negative_binomial_1"))
    reference = json.loads((REFERENCE/"stata.json").read_text())[key]
    assert packet["dispersion"] == dispersion
    assert packet["alpha_estimated"] is True
    assert kernel["param_names"] == ["Intercept", "x1", "x2"]
    assert len(kernel["vcov"]) == 3
    assert kernel["loglik"] == pytest.approx(reference["ll"], abs=1e-6)
    for i, name in enumerate(["_cons", "x1", "x2"]):
        assert kernel["params"][i] == pytest.approx(reference[f"b_{name}"], abs=1e-6)


def test_glm_explicit_alpha_reaches_actual_fit(tmp_path):
    source = Path(__file__).parent/"fixtures/admission/glm_negative_binomial/data.csv"
    project = create_project(tmp_path, "fixed-glm")
    outcome = run_workflow(project.root, [source], mode="auto", model_type="glm:negative_binomial",
        y="y", x=["x1", "x2"], model_options={"alpha": 1.})
    root = project.root/"runs"/outcome["run_id"]
    assert outcome["status"] == "completed", read_json(root/"errors.json")
    packet = read_json(root/"model_results/glm_1.json")
    kernel = read_json(root/kernel_relative_path("glm_1"))
    assert packet["alpha_fixed_value"] == 1.
    assert packet["alpha_estimated"] is False
    assert kernel["model_type"] == "glm:negative_binomial"


def test_glm_postestimation_pairs_are_backed_by_existing_r_cases():
    from workbench.postestimation.registry import VALIDATED
    for family, prefix in [("glm:binomial", "glm_binomial"), ("glm:poisson", "glm_poisson")]:
        for operation in ["wald", "lincom", "nlcom", "lr", "margins"]:
            assert VALIDATED[(family,operation)]
            assert all(case.startswith(prefix+".") for case in VALIDATED[(family,operation)])


def test_count_options_are_declared_for_agent_and_capabilities():
    from workbench.agent.recipes.registry import build_option_vocabulary
    from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS
    from workbench.engine.capabilities import build_capabilities
    for family, fields in [("negative_binomial", {"dispersion", "alpha"}),
                           ("glm:negative_binomial", {"alpha"})]:
        contract=MODEL_FAMILY_CONTRACTS[family]
        assert set(contract.model_options_fields) == fields
        vocabulary=build_option_vocabulary(family)
        assert set(vocabulary["fields"]) == fields
        capability=next(c for c in build_capabilities()["model_types"] if c["key"]==family)
        assert any(p["key"]=="model_options" for p in capability["params"])
    assert MODEL_FAMILY_CONTRACTS["glm:negative_binomial"].model_options_required_fields == ("alpha",)


def test_agent_fixed_dispersion_accepts_native_fractional_response_support():
    import pandas as pd
    from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS
    frame=pd.DataFrame({"y":[0.,.5,2.]})
    branch={"outcome":"y","model_options":{"alpha":.7}}
    for family in ["negative_binomial","glm:negative_binomial"]:
        MODEL_FAMILY_CONTRACTS[family].validate_branch_frame(frame,branch)


@pytest.mark.parametrize("family", ["negative_binomial", "glm:negative_binomial"])
def test_unrepresentable_fixed_alpha_has_a_contract_error(family):
    with pytest.raises(ModelOptionsError, match="finite, strictly positive"):
        bind_new_model_options(family, {"alpha": 10**1000})


def test_fixed_glm_admission_uses_verified_explicit_alpha_reference():
    from workbench.admission import ADMISSION_EVIDENCE, PLANNED
    records=ADMISSION_EVIDENCE["glm:negative_binomial"]
    assert any(item.fixture.endswith("integration-strict-v1811/glm-negative-binomial-v1811-oracle.json")
               and item.test.endswith("test_admission_oracle_glm_negative_binomial.py")
               for item in records["oracle"])
    assert "glm:negative_binomial" not in PLANNED
    assert "v1811_glm_negative_binomial" in ADMISSION_EVIDENCE["glm:negative_binomial"]["live_eval"]
