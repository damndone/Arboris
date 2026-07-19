from pathlib import Path
from collections.abc import Mapping, Sequence

from tests.evaluation.linear_mixed_effects._candidate import require_candidate_module


ROOT = Path(__file__).parents[2] / "fixtures" / "models" / "linear_mixed_effects"


def _fit_known_truth(tmp_path, *, run_name: str) -> tuple[dict[str, object], object]:
    runner = require_candidate_module(
        "workbench.engine.packs.linear_mixed_effects.runner"
    )
    outcome = runner.fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path / run_name,
    )
    assert isinstance(outcome, tuple) and len(outcome) == 2
    result, fitted = outcome
    assert isinstance(result, dict)
    return result, fitted


def test_known_truth_interaction_is_within_locked_tolerance(tmp_path) -> None:
    result, fitted = _fit_known_truth(tmp_path, run_name="tolerance")

    assert abs(result["coefficients"]["group_time_interaction"]["estimate"] - 0.9) <= 0.35
    assert fitted.converged is True


def test_known_truth_result_identity_and_inference_are_stable(tmp_path) -> None:
    first, _ = _fit_known_truth(tmp_path, run_name="first")
    second, _ = _fit_known_truth(tmp_path, run_name="second")

    assert first["result_identity"] == second["result_identity"]
    assert len(first["result_identity"]) == 64
    assert first["fit_method"] == "reml"
    assert first["primary_target_id"] == "group_time_interaction"
    assert (
        first["coefficients"]["group_time_interaction"]["inference_method"]
        == "asymptotic_wald_z_v1"
    )


def test_known_truth_reports_random_effect_and_group_summary(tmp_path) -> None:
    result, _ = _fit_known_truth(tmp_path, run_name="summary")

    random_effects = result["random_effects"]
    assert isinstance(random_effects, Mapping)
    assert {
        "intercept_variance",
        "slope_variance",
        "covariance",
        "residual_variance",
    } <= set(random_effects)
    assert random_effects["intercept_variance"] >= 0
    assert random_effects["slope_variance"] >= 0
    assert random_effects["residual_variance"] > 0
    assert result["n_groups"] == 80

    observations = result["observations_per_group"]
    assert isinstance(observations, (Mapping, Sequence))
    values = (
        list(observations.values())
        if isinstance(observations, Mapping)
        else list(observations)
    )
    assert values
    assert all(value == 6 for value in values)
