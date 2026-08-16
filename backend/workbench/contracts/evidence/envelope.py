"""Strict immutable v1 statistical evidence contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from workbench.canonical import CanonicalJSONError, canonical_json_v1
from workbench.contracts.common.envelope import (
    ContractError,
    freeze_json,
    require_exact_keys,
    thaw_json,
)
from workbench.contracts.common.foundation_status import (
    AvailabilityStatusV1,
    CompletenessStatusV1,
    EvaluationDesignV1,
    ExecutionStatusV1,
    InferenceBasisV1,
    NumericalMethodV1,
    ValidationLevelV1,
    ValidationRequirementStatusV1,
    validation_level_rank,
)


_EnumT = TypeVar("_EnumT")
_MAX_JSON_SAFE_INTEGER = 9_007_199_254_740_991
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_ORACLE_STATUSES = frozenset({"pass", "fail", "not_verified", "not_applicable"})
_TEST_DIRECTIONS = frozenset({"two_sided", "greater", "less"})
_NOT_APPLICABLE_FIELDS = {"status", "reason"}
_CONSUMER_PROJECTION_OUTER_FIELDS = {
    "contract",
    "contract_version",
    "producer_version",
    "payload",
}
_CONSUMER_PROJECTION_PAYLOAD_FIELDS = {
    "projection_id",
    "projection_ref",
    "projection_status",
    "slots",
    "not_applicable_projection",
}
_CONSUMER_PROJECTION_SLOT_FIELDS = {
    "consumer",
    "artifact_facets",
    "payload_schema_ref",
    "source_eligible",
}
_CONSUMER_PROJECTION_STATUS = frozenset({"available", "blocked", "not_applicable"})
_CONSUMER_PROJECTION_CONTRACT = "consumer-projection"
_CONSUMER_PROJECTION_VERSION = "1.0"
_CONSUMER_PRODUCER_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)

EVIDENCE_CONSUMER_PROJECTION_OUTER_FIELDS_INVALID = (
    "EVIDENCE_CONSUMER_PROJECTION_OUTER_FIELDS_INVALID"
)
EVIDENCE_CONSUMER_PROJECTION_CONTRACT_INVALID = (
    "EVIDENCE_CONSUMER_PROJECTION_CONTRACT_INVALID"
)
EVIDENCE_CONSUMER_PROJECTION_VERSION_INVALID = (
    "EVIDENCE_CONSUMER_PROJECTION_VERSION_INVALID"
)
EVIDENCE_CONSUMER_PROJECTION_PRODUCER_INVALID = (
    "EVIDENCE_CONSUMER_PROJECTION_PRODUCER_INVALID"
)
EVIDENCE_CONSUMER_PROJECTION_PAYLOAD_FIELDS_INVALID = (
    "EVIDENCE_CONSUMER_PROJECTION_PAYLOAD_FIELDS_INVALID"
)
EVIDENCE_CONSUMER_PROJECTION_STATUS_INVALID = (
    "EVIDENCE_CONSUMER_PROJECTION_STATUS_INVALID"
)
EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID = (
    "EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID"
)
EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_FIELDS_INVALID = (
    "EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_FIELDS_INVALID"
)
EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_STATUS_INVALID = (
    "EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_STATUS_INVALID"
)
EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_REASON_REQUIRED = (
    "EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_REASON_REQUIRED"
)
EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_REASON_INVALID = (
    "EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_REASON_INVALID"
)


class EvidenceContractError(ContractError):
    """Evidence wire failure with a stable machine-readable reason code."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def _consumer_projection_error(code: str, message: str) -> EvidenceContractError:
    return EvidenceContractError(code, message)


def _consumer_projection_text(
    value: object, name: str, code: str
) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(ord(char) < 0x20 for char in value)
    ):
        raise _consumer_projection_error(code, f"{name} is invalid")
    return value


def _consumer_projection_wire_dict(
    value: object, fields: frozenset[str], code: str, name: str
) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise _consumer_projection_error(code, f"{name} fields are not exact")
    return value


