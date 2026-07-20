import json
from pathlib import Path

import pytest

from workbench.agent.recipes.lmm_explanation import build_lmm_explanation
from workbench.agent.recipes.repeated_measures import build_repeated_measures_recipe
from workbench.contracts.model.linear_mixed_effects import (
    LMM_MODEL_TYPE,
)
from workbench.engine.packs.loader import bootstrap_builtin_packs
from workbench.model_options import bind_new_model_options


_NEUTRAL_EXPLANATION = "未提供可用于生成说明的受控 LMM 诊断。"


def _register_lmm_owner(monkeypatch) -> None:
    """Use Integration's declared owner; never shadow it with a test handler."""

    del monkeypatch
    bootstrap_builtin_packs()


def _bound_lmm_source(
    *, random_slope: bool = True, status: object = None
) -> dict[str, object]:
    options: dict[str, object] = {
        "subject_id": "participant_id",
        "time": "week",
        "group": "arm",
        "fit_method": "reml",
        "random_slope": random_slope,
    }
    bound = bind_new_model_options(LMM_MODEL_TYPE, options)
    assert bound.binding is not None
    source: dict[str, object] = {
        "model_type": LMM_MODEL_TYPE,
        "model_options": bound.payload,
        "model_options_binding": bound.binding.to_dict(),
    }
    if status is not None:
        source["status"] = status
    return source


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


def test_recoverable_slope_diagnostic_creates_confirmable_rerun(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)

    recipe = build_repeated_measures_recipe(
        source=_bound_lmm_source(), diagnostics=[_recovery_diagnostic()]
    )

    assert recipe["proposal"] == {
        "operation": "model.rerun",
        "patch": {"model_options": {"random_slope": False}},
        "requires_confirmation": True,
    }
    assert recipe["plan_diff"] == {
        "expected_impact": [
            "固定效应结构和样本选择保持不变。",
            "随机效应结构从随机截距加随机时间斜率改为仅随机截距。",
            "系数、标准误和不确定性将在运行完成后由 ComparePacket 确认。",
        ]
    }


def test_blocking_subject_diagnostic_has_no_operation(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)

    recipe = build_repeated_measures_recipe(
        source=_bound_lmm_source(),
        diagnostics=[
            _diagnostic(
                code="LMM_SUBJECT_ID_MISSING",
                severity="error",
                status="blocked",
                evidence={"column": "participant_id"},
            )
        ],
    )

    assert recipe["proposal"] is None
    assert "subject identifier" in recipe["explanation"].lower()


def test_explanations_are_fixed_to_permitted_lmm_facts(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)
    source = _bound_lmm_source()
    fixture_path = (
        Path(__file__).parents[1]
        / "fixtures/models/linear_mixed_effects/packets/restricted_reml_child.json"
    )
    restricted_comparison = json.loads(fixture_path.read_text(encoding="utf-8"))

    explanations = [
        build_lmm_explanation(
            [
                _diagnostic(
                    code="LMM_CONVERGENCE_FAILED",
                    severity="error",
                    status="failed",
                    evidence={"reason": "optimizer"},
                )
            ],
            source=source,
        ),
        build_lmm_explanation([_recovery_diagnostic()], source=source),
        build_lmm_explanation([], source=source, comparison=restricted_comparison),
        build_lmm_explanation(
            [
                _diagnostic(
                    code="UNRECOGNIZED_LMM_DIAGNOSTIC",
                    severity="warning",
                    status="complete",
                    evidence={},
                )
            ],
            source=source,
        ),
    ]

    assert explanations == [
        "模型未收敛，不能据此给出稳定的实质性结论。",
        "随机时间斜率的方差接近零。建议在保持固定效应和样本选择不变的前提下，改为仅随机截距模型。",
        "两个模型使用 REML 且固定效应结构不同；不能把 AIC、似然或似然比检验作为直接优劣判断。",
        _NEUTRAL_EXPLANATION,
    ]
    for explanation in explanations:
        assert not any(
            term in explanation
            for term in ("导致", "造成", "证明因果", "因果效应")
        )


def test_malformed_diagnostics_cannot_bypass_a_verified_compare_packet(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)
    fixture_path = (
        Path(__file__).parents[1]
        / "fixtures/models/linear_mixed_effects/packets/restricted_reml_child.json"
    )
    restricted_comparison = json.loads(fixture_path.read_text(encoding="utf-8"))

    explanation = build_lmm_explanation(
        [{"code": "LMM_RANDOM_SLOPE_NEAR_ZERO"}],
        source=_bound_lmm_source(),
        comparison=restricted_comparison,
    )

    assert explanation == _NEUTRAL_EXPLANATION


def test_recipe_returns_a_fresh_plan_diff_for_each_proposal(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)
    source = _bound_lmm_source()
    diagnostics = [_recovery_diagnostic()]

    first = build_repeated_measures_recipe(source=source, diagnostics=diagnostics)
    first["plan_diff"]["expected_impact"].append("unlocked mutation")
    second = build_repeated_measures_recipe(source=source, diagnostics=diagnostics)

    assert second["plan_diff"]["expected_impact"] == [
        "固定效应结构和样本选择保持不变。",
        "随机效应结构从随机截距加随机时间斜率改为仅随机截距。",
        "系数、标准误和不确定性将在运行完成后由 ComparePacket 确认。",
    ]


