"""Versioned, declaration-only provider contribution contracts.

Provider manifests describe how independently owned contracts fit together.  A
manifest is never an execution authority: executor values are opaque IDs and
the trusted registry below only records and checks a later server-owned join.
"""

from __future__ import annotations

import re
from collections import namedtuple
from collections.abc import Mapping, Sequence
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
    refs = tuple(
        item
        if type(item) is ContractRefV1
        else _contract_ref(item, f"{name}[{index}]")
        for index, item in enumerate(value)
    )
    if len({(ref.kind, ref.logical_id, ref.semantic_version) for ref in refs}) != len(refs):
        raise ProviderContractError(PROVIDER_DUPLICATE, name)
    return refs


def _optional_ref(value: object, name: str) -> ContractRefV1 | None:
    if value is None:
        return None
    return _contract_ref(value, name)


def _string_tuple(value: object, name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if type(value) not in {list, tuple}:
        raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, name)
    if not allow_empty and not value:
        raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, name)
    values = tuple(_text(item, f"{name}[{index}]") for index, item in enumerate(value))
    if len(set(values)) != len(values):
        raise ProviderContractError(PROVIDER_DUPLICATE, name)
    return values


def _ref_kind(ref: ContractRefV1, name: str, allowed: frozenset[str]) -> None:
    if type(ref) is not ContractRefV1 or ref.kind not in allowed:
        raise ProviderContractError(PROVIDER_REF_INVALID, name)


class _StrictValueTuple:
    __slots__ = ()
    __hash__ = tuple.__hash__

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return tuple.__eq__(self, other)  # type: ignore[arg-type]


class AdapterDeclarationV1(
    _StrictValueTuple,
    namedtuple(
        "_AdapterDeclarationV1Base",
        (
            "adapter_id",
            "semantic_version",
            "request_schema_ref",
            "executor_ref",
            "result_validator_ref",
            "output_refs",
        ),
        module=__name__,
    ),
):
    """One version-pinned adapter contract, kept as an inseparable group."""
    __slots__ = ()

    adapter_id: str
    semantic_version: str
    request_schema_ref: ContractRefV1
    executor_ref: str
    result_validator_ref: ContractRefV1
    output_refs: tuple[ContractRefV1, ...]

    def __new__(
        cls,
        adapter_id: str,
        semantic_version: str,
        request_schema_ref: ContractRefV1,
        executor_ref: str,
        result_validator_ref: ContractRefV1,
        output_refs: tuple[ContractRefV1, ...],
    ) -> "AdapterDeclarationV1":
        _text(adapter_id, "adapter_id")
        _version(semantic_version)
        if type(request_schema_ref) is not ContractRefV1:
            raise ProviderContractError(PROVIDER_REF_INVALID, "request_schema_ref")
        if type(result_validator_ref) is not ContractRefV1:
            raise ProviderContractError(PROVIDER_REF_INVALID, "result_validator_ref")
        _executor_ref(executor_ref)
        if type(output_refs) is not tuple or not output_refs:
            raise ProviderContractError(PROVIDER_REF_INVALID, "output_refs")
        if any(type(ref) is not ContractRefV1 for ref in output_refs):
            raise ProviderContractError(PROVIDER_REF_INVALID, "output_refs")
        return tuple.__new__(
            cls,
            (
                adapter_id,
                semantic_version,
                request_schema_ref,
                executor_ref,
                result_validator_ref,
                output_refs,
            ),
        )

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


