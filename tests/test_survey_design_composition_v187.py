"""v1.8.7 block 2 — the architecture constraints, not the numbers.

These are the tests that stop the engine from quietly degrading into the thing
it was built to replace: a hand-written matrix of which model family supports
which design.  If they pass, adding a family later costs one declaration and one
oracle test; if they are deleted or weakened, that cost silently returns.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "survey"
REPO = Path(__file__).resolve().parents[1]


def _frame() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "design.csv")


def _wls(frame: pd.DataFrame, weights) -> dict[str, float]:
    x = np.column_stack([np.ones(len(frame)), frame["x1"].to_numpy(), frame["x2"].to_numpy()])
    y = frame["y"].to_numpy()
    w = np.asarray(weights, dtype=float)
    xtw = x.T * w
    beta = np.linalg.solve(xtw @ x, xtw @ y)
    return {"(Intercept)": beta[0], "x1": beta[1], "x2": beta[2]}


# --------------------------------------------------------------------------
# orthogonality: an estimator the engine has never heard of still works
# --------------------------------------------------------------------------

def test_a_synthetic_estimator_gets_design_variance_with_no_design_layer_change():
    """The proof that Design x Estimator x Variance compose freely.

    This estimator belongs to no family, is registered nowhere, and is defined
    entirely inside a test.  If it can obtain a design-based variance, then an
    estimator written by an agent in the sandbox inherits the whole apparatus
    for free -- which is the point of building the engine before the families.
    """
    from workbench.survey import EstimatorSpec, SurveyDesign, estimate_with_design

    design = SurveyDesign(frame=_frame(), strata="stratum", psu="psu", weight="weight")

    def median_of_y(frame: pd.DataFrame, weights) -> dict[str, float]:
        order = np.argsort(frame["y"].to_numpy())
        y = frame["y"].to_numpy()[order]
        w = np.asarray(weights, dtype=float)[order]
        cutoff = 0.5 * w.sum()
        return {"median_y": float(y[np.searchsorted(np.cumsum(w), cutoff)])}

    result = estimate_with_design(
        design,
        EstimatorSpec(name="weighted_median", refit=median_of_y),
        method="replicate",
        replicate_type="jackknife",
    )
    assert set(result.estimates) == {"median_y"}
    assert result.standard_errors["median_y"] > 0
    assert result.degf == 8


def test_capability_tiers_gate_the_variance_channels():
    """Required capability unlocks replicate; the optional one unlocks linearization."""
    from workbench.survey import (
        EstimatorSpec,
        SurveyCompositionError,
        SurveyDesign,
        estimate_with_design,
    )

    design = SurveyDesign(frame=_frame(), strata="stratum", psu="psu", weight="weight")
    minimal = EstimatorSpec(name="refit_only", refit=_wls)

    # The required capability is enough for the general channel.
    assert estimate_with_design(
        design, minimal, method="replicate", replicate_type="jackknife"
    ).standard_errors["x1"] > 0

    # Without an influence function, linearization must be refused -- and refused
    # in a form an agent can act on, not as prose it has to parse.
    with pytest.raises(SurveyCompositionError) as excinfo:
        estimate_with_design(design, minimal, method="linearization")
    assert excinfo.value.code == "SURVEY_ESTIMATOR_LACKS_CAPABILITY"
    assert "influence_function" in excinfo.value.missing_capabilities


def test_composition_failures_name_the_missing_capability_not_just_a_message():
    """A refusal an agent cannot reason about is only marginally better than a crash."""
    from workbench.survey import EstimatorSpec, SurveyCompositionError, SurveyDesign

    design = SurveyDesign(frame=_frame(), strata="stratum", psu="psu", weight="weight")
    spec = EstimatorSpec(name="refit_only", refit=_wls)

    report = design.supported_variance_methods(spec)
    assert report["replicate"] is True
    assert report["linearization"] is False

    error = SurveyCompositionError(
        code="SURVEY_ESTIMATOR_LACKS_CAPABILITY", missing_capabilities=["influence_function"]
    )
    assert isinstance(error.missing_capabilities, list)
    assert error.code


# --------------------------------------------------------------------------
# the two enumeration ceilings must stay down
# --------------------------------------------------------------------------

def test_estimation_delegates_to_the_engine_with_no_per_family_branching():
    """No `if family == ...` around survey logic, and no support matrix.

    The v1.8.5 line already learned this the hard way with
    `materialization-uses-family-contract-not-ols-heuristic`; the same shortcut
    here would make every later family a code change in the design layer.

    The delegation assertion is not decoration.  Scanning for offending branches
    passes trivially while no survey logic exists at all, and would keep passing
    forever if the engine were wired in somewhere this scan never reads -- a
    guard that cannot fail is indistinguishable from one that was deleted.
    """
    import workbench.survey  # noqa: F401  -- the engine must exist to be delegated to

    source = (REPO / "backend/workbench/engine/stages/estimation.py").read_text()
    assert "survey" in source.lower(), (
        "estimation.py never mentions the survey engine, so the branching scan "
        "below is vacuous"
    )
    survey_lines = [
        line for line in source.splitlines()
        if "survey" in line.lower() and line.strip().startswith(("if ", "elif "))
    ]
    offenders = [
        line for line in survey_lines
        if re.search(r"==\s*[\"'](ols|logit|probit|poisson|panel_ols|iv_2sls|did|cs_did"
                     r"|sa_did|dcdh|ordinal_logit|multinomial_logit|survival_cox"
                     r"|quantile_regression)[\"']", line)
    ]
    assert not offenders, f"per-family survey branching found: {offenders}"


def test_result_shape_is_an_open_extension_point():
    """A new output shape must be declarable without editing a closed enum.

    PCA loadings, factor scores, reliability coefficients and cluster
    assignments are all blocked today by a three-value enum; this release opens
    the point even though it does not yet fill it.
    """
    from workbench.agent import workflow_contracts

    source = Path(inspect.getfile(workflow_contracts)).read_text()
    assert "ModelFamilyContract result_shape is invalid" not in source or (
        "register_result_shape" in source
    ), "result_shape still rejects unknown shapes with no way to declare one"

    from workbench.agent.workflow_contracts import register_result_shape

    register_result_shape(
        "synthetic_shape_v187",
        payload_schema={"type": "object", "required": ["synthetic_field"]},
        payload_version="1.0",
    )

    from workbench.agent.workflow_contracts import ModelFamilyContract

    contract = ModelFamilyContract(
        family="synthetic_family_v187",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=(),
        build_model_params=lambda spec: {},
        expected_artifacts=("synthetic_artifact",),
        result_shape="synthetic_shape_v187",
    )
    assert contract.result_shape == "synthetic_shape_v187"


def test_declaring_a_result_shape_requires_its_payload_schema():
    """Opening the point must not reopen the artifact-schema debt.

    v1.8.6 settled this with a minimal payload gate: a new packet declares a
    minimal schema and version, so consumers negotiate rather than guess from
    `artifact_type`.  A shape with no schema would put us back to guessing.
    """
    from workbench.agent.workflow_contracts import ResultShapeError, register_result_shape

    with pytest.raises(ResultShapeError):
        register_result_shape("shape_without_schema_v187", payload_schema=None, payload_version="1.0")


def test_capability_projection_exposes_the_design_variance_matrix():
    """An agent must derive what composes, not hard-code a support list."""
    from workbench.engine.capabilities import build_capabilities

    caps = build_capabilities()
    survey = caps.get("survey_design")
    assert survey, "capability projection does not expose survey design at all"
    assert set(survey["variance_methods"]) >= {"linearization", "replicate"}
    assert set(survey["replicate_types"]) >= {"brr", "jackknife", "bootstrap", "provided"}
    assert set(survey["lonely_psu_policies"]) == {
        "fail", "remove", "adjust", "average", "certainty"
    }


def test_capability_projection_names_the_families_that_take_a_sampling_weight():
    """The form has to know where the design controls belong.

    Without this the frontend either shows the design fields for every family --
    including the ones whose engine refuses a sampling weight -- or carries its
    own copy of the list, which is the enumeration matrix this version spent
    three blocks removing from the backend.  Derived from the family contracts so
    a family that gains or loses `sampling` moves the form with it.
    """
    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS
    from workbench.engine.capabilities import build_capabilities

    published = set(build_capabilities()["survey_design"]["sampling_weight_families"])
    declared = {
        key
        for key, contract in MODEL_FAMILY_CONTRACTS.items()
        if "sampling" in contract.allows_weights
    }
    assert published == declared
    # Guard against the degenerate ways of passing: an empty set, or everything.
    assert "ols" in published
    assert published != set(MODEL_FAMILY_CONTRACTS)
