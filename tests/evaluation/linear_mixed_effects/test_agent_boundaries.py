from __future__ import annotations

from copy import deepcopy

import pytest

from tests.evaluation.linear_mixed_effects._candidate import require_candidate_module


SOURCE = {
    "model_type": "linear_mixed_effects",
    "model_options": {
        "subject_id": "participant_id",
        "time": "week",
        "group": "arm",
        "fit_method": "reml",
        "random_slope": True,
    },
}
RECOVERY = {
    "action_id": "lmm.simplify_random_effects_v1",
    "operation_id": "model.rerun",
    "patch": {"model_options": {"random_slope": False}},
    "required_confirmation": True,
}


def _recipe(source: dict[str, object], diagnostics: list[dict[str, object]]) -> dict[str, object]:
    module = require_candidate_module(
        "workbench.agent.recipes.repeated_measures"
    )
    result = module.build_repeated_measures_recipe(
        source=source,
        diagnostics=diagnostics,
    )
    assert isinstance(result, dict)
    return result


def test_recoverable_random_slope_produces_one_confirmable_rerun() -> None:
    source = deepcopy(SOURCE)
    recipe = _recipe(
        source,
        [
            {
                "code": "LMM_RANDOM_SLOPE_NEAR_ZERO",
                "status": "complete",
                "action_candidate": RECOVERY,
            }
        ],
    )

    assert source == SOURCE
    assert recipe["proposal"] == {
        "operation": "model.rerun",
        "patch": {"model_options": {"random_slope": False}},
        "requires_confirmation": True,
    }
    assert "execution" not in recipe
    assert "child_run" not in recipe


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("LMM_SUBJECT_ID_MISSING", "blocked"),
        ("LMM_TIME_NOT_NUMERIC", "blocked"),
        ("LMM_GROUP_NOT_BINARY", "blocked"),
        ("LMM_GROUP_VARIES_WITHIN_SUBJECT", "blocked"),
        ("LMM_INSUFFICIENT_REPEATED_OBSERVATIONS", "blocked"),
        ("LMM_CONVERGENCE_FAILED", "failed"),
    ],
)
def test_blocking_diagnostics_never_create_a_proposal(code: str, status: str) -> None:
    recipe = _recipe(
        deepcopy(SOURCE),
        [{"code": code, "status": status, "action_candidate": None}],
    )

    assert recipe["proposal"] is None


def test_unknown_diagnostic_and_patch_fail_closed() -> None:
    module = require_candidate_module(
        "workbench.agent.recipes.repeated_measures"
    )
    recipe = _recipe(
        deepcopy(SOURCE),
        [
            {
                "code": "LMM_UNKNOWN_DIAGNOSTIC",
                "status": "complete",
                "action_candidate": RECOVERY,
            }
        ],
    )

    assert recipe["proposal"] is None
    with pytest.raises(ValueError, match="unsupported LMM recovery patch"):
        module.validate_recovery_patch({"model_options": {"fit_method": "ml"}})
