"""Execution-free CF4 preflight for a generic custom capability."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from ..custom_capability.canonical import domain_digest
from .adapter_contract import AdapterContract, AdapterContractError
from .contracts import CONSUMER_SLOTS, ImplementationRevision
from .dispatch import PreparedRunIntent
from .notebook_binding import CapabilityResolutionBinding


CUSTOM_DISPATCH_PREFLIGHT_CONTRACT_VERSION = "custom-dispatch-preflight/v1"
_HEX = frozenset("0123456789abcdef")


class CustomDispatchPreflightError(ValueError):
    """The immutable preflight join cannot be admitted to the next stage."""


def _text(value: Any, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise CustomDispatchPreflightError(f"{field} must be bounded non-empty text")
    if any(ord(char) < 0x20 for char in value):
        raise CustomDispatchPreflightError(f"{field} contains a control character")
    return value


def _digest(value: Any, field: str) -> str:
    text = _text(value, field, maximum=64)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise CustomDispatchPreflightError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _consumers(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or not value:
        raise CustomDispatchPreflightError("requested_consumers must be non-empty")
    result = tuple(_text(item, "consumer") for item in value)
    if len(set(result)) != len(result):
        raise CustomDispatchPreflightError("requested_consumers must be unique")
    if not set(result) <= set(CONSUMER_SLOTS):
        raise CustomDispatchPreflightError("requested_consumers contains an unknown consumer")
    return result


@dataclass(frozen=True, slots=True)
class CustomDispatchPlan:
    """A preflight packet; it deliberately has no execution capability."""

    intent_digest: str
    binding_digest: str
    adapter_digest: str
    implementation_digest: str
    operation_id: str
    requested_consumers: tuple[str, ...]
    consumer_support: Mapping[str, str]

    def __post_init__(self) -> None:
        for field in (
            "intent_digest",
            "binding_digest",
            "adapter_digest",
            "implementation_digest",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        object.__setattr__(self, "operation_id", _text(self.operation_id, "operation_id"))
        consumers = _consumers(self.requested_consumers)
        object.__setattr__(self, "requested_consumers", consumers)
        if not isinstance(self.consumer_support, Mapping):
            raise CustomDispatchPreflightError("consumer_support must be an object")
        if set(self.consumer_support) != set(consumers):
            raise CustomDispatchPreflightError("consumer_support must cover requested consumers exactly")
        normalized = {
            consumer: _text(self.consumer_support[consumer], f"consumer_support.{consumer}")
            for consumer in consumers
        }
        object.__setattr__(self, "consumer_support", MappingProxyType(normalized))

    @property
    def requires_user_confirmation(self) -> bool:
        return True

    @property
    def reservation_required(self) -> bool:
        return True

    @property
    def execution_allowed(self) -> bool:
        return False

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CUSTOM_DISPATCH_PREFLIGHT_CONTRACT_VERSION,
            "intent_digest": self.intent_digest,
            "binding_digest": self.binding_digest,
            "adapter_digest": self.adapter_digest,
            "implementation_digest": self.implementation_digest,
            "operation_id": self.operation_id,
            "requested_consumers": list(self.requested_consumers),
            "consumer_support": dict(self.consumer_support),
            "requires_user_confirmation": True,
            "reservation_required": True,
            "execution_allowed": False,
        }

    @property
    def content_digest(self) -> str:
        return domain_digest("workbench.capability_factory.custom_dispatch_plan/v1", self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "content_digest": self.content_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CustomDispatchPlan":
        expected = {
            "contract_version",
            "intent_digest",
            "binding_digest",
            "adapter_digest",
            "implementation_digest",
            "operation_id",
            "requested_consumers",
            "consumer_support",
            "requires_user_confirmation",
            "reservation_required",
            "execution_allowed",
            "content_digest",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise CustomDispatchPreflightError("custom dispatch plan fields are invalid")
        if value["contract_version"] != CUSTOM_DISPATCH_PREFLIGHT_CONTRACT_VERSION:
            raise CustomDispatchPreflightError("custom dispatch plan contract is unsupported")
        if (
            value["requires_user_confirmation"] is not True
            or value["reservation_required"] is not True
            or value["execution_allowed"] is not False
        ):
            raise CustomDispatchPreflightError("custom dispatch plan execution flags are invalid")
        result = cls(
            intent_digest=value["intent_digest"],
            binding_digest=value["binding_digest"],
            adapter_digest=value["adapter_digest"],
            implementation_digest=value["implementation_digest"],
            operation_id=value["operation_id"],
            requested_consumers=tuple(value["requested_consumers"]),
            consumer_support=value["consumer_support"],
        )
        if value["content_digest"] != result.content_digest:
            raise CustomDispatchPreflightError("custom dispatch plan content digest mismatch")
        return result


class CustomCapabilityDispatcher:
    """Only creates a validated plan; it intentionally has no runner method."""

    @staticmethod
    def prepare(
        *,
        intent: PreparedRunIntent,
        binding: CapabilityResolutionBinding,
        adapter: AdapterContract,
        implementation: ImplementationRevision,
        operation_id: str,
        requested_consumers: tuple[str, ...] | list[str],
    ) -> CustomDispatchPlan:
        if not isinstance(intent, PreparedRunIntent):
            raise CustomDispatchPreflightError("intent must be a PreparedRunIntent")
        if not isinstance(binding, CapabilityResolutionBinding):
            raise CustomDispatchPreflightError("binding must be a CapabilityResolutionBinding")
        if not isinstance(adapter, AdapterContract):
            raise CustomDispatchPreflightError("adapter must be an AdapterContract")
        if not isinstance(implementation, ImplementationRevision):
            raise CustomDispatchPreflightError("implementation must be an ImplementationRevision")
        try:
            adapter.validate_against(implementation)
        except AdapterContractError as error:
            raise CustomDispatchPreflightError(f"implementation or adapter mismatch: {error}") from error
        if binding.resolution_binding_ref != intent.binding_ref:
            raise CustomDispatchPreflightError("binding does not match intent")
        if binding.implementation_ref != implementation.content_digest:
            raise CustomDispatchPreflightError("binding implementation does not match")
        if binding.adapter_ref != adapter.content_digest:
            raise CustomDispatchPreflightError("binding adapter does not match")
        if binding.admission_ref != intent.admission_ref:
            raise CustomDispatchPreflightError("binding admission does not match intent")
        if binding.runtime_policy_ref != intent.runtime_policy_ref:
            raise CustomDispatchPreflightError("binding runtime policy does not match intent")
        if operation_id != intent.operation_id:
            raise CustomDispatchPreflightError("operation does not match intent")
        if operation_id not in binding.allowed_operations or operation_id not in adapter.operations:
            raise CustomDispatchPreflightError("operation is not admitted by the binding and adapter")
        consumers = _consumers(requested_consumers)
        if not set(consumers) <= set(binding.allowed_consumers):
            raise CustomDispatchPreflightError("consumer is outside the admitted binding")
        support: dict[str, str] = {}
        for consumer in consumers:
            slot = adapter.consumer_support.get(consumer)
            if slot is None:
                raise CustomDispatchPreflightError(
                    f"consumer {consumer} is not explicitly supported by the adapter"
                )
            support[consumer] = slot
        return CustomDispatchPlan(
            intent_digest=intent.content_digest,
            binding_digest=binding.content_digest,
            adapter_digest=adapter.content_digest,
            implementation_digest=implementation.content_digest,
            operation_id=operation_id,
            requested_consumers=consumers,
            consumer_support=support,
        )


__all__ = [
    "CUSTOM_DISPATCH_PREFLIGHT_CONTRACT_VERSION",
    "CustomCapabilityDispatcher",
    "CustomDispatchPlan",
    "CustomDispatchPreflightError",
]
