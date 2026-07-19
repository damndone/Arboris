from workbench.agent.recipes.repeated_measures import build_repeated_measures_recipe
from workbench.agent.recipes.lmm_explanation import build_lmm_explanation


def test_recoverable_slope_diagnostic_creates_confirmable_rerun() -> None:
    recipe = build_repeated_measures_recipe(
        source={
            "model_type": "linear_mixed_effects",
            "model_options": {
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": True,
            },
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

    assert recipe["proposal"] == {
        "operation": "model.rerun",
        "patch": {"model_options": {"random_slope": False}},
        "requires_confirmation": True,
    }
    assert recipe["plan_diff"]["expected_impact"] == [
        "固定效应结构和样本选择保持不变。",
        "随机效应结构从随机截距加随机时间斜率改为仅随机截距。",
        "系数、标准误和不确定性将在运行完成后由 ComparePacket 确认。",
    ]


def test_blocking_subject_diagnostic_has_no_operation() -> None:
    recipe = build_repeated_measures_recipe(
        source={"model_type": "linear_mixed_effects", "model_options": {}},
        diagnostics=[
            {
                "code": "LMM_SUBJECT_ID_MISSING",
                "status": "blocked",
                "action_candidate": None,
            }
        ],
    )

    assert recipe["proposal"] is None
    assert "subject identifier" in recipe["explanation"].lower()


def test_explanations_are_fixed_to_permitted_lmm_facts() -> None:
    explanations = [
        build_lmm_explanation(
            [
                {
                    "code": "LMM_CONVERGENCE_FAILED",
                    "status": "failed",
                }
            ]
        ),
        build_lmm_explanation(
            [
                {
                    "code": "LMM_RANDOM_SLOPE_NEAR_ZERO",
                    "status": "complete",
                }
            ]
        ),
        build_lmm_explanation(
            [],
            comparison={
                "compare_status": "restricted",
                "reason_code": "REML_FIXED_EFFECTS_DIFFER",
            },
        ),
        build_lmm_explanation(
            [{"code": "UNRECOGNIZED_LMM_DIAGNOSTIC", "status": "complete"}]
        ),
    ]

    assert explanations == [
        "模型未收敛，不能据此给出稳定的实质性结论。",
        "随机时间斜率的方差接近零。建议在保持固定效应和样本选择不变的前提下，改为仅随机截距模型。",
        "两个模型使用 REML 且固定效应结构不同；不能把 AIC、似然或似然比检验作为直接优劣判断。",
        "未提供可用于生成说明的受控 LMM 诊断。",
    ]
    for explanation in explanations:
        assert not any(
            term in explanation
            for term in ("导致", "造成", "证明因果", "因果效应")
        )


def test_recipe_returns_a_fresh_plan_diff_for_each_proposal() -> None:
    source = {
        "model_type": "linear_mixed_effects",
        "model_options": {"random_slope": True},
    }
    diagnostics = [
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
    ]

    first = build_repeated_measures_recipe(source=source, diagnostics=diagnostics)
    first["plan_diff"]["expected_impact"].append("unlocked mutation")
    second = build_repeated_measures_recipe(source=source, diagnostics=diagnostics)

    assert second["plan_diff"]["expected_impact"] == [
        "固定效应结构和样本选择保持不变。",
        "随机效应结构从随机截距加随机时间斜率改为仅随机截距。",
        "系数、标准误和不确定性将在运行完成后由 ComparePacket 确认。",
    ]