class ExposurePathRefV1(
    _StrictValueTuple,
    namedtuple(
        "_ExposurePathRefV1Base",
        (
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
        ),
        module=__name__,
    ),
):
    """A path row composed solely from existing versioned refs."""

    __slots__ = ()

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

    def __new__(
        cls,
        path_id: str,
        semantic_version: str,
        exposure: str,
        capability_ref: ContractRefV1,
        operation_ref: ContractRefV1 | None,
        step_contract_ref: ContractRefV1 | None,
        family_contract_ref: ContractRefV1 | None,
        execution_adapter_ref: ContractRefV1 | None,
        result_contract_refs: tuple[ContractRefV1, ...],
        evidence_contract_refs: tuple[ContractRefV1, ...],
        projection_refs: Mapping[str, ContractRefV1],
    ) -> "ExposurePathRefV1":
        _text(path_id, "path_id")
        _version(semantic_version)
        if exposure not in {"direct", "composition", "read_only", "closed"}:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "exposure")
        if type(capability_ref) is not ContractRefV1:
            raise ProviderContractError(PROVIDER_REF_INVALID, "capability_ref")
        optional_refs = {
            "operation_ref": operation_ref,
            "step_contract_ref": step_contract_ref,
            "family_contract_ref": family_contract_ref,
            "execution_adapter_ref": execution_adapter_ref,
        }
        for name, ref in optional_refs.items():
            if ref is not None and type(ref) is not ContractRefV1:
                raise ProviderContractError(PROVIDER_REF_INVALID, name)
        for name, refs in {
            "result_contract_refs": result_contract_refs,
            "evidence_contract_refs": evidence_contract_refs,
        }.items():
            if type(refs) is not tuple or any(type(ref) is not ContractRefV1 for ref in refs):
                raise ProviderContractError(PROVIDER_REF_INVALID, name)
        if type(projection_refs) is not MappingProxyType:
            raise ProviderContractError(PROVIDER_REF_INVALID, "projection_refs")
        if not projection_refs or any(
            type(key) is not str or type(ref) is not ContractRefV1
            for key, ref in projection_refs.items()
        ):
            raise ProviderContractError(PROVIDER_REF_INVALID, "projection_refs")
        return tuple.__new__(
            cls,
            (
                path_id,
                semantic_version,
                exposure,
                capability_ref,
                operation_ref,
                step_contract_ref,
                family_contract_ref,
                execution_adapter_ref,
                result_contract_refs,
                evidence_contract_refs,
                projection_refs,
            ),
        )

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


_CONSUMER_SENSITIVITIES = frozenset({"public", "internal", "restricted"})
_ENVELOPE_REF_KINDS = frozenset({"envelope", "evidence"})


