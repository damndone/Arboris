from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.evaluation.linear_mixed_effects._candidate import require_candidate_module


ROOT = Path(__file__).parents[2] / "fixtures" / "models" / "linear_mixed_effects"
OPTIONS = {
    "subject_id": "participant_id",
    "time": "week",
    "group": "arm",
    "fit_method": "reml",
    "random_slope": True,
}


def _prepare(frame: pd.DataFrame) -> object:
    module = require_candidate_module("workbench.engine.packs.linear_mixed_effects.input")
    return module.prepare_lmm_input(
        frame,
        outcome="score",
        controls=["baseline_score"],
        options=OPTIONS,
    )


@pytest.mark.parametrize(
    ("fixture_name", "mutate", "expected_code"),
    [
        ("missing_subject_id.csv", lambda frame: frame, "LMM_SUBJECT_ID_MISSING"),
        (
            "known_truth.csv",
            lambda frame: frame.assign(week="not-a-number"),
            "LMM_TIME_NOT_NUMERIC",
        ),
        (
            "known_truth.csv",
            lambda frame: frame.assign(arm=frame["arm"].mask(frame.index == 0, "other")),
            "LMM_GROUP_NOT_BINARY",
        ),
        (
            "known_truth.csv",
            lambda frame: frame.assign(
                arm=frame["arm"].mask(
                    (frame["participant_id"] == "C001") & (frame["week"] == 0),
                    "treated",
                )
            ),
            "LMM_GROUP_VARIES_WITHIN_SUBJECT",
        ),
        (
            "single_observation_per_subject.csv",
            lambda frame: frame,
            "LMM_INSUFFICIENT_REPEATED_OBSERVATIONS",
        ),
    ],
)
def test_invalid_input_fails_with_the_locked_code(
    fixture_name: str, mutate, expected_code: str
) -> None:
    frame = mutate(pd.read_csv(ROOT / fixture_name))
    module = require_candidate_module("workbench.engine.packs.linear_mixed_effects.input")

    with pytest.raises(module.LmmInputError, match=expected_code):
        _prepare(frame)


@pytest.mark.parametrize(
    ("kwargs", "expected_code", "expected_status"),
    [
        (
            {
                "converged": True,
                "random_slope": False,
                "covariance_matrix": [[0.7, 0.1], [0.1, 0.3]],
                "residual_variance": 0.5,
            },
            "LMM_INVALID_RANDOM_SLOPE_CONFIGURATION",
            "blocked",
        ),
        (
            {
                "converged": False,
                "random_slope": True,
                "covariance_matrix": [[0.7, 0.0], [0.0, 0.3]],
                "residual_variance": 0.5,
            },
            "LMM_CONVERGENCE_FAILED",
            "failed",
        ),
        (
            {
                "converged": True,
                "random_slope": True,
                "covariance_matrix": [[0.7, 0.0], [0.0, 0.0]],
                "residual_variance": 0.5,
            },
            "LMM_RANDOM_EFFECTS_SINGULAR",
            "complete",
        ),
    ],
)
def test_diagnostic_faults_have_exact_code_and_status(
    kwargs: dict[str, object], expected_code: str, expected_status: str
) -> None:
    module = require_candidate_module(
        "workbench.engine.packs.linear_mixed_effects.diagnostics"
    )

    diagnostics = module.classify_lmm_diagnostics(**kwargs)

    assert diagnostics[0].code == expected_code
    assert diagnostics[0].status == expected_status
    if expected_status in {"blocked", "failed"}:
        assert diagnostics[0].action_candidate is None
