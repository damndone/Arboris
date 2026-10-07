"""Fixed-alpha GLM-NB is reachable through the persisted public owner."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from workbench.admission import ADMISSION_EVIDENCE, PLANNED
from workbench.agent.postestimation_steps import execute_postestimation_step
from workbench.agent.workflow import WorkflowExecutionError
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.postestimation.registry import validated_operations
from workbench.projects import create_project

DATA = Path(__file__).parent / "fixtures/postestimation/data.csv"
REFERENCE = DATA.parent / "glm_negative_binomial_v1811/native-r/oracle.json"
REQUESTS = {
    "wald_joint": ("wald", {"constraints": [{"terms": {"x1": 1}, "value": 0}, {"terms": {"x2": 1}, "value": 0}]}),
    "wald_shifted": ("wald", {"constraints": [{"terms": {"x1": 1, "x2": -1}, "value": 1}]}),
    "lincom": ("lincom", {"terms": {"x1": 1, "x2": 2}, "constant": -0.5}),
    "nlcom": ("nlcom", {"expression": "x1 / x2"}),
    "lr_drop_x2_x3": ("lr", {}),
    "average": ("margins", {"variables": ["x1", "x2"], "at": "average"}),
    "at_means": ("margins", {"variables": ["x1", "x2"], "at": "means"}),
}


@pytest.fixture(scope="module")
def owner(tmp_path_factory):
    project = create_project(tmp_path_factory.mktemp("glm-nb-public"), "oracle").root
    runs = {}
    for label, x, alpha in (("full", ["x1", "x2", "x3"], 1.0), ("restricted", ["x1"], 1.0), ("other_alpha", ["x1"], 0.5)):
        outcome = run_workflow(project, [DATA], mode="auto", model_type="glm:negative_binomial", y="ynb", x=x, model_options={"alpha": alpha})
        assert outcome["status"] == "completed", outcome
        runs[label] = outcome["run_id"]
    return project, runs


def execute(owner, operation, spec):
    project, runs = owner
    step = SimpleNamespace(operation_id="postestimation." + operation, depends_on=(), spec={"model_ref": "model:glm_1", **spec})
    return execute_postestimation_step(project, runs["full"], step)[0]


def test_native_evidence_opens_all_five_operations_with_verified_live_eval():
    assert set(validated_operations("glm:negative_binomial")) == {"wald", "lr", "lincom", "nlcom", "margins"}
    assert any(item.fixture.endswith("glm_negative_binomial_v1811/native-r/oracle.json") for item in ADMISSION_EVIDENCE["glm:negative_binomial"]["oracle"])
    assert "glm:negative_binomial" not in PLANNED
    assert "v1811_glm_negative_binomial" in ADMISSION_EVIDENCE["glm:negative_binomial"]["live_eval"]


@pytest.mark.parametrize("case", REQUESTS)
def test_public_completed_owner_matches_native_full_precision(owner, case):
    reference = read_json(REFERENCE)["full_precision"]
    operation, spec = REQUESTS[case]
    if operation == "lr":
        spec = {"restricted_model_ref": "model:glm_1", "restricted_model_run_id": owner[1]["restricted"]}
    result = execute(owner, operation, spec)
    if operation == "margins":
        for effect in result["effects"]:
            expected = reference["margins"][case][effect["variable"]]
            assert effect["estimate"] == pytest.approx(float(expected["estimate"]), rel=1e-6)
            assert effect["std_error"] == pytest.approx(float(expected["std_error"]), rel=1e-5)
    else:
        expected = reference[case]
        for key in ("statistic", "estimate", "std_error", "loglik_full", "loglik_restricted"):
            if key in expected:
                assert result[key] == pytest.approx(float(expected[key]), rel=1e-6), key
        if "p_value" in expected:
            assert result["p_value"] == pytest.approx(float(expected["p_value"]), rel=1e-5)
        for key in ("df", "df_num", "df_den", "distribution"):
            if key in expected:
                assert result[key] == (expected[key] if key == "distribution" else float(expected[key]))


def test_public_lr_refuses_different_fixed_alpha(owner):
    with pytest.raises(WorkflowExecutionError, match="likelihood|settings|alpha|comparable"):
        execute(owner, "lr", {"restricted_model_ref": "model:glm_1", "restricted_model_run_id": owner[1]["other_alpha"]})


@pytest.mark.parametrize("term", ["alpha", "lnalpha"])
def test_fixed_alpha_is_not_a_regression_coefficient(owner, term):
    with pytest.raises(WorkflowExecutionError, match="coefficient|parameter|Unknown|unknown"):
        execute(owner, "wald", {"constraints": [{"terms": {term: 1}, "value": 0}]})
