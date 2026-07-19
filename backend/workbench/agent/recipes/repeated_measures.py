"""Closed-vocabulary recovery recipe for linear mixed-effects diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from workbench.contracts.agent.repeated_measures import (
    LMM_RECOVERY_ACTION_ID,
    LMM_RECOVERY_OPERATION_ID,
)
from workbench.contracts.model.linear_mixed_effects import LmmDiagnostic

from .lmm_explanation import (
    build_lmm_explanation,
    validate_lmm_diagnostics,
    validate_lmm_source,
    validate_recovery_patch,
)


_RECOVERY_EXPECTED_IMPACT = (
    "固定效应结构和样本选择保持不变。",
    "随机效应结构从随机截距加随机时间斜率改为仅随机截距。",
    "系数、标准误和不确定性将在运行完成后由 ComparePacket 确认。",
)
_RECOVERABLE_DIAGNOSTIC_CODES = frozenset(
    {"LMM_RANDOM_SLOPE_NEAR_ZERO", "LMM_RANDOM_EFFECTS_SINGULAR"}
)
_RECOVERY_CANDIDATE_FIELDS = frozenset(
    {"action_id", "operation_id", "patch", "required_confirmation"}
)
_NEUTRAL_EXPLANATION = "未提供可用于生成说明的受控 LMM 诊断。"


def _diagnostics_are_recovery_eligible(
    diagnostics: Sequence[LmmDiagnostic],
) -> bool:
    """Allow a proposal only when every trusted fact is a locked recovery fact."""

    return all(
        diagnostic.code in _RECOVERABLE_DIAGNOSTIC_CODES
        and diagnostic.severity == "warning"
        and diagnostic.status == "complete"
        for diagnostic in diagnostics
    )


def build_repeated_measures_recipe(
    *, source: object, diagnostics: object
) -> dict[str, object]:
    """Return one confirmation-bound recovery proposal when its facts are exact."""

    validated_diagnostics = validate_lmm_diagnostics(diagnostics)
    if validated_diagnostics is None:
        return {
            "proposal": None,
            "plan_diff": None,
            "explanation": _NEUTRAL_EXPLANATION,
        }

    model_input = validate_lmm_source(source)
    if model_input is None or model_input.random_slope is not True:
        return {
            "proposal": None,
            "plan_diff": None,
            "explanation": _NEUTRAL_EXPLANATION,
        }

    if not _diagnostics_are_recovery_eligible(validated_diagnostics):
        return {
            "proposal": None,
            "plan_diff": None,
            "explanation": build_lmm_explanation(diagnostics, source=source),
        }

    for diagnostic in validated_diagnostics:
        candidate = diagnostic.action_candidate
        if (
            not isinstance(candidate, Mapping)
            or set(candidate) != _RECOVERY_CANDIDATE_FIELDS
            or candidate.get("action_id") != LMM_RECOVERY_ACTION_ID
            or candidate.get("operation_id") != LMM_RECOVERY_OPERATION_ID
            or candidate.get("required_confirmation") is not True
        ):
            continue

        try:
            patch = validate_recovery_patch(candidate.get("patch"))
        except (TypeError, ValueError):
            return {
                "proposal": None,
                "plan_diff": None,
                "explanation": _NEUTRAL_EXPLANATION,
            }
        return {
            "proposal": {
                "operation": LMM_RECOVERY_OPERATION_ID,
                "patch": patch,
                "requires_confirmation": True,
            },
            "plan_diff": {"expected_impact": list(_RECOVERY_EXPECTED_IMPACT)},
            "explanation": build_lmm_explanation(diagnostics, source=source),
        }

    return {
        "proposal": None,
        "plan_diff": None,
        "explanation": build_lmm_explanation(diagnostics, source=source),
    }
