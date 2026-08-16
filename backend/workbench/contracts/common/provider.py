"""Versioned, declaration-only provider contribution contracts.

Provider manifests describe how independently owned contracts fit together.  A
manifest is never an execution authority: executor values are opaque IDs and
the trusted registry below only records and checks a later server-owned join.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from workbench.contracts.common.contract_ref import (
    ContractRefError,
    ContractRefV1,
    parse_semantic_version,
)


PROVIDER_REF_INVALID = "PROVIDER_REF_INVALID"
PROVIDER_VERSION_INVALID = "PROVIDER_VERSION_INVALID"
PROVIDER_DUPLICATE = "PROVIDER_DUPLICATE"
PROVIDER_UNRESOLVED = "PROVIDER_UNRESOLVED"
PROVIDER_EXECUTOR_INVALID = "PROVIDER_EXECUTOR_INVALID"
PROVIDER_CONTRIBUTION_INVALID = "PROVIDER_CONTRIBUTION_INVALID"
PROVIDER_TRUST_INVALID = "PROVIDER_TRUST_INVALID"

_ERROR_MESSAGES = {
    PROVIDER_REF_INVALID: "provider contract reference is invalid",
    PROVIDER_VERSION_INVALID: "provider semantic version is invalid",
    PROVIDER_DUPLICATE: "provider identity is duplicated",
    PROVIDER_UNRESOLVED: "provider contract reference is unresolved",
    PROVIDER_EXECUTOR_INVALID: "provider executor reference is not an opaque ID",
    PROVIDER_CONTRIBUTION_INVALID: "provider contribution is invalid",
    PROVIDER_TRUST_INVALID: "trusted executor declaration is invalid",
}
_OPAQUE_EXECUTOR = re.compile(r"executor:[A-Za-z][A-Za-z0-9_.:-]{0,127}")
_EFFECTS = frozenset({"read_only", "mutation"})


class ProviderContractError(ValueError):
    """A provider declaration failed its closed contract."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        if code not in _ERROR_MESSAGES:
            raise ValueError("unknown provider contract error code")
        self.code = code
        message = _ERROR_MESSAGES[code]
        if detail:
            message = f"{message}: {detail}"
        super().__init__(f"{code}: {message}")


def _text(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or "\x00" in value
        or any(ord(char) < 0x20 for char in value)
    ):
        raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, f"{name} is invalid")
    return value


def _version(value: object) -> str:
    if type(value) is not str:
        raise ProviderContractError(PROVIDER_VERSION_INVALID)
    try:
        parse_semantic_version(value)
    except ContractRefError as exc:
        raise ProviderContractError(PROVIDER_VERSION_INVALID) from exc
    return value


def is_opaque_executor_ref(value: object) -> bool:
    """Return whether *value* is a namespaced opaque executor identity."""

    return (
        type(value) is str
        and _OPAQUE_EXECUTOR.fullmatch(value) is not None
        and ".." not in value
        and "/" not in value
        and "\\" not in value
        and "://" not in value
    )


def _executor_ref(value: object) -> str:
    if not is_opaque_executor_ref(value):
        raise ProviderContractError(PROVIDER_EXECUTOR_INVALID)
    return value  # type: ignore[return-value]


def _contract_ref(value: object, name: str) -> ContractRefV1:
    try:
        ref = ContractRefV1.from_dict(value)  # type: ignore[arg-type]
    except (ContractRefError, TypeError, KeyError) as exc:
        raise ProviderContractError(PROVIDER_REF_INVALID, name) from exc
    return ref


def _ref_tuple(value: object, name: str, *, allow_empty: bool = False) -> tuple[ContractRefV1, ...]:
    if type(value) not in {list, tuple}:
        raise ProviderContractError(PROVIDER_REF_INVALID, name)
    if not allow_empty and not value:
        raise ProviderContractError(PROVIDER_REF_INVALID, name)
    refs = tuple(_contract_ref(item, f"{name}[{index}]") for index, item in enumerate(value))
    if len({(ref.kind, ref.logical_id, ref.semantic_version) for ref in refs}) != len(refs):
        raise ProviderContractError(PROVIDER_DUPLICATE, name)
    return refs


def _optional_ref(value: object, name: str) -> ContractRefV1 | None:
    if value is None:
        return None
    return _contract_ref(value, name)


