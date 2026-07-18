"""Strict v1 contracts for the initial linear mixed-effects recipe."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from workbench.analysis_loop.canonical import sha256_canonical
from workbench.contracts.agent.repeated_measures import (
    LMM_BLOCKING_CODES,
    LMM_RECOVERY_ACTION_ID,
    LMM_RECOVERY_OPERATION_ID,
    LMM_RECOVERY_PATCH,
)
from workbench.contracts.common.envelope import (
    ContractError,
    freeze_json,
    require_exact_keys,
    thaw_json,
)


LMM_MODEL_TYPE = "linear_mixed_effects"
LMM_CONTRACT_VERSION = "1.0"
LMM_ESTIMATOR_VERSION = "statsmodels_mixedlm_v1"
LMM_MISSING_POLICY = "complete_case_v1"
LMM_PRIMARY_RESULT_ID = "group_time_interaction"
LMM_INFERENCE_METHOD = "asymptotic_wald_z_v1"

_LMM_INPUT_FIELDS = {
    "subject_id",
    "time",
    "group",
    "fit_method",
    "random_slope",
}
_LMM_RESULT_IDENTITY_FIELDS = {
    "dataset_fingerprint",
    "analysis_unit",
    "outcome",
    "fixed_effects",
    "random_effects",
    "group",
    "reference_group",
    "fit_method",
    "missing_policy",
    "estimator_version",
    "contract_version",
}
_RECOVERABLE_DIAGNOSTIC_CODES = frozenset(
    {"LMM_RANDOM_SLOPE_NEAR_ZERO", "LMM_RANDOM_EFFECTS_SINGULAR"}
)
_ACTION_CANDIDATE_FIELDS = {
    "action_id",
    "operation_id",
    "patch",
    "required_confirmation",
}


def _require_non_empty_string(value: Any, field_name: str) -> None:
    if type(value) is not str or not value:
        raise ContractError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True)
class LmmModelInput:
    """The only model options accepted by v1 linear mixed-effects fitting."""

    subject_id: str
    time: str
    group: str
    fit_method: Literal["reml", "ml"]
    random_slope: bool

    def __post_init__(self) -> None:
        for field_name in ("subject_id", "time", "group"):
            _require_non_empty_string(getattr(self, field_name), field_name)
        if type(self.fit_method) is not str or self.fit_method not in {"reml", "ml"}:
            raise ContractError("fit_method must be reml or ml")
        if type(self.random_slope) is not bool:
            raise ContractError("random_slope must be a bool")

    def to_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "time": self.time,
            "group": self.group,
            "fit_method": self.fit_method,
            "random_slope": self.random_slope,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "LmmModelInput":
        require_exact_keys(value, _LMM_INPUT_FIELDS, "LMM input")
        return cls(
            subject_id=value["subject_id"],
            time=value["time"],
            group=value["group"],
            fit_method=value["fit_method"],
            random_slope=value["random_slope"],
        )


@dataclass(frozen=True)
class LmmDiagnostic:
    """A deterministic LMM diagnostic and its optional user-confirmed recovery."""

    code: str
    severity: Literal["info", "warning", "error"]
    status: Literal["complete", "blocked", "failed"]
    evidence: Mapping[str, object]
    action_candidate: Mapping[str, object] | None

    def __post_init__(self) -> None:
        _require_non_empty_string(self.code, "code")
        if type(self.severity) is not str or self.severity not in {
            "info",
            "warning",
            "error",
        }:
            raise ContractError("severity must be info, warning, or error")
        if type(self.status) is not str or self.status not in {
            "complete",
            "blocked",
            "failed",
        }:
            raise ContractError("status must be complete, blocked, or failed")
        if not isinstance(self.evidence, Mapping):
            raise ContractError("evidence must be a mapping")
        if self.code in LMM_BLOCKING_CODES:
            if self.action_candidate is not None:
                raise ContractError("blocking diagnostic must not include an action_candidate")
            expected_status = (
                "failed" if self.code == "LMM_CONVERGENCE_FAILED" else "blocked"
            )
            if self.status != expected_status or self.severity != "error":
                raise ContractError("blocking diagnostic must be an error at its locked status")

        object.__setattr__(self, "evidence", freeze_json(self.evidence, "evidence"))
        if self.action_candidate is not None:
            object.__setattr__(
                self,
                "action_candidate",
                _freeze_action_candidate(self.code, self.action_candidate),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "status": self.status,
            "evidence": thaw_json(self.evidence),
            "action_candidate": (
                thaw_json(self.action_candidate)
                if self.action_candidate is not None
                else None
            ),
        }


def _freeze_action_candidate(
    code: str, value: Mapping[str, object]
) -> Mapping[str, object]:
    if code not in _RECOVERABLE_DIAGNOSTIC_CODES:
        raise ContractError("only recoverable LMM diagnostics may include an action_candidate")
    require_exact_keys(value, _ACTION_CANDIDATE_FIELDS, "action_candidate")
    if value["action_id"] != LMM_RECOVERY_ACTION_ID:
        raise ContractError("action_candidate action_id is not the locked LMM recovery")
    if value["operation_id"] != LMM_RECOVERY_OPERATION_ID:
        raise ContractError("action_candidate operation_id must be model.rerun")
    if value["required_confirmation"] is not True:
        raise ContractError("action_candidate must require confirmation")
    if thaw_json(freeze_json(value["patch"], "action_candidate.patch")) != LMM_RECOVERY_PATCH:
        raise ContractError("action_candidate patch is not the locked LMM recovery patch")
    frozen = freeze_json(value, "action_candidate")
    assert isinstance(frozen, Mapping)
    return frozen


def build_lmm_result_identity(value: Mapping[str, object]) -> str:
    """Hash exactly the declared facts that make an LMM result comparable."""

    require_exact_keys(value, _LMM_RESULT_IDENTITY_FIELDS, "LMM result identity")
    return sha256_canonical(freeze_json(value, "LMM result identity"))