def test_nonempty_unbound_lmm_source_fails_closed(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)

    recipe = build_repeated_measures_recipe(
        source={
            "model_type": LMM_MODEL_TYPE,
            "model_options": {
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": True,
            },
        },
        diagnostics=[_recovery_diagnostic()],
    )

    assert recipe == {
        "proposal": None,
        "plan_diff": None,
        "explanation": _NEUTRAL_EXPLANATION,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner_model_type", "ordinary_least_squares"),
        ("owner_model_id", "forged-owner"),
        ("normalized_options_hash", "0" * 64),
    ],
)
def test_tampered_lmm_source_binding_fails_closed(
    monkeypatch, field: str, value: str
) -> None:
    _register_lmm_owner(monkeypatch)
    source = _bound_lmm_source()
    binding = source["model_options_binding"]
    assert isinstance(binding, dict)
    binding[field] = value

    recipe = build_repeated_measures_recipe(
        source=source, diagnostics=[_recovery_diagnostic()]
    )

    assert recipe == {
        "proposal": None,
        "plan_diff": None,
        "explanation": _NEUTRAL_EXPLANATION,
    }


@pytest.mark.parametrize(
    "source_kwargs",
    [
        {"random_slope": False},
        {"status": "blocked"},
        {"status": "unknown"},
        {"status": []},
    ],
)
def test_non_actionable_lmm_source_falls_back_neutrally(
    monkeypatch, source_kwargs: dict[str, object]
) -> None:
    _register_lmm_owner(monkeypatch)

    recipe = build_repeated_measures_recipe(
        source=_bound_lmm_source(**source_kwargs),
        diagnostics=[_recovery_diagnostic()],
    )

    assert recipe == {
        "proposal": None,
        "plan_diff": None,
        "explanation": _NEUTRAL_EXPLANATION,
    }


def test_invalid_diagnostic_suppresses_a_valid_candidate_in_either_order(
    monkeypatch,
) -> None:
    _register_lmm_owner(monkeypatch)
    valid = _recovery_diagnostic()
    invalid = _recovery_diagnostic()
    invalid["evidence"] = []

    for diagnostics in ([invalid, valid], [valid, invalid]):
        recipe = build_repeated_measures_recipe(
            source=_bound_lmm_source(), diagnostics=diagnostics
        )
        assert recipe == {
            "proposal": None,
            "plan_diff": None,
            "explanation": _NEUTRAL_EXPLANATION,
        }


@pytest.mark.parametrize(
    ("field", "value"),
    [("severity", "notice"), ("status", "pending")],
)
def test_illegal_diagnostic_severity_or_status_fails_closed(
    monkeypatch, field: str, value: str
) -> None:
    _register_lmm_owner(monkeypatch)
    invalid = _recovery_diagnostic()
    invalid[field] = value

    recipe = build_repeated_measures_recipe(
        source=_bound_lmm_source(), diagnostics=[invalid]
    )

    assert recipe == {
        "proposal": None,
        "plan_diff": None,
        "explanation": _NEUTRAL_EXPLANATION,
    }


def test_bad_candidate_schema_or_patch_fails_closed_before_proposal(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)
    malformed_candidates: list[dict[str, object]] = []

    unlocked = _recovery_diagnostic()
    unlocked_candidate = unlocked["action_candidate"]
    assert isinstance(unlocked_candidate, dict)
    unlocked_candidate["auto_execute"] = True
    malformed_candidates.append(unlocked)

    numeric_false = _recovery_diagnostic()
    numeric_false_candidate = numeric_false["action_candidate"]
    assert isinstance(numeric_false_candidate, dict)
    numeric_false_candidate["patch"] = {"model_options": {"random_slope": 0}}
    malformed_candidates.append(numeric_false)

    for malformed in malformed_candidates:
        for diagnostics in (
            [malformed, _recovery_diagnostic()],
            [_recovery_diagnostic(), malformed],
        ):
            recipe = build_repeated_measures_recipe(
                source=_bound_lmm_source(), diagnostics=diagnostics
            )
            assert recipe == {
                "proposal": None,
                "plan_diff": None,
                "explanation": _NEUTRAL_EXPLANATION,
            }


def test_unverified_source_cannot_emit_a_specific_compare_explanation() -> None:
    explanation = build_lmm_explanation(
        [],
        source={},
        comparison={
            "compare_status": "restricted",
            "reason_code": "REML_FIXED_EFFECTS_DIFFER",
        },
    )

    assert explanation == _NEUTRAL_EXPLANATION


def test_unverified_compare_payload_fails_closed(monkeypatch) -> None:
    _register_lmm_owner(monkeypatch)

    explanation = build_lmm_explanation(
        [],
        source=_bound_lmm_source(),
        comparison={
            "compare_status": "restricted",
            "reason_code": "REML_FIXED_EFFECTS_DIFFER",
        },
    )

    assert explanation == _NEUTRAL_EXPLANATION


@pytest.mark.parametrize(
    ("diagnostics", "comparison"),
    [
        ({}, None),
        ("not a diagnostics list", None),
        ([{"code": "LMM_RANDOM_SLOPE_NEAR_ZERO"}], None),
        ([], {}),
    ],
)
def test_malformed_explanation_inputs_fall_back_without_an_exception(
    monkeypatch, diagnostics: object, comparison: object
) -> None:
    _register_lmm_owner(monkeypatch)

    assert (
        build_lmm_explanation(
            diagnostics, source=_bound_lmm_source(), comparison=comparison
        )
        == _NEUTRAL_EXPLANATION
    )