@dataclass(frozen=True, slots=True)
class AdapterDeclarationV1:
    """One version-pinned adapter contract, kept as an inseparable group."""

    adapter_id: str
    semantic_version: str
    request_schema_ref: ContractRefV1
    executor_ref: str
    result_validator_ref: ContractRefV1
    output_refs: tuple[ContractRefV1, ...]

    def __post_init__(self) -> None:
        _text(self.adapter_id, "adapter_id")
        _version(self.semantic_version)
        if type(self.request_schema_ref) is not ContractRefV1:
            raise ProviderContractError(PROVIDER_REF_INVALID, "request_schema_ref")
        if type(self.result_validator_ref) is not ContractRefV1:
            raise ProviderContractError(PROVIDER_REF_INVALID, "result_validator_ref")
        _executor_ref(self.executor_ref)
        if type(self.output_refs) is not tuple or not self.output_refs:
            raise ProviderContractError(PROVIDER_REF_INVALID, "output_refs")
        if any(type(ref) is not ContractRefV1 for ref in self.output_refs):
            raise ProviderContractError(PROVIDER_REF_INVALID, "output_refs")

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter_id": self.adapter_id,
            "semantic_version": self.semantic_version,
            "request_schema_ref": self.request_schema_ref.to_dict(),
            "executor_ref": self.executor_ref,
            "result_validator_ref": self.result_validator_ref.to_dict(),
            "output_refs": [ref.to_dict() for ref in self.output_refs],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "AdapterDeclarationV1":
        if not isinstance(value, Mapping) or set(value) != {
            "adapter_id",
            "semantic_version",
            "request_schema_ref",
            "executor_ref",
            "result_validator_ref",
            "output_refs",
        }:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "adapter fields")
        return cls(
            adapter_id=_text(value["adapter_id"], "adapter_id"),
            semantic_version=_version(value["semantic_version"]),
            request_schema_ref=_contract_ref(value["request_schema_ref"], "request_schema_ref"),
            executor_ref=_executor_ref(value["executor_ref"]),
            result_validator_ref=_contract_ref(value["result_validator_ref"], "result_validator_ref"),
            output_refs=_ref_tuple(value["output_refs"], "output_refs"),
        )


