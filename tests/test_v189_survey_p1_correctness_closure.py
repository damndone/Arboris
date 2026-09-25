from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from test_survey_design_engine_v187 import _design_frame, _oracle


def test_bootstrap_replicates_are_finite_and_nonnegative() -> None:
    from workbench.survey import SurveyDesign
    from workbench.survey.replicates import build_replicates

    design = SurveyDesign(
        frame=_design_frame(), strata="stratum", psu="psu", weight="weight"
    )
    weights, scales = build_replicates(design, "bootstrap")

    assert weights.shape[0] == len(design.frame)
    assert len(scales) == weights.shape[1]
    assert np.isfinite(weights).all()
    assert (weights >= 0).all()


def test_custom_brr_requires_balanced_orthogonal_matrix() -> None:
    from workbench.survey import SurveyDesign, SurveyEngineError
    from workbench.survey.replicates import build_replicates

    frame = _design_frame()
    invalid_matrix = np.eye(12, dtype=int)
    invalid_matrix[:, 0] = 1
    design = SurveyDesign(
        frame=frame,
        strata="stratum",
        psu="psu",
        weight="weight",
        hadamard_matrix=invalid_matrix.tolist(),
    )

    with pytest.raises(SurveyEngineError) as excinfo:
        build_replicates(design, "brr")

    assert excinfo.value.code == "SURVEY_BRR_HADAMARD_UNBALANCED"


@pytest.mark.parametrize("column", ["stratum", "psu"])
def test_missing_design_identifier_fails_closed(column: str) -> None:
    from workbench.survey import SurveyDesign, SurveyEngineError

    frame = _design_frame()
    frame.loc[0, column] = None

    with pytest.raises(SurveyEngineError) as excinfo:
        SurveyDesign(frame=frame, strata="stratum", psu="psu", weight="weight")

    assert excinfo.value.code == "SURVEY_DESIGN_IDENTIFIER_MISSING"
    assert excinfo.value.context["column"] == column


def test_design_effects_use_a_valid_reference_when_weights_sum_below_n() -> None:
    from workbench.survey import SurveyDesign

    frame = _design_frame()
    frame["weight"] = frame["weight"] * 0.5
    design = SurveyDesign(
        frame=frame,
        strata="stratum",
        psu="psu",
        weight="weight",
        lonely_psu="remove",
    )

    effects = design.design_effects("y")

    assert np.isfinite(effects.deff)
    assert np.isfinite(effects.standard_error)
    assert effects.deff >= 0


def test_survey_projection_requires_explicit_supported_variance_metadata() -> None:
    from workbench.survey.projection import project_survey_design

    projection = project_survey_design(
        {
            "n_obs": 10,
            "n_strata": 2,
            "n_psu": 4,
            "degf": 2,
            "variance_method": "naive",
        }
    )

    assert projection is not None
    assert projection["projection_status"] == "unavailable"
    assert projection["unavailable_reason"] == "SURVEY_DESIGN_PROJECTION_INVALID"


@pytest.mark.parametrize("model_type", ["probit", "poisson"])
def test_supported_glm_family_is_available_to_the_central_consumer(
    tmp_path: Path, model_type: str
) -> None:
    from test_v189_survey_central_consumer import (
        _materialize_survey_run,
        _rewrite_bound_artifact,
    )
    from workbench.services import survey_consumer_service as survey_service

    project_root, run_root = _materialize_survey_run(tmp_path, model_type="ols")

    def rewrite_family(payload: dict[str, object]) -> None:
        payload["model_type"] = model_type

    _rewrite_bound_artifact(run_root, rewrite_family)
    capability = survey_service.issue_survey_run_capability(
        project_root, run_root.name
    )
    projection = survey_service.read_survey_consumer_projection(capability, "agent")

    assert projection["status"] == "validated"
    assert projection["model_family"] == model_type
