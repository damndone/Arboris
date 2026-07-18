"""The finite, immutable recovery-action vocabulary for the golden flow."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class RecoveryAction:
    action_id: str
    operation_id: str
    allowed_model: str
    source_covariance: str
    target_covariance: str
    required_fields: tuple[str, ...]
    covariance_only: bool
    field_mapping: Mapping[str, str]
    policy_version: str

    def __post_init__(self) -> None:
        for name in (
            "action_id",
            "operation_id",
            "allowed_model",
            "source_covariance",
            "target_covariance",
            "policy_version",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.covariance_only) is not bool:
            raise TypeError("covariance_only must be a bool")
        if not isinstance(self.required_fields, (tuple, list)) or any(
            type(item) is not str or not item for item in self.required_fields
        ):
            raise TypeError("required_fields must contain non-empty strings")
        if not isinstance(self.field_mapping, Mapping):
            raise TypeError("field_mapping must be a mapping")
        if any(
            type(key) is not str
            or not key
            or type(value) is not str
            or not value
            for key, value in self.field_mapping.items()
        ):
            raise TypeError("field_mapping must map non-empty strings to strings")
        object.__setattr__(self, "required_fields", tuple(self.required_fields))
        object.__setattr__(self, "field_mapping", MappingProxyType(dict(self.field_mapping)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "operation_id": self.operation_id,
            "allowed_model": self.allowed_model,
            "source_covariance": self.source_covariance,
            "target_covariance": self.target_covariance,
            "required_fields": list(self.required_fields),
            "covariance_only": self.covariance_only,
            "field_mapping": dict(self.field_mapping),
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecoveryAction":
        if not isinstance(value, Mapping):
            raise TypeError("recovery action must be a mapping")
        required = {
            "action_id",
            "operation_id",
            "allowed_model",
            "source_covariance",
            "target_covariance",
            "required_fields",
            "covariance_only",
            "field_mapping",
            "policy_version",
        }
        extra = set(value) - required
        missing = required - set(value)
        if extra:
            raise ValueError("extra recovery action field(s): " + ", ".join(sorted(extra)))
        if missing:
            raise KeyError("missing recovery action field(s): " + ", ".join(sorted(missing)))
        return cls(
            action_id=value["action_id"],
            operation_id=value["operation_id"],
            allowed_model=value["allowed_model"],
            source_covariance=value["source_covariance"],
            target_covariance=value["target_covariance"],
            required_fields=value["required_fields"],
            covariance_only=value["covariance_only"],
            field_mapping=value["field_mapping"],
            policy_version=value["policy_version"],
        )


class RecoveryActionRegistry:
    """An immutable registry that cannot synthesize actions at validation time."""

    def __init__(self, actions: Iterable[RecoveryAction]) -> None:
        by_id: dict[str, RecoveryAction] = {}
        for action in actions:
            if action.action_id in by_id:
                raise ValueError(f"duplicate recovery action: {action.action_id}")
            by_id[action.action_id] = action
        self._actions = MappingProxyType(by_id)

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._actions))

    def get(self, action_id: str) -> RecoveryAction | None:
        if type(action_id) is not str:
            return None
        return self._actions.get(action_id)

    def require(self, action_id: str) -> RecoveryAction:
        action = self.get(action_id)
        if action is None:
            raise KeyError(action_id)
        return action

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {action_id: action.to_dict() for action_id, action in self._actions.items()}


OLS_CLUSTERED_RECOVERY_ACTION = RecoveryAction(
    action_id="ols.use_clustered_covariance_v1",
    operation_id="model.rerun",
    allowed_model="ols",
    source_covariance="unadjusted",
    target_covariance="clustered",
    required_fields=("cluster_variable",),
    covariance_only=True,
    field_mapping={"cluster_variable": "entity_col"},
    policy_version="ols_cluster_policy_v1",
)

RECOVERY_ACTION_REGISTRY = RecoveryActionRegistry((OLS_CLUSTERED_RECOVERY_ACTION,))
RECOVERY_ACTIONS = MappingProxyType(
    {OLS_CLUSTERED_RECOVERY_ACTION.action_id: OLS_CLUSTERED_RECOVERY_ACTION}
)
recovery_action_registry = RECOVERY_ACTION_REGISTRY


def get_recovery_action(action_id: str) -> RecoveryAction | None:
    return RECOVERY_ACTION_REGISTRY.get(action_id)