class ConsumerProjectionDeclarationV1(
    _StrictValueTuple,
    namedtuple(
        "_ConsumerProjectionDeclarationV1Base",
        (
            "path_id",
            "consumer_id",
            "projection_ref",
            "evidence_contract_refs",
            "envelope_contract_refs",
            "fact_kinds",
            "policy_ref",
            "renderer_ref",
            "max_token_budget",
            "max_row_budget",
            "allowed_sensitivity",
            "ordering",
            "coverage_status",
            "exemption_reason",
        ),
        module=__name__,
    ),
):
    """Provider-owned, immutable policy for one consumer projection row."""

    __slots__ = ()

    path_id: str
    consumer_id: str
    projection_ref: ContractRefV1
    evidence_contract_refs: tuple[ContractRefV1, ...]
    envelope_contract_refs: tuple[ContractRefV1, ...]
    fact_kinds: tuple[str, ...]
    policy_ref: ContractRefV1
    renderer_ref: ContractRefV1
    max_token_budget: int
    max_row_budget: int
    allowed_sensitivity: tuple[str, ...]
    ordering: tuple[str, ...]
    coverage_status: str
    exemption_reason: str | None

    def __new__(
        cls,
        path_id: str,
        consumer_id: str,
        projection_ref: ContractRefV1,
        evidence_contract_refs: tuple[ContractRefV1, ...],
        envelope_contract_refs: tuple[ContractRefV1, ...],
        fact_kinds: tuple[str, ...],
        policy_ref: ContractRefV1,
        renderer_ref: ContractRefV1,
        max_token_budget: int,
        max_row_budget: int,
        allowed_sensitivity: tuple[str, ...],
        ordering: tuple[str, ...],
        coverage_status: str,
        exemption_reason: str | None,
    ) -> "ConsumerProjectionDeclarationV1":
        _text(path_id, "path_id")
        _text(consumer_id, "consumer_id")
        _ref_kind(projection_ref, "projection_ref", frozenset({"projection"}))
        _ref_kind(policy_ref, "policy_ref", frozenset({"policy"}))
        _ref_kind(renderer_ref, "renderer_ref", frozenset({"renderer"}))

        evidence_refs = _ref_tuple(evidence_contract_refs, "evidence_contract_refs")
        for ref in evidence_refs:
            _ref_kind(ref, "evidence_contract_refs", frozenset({"evidence"}))
        envelope_refs = _ref_tuple(
            envelope_contract_refs,
            "envelope_contract_refs",
            allow_empty=True,
        )
        for ref in envelope_refs:
            _ref_kind(ref, "envelope_contract_refs", _ENVELOPE_REF_KINDS)

        fact_kind_values = _string_tuple(fact_kinds, "fact_kinds")
        if type(max_token_budget) is not int or max_token_budget <= 0:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "max_token_budget")
        if type(max_row_budget) is not int or max_row_budget <= 0:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "max_row_budget")
        sensitivity_values = _string_tuple(allowed_sensitivity, "allowed_sensitivity")
        if any(value not in _CONSUMER_SENSITIVITIES for value in sensitivity_values):
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "allowed_sensitivity")
        ordering_values = _string_tuple(ordering, "ordering")

        if coverage_status not in {"required", "exempt"}:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "coverage_status")
        if coverage_status == "required":
            if exemption_reason is not None:
                raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "exemption_reason")
        else:
            if type(exemption_reason) is not str or not exemption_reason.strip():
                raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "exemption_reason")
            _text(exemption_reason, "exemption_reason")

        return tuple.__new__(
            cls,
            (
                path_id,
                consumer_id,
                projection_ref,
                evidence_refs,
                envelope_refs,
                fact_kind_values,
                policy_ref,
                renderer_ref,
                max_token_budget,
                max_row_budget,
                sensitivity_values,
                ordering_values,
                coverage_status,
                exemption_reason,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path_id": self.path_id,
            "consumer_id": self.consumer_id,
            "projection_ref": self.projection_ref.to_dict(),
            "evidence_contract_refs": [ref.to_dict() for ref in self.evidence_contract_refs],
            "envelope_contract_refs": [ref.to_dict() for ref in self.envelope_contract_refs],
            "fact_kinds": list(self.fact_kinds),
            "policy_ref": self.policy_ref.to_dict(),
            "renderer_ref": self.renderer_ref.to_dict(),
            "max_token_budget": self.max_token_budget,
            "max_row_budget": self.max_row_budget,
            "allowed_sensitivity": list(self.allowed_sensitivity),
            "ordering": list(self.ordering),
            "coverage_status": self.coverage_status,
            "exemption_reason": self.exemption_reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ConsumerProjectionDeclarationV1":
        fields = {
            "path_id",
            "consumer_id",
            "projection_ref",
            "evidence_contract_refs",
            "envelope_contract_refs",
            "fact_kinds",
            "policy_ref",
            "renderer_ref",
            "max_token_budget",
            "max_row_budget",
            "allowed_sensitivity",
            "ordering",
            "coverage_status",
            "exemption_reason",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "projection declaration fields")
        return cls(
            path_id=_text(value["path_id"], "path_id"),
            consumer_id=_text(value["consumer_id"], "consumer_id"),
            projection_ref=_contract_ref(value["projection_ref"], "projection_ref"),
            evidence_contract_refs=_ref_tuple(
                value["evidence_contract_refs"],
                "evidence_contract_refs",
            ),
            envelope_contract_refs=_ref_tuple(
                value["envelope_contract_refs"],
                "envelope_contract_refs",
                allow_empty=True,
            ),
            fact_kinds=_string_tuple(value["fact_kinds"], "fact_kinds"),
            policy_ref=_contract_ref(value["policy_ref"], "policy_ref"),
            renderer_ref=_contract_ref(value["renderer_ref"], "renderer_ref"),
            max_token_budget=value["max_token_budget"],  # type: ignore[arg-type]
            max_row_budget=value["max_row_budget"],  # type: ignore[arg-type]
            allowed_sensitivity=_string_tuple(
                value["allowed_sensitivity"],
                "allowed_sensitivity",
            ),
            ordering=_string_tuple(value["ordering"], "ordering"),
            coverage_status=value["coverage_status"],  # type: ignore[arg-type]
            exemption_reason=value["exemption_reason"],  # type: ignore[arg-type]
        )


def _unique_ref_identities(refs: Sequence[ContractRefV1], name: str) -> None:
    identities = [(ref.kind, ref.logical_id, ref.semantic_version) for ref in refs]
    if len(set(identities)) != len(identities):
        raise ProviderContractError(PROVIDER_DUPLICATE, name)


class ProviderContributionV1(
    _StrictValueTuple,
    namedtuple(
        "_ProviderContributionV1Base",
        (
            "provider_id",
            "semantic_version",
            "contract_refs",
            "exposure_paths",
            "adapter_declarations",
            "projection_refs",
            "renderer_refs",
            "policy_refs",
            "projection_declarations",
        ),
        module=__name__,
    ),
):
    """The provider manifest root; it carries refs, never feature behavior."""

    __slots__ = ()

    provider_id: str
    semantic_version: str
    contract_refs: tuple[ContractRefV1, ...]
    exposure_paths: tuple[ExposurePathRefV1, ...]
    adapter_declarations: tuple[AdapterDeclarationV1, ...]
    projection_refs: tuple[ContractRefV1, ...]
    renderer_refs: tuple[ContractRefV1, ...]
    policy_refs: tuple[ContractRefV1, ...]
    projection_declarations: tuple[ConsumerProjectionDeclarationV1, ...]

    @property
    def contracts(self) -> tuple[ContractRefV1, ...]:
        return self.contract_refs

    def __new__(
        cls,
        provider_id: str,
        semantic_version: str,
        contract_refs: tuple[ContractRefV1, ...],
        exposure_paths: tuple[ExposurePathRefV1, ...],
        adapter_declarations: tuple[AdapterDeclarationV1, ...],
        projection_refs: tuple[ContractRefV1, ...],
        renderer_refs: tuple[ContractRefV1, ...],
        policy_refs: tuple[ContractRefV1, ...],
        projection_declarations: tuple[ConsumerProjectionDeclarationV1, ...] = (),
    ) -> "ProviderContributionV1":
        _text(provider_id, "provider_id")
        _version(semantic_version)
        values = {
            "contract_refs": contract_refs,
            "exposure_paths": exposure_paths,
            "adapter_declarations": adapter_declarations,
            "projection_refs": projection_refs,
            "renderer_refs": renderer_refs,
            "policy_refs": policy_refs,
            "projection_declarations": projection_declarations,
        }
        for name in (
            "contract_refs",
            "exposure_paths",
            "adapter_declarations",
            "projection_refs",
            "renderer_refs",
            "policy_refs",
            "projection_declarations",
        ):
            if type(values[name]) is not tuple:
                raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, name)
        if not exposure_paths or not adapter_declarations:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "empty contribution")
        if any(type(path) is not ExposurePathRefV1 for path in exposure_paths):
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "exposure_paths")
        if any(type(adapter) is not AdapterDeclarationV1 for adapter in adapter_declarations):
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "adapter_declarations")
        if any(
            type(declaration) is not ConsumerProjectionDeclarationV1
            for declaration in projection_declarations
        ):
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "projection_declarations")
        if len({path.path_id for path in exposure_paths}) != len(exposure_paths):
            raise ProviderContractError(PROVIDER_DUPLICATE, "path_id")
        if len({adapter.adapter_id for adapter in adapter_declarations}) != len(adapter_declarations):
            raise ProviderContractError(PROVIDER_DUPLICATE, "adapter_id")
        declaration_keys = {
            (declaration.path_id, declaration.consumer_id)
            for declaration in projection_declarations
        }
        if len(declaration_keys) != len(projection_declarations):
            raise ProviderContractError(PROVIDER_DUPLICATE, "projection_declarations")
        _unique_ref_identities(contract_refs, "contracts")
        for name in ("projection_refs", "renderer_refs", "policy_refs"):
            refs = values[name]
            if any(type(ref) is not ContractRefV1 for ref in refs):
                raise ProviderContractError(PROVIDER_REF_INVALID, name)
            _unique_ref_identities(refs, name)
        paths_by_id = {path.path_id: path for path in exposure_paths}
        projection_ref_set = set(projection_refs)
        renderer_ref_set = set(renderer_refs)
        policy_ref_set = set(policy_refs)
        contract_ref_set = set(contract_refs)
        expected_declaration_keys: set[tuple[str, str]] = set()
        for path in exposure_paths:
            expected_declaration_keys.update(
                (path.path_id, consumer_id) for consumer_id in path.projection_refs
            )
        for declaration in projection_declarations:
            path = paths_by_id.get(declaration.path_id)
            if path is None:
                raise ProviderContractError(
                    PROVIDER_UNRESOLVED,
                    f"projection declaration path {declaration.path_id}",
                )
            if path.projection_refs.get(declaration.consumer_id) != declaration.projection_ref:
                raise ProviderContractError(
                    PROVIDER_REF_INVALID,
                    f"projection_ref for {declaration.path_id}:{declaration.consumer_id}",
                )
            if declaration.projection_ref not in projection_ref_set:
                raise ProviderContractError(PROVIDER_UNRESOLVED, "projection_ref")
            if declaration.policy_ref not in policy_ref_set:
                raise ProviderContractError(PROVIDER_UNRESOLVED, "policy_ref")
            if declaration.renderer_ref not in renderer_ref_set:
                raise ProviderContractError(PROVIDER_UNRESOLVED, "renderer_ref")
            if any(ref not in path.evidence_contract_refs for ref in declaration.evidence_contract_refs):
                raise ProviderContractError(PROVIDER_REF_INVALID, "evidence_contract_refs")
            if any(ref not in contract_ref_set for ref in declaration.envelope_contract_refs):
                raise ProviderContractError(PROVIDER_UNRESOLVED, "envelope_contract_refs")
        if expected_declaration_keys != declaration_keys:
            missing = sorted(expected_declaration_keys - declaration_keys)
            extra = sorted(declaration_keys - expected_declaration_keys)
            raise ProviderContractError(
                PROVIDER_CONTRIBUTION_INVALID,
                f"projection_declarations coverage missing={missing} extra={extra}",
            )
        return tuple.__new__(
            cls,
            (
                provider_id,
                semantic_version,
                contract_refs,
                exposure_paths,
                adapter_declarations,
                projection_refs,
                renderer_refs,
                policy_refs,
                projection_declarations,
            ),
        )

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
        for declaration in self.projection_declarations:
            refs.extend(
                (
                    declaration.projection_ref,
                    *declaration.evidence_contract_refs,
                    *declaration.envelope_contract_refs,
                    declaration.policy_ref,
                    declaration.renderer_ref,
                )
            )
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
            "projection_declarations": [
                declaration.to_dict() for declaration in self.projection_declarations
            ],
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
        required = required | {"projection_declarations"}
        if not isinstance(value, Mapping) or set(value) != required:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "contribution fields")
        paths = value["exposure_paths"]
        adapters = value["adapter_declarations"]
        declaration_values = value["projection_declarations"]
        if (
            type(paths) not in {list, tuple}
            or type(adapters) not in {list, tuple}
            or type(declaration_values) not in {list, tuple}
        ):
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
            projection_declarations=tuple(
                ConsumerProjectionDeclarationV1.from_dict(item)
                for item in declaration_values  # type: ignore[arg-type]
            ),
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
    "ConsumerProjectionDeclarationV1",
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
