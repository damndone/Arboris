"""Raw-key coverage for package-local consumer projection declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.evidence.consumer_adapters import (
    ConsumerProjectionRegistryV1,
    default_projection_registry,
)
from workbench.providers.catalog import ProviderCatalogV1, load_builtin_catalog


_GENERIC_PROVIDER_ID = "workbench.consumer_projection"
_GENERIC_EXPOSURE_PATH = "workbench.consumer_projection.evidence"


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _refs(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    return tuple(_text(value, f"{name}[]") for value in values)


def _path_class(exposure: object) -> str:
    """Normalize catalog exposure labels without hiding unknown paths."""

    if type(exposure) is not str:
        raise ValueError("exposure must be non-empty text")
    if exposure in {"direct", "read_only"}:
        return "direct"
    if exposure in {"composition", "composable"}:
        return "composable"
    if exposure in {"unreachable", "exempt"}:
        return exposure
    raise ValueError(f"unsupported exposure class: {exposure}")


@dataclass(frozen=True)
class RawCoverageKeyV1:
    provider_id: str
    provider_version: str
    exposure_path: str
    operation_version: str
    input_contract_refs: tuple[str, ...]
    output_contract_refs: tuple[str, ...]
    evidence_contract_refs: tuple[str, ...]
    consumer_id: str
    consumer_version: str
    path_class: str = "direct"

    def __post_init__(self) -> None:
        for name in (
            "provider_id",
            "provider_version",
            "exposure_path",
            "operation_version",
            "consumer_id",
            "consumer_version",
        ):
            _text(getattr(self, name), name)
        for name in ("input_contract_refs", "output_contract_refs", "evidence_contract_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "path_class", _path_class(self.path_class))

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "exposure_path": self.exposure_path,
            "operation_version": self.operation_version,
            "input_contract_refs": list(self.input_contract_refs),
            "output_contract_refs": list(self.output_contract_refs),
            "evidence_contract_refs": list(self.evidence_contract_refs),
            "consumer_id": self.consumer_id,
            "consumer_version": self.consumer_version,
            "path_class": self.path_class,
        }


@dataclass(frozen=True)
class ConsumerCoverageRowV1:
    raw_key: RawCoverageKeyV1
    provider_digest: str
    projection_ref: ContractRefV1
    status: str
    reason: str
    coverage_status: str = "required"
    exemption_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.provider_digest) is not str or len(self.provider_digest) != 64:
            raise ValueError("provider_digest must be a SHA-256 digest")
        if type(self.projection_ref) is not ContractRefV1:
            raise ValueError("projection_ref must be ContractRefV1")
        if self.status not in {"covered", "blocked"}:
            raise ValueError("coverage status is invalid")
        _text(self.reason, "reason")
        if self.coverage_status not in {"required", "exempt", "missing"}:
            raise ValueError("coverage declaration status is invalid")
        if self.coverage_status == "exempt":
            _text(self.exemption_reason, "exemption_reason")
        elif self.exemption_reason is not None:
            raise ValueError("exemption_reason is only valid for exempt rows")

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_key": self.raw_key.to_dict(),
            "provider_digest": self.provider_digest,
            "projection_ref": self.projection_ref.to_dict(),
            "status": self.status,
            "reason": self.reason,
            "coverage_status": self.coverage_status,
            "exemption_reason": self.exemption_reason,
        }


@dataclass(frozen=True)
class ConsumerCoverageReportV1:
    rows: tuple[ConsumerCoverageRowV1, ...]
    coverage_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.rows, tuple) or any(type(row) is not ConsumerCoverageRowV1 for row in self.rows):
            raise ValueError("rows must contain ConsumerCoverageRowV1")
        expected = sha256_canonical([row.to_dict() for row in self.rows])
        if self.coverage_digest != expected:
            raise ValueError("coverage_digest does not match rows")

    @property
    def covered_count(self) -> int:
        return sum(row.status == "covered" for row in self.rows)

    @property
    def blocked_count(self) -> int:
        return sum(row.status == "blocked" for row in self.rows)

    @property
    def path_class_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.rows:
            path_class = row.raw_key.path_class
            counts[path_class] = counts.get(path_class, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, object]:
        return {
            "rows": [row.to_dict() for row in self.rows],
            "coverage_digest": self.coverage_digest,
            "covered_count": self.covered_count,
            "blocked_count": self.blocked_count,
            "path_class_counts": self.path_class_counts,
        }


def _ref_identity(ref: ContractRefV1) -> str:
    return f"{ref.kind}:{ref.logical_id}@{ref.semantic_version}"


def build_consumer_coverage(
    catalog: ProviderCatalogV1 | None = None,
    registry: ConsumerProjectionRegistryV1 | None = None,
) -> ConsumerCoverageReportV1:
    """Expand declared provider path projection keys into auditable raw rows."""

    catalog = load_builtin_catalog() if catalog is None else catalog
    registry = default_projection_registry() if registry is None else registry
    rows: list[ConsumerCoverageRowV1] = []
    for provider in catalog.providers:
        provider_digest = sha256_canonical(provider.to_dict())
        declarations = {
            (declaration.path_id, declaration.consumer_id): declaration
            for declaration in provider.projection_declarations
        }
        for path in provider.exposure_paths:
            input_refs = [path.capability_ref]
            input_refs.extend(
                ref
                for ref in (
                    path.operation_ref,
                    path.step_contract_ref,
                    path.family_contract_ref,
                    path.execution_adapter_ref,
                )
                if ref is not None
            )
            for consumer_id, projection_ref in sorted(path.projection_refs.items()):
                scoped_resolve = getattr(registry, "resolve_for", None)
                spec = (
                    scoped_resolve(provider.provider_id, path.path_id, consumer_id)
                    if callable(scoped_resolve)
                    else None
                )
                if (
                    spec is None
                    and provider.provider_id == _GENERIC_PROVIDER_ID
                    and path.path_id == _GENERIC_EXPOSURE_PATH
                ):
                    generic_resolve = getattr(registry, "resolve", None)
                    spec = generic_resolve(consumer_id) if callable(generic_resolve) else None
                declaration = declarations.get((path.path_id, consumer_id))
                if declaration is None:
                    status = "blocked"
                    reason = "projection_declaration_missing"
                    consumer_version = "unresolved"
                    coverage_status = "missing"
                    exemption_reason = None
                elif declaration.coverage_status == "exempt":
                    status = "blocked"
                    reason = "projection_exempt"
                    consumer_version = "exempt"
                    coverage_status = "exempt"
                    exemption_reason = declaration.exemption_reason
                elif spec is None:
                    status = "blocked"
                    reason = "projection_missing"
                    consumer_version = "unresolved"
                    coverage_status = "required"
                    exemption_reason = None
                elif spec.projection_ref != projection_ref:
                    status = "blocked"
                    reason = "projection_ref_mismatch"
                    consumer_version = spec.semantic_version
                    coverage_status = "required"
                    exemption_reason = None
                else:
                    status = "covered"
                    reason = "projection_registered"
                    consumer_version = spec.semantic_version
                    coverage_status = "required"
                    exemption_reason = None
                rows.append(
                    ConsumerCoverageRowV1(
                        raw_key=RawCoverageKeyV1(
                            provider_id=provider.provider_id,
                            provider_version=provider.semantic_version,
                            exposure_path=path.path_id,
                            operation_version=path.semantic_version,
                            input_contract_refs=tuple(_ref_identity(ref) for ref in input_refs),
                            output_contract_refs=tuple(_ref_identity(ref) for ref in path.result_contract_refs),
                            evidence_contract_refs=tuple(_ref_identity(ref) for ref in path.evidence_contract_refs),
                            consumer_id=consumer_id,
                            consumer_version=consumer_version,
                            path_class=_path_class(path.exposure),
                        ),
                        provider_digest=provider_digest,
                        projection_ref=projection_ref,
                        status=status,
                        reason=reason,
                        coverage_status=coverage_status,
                        exemption_reason=exemption_reason,
                    )
                )
    immutable_rows = tuple(rows)
    return ConsumerCoverageReportV1(
        rows=immutable_rows,
        coverage_digest=sha256_canonical([row.to_dict() for row in immutable_rows]),
    )


__all__ = [
    "ConsumerCoverageReportV1",
    "ConsumerCoverageRowV1",
    "RawCoverageKeyV1",
    "build_consumer_coverage",
]
