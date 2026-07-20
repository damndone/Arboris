"""Closed-vocabulary repeated-measures recovery presentation."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from workbench.contracts.agent.repeated_measures import LMM_RECOVERY_ACTION_ID, LMM_RECOVERY_OPERATION_ID
from workbench.contracts.model.linear_mixed_effects import LmmDiagnostic, LmmModelInput
from .lmm_explanation import build_lmm_explanation, build_lmm_explanation_from_validated_facts, validate_lmm_diagnostics, validate_lmm_source, validate_recovery_patch

_NEUTRAL = "未提供可用于生成说明的受控 LMM 诊断。"
_IMPACT = ("固定效应结构和样本选择保持不变。", "随机效应结构从随机截距加随机时间斜率改为仅随机截距。", "系数、标准误和不确定性将在运行完成后由 ComparePacket 确认。")
_CODES = frozenset({"LMM_RANDOM_SLOPE_NEAR_ZERO", "LMM_RANDOM_EFFECTS_SINGULAR"})

def _neutral() -> dict[str, object]:
    return {"proposal": None, "plan_diff": None, "explanation": _NEUTRAL}

def _eligible(diagnostics: Sequence[LmmDiagnostic]) -> bool:
    return bool(diagnostics) and all(d.code in _CODES and d.severity == "warning" and d.status == "complete" for d in diagnostics)

def build_repeated_measures_recipe_from_validated_facts(model_input: LmmModelInput, diagnostics: tuple[LmmDiagnostic, ...]) -> dict[str, object]:
    """Pure view constructor.  It neither loads a Pack nor executes a proposal."""
    explanation = build_lmm_explanation_from_validated_facts(model_input, diagnostics)
    if model_input.random_slope is not True or not _eligible(diagnostics):
        return {"proposal": None, "plan_diff": None, "explanation": explanation}
    for diagnostic in diagnostics:
        candidate = diagnostic.action_candidate
        if (not isinstance(candidate, Mapping) or set(candidate) != {"action_id", "operation_id", "patch", "required_confirmation"} or candidate.get("action_id") != LMM_RECOVERY_ACTION_ID or candidate.get("operation_id") != LMM_RECOVERY_OPERATION_ID or candidate.get("required_confirmation") is not True):
            return _neutral()
        try:
            patch = validate_recovery_patch(candidate.get("patch"))
        except (TypeError, ValueError):
            return _neutral()
        return {"proposal": {"operation": LMM_RECOVERY_OPERATION_ID, "patch": patch, "requires_confirmation": True}, "plan_diff": {"expected_impact": list(_IMPACT)}, "explanation": explanation}
    return _neutral()

def build_repeated_measures_recipe(*, source: object, diagnostics: object) -> dict[str, object]:
    model_input, parsed = validate_lmm_source(source), validate_lmm_diagnostics(diagnostics)
    if model_input is None or parsed is None:
        return _neutral()
    return build_repeated_measures_recipe_from_validated_facts(model_input, parsed)
