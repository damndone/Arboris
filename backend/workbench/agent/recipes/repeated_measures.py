"""Closed-vocabulary recovery recipe for linear mixed-effects diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from workbench.contracts.agent.repeated_measures import (
    LMM_RECOVERY_ACTION_ID,
    LMM_RECOVERY_OPERATION_ID,
)

from .lmm_explanation import build_lmm_explanation


_RECOVERY_EXPECTED_IMPACT = (
    "固定效应结构和样本选择保持不变。",
    "随机效应结构从随机截距加随机时间斜率改为仅随机截距。",
    "系数、标准误和不确定性将在运行完成后由 ComparePacket 确认。",
)
_RECOVERABLE_DIAGNOSTIC_CODES = frozenset(
    {"LMM_RANDOM_SLOPE_NEAR_ZERO", "LMM_RANDOM_EFFECTS_SINGULAR"}
)
_DIAGNOSTIC_STATUSES = {
    "LMM_SUBJECT_ID_MISSING": "blocked",
    "LMM_TIME_NOT_NUMERIC": "blocked",
    "LMM_GROUP_NOT_BINARY": "blocked",
    "LMM_GROUP_VARIES_WITHIN_SUBJECT": "blocked",
    "LMM_INSUFFICIENT_REPEATED_OBSERVATIONS": "blocked",
    "LMM_INVALID_RANDOM_SLOPE_CONFIGURATION": "blocked",
    "LMM_CONVERGENCE_FAILED": "failed",
    "LMM_RANDOM_SLOPE_NEAR_ZERO": "complete",
    "LMM_RANDOM_EFFECTS_SINGULAR": "complete",
}
_RECOVERY_CANDIDATE_FIELDS = frozenset(
    {"action_id", "operation_id", "patch", "required_confirmation"}
)


def validate_recovery_patch(value: object) -> dict[str, object]:
    """Accept only the contract-locked random-slope removal patch."""

    expected = {"model_options": {"random_slope": False}}
    if value != expected:
        raise ValueError("unsupported LMM recovery patch")
    return expected


def _diagnostics_are_closed_vocabulary(
    diagnostics: Sequence[Mapping[str, object]],
) -> bool:
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, Mapping):
            return False
        code = diagnostic.get("code")
        status = diagnostic.get("status")
        if (
            type(code) is not str
            or type(status) is not str
            or code not in _RECOVERABLE_DIAGNOSTIC_CODES
            or _DIAGNOSTIC_STATUSES.get(code) != status
        ):
            return False
    return True


def build_repeated_measures_recipe(
    *, source: Mapping[str, object], diagnostics: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Return one confirmation-bound recovery proposal when its facts are exact."""

    if not _diagnostics_are_closed_vocabulary(diagnostics):
        return {
            "proposal": None,
            "plan_diff": None,
            "explanation": build_lmm_explanation(diagnostics),
        }

    model_options = source.get("model_options")
    if (
        source.get("model_type") != "linear_mixed_effects"
        or not isinstance(model_options, Mapping)
        or model_options.get("random_slope") is not True
    ):
        return {
            "proposal": None,
            "plan_diff": None,
            "explanation": build_lmm_explanation(diagnostics),
        }

    for diagnostic in diagnostics:
        candidate = diagnostic.get("action_candidate")
        if (
            diagnostic.get("code") not in _RECOVERABLE_DIAGNOSTIC_CODES
            or diagnostic.get("status") != "complete"
            or not isinstance(candidate, Mapping)
            or set(candidate) != _RECOVERY_CANDIDATE_FIELDS
            or candidate.get("action_id") != LMM_RECOVERY_ACTION_ID
            or candidate.get("operation_id") != LMM_RECOVERY_OPERATION_ID
        ):
            continue

        patch = validate_recovery_patch(candidate.get("patch"))
        if candidate.get("required_confirmation") is not True:
            raise ValueError("LMM recovery requires confirmation")
        return {
            "proposal": {
                "operation": LMM_RECOVERY_OPERATION_ID,
                "patch": patch,
                "requires_confirmation": True,
            },
            "plan_diff": {"expected_impact": list(_RECOVERY_EXPECTED_IMPACT)},
            "explanation": build_lmm_explanation(diagnostics),
        }

    return {
        "proposal": None,
        "plan_diff": None,
        "explanation": build_lmm_explanation(diagnostics),
    }
