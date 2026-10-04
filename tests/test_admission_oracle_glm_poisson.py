"""Independent R admission oracle for glm_poisson; real Workbench workflow."""
import math
from pathlib import Path

import pytest
from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures/admission/glm_poisson"
ORACLE = read_json(FIXTURES / "oracle.json")


@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    project = create_project(tmp_path_factory.mktemp("oracle-glm_poisson"), "oracle")
    outcome = run_workflow(project.root, [FIXTURES / "data.csv"], mode="auto",
                           model_type='glm:poisson', y='y', x=['x1', 'x2'], **{})
    root = project.root / "runs" / outcome["run_id"]
    assert outcome["status"] == "completed", read_json(root / "errors.json")
    return read_json(root / kernel_relative_path('glm_1'))


def test_coefficients_and_standard_errors_match_r(fitted):
    names = fitted["param_names"]
    assert set(names) == set(ORACLE["coefficients"]), (names, ORACLE["coefficients"])
    assert fitted["nobs"] == ORACLE["meta"]["n"]
    rows = []
    for index, term in enumerate(names):
        rows.append((term, fitted["params"][index], ORACLE["coefficients"][term],
                     math.sqrt(fitted["vcov"][index][index]), ORACLE["std_error"][term]))
    print("first three coefficients and SE (Workbench / R):", rows[:3])
    print("kernel settings:", {key: fitted.get(key) for key in (
        "covariance_estimator", "df_method", "reference_distribution", "df_resid")})
    print("max absolute differences:", max(abs(a-b) for _,a,b,_,_ in rows),
          max(abs(a-b) for _,_,_,a,b in rows))
    errors = []
    for term, estimate, reference, se, reference_se in rows:
        if abs(estimate-reference) > 1e-8:
            errors.append((term, "estimate", estimate, reference, estimate-reference))
        # LMM's 1e-4 allowance is exclusively for REML optimizer differences.
        if abs(se-reference_se) > 1e-06:
            errors.append((term, "std_error", se, reference_se, se-reference_se))
    assert not errors, errors


def test_inference_settings_match_reference(fitted):
    for key in ("covariance_estimator", "df_method", "reference_distribution"):
        assert fitted[key] == ORACLE["inference"][key], key