@dataclass(frozen=True)
class ConsumerProjectionNotApplicableV1:
    status: str
    reason: str

    def __post_init__(self) -> None:
        if self.status != "not_applicable":
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_STATUS_INVALID,
                "not_applicable status must be not_applicable",
            )
        _consumer_projection_text(
            self.reason,
            "not_applicable.reason",
            EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_REASON_INVALID,
        )

    def to_dict(self) -> dict[str, str]:
        return {"status": self.status, "reason": self.reason}

    @classmethod
    def from_dict(cls, value: object) -> "ConsumerProjectionNotApplicableV1":
        if type(value) is not dict:
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_FIELDS_INVALID,
                "not_applicable projection must be a built-in dict",
            )
        if "reason" not in value:
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_REASON_REQUIRED,
                "not_applicable projection requires reason",
            )
        value = _consumer_projection_wire_dict(
            value,
            frozenset({"status", "reason"}),
            EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_FIELDS_INVALID,
            "not_applicable projection",
        )
        return cls(
            status=value["status"],  # type: ignore[arg-type]
            reason=value["reason"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ConsumerProjectionSlotV1:
    consumer: str
    artifact_facets: tuple[str, ...]
    payload_schema_ref: str
    source_eligible: bool

    def __post_init__(self) -> None:
        _consumer_projection_text(
            self.consumer,
            "slot.consumer",
            EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID,
        )
        if not isinstance(self.artifact_facets, (list, tuple)):
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID,
                "slot.artifact_facets must be an array",
            )
        facets = tuple(
            _consumer_projection_text(
                item,
                "slot.artifact_facets[]",
                EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID,
            )
            for item in self.artifact_facets
        )
        if len(facets) != len(set(facets)):
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID,
                "slot.artifact_facets must be unique",
            )
        object.__setattr__(self, "artifact_facets", facets)
        _consumer_projection_text(
            self.payload_schema_ref,
            "slot.payload_schema_ref",
            EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID,
        )
        if type(self.source_eligible) is not bool:
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID,
                "slot.source_eligible must be a boolean",
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "consumer": self.consumer,
            "artifact_facets": list(self.artifact_facets),
            "payload_schema_ref": self.payload_schema_ref,
            "source_eligible": self.source_eligible,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ConsumerProjectionSlotV1":
        value = _consumer_projection_wire_dict(
            value,
            frozenset(
                {
                    "consumer",
                    "artifact_facets",
                    "payload_schema_ref",
                    "source_eligible",
                }
            ),
            EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID,
            "consumer projection slot",
        )
        if type(value["artifact_facets"]) is not list:
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID,
                "slot.artifact_facets must be a list",
            )
        return cls(
            consumer=value["consumer"],  # type: ignore[arg-type]
            artifact_facets=tuple(value["artifact_facets"]),  # type: ignore[arg-type]
            payload_schema_ref=value["payload_schema_ref"],  # type: ignore[arg-type]
            source_eligible=value["source_eligible"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ConsumerProjectionPayloadV1:
    projection_id: str
    projection_ref: str
    projection_status: str
    slots: tuple[ConsumerProjectionSlotV1, ...]
    not_applicable_projection: ConsumerProjectionNotApplicableV1

    def __post_init__(self) -> None:
        _consumer_projection_text(
            self.projection_id,
            "projection_id",
            EVIDENCE_CONSUMER_PROJECTION_PAYLOAD_FIELDS_INVALID,
        )
        _consumer_projection_text(
            self.projection_ref,
            "projection_ref",
            EVIDENCE_CONSUMER_PROJECTION_PAYLOAD_FIELDS_INVALID,
        )
        if type(self.projection_status) is not str or self.projection_status not in frozenset(
            {"available", "blocked", "not_applicable"}
        ):
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_STATUS_INVALID,
                "projection_status is not allowed",
            )
        if not isinstance(self.slots, (list, tuple)) or any(
            type(slot) is not ConsumerProjectionSlotV1 for slot in self.slots
        ):
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID,
                "slots must contain ConsumerProjectionSlotV1 values",
            )
        slots = tuple(self.slots)
        if len({slot.consumer for slot in slots}) != len(slots):
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID,
                "slots must have unique consumers",
            )
        object.__setattr__(self, "slots", slots)
        if type(self.not_applicable_projection) is not ConsumerProjectionNotApplicableV1:
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_NOT_APPLICABLE_FIELDS_INVALID,
                "not_applicable_projection has an invalid type",
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "projection_id": self.projection_id,
            "projection_ref": self.projection_ref,
            "projection_status": self.projection_status,
            "slots": [slot.to_dict() for slot in self.slots],
            "not_applicable_projection": self.not_applicable_projection.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> "ConsumerProjectionPayloadV1":
        value = _consumer_projection_wire_dict(
            value,
            frozenset(
                {
                    "projection_id",
                    "projection_ref",
                    "projection_status",
                    "slots",
                    "not_applicable_projection",
                }
            ),
            EVIDENCE_CONSUMER_PROJECTION_PAYLOAD_FIELDS_INVALID,
            "consumer projection payload",
        )
        raw_slots = value["slots"]
        if type(raw_slots) is not list:
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_SLOT_FIELDS_INVALID,
                "slots must be a list",
            )
        return cls(
            projection_id=value["projection_id"],  # type: ignore[arg-type]
            projection_ref=value["projection_ref"],  # type: ignore[arg-type]
            projection_status=value["projection_status"],  # type: ignore[arg-type]
            slots=tuple(ConsumerProjectionSlotV1.from_dict(slot) for slot in raw_slots),
            not_applicable_projection=ConsumerProjectionNotApplicableV1.from_dict(
                value["not_applicable_projection"]
            ),
        )


