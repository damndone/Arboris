"""v1.8.7 P0 — one result envelope, and marginal effects where they were missing.

Three regression-shaped result contracts carry fourteen fields each, eight of
them identical.  `_require_common` already existed but validated two of the
eight, so the other six were re-declared per family and nothing kept them in
step.  This file drives them onto a single declaration.

It also closes a gap that is not about correctness but about being readable:
`logit`, `probit` and `poisson` produced no marginal effects at all.  Their
coefficients are log-odds and log-rates, which nobody interprets directly, so
the last step of the analysis was left for the user to do by hand.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "marginal_effects"
REPO = Path(__file__).resolve().parents[1]

GLM_FAMILIES = (("logit", "binary"), ("probit", "binary"), ("poisson", "count"))

#: Declared per family with the reason, rather than one loose band covering all
#: three.  logit and poisson agree with R to 1e-6; probit differs by 3.1e-6
#: because statsmodels solves it by Newton and R's glm by IRLS -- a solver
#: difference, not an error, and stating it is the honest form of the claim.
COEFFICIENT_TOLERANCE = {"logit": 1e-6, "poisson": 1e-6, "probit": 1e-5}
AME_TOLERANCE = {"logit": 1e-6, "poisson": 1e-6, "probit": 1e-5}


def _oracle() -> dict:
    return json.loads((FIXTURES / "oracle.json").read_text())


def _glm_frame() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "glm.csv")


def _primary_result(project, outcome, model_type: str) -> dict:
    """Select the model result by name, never by glob order.

    `glob("*.json")[0]` picked the diagnostics packet for probit and the model
    result for logit purely by directory order -- the kind of accident that
    reports a false failure here and would report a false pass just as easily.
    """
    from workbench.artifacts import read_json

    path = (
        project.root / "runs" / outcome["run_id"] / "model_results" / f"{model_type}_1.json"
    )
    assert path.exists(), f"expected {path.name}; found {[p.name for p in path.parent.glob('*.json')]}"
    return read_json(path)


def _run(tmp_path, model_type: str, y: str):
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    project = create_project(tmp_path, f"me_{model_type}")
    source_dir = tmp_path / f"src_{model_type}"
    source_dir.mkdir()
    source = source_dir / "data.csv"
    _glm_frame().to_csv(source, index=False)
    outcome = run_workflow(
        project.root, [source], mode="auto", model_type=model_type, y=y, x=["x1", "x2"]
    )
    return project, outcome


# --------------------------------------------------------------------------
# 1. The shared core must have exactly one definition
# --------------------------------------------------------------------------

def test_shared_result_fields_come_from_one_declaration():
    """Not "the same eight strings appear in three files" -- one source.

    Asserting the field lists merely match would pass while they are still three
    copies that happen to agree today, which is the state this line exists to
    end.  The contracts must read their shared core from the envelope.
    """
    from workbench.contracts.model.result_envelope import RESULT_ENVELOPE_FIELDS

    assert set(RESULT_ENVELOPE_FIELDS) == {
        "contract", "schema_version", "model_id", "model_type",
        "engine", "nobs", "coefficients", "validation",
    }

    source = (REPO / "backend/workbench/contracts/model/v186_model_families.py").read_text()
    assert "result_envelope" in source, (
        "the per-family contracts still declare the shared core themselves"
    )


@pytest.mark.parametrize("missing", [
    "contract", "schema_version", "model_id", "model_type", "engine", "nobs",
    "coefficients", "validation",
])
def test_envelope_validation_rejects_every_missing_shared_field(missing):
    """All eight, not the two `_require_common` used to check."""
    from workbench.contracts.model.result_envelope import (
        ResultEnvelopeError,
        validate_result_envelope,
    )

    payload = {
        "contract": "ordinal_result", "schema_version": 1, "model_id": "ordinal_logit_1",
        "model_type": "ordinal_logit", "engine": "statsmodels", "nobs": 100,
        "coefficients": {}, "validation": {"status": "ok"},
    }
    payload.pop(missing)
    with pytest.raises(ResultEnvelopeError) as excinfo:
        validate_result_envelope(
            payload, packet_name="ordinal_result",
            expected_contract="ordinal_result", expected_model_type="ordinal_logit",
        )
    assert missing in str(excinfo.value)


# --------------------------------------------------------------------------
# 2. Marginal effects on the GLM families
# --------------------------------------------------------------------------

@pytest.mark.parametrize(("model_type", "outcome"), GLM_FAMILIES)
def test_glm_run_produces_marginal_effects(tmp_path, model_type, outcome):
    """A real run, not a function call: the point is that a user can see them."""
    project, result = _run(tmp_path, model_type, outcome)
    assert result["status"] == "completed"
    primary = _primary_result(project, result, model_type)

    assert "marginal_effects" in primary, (
        f"{model_type} still reports only log-odds/log-rate coefficients"
    )
    assert primary["marginal_effects"], "marginal effects present but empty"


@pytest.mark.parametrize(("model_type", "outcome"), GLM_FAMILIES)
def test_glm_marginal_effects_match_the_oracle(tmp_path, model_type, outcome):
    """Average marginal effects against R's glm plus the definition.

    The fit is checked against an independent implementation; the average
    marginal effect is the sample mean of the analytic derivative, which is what
    Stata's `margins, dydx(*)` computes.  No third-party AME package is
    installed here, and the fixture records that distinction rather than
    implying one was used.
    """
    project, result = _run(tmp_path, model_type, outcome)
    primary = _primary_result(project, result, model_type)
    oracle = _oracle()[model_type]

    for term, expected in oracle["coefficients"].items():
        if term == "(Intercept)":
            continue
        assert primary["coefficients"][term]["estimate"] == pytest.approx(
            expected, rel=COEFFICIENT_TOLERANCE[model_type]
        )

    effects = {
        entry.get("term") or entry.get("index"): entry.get("dy/dx", entry.get("estimate"))
        for entry in primary["marginal_effects"]
    }
    for term, expected in oracle["average_marginal_effects"].items():
        assert effects[term] == pytest.approx(expected, rel=AME_TOLERANCE[model_type]), (
            f"{model_type} average marginal effect for {term} disagrees with the oracle"
        )


# --------------------------------------------------------------------------
# 3. Consumers must stop branching per family
# --------------------------------------------------------------------------

def test_agent_evidence_projection_has_no_per_family_branches():
    """Five `if model_type == ...` blocks are the enumeration matrix again.

    Blocks 2 and 3 removed it from the design layer and from `result_shape`;
    leaving it in the consumer just relocates the cost of adding a family.
    """
    source = (REPO / "backend/workbench/agent/context_tools.py").read_text()
    offenders = re.findall(
        r'model_type\s*==\s*"(ordinal_logit|multinomial_logit|survival_cox'
        r'|quantile_regression|time_series\.ets)"',
        source,
    )
    assert not offenders, (
        f"evidence projection still branches per family: {sorted(set(offenders))}"
    )


def test_a_synthetic_family_is_projected_without_touching_consumers():
    """Adding a family must cost a declaration, not a consumer edit.

    Same shape of proof as the engine's orthogonality test: register a family
    that exists only inside this test and check its evidence still travels.
    """
    from workbench.agent.result_shapes import register_result_shape
    from workbench.agent.workflow_contracts import ModelFamilyContract
    from workbench.contracts.model.result_envelope import project_result_evidence

    register_result_shape(
        "synthetic_p0_shape",
        payload_schema={"type": "object", "required": ["coefficients"]},
        payload_version="1.0",
    )
    contract = ModelFamilyContract(
        family="synthetic_p0_family",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=(),
        build_model_params=lambda spec: {},
        expected_artifacts=("synthetic_p0_result",),
        result_shape="synthetic_p0_shape",
    )

    payload = {
        "contract": "synthetic_p0_result", "schema_version": 1,
        "model_id": "synthetic_p0_family_1", "model_type": "synthetic_p0_family",
        "engine": "test", "nobs": 42,
        "coefficients": {"x1": {"estimate": 1.5, "std_error": 0.25}},
        "validation": {"status": "ok"},
    }
    projected = project_result_evidence(payload, contract=contract)

    assert projected["model_type"] == "synthetic_p0_family"
    assert projected["nobs"] == 42
    assert "x1" in projected["coefficients"]
