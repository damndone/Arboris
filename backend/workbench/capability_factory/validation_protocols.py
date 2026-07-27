"""Server-owned, versioned validation protocol contracts for CF3."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .contracts import _content_digest, _digest, _positive_int, _sequence, _text


CHECK_KINDS = frozenset(
    {
        "known_truth",
        "boundary_error",
        "trusted_comparison",
        "numerical_stability",
        "repeatability",
        "scale_resource",
        "output_schema",
    }
)
VALIDATION_TIERS = frozenset({"E0", "E1", "E2", "E3"})


class ValidationProtocolError(ValueError):
    """Raised when a validation protocol is incomplete or untrusted."""


@dataclass(frozen=True, slots=True)
class ValidationProtocol:
    protocol_id: str
    revision: int
    check_kinds: tuple[str, ...]
    evidence_floor: str
    max_attempts: int
    seed_policy_ref: str
    threshold_policy_ref: str
    holdout_policy_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_id", _text(self.protocol_id, "protocol_id"))
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        checks = _sequence(self.check_kinds, "check_kinds")
        if any(item not in CHECK_KINDS for item in checks):
            raise ValidationProtocolError("check_kinds contains an unknown validation check")
        object.__setattr__(self, "check_kinds", checks)
        if self.evidence_floor not in VALIDATION_TIERS:
            raise ValidationProtocolError("unsupported evidence floor")
        object.__setattr__(self, "evidence_floor", self.evidence_floor)
        try:
            object.__setattr__(self, "max_attempts", _positive_int(self.max_attempts, "max_attempts"))
            for field in ("seed_policy_ref", "threshold_policy_ref", "holdout_policy_ref"):
                object.__setattr__(self, field, _digest(getattr(self, field), field))
        except ValueError as error:
            if isinstance(error, ValidationProtocolError):
                raise
            raise ValidationProtocolError(str(error)) from error

    @property
    def requires_independent_oracle(self) -> bool:
        return self.evidence_floor in {"E2", "E3"}

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


class ValidationProtocolRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ValidationProtocol] = {}
        self._identities: dict[tuple[str, int], str] = {}
        self._lock = RLock()

    def register(self, protocol: ValidationProtocol) -> str:
        if not isinstance(protocol, ValidationProtocol):
            raise ValidationProtocolError("only ValidationProtocol values can be registered")
        with self._lock:
            identity = (protocol.protocol_id, protocol.revision)
            previous_ref = self._identities.get(identity)
            if previous_ref is not None and previous_ref != protocol.content_digest:
                raise ValidationProtocolError("protocol identity is already bound")
            previous = self._items.get(protocol.content_digest)
            if previous is not None and previous != protocol:
                raise ValidationProtocolError("protocol digest is already bound")
            self._items[protocol.content_digest] = protocol
            self._identities[identity] = protocol.content_digest
            return protocol.content_digest

    def get(self, reference: str) -> ValidationProtocol:
        reference = _digest(reference, "protocol_ref")
        try:
            return self._items[reference]
        except KeyError as error:
            raise ValidationProtocolError("validation protocol was not found") from error


__all__ = [
    "CHECK_KINDS",
    "VALIDATION_TIERS",
    "ValidationProtocol",
    "ValidationProtocolError",
    "ValidationProtocolRegistry",
]