@dataclass(frozen=True)
class ConsumerProjectionV1:
    contract: str
    contract_version: str
    producer_version: str
    payload: ConsumerProjectionPayloadV1

    def __post_init__(self) -> None:
        if self.contract != "consumer-projection":
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_CONTRACT_INVALID,
                "consumer projection contract is invalid",
            )
        if self.contract_version != "1.0":
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_VERSION_INVALID,
                "consumer projection contract version is invalid",
            )
        if (
            type(self.producer_version) is not str
            or re.fullmatch(
                r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)",
                self.producer_version,
            )
            is None
        ):
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_PRODUCER_INVALID,
                "consumer projection producer version is invalid",
            )
        if type(self.payload) is not ConsumerProjectionPayloadV1:
            raise _consumer_projection_error(
                EVIDENCE_CONSUMER_PROJECTION_PAYLOAD_FIELDS_INVALID,
                "consumer projection payload has an invalid type",
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": self.contract,
            "contract_version": self.contract_version,
            "producer_version": self.producer_version,
            "payload": self.payload.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> "ConsumerProjectionV1":
        value = _consumer_projection_wire_dict(
            value,
            frozenset({"contract", "contract_version", "producer_version", "payload"}),
            EVIDENCE_CONSUMER_PROJECTION_OUTER_FIELDS_INVALID,
            "consumer projection",
        )
        return cls(
            contract=value["contract"],  # type: ignore[arg-type]
            contract_version=value["contract_version"],  # type: ignore[arg-type]
            producer_version=value["producer_version"],  # type: ignore[arg-type]
            payload=ConsumerProjectionPayloadV1.from_dict(value["payload"]),
        )


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ContractError(f"{name} must be an exact non-empty string")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{name} must be an array")
    return tuple(_text(item, f"{name}[]") for item in value)


def _finite_number(value: object, name: str) -> int | float:
    if type(value) is int:
        if -_MAX_JSON_SAFE_INTEGER <= value <= _MAX_JSON_SAFE_INTEGER:
            return value
        raise ContractError(f"{name} must be a portable finite number")
    if type(value) is float:
        if math.isfinite(value):
            return value
        raise ContractError(f"{name} must be a finite number")
    raise ContractError(f"{name} must be a finite number")


def _finite_float(value: object, name: str) -> float:
    if type(value) is not float:
        raise ContractError(f"{name} must be a finite float")
    if not math.isfinite(value):
        raise ContractError(f"{name} must be a finite float")
    return value


def _enum(value: object, enum_type: type[_EnumT], name: str) -> _EnumT:
    if type(value) is not str:
        raise ContractError(f"{name} is invalid")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ContractError(f"{name} is invalid") from exc


def _validate_portable_json_integers(
    value: object,
    name: str,
    active_container_ids: set[int] | None = None,
) -> None:
    if type(value) is int:
        if not -_MAX_JSON_SAFE_INTEGER <= value <= _MAX_JSON_SAFE_INTEGER:
            raise ContractError(f"{name} contains a nonportable integer")
        return
    if not isinstance(value, (Mapping, list, tuple)):
        return

    active = active_container_ids if active_container_ids is not None else set()
    container_id = id(value)
    if container_id in active:
        raise ContractError(f"{name} must be acyclic JSON")
    active.add(container_id)
    try:
        items = value.values() if isinstance(value, Mapping) else value
        for item in items:
            _validate_portable_json_integers(item, name, active)
    finally:
        active.remove(container_id)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a mapping")
    try:
        _validate_portable_json_integers(value, name)
        canonical_json_v1(value)
        frozen = freeze_json(value, name)
    except (CanonicalJSONError, ValueError, OverflowError, RecursionError) as exc:
        raise ContractError(f"{name} must be canonical JSON") from exc
    if not isinstance(frozen, Mapping):  # pragma: no cover - freeze_json contract
        raise ContractError(f"{name} must be a mapping")
    return frozen


def _mapping_tuple(value: object, name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{name} must be an array")
    return tuple(_mapping(item, f"{name}[]") for item in value)


def _wire_dict(
    value: object,
    required: set[str],
    name: str,
) -> dict[str, object]:
    if type(value) is not dict:
        raise ContractError(f"{name} must be a built-in dict")
    require_exact_keys(value, required, name)
    return value


def _wire_mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ContractError(f"{name} must be a built-in dict")
    return value


def _wire_mapping_tuple(
    value: object,
    name: str,
) -> tuple[dict[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{name} must be an array")
    return tuple(_wire_mapping(item, f"{name}[]") for item in value)


@dataclass(frozen=True)
class NotApplicableV1:
    reason: str

    def __post_init__(self) -> None:
        _text(self.reason, "reason")

    def to_dict(self) -> dict[str, str]:
        return {"status": "not_applicable", "reason": self.reason}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "NotApplicableV1":
        value = _wire_dict(value, _NOT_APPLICABLE_FIELDS, "not_applicable")
        if value["status"] != "not_applicable":
            raise ContractError("not_applicable.status must be not_applicable")
        return cls(reason=value["reason"])  # type: ignore[arg-type]


def _not_applicable(value: object, name: str) -> NotApplicableV1:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a not-applicable object")
    return NotApplicableV1.from_dict(value)


def _string_or_not_applicable(value: object, name: str) -> str | NotApplicableV1:
    if type(value) is str:
        return _text(value, name)
    return _not_applicable(value, name)


def _float_or_not_applicable(value: object, name: str) -> float | NotApplicableV1:
    if type(value) is float:
        return _finite_float(value, name)
    return _not_applicable(value, name)


def _serialize_union(value: object) -> object:
    if isinstance(value, NotApplicableV1):
        return value.to_dict()
    return value


@dataclass(frozen=True)
class EvidenceReasonV1:
    code: str
    message: str
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.code, "code")
        _text(self.message, "message")
        object.__setattr__(self, "source_refs", _string_tuple(self.source_refs, "source_refs"))

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "source_refs": list(self.source_refs),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "EvidenceReasonV1":
        value = _wire_dict(
            value,
            {"code", "message", "source_refs"},
            "evidence_reason",
        )
        return cls(
            code=value["code"],  # type: ignore[arg-type]
            message=value["message"],  # type: ignore[arg-type]
            source_refs=_string_tuple(value["source_refs"], "source_refs"),
        )


@dataclass(frozen=True)
class DenominatorV1:
    kind: str
    value: int | float
    unit: str

    def __post_init__(self) -> None:
        _text(self.kind, "kind")
        value = _finite_number(self.value, "value")
        if value <= 0:
            raise ContractError("value must be greater than zero")
        _text(self.unit, "unit")

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "value": self.value, "unit": self.unit}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "DenominatorV1":
        value = _wire_dict(value, {"kind", "value", "unit"}, "denominator")
        return cls(
            kind=value["kind"],  # type: ignore[arg-type]
            value=value["value"],  # type: ignore[arg-type]
            unit=value["unit"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class WeightBasisV1:
    kind: str
    variable_ref: str | NotApplicableV1

    def __post_init__(self) -> None:
        _text(self.kind, "kind")
        if type(self.variable_ref) is str:
            _text(self.variable_ref, "variable_ref")
        elif type(self.variable_ref) is not NotApplicableV1:
            raise ContractError("variable_ref must be a string or NotApplicableV1")

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "variable_ref": _serialize_union(self.variable_ref)}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "WeightBasisV1":
        value = _wire_dict(value, {"kind", "variable_ref"}, "weight_basis")
        return cls(
            kind=value["kind"],  # type: ignore[arg-type]
            variable_ref=_string_or_not_applicable(value["variable_ref"], "variable_ref"),
        )


@dataclass(frozen=True)
class IntervalV1:
    lower: float
    upper: float
    method: str

    def __post_init__(self) -> None:
        lower = _finite_float(self.lower, "lower")
        upper = _finite_float(self.upper, "upper")
        if lower > upper:
            raise ContractError("lower must be less than or equal to upper")
        _text(self.method, "method")

    def to_dict(self) -> dict[str, object]:
        return {"lower": self.lower, "upper": self.upper, "method": self.method}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "IntervalV1":
        value = _wire_dict(value, {"lower", "upper", "method"}, "interval")
        return cls(
            lower=value["lower"],  # type: ignore[arg-type]
            upper=value["upper"],  # type: ignore[arg-type]
            method=value["method"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class DistributionRefV1:
    name: str
    degrees_of_freedom: float | NotApplicableV1
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        _text(self.name, "name")
        if type(self.degrees_of_freedom) is float:
            degrees_of_freedom = _finite_float(
                self.degrees_of_freedom,
                "degrees_of_freedom",
            )
            if degrees_of_freedom <= 0:
                raise ContractError("degrees_of_freedom must be greater than zero")
        elif type(self.degrees_of_freedom) is not NotApplicableV1:
            raise ContractError("degrees_of_freedom must be a float or NotApplicableV1")
        object.__setattr__(self, "parameters", _mapping(self.parameters, "parameters"))

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "degrees_of_freedom": _serialize_union(self.degrees_of_freedom),
            "parameters": thaw_json(self.parameters),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "DistributionRefV1":
        value = _wire_dict(
            value,
            {"name", "degrees_of_freedom", "parameters"},
            "distribution_ref",
        )
        return cls(
            name=value["name"],  # type: ignore[arg-type]
            degrees_of_freedom=_float_or_not_applicable(
                value["degrees_of_freedom"], "degrees_of_freedom"
            ),
            parameters=_wire_mapping(value["parameters"], "parameters"),
        )


@dataclass(frozen=True)
class MultipleComparisonV1:
    family_id: str | NotApplicableV1
    correction: str | NotApplicableV1

    def __post_init__(self) -> None:
        for name in ("family_id", "correction"):
            value = getattr(self, name)
            if type(value) is str:
                _text(value, name)
            elif type(value) is not NotApplicableV1:
                raise ContractError(f"{name} must be a string or NotApplicableV1")

    def to_dict(self) -> dict[str, object]:
        return {
            "family_id": _serialize_union(self.family_id),
            "correction": _serialize_union(self.correction),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "MultipleComparisonV1":
        value = _wire_dict(
            value,
            {"family_id", "correction"},
            "multiple_comparison",
        )
        return cls(
            family_id=_string_or_not_applicable(value["family_id"], "family_id"),
            correction=_string_or_not_applicable(value["correction"], "correction"),
        )


@dataclass(frozen=True)
class SourceSelectorV1:
    artifact_ref: str
    selector: str
    artifact_digest: str

    def __post_init__(self) -> None:
        _text(self.artifact_ref, "artifact_ref")
        _text(self.selector, "selector")
        if type(self.artifact_digest) is not str or _SHA256_PATTERN.fullmatch(self.artifact_digest) is None:
            raise ContractError("artifact_digest must be a lowercase SHA-256 digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "artifact_ref": self.artifact_ref,
            "selector": self.selector,
            "artifact_digest": self.artifact_digest,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "SourceSelectorV1":
        value = _wire_dict(
            value,
            {"artifact_ref", "selector", "artifact_digest"},
            "source_selector",
        )
        return cls(
            artifact_ref=value["artifact_ref"],  # type: ignore[arg-type]
            selector=value["selector"],  # type: ignore[arg-type]
            artifact_digest=value["artifact_digest"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class OracleCheckV1:
    check_id: str
    status: str
    basis: ValidationLevelV1
    reference: str | NotApplicableV1
    tolerance: str | NotApplicableV1
    observed_difference: float | NotApplicableV1

    def __post_init__(self) -> None:
        _text(self.check_id, "check_id")
        if type(self.status) is not str or self.status not in _ORACLE_STATUSES:
            raise ContractError("status is invalid")
        if type(self.basis) is not ValidationLevelV1:
            raise ContractError("basis must be ValidationLevelV1")
        for name in ("reference", "tolerance"):
            value = getattr(self, name)
            if type(value) is str:
                _text(value, name)
            elif type(value) is not NotApplicableV1:
                raise ContractError(f"{name} must be a string or NotApplicableV1")
        if type(self.observed_difference) is float:
            _finite_float(self.observed_difference, "observed_difference")
        elif type(self.observed_difference) is not NotApplicableV1:
            raise ContractError(
                "observed_difference must be a float or NotApplicableV1"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "basis": self.basis.value,
            "reference": _serialize_union(self.reference),
            "tolerance": _serialize_union(self.tolerance),
            "observed_difference": _serialize_union(self.observed_difference),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "OracleCheckV1":
        value = _wire_dict(
            value,
            {
                "check_id",
                "status",
                "basis",
                "reference",
                "tolerance",
                "observed_difference",
            },
            "oracle_check",
        )
        return cls(
            check_id=value["check_id"],  # type: ignore[arg-type]
            status=value["status"],  # type: ignore[arg-type]
            basis=_enum(value["basis"], ValidationLevelV1, "basis"),
            reference=_string_or_not_applicable(value["reference"], "reference"),
            tolerance=_string_or_not_applicable(value["tolerance"], "tolerance"),
            observed_difference=_float_or_not_applicable(
                value["observed_difference"], "observed_difference"
            ),
        )


_NUMERIC_FACT_FIELDS = {
    "fact_id",
    "estimand_id",
    "statistic_id",
    "value",
    "denominator",
    "weight",
    "unit",
    "scale",
    "standard_error",
    "confidence_interval",
    "confidence_level",
    "test_direction",
    "reference_distribution",
    "multiple_comparison",
    "evaluation_design",
    "source_selector",
    "oracle_checks",
    "validation_level",
}


@dataclass(frozen=True)
class NumericFactV1:
    fact_id: str
    estimand_id: str | NotApplicableV1
    statistic_id: str
    value: int | float
    denominator: DenominatorV1 | NotApplicableV1
    weight: WeightBasisV1 | NotApplicableV1
    unit: str | NotApplicableV1
    scale: str | NotApplicableV1
    standard_error: float | NotApplicableV1
    confidence_interval: IntervalV1 | NotApplicableV1
    confidence_level: float | NotApplicableV1
    test_direction: str | NotApplicableV1
    reference_distribution: DistributionRefV1 | NotApplicableV1
    multiple_comparison: MultipleComparisonV1 | NotApplicableV1
    evaluation_design: EvaluationDesignV1
    source_selector: SourceSelectorV1
    oracle_checks: tuple[OracleCheckV1, ...]
    validation_level: ValidationLevelV1

    def __post_init__(self) -> None:
        _text(self.fact_id, "fact_id")
        if type(self.estimand_id) is str:
            _text(self.estimand_id, "estimand_id")
        elif type(self.estimand_id) is not NotApplicableV1:
            raise ContractError("estimand_id must be a string or NotApplicableV1")
        _text(self.statistic_id, "statistic_id")
        _finite_number(self.value, "value")
        if type(self.denominator) not in {DenominatorV1, NotApplicableV1}:
            raise ContractError("denominator has an invalid type")
        if type(self.weight) not in {WeightBasisV1, NotApplicableV1}:
            raise ContractError("weight has an invalid type")
        for name in ("unit", "scale"):
            value = getattr(self, name)
            if type(value) is str:
                _text(value, name)
            elif type(value) is not NotApplicableV1:
                raise ContractError(f"{name} must be a string or NotApplicableV1")
        if type(self.standard_error) is float:
            standard_error = _finite_float(self.standard_error, "standard_error")
            if standard_error < 0:
                raise ContractError("standard_error must be non-negative")
        elif type(self.standard_error) is not NotApplicableV1:
            raise ContractError("standard_error must be a float or NotApplicableV1")
        if type(self.confidence_interval) not in {IntervalV1, NotApplicableV1}:
            raise ContractError("confidence_interval has an invalid type")
        if type(self.confidence_level) is float:
            confidence_level = _finite_float(self.confidence_level, "confidence_level")
            if not 0 < confidence_level < 1:
                raise ContractError("confidence_level must be between zero and one")
        elif type(self.confidence_level) is not NotApplicableV1:
            raise ContractError("confidence_level must be a float or NotApplicableV1")
        if type(self.test_direction) is str:
            if self.test_direction not in _TEST_DIRECTIONS:
                raise ContractError("test_direction is invalid")
        elif type(self.test_direction) is not NotApplicableV1:
            raise ContractError("test_direction has an invalid type")
        if type(self.reference_distribution) not in {
            DistributionRefV1,
            NotApplicableV1,
        }:
            raise ContractError("reference_distribution has an invalid type")
        if type(self.multiple_comparison) not in {
            MultipleComparisonV1,
            NotApplicableV1,
        }:
            raise ContractError("multiple_comparison has an invalid type")
        if type(self.evaluation_design) is not EvaluationDesignV1:
            raise ContractError("evaluation_design must be EvaluationDesignV1")
        if type(self.source_selector) is not SourceSelectorV1:
            raise ContractError("source_selector must be SourceSelectorV1")
        if not isinstance(self.oracle_checks, (list, tuple)) or any(
            type(check) is not OracleCheckV1 for check in self.oracle_checks
        ):
            raise ContractError("oracle_checks must contain OracleCheckV1 values")
        object.__setattr__(self, "oracle_checks", tuple(self.oracle_checks))
        check_ids = [check.check_id for check in self.oracle_checks]
        if len(check_ids) != len(set(check_ids)):
            raise ContractError("oracle_checks must have unique check_id values")
        if type(self.validation_level) is not ValidationLevelV1:
            raise ContractError("validation_level must be ValidationLevelV1")

        passing_levels = [
            check.basis for check in self.oracle_checks if check.status == "pass"
        ]
        expected_level = (
            max(passing_levels, key=validation_level_rank)
            if passing_levels
            else ValidationLevelV1.NONE
        )
        if self.validation_level is not expected_level:
            raise ContractError(
                "validation_level must equal the strongest passing oracle basis"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "estimand_id": _serialize_union(self.estimand_id),
            "statistic_id": self.statistic_id,
            "value": self.value,
            "denominator": self.denominator.to_dict(),
            "weight": self.weight.to_dict(),
            "unit": _serialize_union(self.unit),
            "scale": _serialize_union(self.scale),
            "standard_error": _serialize_union(self.standard_error),
            "confidence_interval": self.confidence_interval.to_dict(),
            "confidence_level": _serialize_union(self.confidence_level),
            "test_direction": _serialize_union(self.test_direction),
            "reference_distribution": self.reference_distribution.to_dict(),
            "multiple_comparison": self.multiple_comparison.to_dict(),
            "evaluation_design": self.evaluation_design.value,
            "source_selector": self.source_selector.to_dict(),
            "oracle_checks": [check.to_dict() for check in self.oracle_checks],
            "validation_level": self.validation_level.value,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "NumericFactV1":
        value = _wire_dict(value, _NUMERIC_FACT_FIELDS, "numeric_fact")
        oracle_checks = value["oracle_checks"]
        if not isinstance(oracle_checks, (list, tuple)):
            raise ContractError("oracle_checks must be an array")
        return cls(
            fact_id=value["fact_id"],  # type: ignore[arg-type]
            estimand_id=_string_or_not_applicable(value["estimand_id"], "estimand_id"),
            statistic_id=value["statistic_id"],  # type: ignore[arg-type]
            value=value["value"],  # type: ignore[arg-type]
            denominator=(
                DenominatorV1.from_dict(value["denominator"])
                if isinstance(value["denominator"], Mapping)
                and value["denominator"].get("status") != "not_applicable"
                else _not_applicable(value["denominator"], "denominator")
            ),
            weight=(
                WeightBasisV1.from_dict(value["weight"])
                if isinstance(value["weight"], Mapping)
                and value["weight"].get("status") != "not_applicable"
                else _not_applicable(value["weight"], "weight")
            ),
            unit=_string_or_not_applicable(value["unit"], "unit"),
            scale=_string_or_not_applicable(value["scale"], "scale"),
            standard_error=_float_or_not_applicable(
                value["standard_error"], "standard_error"
            ),
            confidence_interval=(
                IntervalV1.from_dict(value["confidence_interval"])
                if isinstance(value["confidence_interval"], Mapping)
                and value["confidence_interval"].get("status") != "not_applicable"
                else _not_applicable(value["confidence_interval"], "confidence_interval")
            ),
            confidence_level=_float_or_not_applicable(
                value["confidence_level"], "confidence_level"
            ),
            test_direction=(
                value["test_direction"]
                if type(value["test_direction"]) is str
                else _not_applicable(value["test_direction"], "test_direction")
            ),  # type: ignore[arg-type]
            reference_distribution=(
                DistributionRefV1.from_dict(value["reference_distribution"])
                if isinstance(value["reference_distribution"], Mapping)
                and value["reference_distribution"].get("status") != "not_applicable"
                else _not_applicable(
                    value["reference_distribution"], "reference_distribution"
                )
            ),
            multiple_comparison=(
                MultipleComparisonV1.from_dict(value["multiple_comparison"])
                if isinstance(value["multiple_comparison"], Mapping)
                and value["multiple_comparison"].get("status") != "not_applicable"
                else _not_applicable(value["multiple_comparison"], "multiple_comparison")
            ),
            evaluation_design=_enum(
                value["evaluation_design"], EvaluationDesignV1, "evaluation_design"
            ),
            source_selector=SourceSelectorV1.from_dict(value["source_selector"]),  # type: ignore[arg-type]
            oracle_checks=tuple(
                OracleCheckV1.from_dict(check) for check in oracle_checks  # type: ignore[arg-type]
            ),
            validation_level=_enum(
                value["validation_level"], ValidationLevelV1, "validation_level"
            ),
        )


@dataclass(frozen=True)
class ValidationSummaryV1:
    levels_present: tuple[ValidationLevelV1, ...]
    minimum_required: ValidationLevelV1
    requirement_status: ValidationRequirementStatusV1

    def __post_init__(self) -> None:
        if not isinstance(self.levels_present, (list, tuple)) or any(
            type(level) is not ValidationLevelV1 for level in self.levels_present
        ):
            raise ContractError("levels_present must contain ValidationLevelV1 values")
        levels = tuple(self.levels_present)
        expected_levels = tuple(sorted(set(levels), key=validation_level_rank))
        if levels != expected_levels:
            raise ContractError("levels_present must be unique and weakest-to-strongest")
        object.__setattr__(self, "levels_present", levels)
        if type(self.minimum_required) is not ValidationLevelV1:
            raise ContractError("minimum_required must be ValidationLevelV1")
        if type(self.requirement_status) is not ValidationRequirementStatusV1:
            raise ContractError(
                "requirement_status must be ValidationRequirementStatusV1"
            )
        expected_status = self._status_for_levels(levels, self.minimum_required)
        if self.requirement_status is not expected_status:
            raise ContractError("requirement_status does not match levels_present")

    @staticmethod
    def _status_for_levels(
        levels: tuple[ValidationLevelV1, ...],
        minimum_required: ValidationLevelV1,
    ) -> ValidationRequirementStatusV1:
        if minimum_required is ValidationLevelV1.NONE:
            return ValidationRequirementStatusV1.NOT_APPLICABLE
        if levels and all(
            validation_level_rank(level) >= validation_level_rank(minimum_required)
            for level in levels
        ):
            return ValidationRequirementStatusV1.MET
        return ValidationRequirementStatusV1.NOT_MET

    @classmethod
    def from_facts(
        cls,
        facts: Iterable[NumericFactV1],
        minimum_required: ValidationLevelV1,
    ) -> "ValidationSummaryV1":
        fact_tuple = tuple(facts)
        if any(type(fact) is not NumericFactV1 for fact in fact_tuple):
            raise ContractError("facts must contain NumericFactV1 values")
        if type(minimum_required) is not ValidationLevelV1:
            raise ContractError("minimum_required must be ValidationLevelV1")
        levels = tuple(
            sorted(
                {fact.validation_level for fact in fact_tuple},
                key=validation_level_rank,
            )
        )
        status = (
            ValidationRequirementStatusV1.NOT_APPLICABLE
            if minimum_required is ValidationLevelV1.NONE
            else (
                ValidationRequirementStatusV1.MET
                if fact_tuple
                and all(
                    validation_level_rank(fact.validation_level)
                    >= validation_level_rank(minimum_required)
                    for fact in fact_tuple
                )
                else ValidationRequirementStatusV1.NOT_MET
            )
        )
        return cls(
            levels_present=levels,
            minimum_required=minimum_required,
            requirement_status=status,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "levels_present": [level.value for level in self.levels_present],
            "minimum_required": self.minimum_required.value,
            "requirement_status": self.requirement_status.value,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ValidationSummaryV1":
        value = _wire_dict(
            value,
            {"levels_present", "minimum_required", "requirement_status"},
            "validation_summary",
        )
        levels = value["levels_present"]
        if not isinstance(levels, (list, tuple)):
            raise ContractError("levels_present must be an array")
        return cls(
            levels_present=tuple(
                _enum(level, ValidationLevelV1, "levels_present[]") for level in levels
            ),
            minimum_required=_enum(
                value["minimum_required"], ValidationLevelV1, "minimum_required"
            ),
            requirement_status=_enum(
                value["requirement_status"],
                ValidationRequirementStatusV1,
                "requirement_status",
            ),
        )


_ENVELOPE_FIELDS = {
    "result_identity",
    "execution_status",
    "availability",
    "completeness_status",
    "execution_reasons",
    "availability_reasons",
    "degradation_reasons",
    "numerical_method",
    "inference_basis",
    "evaluation_design",
    "validation_summary",
    "method",
    "estimand",
    "input_provenance",
    "assumptions",
    "diagnostics",
    "figures",
    "warnings",
    "dependencies",
    "numeric_facts",
    "family_evidence",
    "oracle",
    "lineage_refs",
}


@dataclass(frozen=True)
class EvidenceEnvelopeV1:
    result_identity: Mapping[str, Any]
    execution_status: ExecutionStatusV1
    availability: AvailabilityStatusV1
    completeness_status: CompletenessStatusV1
    execution_reasons: tuple[EvidenceReasonV1, ...]
    availability_reasons: tuple[EvidenceReasonV1, ...]
    degradation_reasons: tuple[EvidenceReasonV1, ...]
    numerical_method: NumericalMethodV1
    inference_basis: InferenceBasisV1
    evaluation_design: EvaluationDesignV1
    validation_summary: ValidationSummaryV1
    method: Mapping[str, Any]
    estimand: Mapping[str, Any]
    input_provenance: Mapping[str, Any]
    assumptions: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[Mapping[str, Any], ...]
    figures: tuple[Mapping[str, Any], ...]
    warnings: tuple[Mapping[str, Any], ...]
    dependencies: tuple[Mapping[str, Any], ...]
    numeric_facts: tuple[NumericFactV1, ...]
    family_evidence: Mapping[str, Any]
    oracle: Mapping[str, Any]
    lineage_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "result_identity",
            "method",
            "estimand",
            "input_provenance",
            "family_evidence",
            "oracle",
        ):
            object.__setattr__(self, name, _mapping(getattr(self, name), name))
        for name in (
            "assumptions",
            "diagnostics",
            "figures",
            "warnings",
            "dependencies",
        ):
            object.__setattr__(
                self,
                name,
                _mapping_tuple(getattr(self, name), name),
            )
        for name in (
            "execution_reasons",
            "availability_reasons",
            "degradation_reasons",
        ):
            values = getattr(self, name)
            if not isinstance(values, (list, tuple)) or any(
                type(reason) is not EvidenceReasonV1 for reason in values
            ):
                raise ContractError(f"{name} must contain EvidenceReasonV1 values")
            object.__setattr__(self, name, tuple(values))
        if not isinstance(self.numeric_facts, (list, tuple)) or any(
            type(fact) is not NumericFactV1 for fact in self.numeric_facts
        ):
            raise ContractError("numeric_facts must contain NumericFactV1 values")
        object.__setattr__(self, "numeric_facts", tuple(self.numeric_facts))
        fact_id_list = [fact.fact_id for fact in self.numeric_facts]
        if len(fact_id_list) != len(set(fact_id_list)):
            raise ContractError("numeric_facts must have unique fact_id values")
        object.__setattr__(
            self,
            "lineage_refs",
            _string_tuple(self.lineage_refs, "lineage_refs"),
        )
        for name, enum_type in (
            ("execution_status", ExecutionStatusV1),
            ("availability", AvailabilityStatusV1),
            ("completeness_status", CompletenessStatusV1),
            ("numerical_method", NumericalMethodV1),
            ("inference_basis", InferenceBasisV1),
            ("evaluation_design", EvaluationDesignV1),
        ):
            if type(getattr(self, name)) is not enum_type:
                raise ContractError(f"{name} has an invalid type")
        if type(self.validation_summary) is not ValidationSummaryV1:
            raise ContractError("validation_summary must be ValidationSummaryV1")

        if self.execution_status is ExecutionStatusV1.COMPLETED:
            if self.execution_reasons:
                raise ContractError("completed execution forbids execution_reasons")
        elif not self.execution_reasons:
            raise EvidenceContractError(
                "EVIDENCE_EXECUTION_REASON_REQUIRED",
                "partial, blocked, and failed execution require execution_reasons",
            )

        if self.availability is AvailabilityStatusV1.AVAILABLE:
            if self.availability_reasons:
                raise ContractError("available evidence forbids availability_reasons")
        elif not self.availability_reasons:
            raise ContractError(
                "not_available and not_applicable require availability_reasons"
            )
        elif self.numeric_facts or self.figures:
            raise ContractError(
                "unavailable and not-applicable evidence forbid numeric_facts and figures"
            )

        if self.completeness_status is CompletenessStatusV1.COMPLETE:
            if self.degradation_reasons:
                raise ContractError("complete evidence forbids degradation_reasons")
            if (
                self.execution_status is not ExecutionStatusV1.COMPLETED
                or self.availability is not AvailabilityStatusV1.AVAILABLE
            ):
                raise ContractError(
                    "complete evidence requires completed and available status"
                )
        elif not self.degradation_reasons:
            raise ContractError(
                "non-complete evidence requires degradation_reasons"
            )

        if self.execution_status in {
            ExecutionStatusV1.BLOCKED,
            ExecutionStatusV1.FAILED,
        }:
            if self.availability is AvailabilityStatusV1.AVAILABLE:
                raise ContractError("blocked and failed execution cannot be available")
            if self.completeness_status not in {
                CompletenessStatusV1.INSUFFICIENT,
                CompletenessStatusV1.NOT_APPLICABLE,
            }:
                raise ContractError(
                    "blocked and failed execution require insufficient or "
                    "not_applicable completeness"
                )
            if self.numeric_facts or self.figures:
                raise ContractError(
                    "blocked and failed execution forbid numeric_facts and figures"
                )
        elif (
            self.execution_status is ExecutionStatusV1.PARTIAL
            and self.completeness_status is CompletenessStatusV1.COMPLETE
        ):
            raise ContractError("partial execution cannot be complete")

        expected_summary = ValidationSummaryV1.from_facts(
            self.numeric_facts,
            self.validation_summary.minimum_required,
        )
        if self.validation_summary != expected_summary:
            raise ContractError("validation_summary must be derived from numeric_facts")

        fact_ids = {fact.fact_id for fact in self.numeric_facts}
        for figure in self.figures:
            if "numeric_source_fact_ids" not in figure:
                raise ContractError("figure requires numeric_source_fact_ids")
            source_ids = _string_tuple(
                figure["numeric_source_fact_ids"],
                "figure.numeric_source_fact_ids",
            )
            if not source_ids or any(source_id not in fact_ids for source_id in source_ids):
                raise ContractError("figure must reference existing numeric facts")
        for warning in self.warnings:
            if "code" not in warning or "message" not in warning:
                raise ContractError("warning requires code and message")
            _text(warning["code"], "warning.code")
            _text(warning["message"], "warning.message")
        collisions = set(self.family_evidence) & _ENVELOPE_FIELDS
        if collisions:
            raise ContractError("family_evidence cannot override common envelope fields")

    def to_dict(self) -> dict[str, object]:
        return {
            "result_identity": thaw_json(self.result_identity),
            "execution_status": self.execution_status.value,
            "availability": self.availability.value,
            "completeness_status": self.completeness_status.value,
            "execution_reasons": [reason.to_dict() for reason in self.execution_reasons],
            "availability_reasons": [
                reason.to_dict() for reason in self.availability_reasons
            ],
            "degradation_reasons": [
                reason.to_dict() for reason in self.degradation_reasons
            ],
            "numerical_method": self.numerical_method.value,
            "inference_basis": self.inference_basis.value,
            "evaluation_design": self.evaluation_design.value,
            "validation_summary": self.validation_summary.to_dict(),
            "method": thaw_json(self.method),
            "estimand": thaw_json(self.estimand),
            "input_provenance": thaw_json(self.input_provenance),
            "assumptions": [thaw_json(value) for value in self.assumptions],
            "diagnostics": [thaw_json(value) for value in self.diagnostics],
            "figures": [thaw_json(value) for value in self.figures],
            "warnings": [thaw_json(value) for value in self.warnings],
            "dependencies": [thaw_json(value) for value in self.dependencies],
            "numeric_facts": [fact.to_dict() for fact in self.numeric_facts],
            "family_evidence": thaw_json(self.family_evidence),
            "oracle": thaw_json(self.oracle),
            "lineage_refs": list(self.lineage_refs),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "EvidenceEnvelopeV1":
        value = _wire_dict(value, _ENVELOPE_FIELDS, "evidence_envelope")

        def reasons(name: str) -> tuple[EvidenceReasonV1, ...]:
            raw = value[name]
            if not isinstance(raw, (list, tuple)):
                raise ContractError(f"{name} must be an array")
            return tuple(EvidenceReasonV1.from_dict(item) for item in raw)  # type: ignore[arg-type]

        raw_facts = value["numeric_facts"]
        if not isinstance(raw_facts, (list, tuple)):
            raise ContractError("numeric_facts must be an array")
        return cls(
            result_identity=_wire_mapping(
                value["result_identity"], "result_identity"
            ),
            execution_status=_enum(
                value["execution_status"], ExecutionStatusV1, "execution_status"
            ),
            availability=_enum(
                value["availability"], AvailabilityStatusV1, "availability"
            ),
            completeness_status=_enum(
                value["completeness_status"],
                CompletenessStatusV1,
                "completeness_status",
            ),
            execution_reasons=reasons("execution_reasons"),
            availability_reasons=reasons("availability_reasons"),
            degradation_reasons=reasons("degradation_reasons"),
            numerical_method=_enum(
                value["numerical_method"], NumericalMethodV1, "numerical_method"
            ),
            inference_basis=_enum(
                value["inference_basis"], InferenceBasisV1, "inference_basis"
            ),
            evaluation_design=_enum(
                value["evaluation_design"], EvaluationDesignV1, "evaluation_design"
            ),
            validation_summary=ValidationSummaryV1.from_dict(
                value["validation_summary"]  # type: ignore[arg-type]
            ),
            method=_wire_mapping(value["method"], "method"),
            estimand=_wire_mapping(value["estimand"], "estimand"),
            input_provenance=_wire_mapping(
                value["input_provenance"], "input_provenance"
            ),
            assumptions=_wire_mapping_tuple(value["assumptions"], "assumptions"),
            diagnostics=_wire_mapping_tuple(value["diagnostics"], "diagnostics"),
            figures=_wire_mapping_tuple(value["figures"], "figures"),
            warnings=_wire_mapping_tuple(value["warnings"], "warnings"),
            dependencies=_wire_mapping_tuple(value["dependencies"], "dependencies"),
            numeric_facts=tuple(
                NumericFactV1.from_dict(fact) for fact in raw_facts  # type: ignore[arg-type]
            ),
            family_evidence=_wire_mapping(
                value["family_evidence"], "family_evidence"
            ),
            oracle=_wire_mapping(value["oracle"], "oracle"),
            lineage_refs=_string_tuple(value["lineage_refs"], "lineage_refs"),
        )


__all__ = [
    "ConsumerProjectionNotApplicableV1",
    "ConsumerProjectionPayloadV1",
    "ConsumerProjectionSlotV1",
    "ConsumerProjectionV1",
    "DenominatorV1",
    "DistributionRefV1",
    "EvidenceContractError",
    "EvidenceEnvelopeV1",
    "EvidenceReasonV1",
    "IntervalV1",
    "MultipleComparisonV1",
    "NotApplicableV1",
    "NumericFactV1",
    "OracleCheckV1",
    "SourceSelectorV1",
    "ValidationSummaryV1",
    "WeightBasisV1",
]
