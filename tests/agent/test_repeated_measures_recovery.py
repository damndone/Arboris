import pytest

from workbench.agent.recipes.repeated_measures import (
    build_repeated_measures_recipe,
    validate_recovery_patch,
)


def test_recovery_candidate_without_confirmation_is_rejected() -> None:
    with pytest.raises(ValueError, match="confirmation"):
        build_repeated_measures_recipe(
            source={
                "model_type": "linear_mixed_effects",
                "model_options": {"random_slope": True},
            },
            diagnostics=[
                {
                    "code": "LMM_RANDOM_SLOPE_NEAR_ZERO",
                    "status": "complete",
                    "action_candidate": {
                        "action_id": "lmm.simplify_random_effects_v1",
                        "operation_id": "model.rerun",
                        "patch": {"model_options": {"random_slope": False}},
                        "required_confirmation": False,
                    },
                }
            ],
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"model_options": {"random_slope": False, "fit_method": "ml"}},
        {"model_options": {"random_slope": False}, "controls": ["baseline"]},
    ],
)
def test_recovery_patch_cannot_change_any_other_model_fact(patch: object) -> None:
    with pytest.raises(ValueError, match="unsupported LMM recovery patch"):
        validate_recovery_patch(patch)


def test_recovery_is_not_offered_for_a_non_lmm_source() -> None:
    recipe = build_repeated_measures_recipe(
        source={"model_type": "ordinary_least_squares", "model_options": {}},
        diagnostics=[
            {
                "code": "LMM_RANDOM_SLOPE_NEAR_ZERO",
                "status": "complete",
                "action_candidate": {
                    "action_id": "lmm.simplify_random_effects_v1",
                    "operation_id": "model.rerun",
                    "patch": {"model_options": {"random_slope": False}},
                    "required_confirmation": True,
                },
            }
        ],
    )

    assert recipe["proposal"] is None


def test_recovery_requires_a_source_random_slope_to_remove() -> None:
    recipe = build_repeated_measures_recipe(
        source={
            "model_type": "linear_mixed_effects",
            "model_options": {"random_slope": False},
        },
        diagnostics=[
            {
                "code": "LMM_RANDOM_SLOPE_NEAR_ZERO",
                "status": "complete",
                "action_candidate": {
                    "action_id": "lmm.simplify_random_effects_v1",
                    "operation_id": "model.rerun",
                    "patch": {"model_options": {"random_slope": False}},
                    "required_confirmation": True,
                },
            }
        ],
    )

    assert recipe["proposal"] is None


def test_singular_random_effects_can_offer_the_locked_recovery() -> None:
    recipe = build_repeated_measures_recipe(
        source={
            "model_type": "linear_mixed_effects",
            "model_options": {"random_slope": True},
        },
        diagnostics=[
            {
                "code": "LMM_RANDOM_EFFECTS_SINGULAR",
                "status": "complete",
                "action_candidate": {
                    "action_id": "lmm.simplify_random_effects_v1",
                    "operation_id": "model.rerun",
                    "patch": {"model_options": {"random_slope": False}},
                    "required_confirmation": True,
                },
            }
        ],
    )

    assert recipe["proposal"] == {
        "operation": "model.rerun",
        "patch": {"model_options": {"random_slope": False}},
        "requires_confirmation": True,
    }


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("LMM_SUBJECT_ID_MISSING", "blocked"),
        ("UNRECOGNIZED_LMM_DIAGNOSTIC", "complete"),
    ],
)
def test_blocking_or_unknown_diagnostic_suppresses_recovery(
    code: str, status: str
) -> None:
    recipe = build_repeated_measures_recipe(
        source={
            "model_type": "linear_mixed_effects",
            "model_options": {"random_slope": True},
        },
        diagnostics=[
            {"code": code, "status": status, "action_candidate": None},
            {
                "code": "LMM_RANDOM_SLOPE_NEAR_ZERO",
                "status": "complete",
                "action_candidate": {
                    "action_id": "lmm.simplify_random_effects_v1",
                    "operation_id": "model.rerun",
                    "patch": {"model_options": {"random_slope": False}},
                    "required_confirmation": True,
                },
            },
        ],
    )

    assert recipe["proposal"] is None


def test_non_string_diagnostic_code_fails_closed_without_a_proposal() -> None:
    recipe = build_repeated_measures_recipe(
        source={
            "model_type": "linear_mixed_effects",
            "model_options": {"random_slope": True},
        },
        diagnostics=[
            {"code": ["LMM_RANDOM_SLOPE_NEAR_ZERO"], "status": "complete"},
            {
                "code": "LMM_RANDOM_SLOPE_NEAR_ZERO",
                "status": "complete",
                "action_candidate": {
                    "action_id": "lmm.simplify_random_effects_v1",
                    "operation_id": "model.rerun",
                    "patch": {"model_options": {"random_slope": False}},
                    "required_confirmation": True,
                },
            },
        ],
    )

    assert recipe["proposal"] is None


def test_recovery_candidate_with_an_unlocked_field_is_rejected() -> None:
    recipe = build_repeated_measures_recipe(
        source={
            "model_type": "linear_mixed_effects",
            "model_options": {"random_slope": True},
        },
        diagnostics=[
            {
                "code": "LMM_RANDOM_SLOPE_NEAR_ZERO",
                "status": "complete",
                "action_candidate": {
                    "action_id": "lmm.simplify_random_effects_v1",
                    "operation_id": "model.rerun",
                    "patch": {"model_options": {"random_slope": False}},
                    "required_confirmation": True,
                    "auto_execute": True,
                },
            }
        ],
    )

    assert recipe["proposal"] is None
