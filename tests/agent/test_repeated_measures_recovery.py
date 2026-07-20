import pytest

from workbench.agent.recipes.repeated_measures import (
    build_repeated_measures_recipe,
    validate_recovery_patch,
)
from workbench.contracts.model.linear_mixed_effects import (
    LMM_MODEL_TYPE,
)
from workbench.engine.packs.loader import bootstrap_builtin_packs
from workbench.model_options import bind_new_model_options


_NEUTRAL_EXPLANATION = "未提供可用于生成说明的受控 LMM 诊断。"


def _register_lmm_owner(monkeypatch) -> None:
    del monkeypatch
    bootstrap_builtin_packs()


def _bound_lmm_source(*, random_slope: bool = True) -> dict[str, object]:
    bound = bind_new_model_options(
        LMM_MODEL_TYPE,
        {
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": random_slope,
        },
    )
    assert bound.binding is not None
    return {
        "model_type": LMM_MODEL_TYPE,
        "model_options": bound.payload,
        "model_options_binding": bound.binding.to_dict(),
    }


def _diagnostic(
    *,
    code: str,
    severity: str,
    status: str,
    evidence: object,
    action_candidate: object = None,
) -> dict[str, object]:
    return {
        "code": code,
        "severity": severity,
        "status": status,
        "evidence": evidence,
        "action_candidate": action_candidate,
    }


def _recovery_diagnostic(
    code: str = "LMM_RANDOM_SLOPE_NEAR_ZERO",
) -> dict[str, object]:
    return _diagnostic(
        code=code,
        severity="warning",
        status="complete",
        evidence={"slope_variance": 0.0},
        action_candidate={
            "action_id": "lmm.simplify_random_effects_v1",
            "operation_id": "model.rerun",
            "patch": {"model_options": {"random_slope": False}},
            "required_confirmation": True,
        },
    )


def test_recovery_candidate_without_confirmation_fails_closed(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)
    diagnostic = _recovery_diagnostic()
    candidate = diagnostic["action_candidate"]
    assert isinstance(candidate, dict)
    candidate["required_confirmation"] = False

    recipe = build_repeated_measures_recipe(
        source=_bound_lmm_source(), diagnostics=[diagnostic]
    )

    assert recipe == {
        "proposal": None,
        "plan_diff": None,
        "explanation": _NEUTRAL_EXPLANATION,
    }


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


@pytest.mark.parametrize(
    "patch",
    [
        {"model_options": {"random_slope": 0}},
        {"model_options": {"random_slope": 0.0}},
        {"model_options": {"random_slope": "false"}},
        {"model_options": {"random_slope": False, "fit_method": "reml"}},
    ],
)
def test_recovery_patch_requires_the_exact_boolean_false_literal(patch: object) -> None:
    with pytest.raises(ValueError, match="unsupported LMM recovery patch"):
        validate_recovery_patch(patch)


def test_recovery_is_not_offered_for_a_non_lmm_source() -> None:
    recipe = build_repeated_measures_recipe(
        source={"model_type": "ordinary_least_squares", "model_options": {}},
        diagnostics=[_recovery_diagnostic()],
    )

    assert recipe == {
        "proposal": None,
        "plan_diff": None,
        "explanation": _NEUTRAL_EXPLANATION,
    }


def test_recovery_requires_a_source_random_slope_to_remove(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)

    recipe = build_repeated_measures_recipe(
        source=_bound_lmm_source(random_slope=False),
        diagnostics=[_recovery_diagnostic()],
    )

    assert recipe == {
        "proposal": None,
        "plan_diff": None,
        "explanation": _NEUTRAL_EXPLANATION,
    }


def test_singular_random_effects_can_offer_the_locked_recovery(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)

    recipe = build_repeated_measures_recipe(
        source=_bound_lmm_source(),
        diagnostics=[_recovery_diagnostic("LMM_RANDOM_EFFECTS_SINGULAR")],
    )

    assert recipe["proposal"] == {
        "operation": "model.rerun",
        "patch": {"model_options": {"random_slope": False}},
        "requires_confirmation": True,
    }


@pytest.mark.parametrize(
    ("code", "severity", "status"),
    [
        ("LMM_SUBJECT_ID_MISSING", "error", "blocked"),
        ("UNRECOGNIZED_LMM_DIAGNOSTIC", "warning", "complete"),
    ],
)
def test_blocking_or_unknown_diagnostic_suppresses_recovery(
    monkeypatch, code: str, severity: str, status: str
) -> None:
    _register_lmm_owner(monkeypatch)

    recipe = build_repeated_measures_recipe(
        source=_bound_lmm_source(),
        diagnostics=[
            _diagnostic(
                code=code,
                severity=severity,
                status=status,
                evidence={},
            ),
            _recovery_diagnostic(),
        ],
    )

    assert recipe["proposal"] is None


def test_non_string_diagnostic_code_fails_closed_without_a_proposal(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)
    invalid = _recovery_diagnostic()
    invalid["code"] = ["LMM_RANDOM_SLOPE_NEAR_ZERO"]

    recipe = build_repeated_measures_recipe(
        source=_bound_lmm_source(),
        diagnostics=[invalid, _recovery_diagnostic()],
    )

    assert recipe == {
        "proposal": None,
        "plan_diff": None,
        "explanation": _NEUTRAL_EXPLANATION,
    }


def test_recovery_candidate_with_an_unlocked_field_is_rejected(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)
    diagnostic = _recovery_diagnostic()
    candidate = diagnostic["action_candidate"]
    assert isinstance(candidate, dict)
    candidate["auto_execute"] = True

    recipe = build_repeated_measures_recipe(
        source=_bound_lmm_source(), diagnostics=[diagnostic]
    )

    assert recipe == {
        "proposal": None,
        "plan_diff": None,
        "explanation": _NEUTRAL_EXPLANATION,
    }