@dataclass(frozen=True, slots=True)
class ExposurePathRefV1:
    """A path row composed solely from existing versioned refs."""

    path_id: str
    semantic_version: str
    exposure: str
    capability_ref: ContractRefV1
    operation_ref: ContractRefV1 | None
    step_contract_ref: ContractRefV1 | None
    family_contract_ref: ContractRefV1 | None
    execution_adapter_ref: ContractRefV1 | None
    result_contract_refs: tuple[ContractRefV1, ...]
    evidence_contract_refs: tuple[ContractRefV1, ...]
    projection_refs: Mapping[str, ContractRefV1]

    def __post_init__(self) -> None:
        _text(self.path_id, "path_id")
        _version(self.semantic_version)
        if self.exposure not in {"direct", "composition", "read_only", "closed"}:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "exposure")
        if type(self.capability_ref) is not ContractRefV1:
            raise ProviderContractError(PROVIDER_REF_INVALID, "capability_ref")
        for name in (
            "operation_ref",
            "step_contract_ref",
            "family_contract_ref",
            "execution_adapter_ref",
        ):
            if getattr(self, name) is not None and type(getattr(self, name)) is not ContractRefV1:
                raise ProviderContractError(PROVIDER_REF_INVALID, name)
        for name in ("result_contract_refs", "evidence_contract_refs"):
            refs = getattr(self, name)
            if type(refs) is not tuple or any(type(ref) is not ContractRefV1 for ref in refs):
                raise ProviderContractError(PROVIDER_REF_INVALID, name)
        if type(self.projection_refs) is not MappingProxyType:
            raise ProviderContractError(PROVIDER_REF_INVALID, "projection_refs")
        if not self.projection_refs or any(
            type(key) is not str or type(ref) is not ContractRefV1
            for key, ref in self.projection_refs.items()
        ):
            raise ProviderContractError(PROVIDER_REF_INVALID, "projection_refs")

    def to_dict(self) -> dict[str, object]:
        def optional(ref: ContractRefV1 | None) -> dict[str, str] | None:
            return None if ref is None else ref.to_dict()

        return {
            "path_id": self.path_id,
            "semantic_version": self.semantic_version,
            "exposure": self.exposure,
            "capability_ref": self.capability_ref.to_dict(),
            "operation_ref": optional(self.operation_ref),
            "step_contract_ref": optional(self.step_contract_ref),
            "family_contract_ref": optional(self.family_contract_ref),
            "execution_adapter_ref": optional(self.execution_adapter_ref),
            "result_contract_refs": [ref.to_dict() for ref in self.result_contract_refs],
            "evidence_contract_refs": [ref.to_dict() for ref in self.evidence_contract_refs],
            "projection_refs": {
                key: ref.to_dict() for key, ref in sorted(self.projection_refs.items())
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ExposurePathRefV1":
        fields = {
            "path_id",
            "semantic_version",
            "exposure",
            "capability_ref",
            "operation_ref",
            "step_contract_ref",
            "family_contract_ref",
            "execution_adapter_ref",
            "result_contract_refs",
            "evidence_contract_refs",
            "projection_refs",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "exposure path fields")
        projection_refs = value["projection_refs"]
        if not isinstance(projection_refs, Mapping):
            raise ProviderContractError(PROVIDER_REF_INVALID, "projection_refs")
        normalized_projection_refs = MappingProxyType(
            {
                _text(key, "projection key"): _contract_ref(ref, f"projection_refs.{key}")
                for key, ref in projection_refs.items()
            }
        )
        return cls(
            path_id=_text(value["path_id"], "path_id"),
            semantic_version=_version(value["semantic_version"]),
            exposure=_text(value["exposure"], "exposure"),
            capability_ref=_contract_ref(value["capability_ref"], "capability_ref"),
            operation_ref=_optional_ref(value["operation_ref"], "operation_ref"),
            step_contract_ref=_optional_ref(value["step_contract_ref"], "step_contract_ref"),
            family_contract_ref=_optional_ref(value["family_contract_ref"], "family_contract_ref"),
            execution_adapter_ref=_optional_ref(
                value["execution_adapter_ref"], "execution_adapter_ref"
            ),
            result_contract_refs=_ref_tuple(
                value["result_contract_refs"], "result_contract_refs", allow_empty=True
            ),
            evidence_contract_refs=_ref_tuple(
                value["evidence_contract_refs"], "evidence_contract_refs", allow_empty=True
            ),
            projection_refs=normalized_projection_refs,
        )


def _unique_ref_identities(refs: Sequence[ContractRefV1], name: str) -> None:
    identities = [(ref.kind, ref.logical_id, ref.semantic_version) for ref in refs]
    if len(set(identities)) != len(identities):
        raise ProviderContractError(PROVIDER_DUPLICATE, name)


@dataclass(frozen=True, slots=True)
class ProviderContributionV1:
    """The provider manifest root; it carries refs, never feature behavior."""

    provider_id: str
    semantic_version: str
    contract_refs: tuple[ContractRefV1, ...]
    exposure_paths: tuple[ExposurePathRefV1, ...]
    adapter_declarations: tuple[AdapterDeclarationV1, ...]
    projection_refs: tuple[ContractRefV1, ...]
    renderer_refs: tuple[ContractRefV1, ...]
    policy_refs: tuple[ContractRefV1, ...]

    @property
    def contracts(self) -> tuple[ContractRefV1, ...]:
        return self.contract_refs

    def __post_init__(self) -> None:
        _text(self.provider_id, "provider_id")
        _version(self.semantic_version)
        for name in (
            "contract_refs",
            "exposure_paths",
            "adapter_declarations",
            "projection_refs",
            "renderer_refs",
            "policy_refs",
        ):
            if type(getattr(self, name)) is not tuple:
                raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, name)
        if not self.exposure_paths or not self.adapter_declarations:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "empty contribution")
        if any(type(path) is not ExposurePathRefV1 for path in self.exposure_paths):
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "exposure_paths")
        if any(type(adapter) is not AdapterDeclarationV1 for adapter in self.adapter_declarations):
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "adapter_declarations")
        if len({path.path_id for path in self.exposure_paths}) != len(self.exposure_paths):
            raise ProviderContractError(PROVIDER_DUPLICATE, "path_id")
        if len({adapter.adapter_id for adapter in self.adapter_declarations}) != len(self.adapter_declarations):
            raise ProviderContractError(PROVIDER_DUPLICATE, "adapter_id")
        _unique_ref_identities(self.contract_refs, "contracts")
        for name in ("projection_refs", "renderer_refs", "policy_refs"):
            refs = getattr(self, name)
            if any(type(ref) is not ContractRefV1 for ref in refs):
                raise ProviderContractError(PROVIDER_REF_INVALID, name)
            _unique_ref_identities(refs, name)

    def all_referenced_contracts(self) -> tuple[ContractRefV1, ...]:
        refs: list[ContractRefV1] = []
        for path in self.exposure_paths:
            refs.append(path.capability_ref)
            refs.extend(
                ref
                for ref in (
                    path.operation_ref,
                    path.step_contract_ref,
                    path.family_contract_ref,
                    path.execution_adapter_ref,
                )
                if ref is not None
            )
            refs.extend(path.result_contract_refs)
            refs.extend(path.evidence_contract_refs)
            refs.extend(path.projection_refs.values())
        for adapter in self.adapter_declarations:
            refs.extend(
                (adapter.request_schema_ref, adapter.result_validator_ref, *adapter.output_refs)
            )
        refs.extend(self.projection_refs)
        refs.extend(self.renderer_refs)
        refs.extend(self.policy_refs)
        return tuple(refs)

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "semantic_version": self.semantic_version,
            "contracts": [ref.to_dict() for ref in self.contract_refs],
            "exposure_paths": [path.to_dict() for path in self.exposure_paths],
            "adapter_declarations": [adapter.to_dict() for adapter in self.adapter_declarations],
            "projection_refs": [ref.to_dict() for ref in self.projection_refs],
            "renderer_refs": [ref.to_dict() for ref in self.renderer_refs],
            "policy_refs": [ref.to_dict() for ref in self.policy_refs],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ProviderContributionV1":
        required = {
            "provider_id",
            "semantic_version",
            "contracts",
            "exposure_paths",
            "adapter_declarations",
            "projection_refs",
            "renderer_refs",
            "policy_refs",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "contribution fields")
        paths = value["exposure_paths"]
        adapters = value["adapter_declarations"]
        if type(paths) not in {list, tuple} or type(adapters) not in {list, tuple}:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "declarations")
        return cls(
            provider_id=_text(value["provider_id"], "provider_id"),
            semantic_version=_version(value["semantic_version"]),
            contract_refs=_ref_tuple(value["contracts"], "contracts"),
            exposure_paths=tuple(ExposurePathRefV1.from_dict(item) for item in paths),  # type: ignore[arg-type]
            adapter_declarations=tuple(AdapterDeclarationV1.from_dict(item) for item in adapters),  # type: ignore[arg-type]
            projection_refs=_ref_tuple(value["projection_refs"], "projection_refs"),
            renderer_refs=_ref_tuple(value["renderer_refs"], "renderer_refs"),
            policy_refs=_ref_tuple(value["policy_refs"], "policy_refs"),
        )


