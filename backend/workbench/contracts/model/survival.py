"""Typed contracts for the independent v1.8.6 survival evidence packet."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..common.envelope import ContractError, require_exact_keys


_VALIDATION_FIELDS = {"level", "external_oracle"}
from .validation_levels import check_validation  # noqa: E402
_EXTERNAL_ORACLE_STATUS = "not_verified"


@dataclass(frozen=True)
class SurvivalCoxRequest:
    """Independent typed input contract for the survival model family."""

    event_column: str
    group_column: str | None = None
    entry_column: str | None = None
    ties: Literal["breslow", "efron"] = "breslow"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SurvivalCoxRequest":
        if not isinstance(value, Mapping):
            raise ContractError("survival_cox request must be a mapping")
        unknown = sorted(set(value) - {"event_column", "group_column", "entry_column", "ties"})
        if unknown:
            raise ContractError(f"survival_cox request has unknown field(s): {', '.join(unknown)}")
        event_column = value.get("event_column")
        if type(event_column) is not str or not event_column:
            raise ContractError("survival_cox.event_column is required")
        for field_name in ("group_column", "entry_column"):
            field_value = value.get(field_name)
            if field_value is not None and (type(field_value) is not str or not field_value):
                raise ContractError(f"survival_cox.{field_name} must be a non-empty column name")
        ties = value.get("ties", "breslow")
        if ties not in {"breslow", "efron"}:
            raise ContractError("survival_cox.ties must be breslow or efron")
        return cls(
            event_column=event_column,
            group_column=value.get("group_column"),
            entry_column=value.get("entry_column"),
            ties=ties,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_column": self.event_column,
            "group_column": self.group_column,
            "entry_column": self.entry_column,
            "ties": self.ties,
        }


def _require_string(value: Any, field_name: str) -> str:
    if type(value) is not str or not value:
        raise ContractError(f"{field_name} must be a non-empty string")
    return value


def _require_positive_int(value: Any, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ContractError(f"{field_name} must be a positive int")
    return value


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field_name} must be a mapping")
    if any(type(key) is not str for key in value):
        raise ContractError(f"{field_name} mapping keys must be strings")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{field_name} must be an array")
    return value


def _require_validation(value: Any) -> Mapping[str, str]:
    validation = _require_mapping(value, "survival_evidence.validation")
    require_exact_keys(validation, _VALIDATION_FIELDS, "survival_evidence.validation")
    # Shared with the family contracts rather than re-stated: the two used to
    # carry separate copies of these constants, so raising the level in one made
    # the other reject the payload the first had just started requiring.
    check_validation(dict(validation), "survival_evidence.validation")
    return validation  # type: ignore[return-value]


@dataclass(frozen=True)
class SurvivalEvidenceContract:
    """Independent censoring, risk-set, and time-to-event evidence packet."""

    contract: str
    model_type: Literal["survival_cox"]
    duration_column: str
    event_column: str
    entry_column: str | None
    nobs: int
    censoring: Mapping[str, Any]
    time_to_event: Mapping[str, Any]
    kaplan_meier: list[Mapping[str, Any]]
    log_rank: Mapping[str, Any]
    risk_set: list[Mapping[str, Any]]
    schoenfeld: list[Mapping[str, Any]]
    validation: Mapping[str, str]

    def __post_init__(self) -> None:
        payload = self.to_dict()
        if payload.get("contract") != "workbench.survival.v1":
            raise ContractError("survival_evidence.contract must be workbench.survival.v1")
        if payload.get("model_type") != "survival_cox":
            raise ContractError("survival_evidence.model_type must be survival_cox")
        _require_string(self.duration_column, "survival_evidence.duration_column")
        _require_string(self.event_column, "survival_evidence.event_column")
        if self.entry_column is not None:
            _require_string(self.entry_column, "survival_evidence.entry_column")
        _require_positive_int(self.nobs, "survival_evidence.nobs")
        _require_mapping(self.censoring, "survival_evidence.censoring")
        _require_mapping(self.time_to_event, "survival_evidence.time_to_event")
        _require_list(self.kaplan_meier, "survival_evidence.kaplan_meier")
        _require_mapping(self.log_rank, "survival_evidence.log_rank")
        _require_list(self.risk_set, "survival_evidence.risk_set")
        _require_list(self.schoenfeld, "survival_evidence.schoenfeld")
        _require_validation(self.validation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "model_type": self.model_type,
            "duration_column": self.duration_column,
            "event_column": self.event_column,
            "entry_column": self.entry_column,
            "nobs": self.nobs,
            "censoring": dict(self.censoring),
            "time_to_event": dict(self.time_to_event),
            "kaplan_meier": list(self.kaplan_meier),
            "log_rank": dict(self.log_rank),
            "risk_set": list(self.risk_set),
            "schoenfeld": list(self.schoenfeld),
            "validation": dict(self.validation),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SurvivalEvidenceContract":
        require_exact_keys(
            value,
            {
                "contract", "model_type", "duration_column", "event_column", "entry_column", "nobs",
                "censoring", "time_to_event", "kaplan_meier", "log_rank", "risk_set", "schoenfeld",
                "validation",
            },
            "survival_evidence",
        )
        return cls(**value)
