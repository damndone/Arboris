"""Deterministic explanations for permitted LMM packet facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from workbench.contracts.common.envelope import ContractError, PacketEnvelope
from workbench.contracts.model.linear_mixed_effects import (
    LMM_CONTRACT_VERSION,
    LMM_MODEL_TYPE,
    LmmDiagnostic,
    LmmModelInput,
)
from workbench.model_options import (
    ModelOptionsError,
    verify_binding_owner_for_model_type,
    verify_bound_model_options,
)


_FALLBACK_EXPLANATION = "未提供可用于生成说明的受控 LMM 诊断。"
_RESTRICTED_REML_EXPLANATION = (
    "两个模型使用 REML 且固定效应结构不同；"
    "不能把 AIC、似然或似然比检验作为直接优劣判断。"
)
_RESTRICTED_REML_PACKET_MESSAGE = (
    "两个模型使用 REML 且固定效应结构不同；"
    "似然、AIC 和似然比检验不作为有效的直接比较依据。"
)
_DIAGNOSTIC_FIELDS = frozenset(
    {"code", "severity", "status", "evidence", "action_candidate"}
)
_EXPLANATION_BY_FACT = {
    (
        "LMM_CONVERGENCE_FAILED",
        "error",
        "failed",
    ): "模型未收敛，不能据此给出稳定的实质性结论。",
    (
        "LMM_SUBJECT_ID_MISSING",
        "error",
        "blocked",
    ): "缺少可用的受试者标识列（subject identifier）；请提供能识别重复观测单位的列后重新运行。",
    (
        "LMM_TIME_NOT_NUMERIC",
        "error",
        "blocked",
    ): "时间列不是可用的数值列；请提供数值时间列后重新运行。",
    (
        "LMM_GROUP_NOT_BINARY",
        "error",
        "blocked",
    ): "分组列不是二元分组；当前重复测量模型只支持二元分组。",
    (
        "LMM_GROUP_VARIES_WITHIN_SUBJECT",
        "error",
        "blocked",
    ): "分组在同一受试者内发生变化；请提供受试者内保持不变的分组列后重新运行。",
    (
        "LMM_INSUFFICIENT_REPEATED_OBSERVATIONS",
        "error",
        "blocked",
    ): "重复观测不足；请提供每个受试者的足够重复观测后重新运行。",
    (
        "LMM_INVALID_RANDOM_SLOPE_CONFIGURATION",
        "error",
        "blocked",
    ): "随机时间斜率配置无效；请检查时间列与重复观测结构后重新运行。",
    (
        "LMM_RANDOM_SLOPE_NEAR_ZERO",
        "warning",
        "complete",
    ): "随机时间斜率的方差接近零。建议在保持固定效应和样本选择不变的前提下，改为仅随机截距模型。",
    (
        "LMM_RANDOM_EFFECTS_SINGULAR",
        "warning",
        "complete",
    ): "随机效应结构出现奇异性。建议在保持固定效应和样本选择不变的前提下，改为仅随机截距模型。",
}


def validate_recovery_patch(value: object) -> dict[str, object]:
    """Accept only the contract-locked random-slope removal patch."""

    if (
        not isinstance(value, Mapping)
        or set(value) != {"model_options"}
        or not isinstance(value.get("model_options"), Mapping)
        or set(value["model_options"]) != {"random_slope"}
        or type(value["model_options"]["random_slope"]) is not bool
        or value["model_options"]["random_slope"] is not False
    ):
        raise ValueError("unsupported LMM recovery patch")
    return {"model_options": {"random_slope": False}}


def validate_lmm_diagnostics(value: object) -> tuple[LmmDiagnostic, ...] | None:
    """Parse the whole diagnostics list before any consumer may inspect it."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None

    diagnostics: list[LmmDiagnostic] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != _DIAGNOSTIC_FIELDS:
            return None
        try:
            diagnostic = LmmDiagnostic(
                code=item["code"],
                severity=item["severity"],
                status=item["status"],
                evidence=item["evidence"],
                action_candidate=item["action_candidate"],
            )
            if diagnostic.action_candidate is not None:
                validate_recovery_patch(diagnostic.action_candidate["patch"])
        except (ContractError, KeyError, TypeError, ValueError):
            return None
        diagnostics.append(diagnostic)
    return tuple(diagnostics)


def validate_lmm_source(source: object) -> LmmModelInput | None:
    """Return a trusted LMM source only after C1.1 binding verification."""

    if not isinstance(source, Mapping) or source.get("model_type") != LMM_MODEL_TYPE:
        return None
    source_status = source.get("status")
    if source_status is not None and (
        type(source_status) is not str
        or source_status not in {"complete", "completed"}
    ):
        return None
    try:
        bound = verify_bound_model_options(
            source.get("model_options"), source.get("model_options_binding")
        )
        if bound.binding is None or not bound.payload:
            return None
        verify_binding_owner_for_model_type(bound.binding, LMM_MODEL_TYPE)
        return LmmModelInput.from_dict(bound.payload)
    except (ContractError, ModelOptionsError, TypeError, ValueError):
        return None


def _is_verified_restricted_reml_comparison(value: object) -> bool:
    """Recognize only the versioned C1 restricted-REML comparison packet."""

    if not isinstance(value, Mapping):
        return False
    try:
        envelope = PacketEnvelope.from_dict(value)
    except (ContractError, TypeError, ValueError):
        return False

    if (
        envelope.contract != "analysis_loop.compare"
        or envelope.contract_version != LMM_CONTRACT_VERSION
        or envelope.producer_version != "linear_mixed_effects@1.0"
    ):
        return False

    payload = envelope.payload
    return (
        type(payload.get("source_run_id")) is str
        and bool(payload["source_run_id"])
        and type(payload.get("child_run_id")) is str
        and bool(payload["child_run_id"])
        and payload.get("compare_status") == "restricted"
        and payload.get("reason_code") == "REML_FIXED_EFFECTS_DIFFER"
        and payload.get("user_safe_message") == _RESTRICTED_REML_PACKET_MESSAGE
    )


def build_lmm_explanation(
    diagnostics: object,
    *,
    source: object = None,
    comparison: object = None,
) -> str:
    """Explain only recognized diagnostic or restricted-comparison facts."""

    model_input = validate_lmm_source(source)
    if model_input is None or model_input.random_slope is not True:
        return _FALLBACK_EXPLANATION

    trusted_diagnostics = validate_lmm_diagnostics(diagnostics)
    if trusted_diagnostics is None:
        return _FALLBACK_EXPLANATION

    if comparison is not None:
        if _is_verified_restricted_reml_comparison(comparison):
            return _RESTRICTED_REML_EXPLANATION
        return _FALLBACK_EXPLANATION

    explanations: list[tuple[str, str]] = []
    for diagnostic in trusted_diagnostics:
        explanation = _EXPLANATION_BY_FACT.get(
            (diagnostic.code, diagnostic.severity, diagnostic.status)
        )
        if explanation is None:
            return _FALLBACK_EXPLANATION
        explanations.append((diagnostic.status, explanation))

    for status in ("failed", "blocked", "complete"):
        for explanation_status, explanation in explanations:
            if explanation_status == status:
                return explanation
    return _FALLBACK_EXPLANATION