class TrustedExecutorRegistryV1:
    """Declaration-only seam for a future server-owned executor join.

    This class intentionally has no callable storage, import path handling, or
    execution method.  Cutover code may add a runtime-owned implementation in
    its own line after validating this contract boundary.
    """

    def __init__(self) -> None:
        self._declarations: dict[str, tuple[str, str, str, ContractRefV1, ContractRefV1]] = {}

    def declare(
        self,
        *,
        executor_ref: str,
        owner_ref: str,
        signature_ref: str,
        effect: str,
        request_schema_ref: ContractRefV1,
        result_validator_ref: ContractRefV1,
    ) -> None:
        executor_ref = _executor_ref(executor_ref)
        owner_ref = _text(owner_ref, "owner_ref")
        signature_ref = _text(signature_ref, "signature_ref")
        if effect not in _EFFECTS:
            raise ProviderContractError(PROVIDER_TRUST_INVALID, "effect")
        if type(request_schema_ref) is not ContractRefV1 or type(result_validator_ref) is not ContractRefV1:
            raise ProviderContractError(PROVIDER_TRUST_INVALID, "contract refs")
        if executor_ref in self._declarations:
            raise ProviderContractError(PROVIDER_DUPLICATE, executor_ref)
        self._declarations[executor_ref] = (
            owner_ref,
            signature_ref,
            effect,
            request_schema_ref,
            result_validator_ref,
        )

    def validate(self, adapter: AdapterDeclarationV1) -> None:
        if type(adapter) is not AdapterDeclarationV1:
            raise ProviderContractError(PROVIDER_TRUST_INVALID, "adapter")
        declaration = self._declarations.get(adapter.executor_ref)
        if declaration is None:
            raise ProviderContractError(PROVIDER_UNRESOLVED, adapter.executor_ref)
        if declaration[3] != adapter.request_schema_ref or declaration[4] != adapter.result_validator_ref:
            raise ProviderContractError(PROVIDER_TRUST_INVALID, "adapter contract mismatch")

    @property
    def executor_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._declarations))


__all__ = [
    "AdapterDeclarationV1",
    "ExposurePathRefV1",
    "ProviderContributionV1",
    "ProviderContractError",
    "PROVIDER_CONTRIBUTION_INVALID",
    "PROVIDER_DUPLICATE",
    "PROVIDER_EXECUTOR_INVALID",
    "PROVIDER_REF_INVALID",
    "PROVIDER_TRUST_INVALID",
    "PROVIDER_UNRESOLVED",
    "PROVIDER_VERSION_INVALID",
    "TrustedExecutorRegistryV1",
    "is_opaque_executor_ref",
]
