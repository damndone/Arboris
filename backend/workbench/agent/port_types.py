"""Closed, directional port types for agent-plan compilation."""

from __future__ import annotations

from dataclasses import dataclass


_PORT_KINDS = frozenset({"artifact", "evidence", "model", "scalar", "table"})


class PortCompatibilityError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PortTypeV1:
    kind: str
    schema_ref: str = ""
    nullable: bool = False
    collection: bool = False

    def __post_init__(self) -> None:
        if self.kind not in _PORT_KINDS:
            raise PortCompatibilityError("PORT_TYPE_INVALID")
        if type(self.schema_ref) is not str or len(self.schema_ref) > 160:
            raise PortCompatibilityError("PORT_TYPE_INVALID")
        if any(token in self.schema_ref for token in ("/", "\\", "..", "://")):
            raise PortCompatibilityError("PATH_LIKE_INPUT")
        if type(self.nullable) is not bool or type(self.collection) is not bool:
            raise PortCompatibilityError("PORT_TYPE_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "schema_ref": self.schema_ref,
            "nullable": self.nullable,
            "collection": self.collection,
        }

    def is_compatible_with(self, target: "PortTypeV1") -> bool:
        if type(target) is not PortTypeV1:
            return False
        if self.kind != target.kind or self.collection != target.collection:
            return False
        if self.schema_ref != target.schema_ref:
            return False
        return self.nullable == target.nullable

    def require_compatible(self, target: "PortTypeV1") -> None:
        if type(target) is not PortTypeV1:
            raise PortCompatibilityError("PORT_TYPE_INVALID")
        if self.kind != target.kind or self.collection != target.collection:
            raise PortCompatibilityError("PORT_KIND_MISMATCH")
        if self.schema_ref != target.schema_ref:
            raise PortCompatibilityError("PORT_SCHEMA_MISMATCH")
        if self.nullable != target.nullable:
            raise PortCompatibilityError("PORT_NULLABILITY_MISMATCH")


PortType = PortTypeV1


def ports_compatible(source: PortTypeV1, target: PortTypeV1) -> bool:
    return source.is_compatible_with(target)


def require_port_compatibility(source: PortTypeV1, target: PortTypeV1) -> None:
    source.require_compatible(target)


__all__ = [
    "PortCompatibilityError",
    "PortType",
    "PortTypeV1",
    "ports_compatible",
    "require_port_compatibility",
]
