from __future__ import annotations

from workbench.engine.packs.linear_mixed_effects.diagnostics import (
    classify_lmm_diagnostics,
)


def test_near_zero_slope_is_recoverable() -> None:
    diagnostics = classify_lmm_diagnostics(
        converged=True,
        random_slope=True,
        covariance_matrix=[[0.7, 0.0], [0.0, 0.0]],
        residual_variance=0.5,
    )

    candidate = diagnostics[0].action_candidate
    assert candidate is not None
    assert candidate["action_id"] == "lmm.simplify_random_effects_v1"
    assert candidate["patch"] == {"model_options": {"random_slope": False}}


def test_slope_variance_below_the_locked_relative_threshold_is_near_zero() -> None:
    diagnostics = classify_lmm_diagnostics(
        converged=True,
        random_slope=True,
        covariance_matrix=[[0.7, 0.0], [0.0, 0.0000001]],
        residual_variance=0.5,
    )

    assert diagnostics[0].code == "LMM_RANDOM_SLOPE_NEAR_ZERO"


def test_blocking_design_error_has_no_candidate() -> None:
    diagnostics = classify_lmm_diagnostics(
        converged=True,
        random_slope=False,
        covariance_matrix=[[0.7]],
        residual_variance=0.5,
        blocking_code="LMM_SUBJECT_ID_MISSING",
    )

    assert diagnostics[0].status == "blocked"
    assert diagnostics[0].action_candidate is None


def test_non_convergence_is_terminally_failed_without_a_candidate() -> None:
    diagnostics = classify_lmm_diagnostics(
        converged=False,
        random_slope=False,
        covariance_matrix=[[0.7]],
        residual_variance=0.5,
    )

    assert diagnostics[0].code == "LMM_CONVERGENCE_FAILED"
    assert diagnostics[0].status == "failed"
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].action_candidate is None


def test_singular_random_effects_are_recoverable_only_with_a_random_slope() -> None:
    diagnostics = classify_lmm_diagnostics(
        converged=True,
        random_slope=True,
        covariance_matrix=[[1.0, 1.0], [1.0, 1.0]],
        residual_variance=0.5,
    )

    assert diagnostics[0].code == "LMM_RANDOM_EFFECTS_SINGULAR"
    assert diagnostics[0].severity == "warning"
    assert diagnostics[0].status == "complete"
    assert diagnostics[0].action_candidate is not None


def test_singular_intercept_without_a_random_slope_has_no_action() -> None:
    diagnostics = classify_lmm_diagnostics(
        converged=True,
        random_slope=False,
        covariance_matrix=[[0.0]],
        residual_variance=0.5,
    )

    assert diagnostics[0].code == "LMM_RANDOM_EFFECTS_SINGULAR"
    assert diagnostics[0].severity == "warning"
    assert diagnostics[0].status == "complete"
    assert diagnostics[0].action_candidate is None
