"""Deterministic explanations for permitted LMM packet facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


_FALLBACK_EXPLANATION = "未提供可用于生成说明的受控 LMM 诊断。"
_RESTRICTED_REML_EXPLANATION = (
    "两个模型使用 REML 且固定效应结构不同；"
    "不能把 AIC、似然或似然比检验作为直接优劣判断。"
)
_EXPLANATION_BY_FACT = {
    ("LMM_CONVERGENCE_FAILED", "failed"): "模型未收敛，不能据此给出稳定的实质性结论。",
    (
        "LMM_SUBJECT_ID_MISSING",
        "blocked",
    ): "缺少可用的受试者标识列（subject identifier）；请提供能识别重复观测单位的列后重新运行。",
    (
        "LMM_TIME_NOT_NUMERIC",
        "blocked",
    ): "时间列不是可用的数值列；请提供数值时间列后重新运行。",
    (
        "LMM_GROUP_NOT_BINARY",
        "blocked",
    ): "分组列不是二元分组；当前重复测量模型只支持二元分组。",
    (
        "LMM_GROUP_VARIES_WITHIN_SUBJECT",
        "blocked",
    ): "分组在同一受试者内发生变化；请提供受试者内保持不变的分组列后重新运行。",
    (
        "LMM_INSUFFICIENT_REPEATED_OBSERVATIONS",
        "blocked",
    ): "重复观测不足；请提供每个受试者的足够重复观测后重新运行。",
    (
        "LMM_INVALID_RANDOM_SLOPE_CONFIGURATION",
        "blocked",
    ): "随机时间斜率配置无效；请检查时间列与重复观测结构后重新运行。",
    (
        "LMM_RANDOM_SLOPE_NEAR_ZERO",
        "complete",
    ): "随机时间斜率的方差接近零。建议在保持固定效应和样本选择不变的前提下，改为仅随机截距模型。",
    (
        "LMM_RANDOM_EFFECTS_SINGULAR",
        "complete",
    ): "随机效应结构出现奇异性。建议在保持固定效应和样本选择不变的前提下，改为仅随机截距模型。",
}


def build_lmm_explanation(
    diagnostics: Sequence[Mapping[str, object]],
    *,
    comparison: Mapping[str, object] | None = None,
) -> str:
    """Explain only recognized diagnostic or restricted-comparison facts."""

    if (
        isinstance(comparison, Mapping)
        and comparison.get("compare_status") == "restricted"
        and comparison.get("reason_code") == "REML_FIXED_EFFECTS_DIFFER"
    ):
        return _RESTRICTED_REML_EXPLANATION

    explanations: list[tuple[str, str]] = []
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, Mapping):
            return _FALLBACK_EXPLANATION
        code = diagnostic.get("code")
        status = diagnostic.get("status")
        if type(code) is not str or type(status) is not str:
            return _FALLBACK_EXPLANATION
        explanation = _EXPLANATION_BY_FACT.get((code, status))
        if explanation is None:
            return _FALLBACK_EXPLANATION
        explanations.append((status, explanation))

    for status in ("failed", "blocked", "complete"):
        for explanation_status, explanation in explanations:
            if explanation_status == status:
                return explanation
    return _FALLBACK_EXPLANATION
