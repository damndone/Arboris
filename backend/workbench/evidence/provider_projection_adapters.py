"""Provider-scoped, server-owned consumer projection bindings.

The generic consumer registry remains a compatibility surface.  This module
adds the missing provider/path dimension without deriving facts or guessing a
projection from a consumer name.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
import secrets
from typing import Any
import weakref
from types import MappingProxyType

from workbench.canonical import sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1, ContractRefError
from workbench.evidence.consumer_adapters import (
    ConsumerProjectionSpecV1,
    EvidenceProjectionError,
)
from workbench.providers.catalog import (
    ProviderCatalogV1,
    is_server_owned_catalog,
    load_builtin_catalog,
)


_SHA256 = re.compile(r"[0-9a-f]{64}")
# Classification evidence is a typed, bounded packet rather than a raw data
# export.  Its complete metrics/diagnostics contract needs this provider-local
# ceiling; the catalog must declare the same value for every central consumer.
_MAX_TOKEN_BUDGET = 8192
_MAX_ROW_BUDGET = 64
_ALLOWED_SENSITIVITIES = frozenset({"public", "internal"})
_ALLOWED_ORDERING = frozenset({"fact_id"})
_RAW_FIELD_NAMES = frozenset(
    {
        "raw",
        "raw_rows",
        "rows",
        "records",
        "observations",
        "feature_values",
        "feature_matrix",
        "input_rows",
        "target_rows",
    }
)
_CLASSIFICATION_DIAGNOSTIC_FIELDS = frozenset(
    {
        "metrics",
        "calibration",
        "comparison",
        "explanations",
        "stability",
        "shift",
        "decision_policy",
        "blocked_reasons",
        "c0_evidence_envelope",
        "c0_consumer_projection",
        "foundation_status",
    }
)
_CLASSIFICATION_CONTROL_FIELDS = frozenset(
    {
        "status",
        "consumer",
        "server_identity",
        "task_hash",
        "split_hash",
        "c0_evidence_envelope",
        "c0_consumer_projection",
    }
)
CLASSIFICATION_PROVIDER_ID = "workbench.classification_ml"
CLASSIFICATION_EXPOSURE_PATH = "workbench.classification_ml.direct"
CLASSIFICATION_CONSUMERS = frozenset({"agent", "notebook", "report"})
CLASSIFICATION_EVIDENCE_SCHEMA = "workbench.prediction.classification-evidence"


@dataclass(frozen=True, slots=True, weakref_slot=True)
class ClassificationSourceSnapshotV1:
    """Opaque server-validated source input for a consumer projection.

    A raw artifact mapping is deliberately not an adapter input.  The central
    service issues this handle only after the indexed artifact, receipt,
    server identity and C0 contracts have been validated together.
    """

    _token: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("classification source snapshots are server-issued")


@dataclass(frozen=True, slots=True, weakref_slot=True)
class ClassificationSourceReceiptAuthorizationV1:
    """Opaque proof that the persisted server receipt already passed validation."""

    _token: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("classification receipt authorizations are server-issued")


@dataclass(frozen=True, slots=True)
class _SourceSnapshotRecord:
    artifact: Mapping[str, Any]
    source_contract: Mapping[str, Any]
    metadata: Mapping[str, Any]


_SOURCE_SNAPSHOTS: weakref.WeakKeyDictionary[
    ClassificationSourceSnapshotV1, _SourceSnapshotRecord
] = weakref.WeakKeyDictionary()
_SOURCE_RECEIPT_AUTHORIZATIONS: weakref.WeakKeyDictionary[
    ClassificationSourceReceiptAuthorizationV1, Mapping[str, Any]
] = weakref.WeakKeyDictionary()


def _authorize_classification_source_receipt(
    metadata: Mapping[str, Any],
) -> ClassificationSourceReceiptAuthorizationV1:
    required = {"artifact_id", "artifact_sha256", "receipt_digest", "server_identity"}
    if not isinstance(metadata, Mapping) or set(metadata) != required:
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_RECEIPT_REQUIRED",
            "classification source receipt authorization is incomplete",
        )
    authorization = object.__new__(ClassificationSourceReceiptAuthorizationV1)
    object.__setattr__(authorization, "_token", secrets.token_urlsafe(32))
    _SOURCE_RECEIPT_AUTHORIZATIONS[authorization] = dict(metadata)
    return authorization


def _issue_classification_source_snapshot(
    artifact: Mapping[str, Any],
    source_contract: Mapping[str, Any],
    *,
    authorization: object,
    metadata: Mapping[str, Any],
) -> ClassificationSourceSnapshotV1:
    """Issue a snapshot from the validated server wrapper only.

    This is intentionally an internal seam used by the central persisted
    wrapper reader.  The projection adapter accepts only the resulting opaque
    handle, never caller-provided artifact bytes or mappings.
    """

    if (
        not isinstance(artifact, Mapping)
        or not isinstance(source_contract, Mapping)
        or type(authorization) is not ClassificationSourceReceiptAuthorizationV1
        or _SOURCE_RECEIPT_AUTHORIZATIONS.get(authorization) != dict(metadata)
    ):
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_RECEIPT_REQUIRED",
            "classification source snapshot requires an authorized server receipt",
        )
    snapshot = object.__new__(ClassificationSourceSnapshotV1)
    object.__setattr__(snapshot, "_token", secrets.token_urlsafe(32))
    _SOURCE_SNAPSHOTS[snapshot] = _SourceSnapshotRecord(
        artifact=dict(artifact),
        source_contract=dict(source_contract),
        metadata=dict(metadata),
    )
    return snapshot


def _source_snapshot_record(source: object) -> _SourceSnapshotRecord:
    if type(source) is not ClassificationSourceSnapshotV1:
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_SNAPSHOT_REQUIRED",
            "classification projection requires a server-issued source snapshot",
        )
    record = _SOURCE_SNAPSHOTS.get(source)
    if record is None:
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_SNAPSHOT_REQUIRED",
            "classification source snapshot is unknown or expired",
        )
    return record


def source_snapshot_metadata(source: object) -> dict[str, Any]:
    return dict(_source_snapshot_record(source).metadata)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise EvidenceProjectionError("PROJECTION_BINDING_INVALID", f"{name} is invalid")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise EvidenceProjectionError("PROJECTION_BINDING_INVALID", f"{name} is invalid")
    return value


def _ref(value: object, name: str, kind: str) -> ContractRefV1:
    if type(value) is not ContractRefV1 or value.kind != kind:
        raise EvidenceProjectionError("PROJECTION_REF_INVALID", f"{name} must be a {kind} ref")
    return value


@dataclass(frozen=True)
class ProviderProjectionBindingV1:
    """One immutable exact catalog join for one provider/path/consumer."""

    provider_id: str
    provider_version: str
    provider_digest: str
    catalog_digest: str
    exposure_path: str
    exposure_version: str
    consumer_id: str
    semantic_version: str
    projection_ref: ContractRefV1
    policy_ref: ContractRefV1
    renderer_ref: ContractRefV1
    evidence_contract_refs: tuple[ContractRefV1, ...]
    envelope_contract_refs: tuple[ContractRefV1, ...]
    fact_kinds: tuple[str, ...]
    max_token_budget: int
    max_row_budget: int
    allowed_sensitivity: tuple[str, ...]
    ordering: tuple[str, ...]
    coverage_status: str
    exemption_reason: str | None

    def __post_init__(self) -> None:
        for name in (
            "provider_id",
            "provider_version",
            "exposure_path",
            "exposure_version",
            "consumer_id",
            "semantic_version",
        ):
            _text(getattr(self, name), name)
        _digest(self.provider_digest, "provider_digest")
        _digest(self.catalog_digest, "catalog_digest")
        _ref(self.projection_ref, "projection_ref", "projection")
        _ref(self.policy_ref, "policy_ref", "policy")
        _ref(self.renderer_ref, "renderer_ref", "renderer")
        if type(self.max_token_budget) is not int or not 0 < self.max_token_budget <= _MAX_TOKEN_BUDGET:
            raise EvidenceProjectionError("PROJECTION_BUDGET_INVALID", "max_token_budget is outside the server bound")
        if type(self.max_row_budget) is not int or not 0 < self.max_row_budget <= _MAX_ROW_BUDGET:
            raise EvidenceProjectionError("PROJECTION_BUDGET_INVALID", "max_row_budget is outside the server bound")
        for name in ("evidence_contract_refs", "envelope_contract_refs"):
            refs = getattr(self, name)
            if type(refs) is not tuple or any(type(ref) is not ContractRefV1 for ref in refs):
                raise EvidenceProjectionError("PROJECTION_REF_INVALID", f"{name} is invalid")
        if type(self.fact_kinds) is not tuple or not self.fact_kinds:
            raise EvidenceProjectionError("PROJECTION_BINDING_INVALID", "fact_kinds is invalid")
        if type(self.allowed_sensitivity) is not tuple or not self.allowed_sensitivity:
            raise EvidenceProjectionError("PROJECTION_SENSITIVITY_INVALID", "allowed_sensitivity is invalid")
        if not set(self.allowed_sensitivity).issubset(_ALLOWED_SENSITIVITIES):
            raise EvidenceProjectionError("PROJECTION_SENSITIVITY_INVALID", "sensitivity is not allowed")
        if type(self.ordering) is not tuple or not self.ordering or not set(self.ordering).issubset(_ALLOWED_ORDERING):
            raise EvidenceProjectionError("PROJECTION_ORDERING_INVALID", "ordering is not allowed")
        if self.coverage_status not in {"required", "exempt"}:
            raise EvidenceProjectionError("PROJECTION_COVERAGE_INVALID", "coverage status is invalid")
        if self.coverage_status == "exempt":
            _text(self.exemption_reason, "exemption_reason")
        elif self.exemption_reason is not None:
            raise EvidenceProjectionError("PROJECTION_COVERAGE_INVALID", "required binding has an exemption")

    def to_consumer_spec(self) -> ConsumerProjectionSpecV1:
        return ConsumerProjectionSpecV1(
            consumer_id=self.consumer_id,
            semantic_version=self.semantic_version,
            projection_ref=self.projection_ref,
            policy_ref=self.policy_ref,
            renderer_key=self.renderer_ref.logical_id,
            max_token_budget=self.max_token_budget,
            max_row_budget=self.max_row_budget,
            allowed_sensitivity=self.allowed_sensitivity,
            ordering=self.ordering,
            accepted_evidence_refs=self.evidence_contract_refs,
            accepted_envelope_refs=self.envelope_contract_refs,
            fact_kinds=self.fact_kinds,
            renderer_ref=self.renderer_ref,
        )

    def identity(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "provider_digest": self.provider_digest,
            "catalog_digest": self.catalog_digest,
            "exposure_path": self.exposure_path,
            "exposure_version": self.exposure_version,
            "consumer": self.consumer_id,
            "projection_ref": self.projection_ref.to_dict(),
            "policy_ref": self.policy_ref.to_dict(),
            "renderer_ref": self.renderer_ref.to_dict(),
        }


class ProviderProjectionRegistryV1:
    """Closed exact-key registry; no consumer-name fallback is provided."""

    def __init__(self, bindings: Sequence[ProviderProjectionBindingV1] = ()) -> None:
        self._bindings: dict[tuple[str, str, str], ProviderProjectionBindingV1] = {}
        for binding in bindings:
            if type(binding) is not ProviderProjectionBindingV1:
                raise EvidenceProjectionError("PROJECTION_BINDING_INVALID", "binding is invalid")
            key = (binding.provider_id, binding.exposure_path, binding.consumer_id)
            if key in self._bindings:
                raise EvidenceProjectionError("PROJECTION_DUPLICATE", str(key))
            self._bindings[key] = binding

    @classmethod
    def _sealed_from_catalog(
        cls,
        catalog: ProviderCatalogV1,
        bindings: Sequence[ProviderProjectionBindingV1],
    ) -> "ProviderProjectionRegistryV1":
        """Issue a registry only after replaying the server catalog join.

        The leading underscore is not an authority boundary in Python.  A
        caller may invoke this method directly, so issuance must independently
        reject forged bindings instead of trusting the caller to have used the
        public factory correctly.
        """

        if type(catalog) is not ProviderCatalogV1 or not is_server_owned_catalog(catalog):
            raise EvidenceProjectionError(
                "PROJECTION_CATALOG_UNTRUSTED",
                "sealed registry requires a server-owned catalog",
            )
        expected_bindings = _bindings_from_catalog(catalog)
        supplied_registry = cls(bindings)
        if _registry_bindings_digest(supplied_registry.bindings) != _registry_bindings_digest(expected_bindings):
            raise EvidenceProjectionError(
                "PROJECTION_REGISTRY_ISSUANCE_INVALID",
                "sealed registry bindings do not exactly match the server catalog",
            )

        registry = supplied_registry
        registry._bindings = MappingProxyType(dict(registry._bindings))  # type: ignore[assignment]
        _TRUSTED_REGISTRIES[registry] = (catalog, _registry_bindings_digest(registry.bindings))
        return registry

    def resolve_for(
        self,
        provider_id: str,
        exposure_path: str,
        consumer_id: str,
        *,
        projection_ref: ContractRefV1 | None = None,
        policy_ref: ContractRefV1 | None = None,
        renderer_ref: ContractRefV1 | None = None,
    ) -> ProviderProjectionBindingV1 | None:
        key = (_text(provider_id, "provider_id"), _text(exposure_path, "exposure_path"), _text(consumer_id, "consumer_id"))
        binding = self._bindings.get(key)
        if binding is None:
            return None
        for name, expected, actual in (
            ("projection_ref", projection_ref, binding.projection_ref),
            ("policy_ref", policy_ref, binding.policy_ref),
            ("renderer_ref", renderer_ref, binding.renderer_ref),
        ):
            if expected is not None and expected != actual:
                raise EvidenceProjectionError("PROJECTION_REF_MISMATCH", f"{name} does not match the catalog binding")
        return binding

    def require_for(self, provider_id: str, exposure_path: str, consumer_id: str, **refs: object) -> ProviderProjectionBindingV1:
        binding = self.resolve_for(provider_id, exposure_path, consumer_id, **refs)  # type: ignore[arg-type]
        if binding is None:
            raise EvidenceProjectionError(
                "PROJECTION_DECLARATION_REQUIRED",
                f"no exact declaration for {provider_id}:{exposure_path}:{consumer_id}",
            )
        return binding

    @property
    def bindings(self) -> tuple[ProviderProjectionBindingV1, ...]:
        return tuple(self._bindings[key] for key in sorted(self._bindings))


def _binding_payload(binding: ProviderProjectionBindingV1) -> dict[str, object]:
    return {
        "provider_id": binding.provider_id,
        "provider_version": binding.provider_version,
        "provider_digest": binding.provider_digest,
        "catalog_digest": binding.catalog_digest,
        "exposure_path": binding.exposure_path,
        "exposure_version": binding.exposure_version,
        "consumer_id": binding.consumer_id,
        "semantic_version": binding.semantic_version,
        "projection_ref": binding.projection_ref.to_dict(),
        "policy_ref": binding.policy_ref.to_dict(),
        "renderer_ref": binding.renderer_ref.to_dict(),
        "evidence_contract_refs": [ref.to_dict() for ref in binding.evidence_contract_refs],
        "envelope_contract_refs": [ref.to_dict() for ref in binding.envelope_contract_refs],
        "fact_kinds": list(binding.fact_kinds),
        "max_token_budget": binding.max_token_budget,
        "max_row_budget": binding.max_row_budget,
        "allowed_sensitivity": list(binding.allowed_sensitivity),
        "ordering": list(binding.ordering),
        "coverage_status": binding.coverage_status,
        "exemption_reason": binding.exemption_reason,
    }


def _registry_bindings_digest(bindings: Sequence[ProviderProjectionBindingV1]) -> str:
    ordered = sorted(
        bindings,
        key=lambda binding: (
            binding.provider_id,
            binding.exposure_path,
            binding.consumer_id,
        ),
    )
    return sha256_canonical([_binding_payload(binding) for binding in ordered])


def _projection_token_cost(value: object) -> int:
    """Use a deterministic structured-size estimate for projection admission."""

    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise EvidenceProjectionError(
                "PROJECTION_PAYLOAD_INVALID",
                "classification projection contains a non-text mapping key",
            )
        return 1 + sum(_projection_token_cost(key) + _projection_token_cost(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return 1 + sum(_projection_token_cost(item) for item in value)
    if type(value) is str:
        return max(1, (len(value) + 3) // 4)
    if value is None or type(value) in {bool, int, float}:
        return 1
    raise EvidenceProjectionError(
        "PROJECTION_PAYLOAD_INVALID",
        "classification projection contains a non-serializable value",
    )


def _reject_raw_fields(value: object, *, location: str = "projection") -> None:
    """Reject raw row-like payloads before a consumer can display them."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise EvidenceProjectionError(
                    "PROJECTION_PAYLOAD_INVALID",
                    f"{location} contains a non-text key",
                )
            normalized = key.casefold().replace("-", "_")
            if normalized in _RAW_FIELD_NAMES or normalized.startswith("raw_"):
                raise EvidenceProjectionError(
                    "PROJECTION_RAW_FIELDS_REJECTED",
                    f"{location}.{key} is not an admitted evidence field",
                )
            _reject_raw_fields(item, location=f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_raw_fields(item, location=f"{location}[{index}]")


def _observed_sensitivity(artifact: Mapping[str, Any]) -> str:
    """Read the optional producer sensitivity declaration without guessing it."""

    declared: list[object] = []
    evidence = artifact.get("evidence")
    for container in (artifact, evidence):
        if isinstance(container, Mapping) and "sensitivity" in container:
            declared.append(container["sensitivity"])
    if isinstance(evidence, Mapping):
        envelope = evidence.get("c0_evidence_envelope")
        if isinstance(envelope, Mapping) and "sensitivity" in envelope:
            declared.append(envelope["sensitivity"])
    if not declared:
        # Existing classification packets predate an explicit sensitivity
        # field.  Their typed evidence contains no rows, so the only admitted
        # legacy value is the public class; any explicit value is checked.
        return "public"
    if any(type(value) is not str or value not in _ALLOWED_SENSITIVITIES for value in declared):
        raise EvidenceProjectionError(
            "PROJECTION_SENSITIVITY_NOT_ALLOWED",
            "classification evidence declares an unadmitted sensitivity",
        )
    if len(set(declared)) != 1:
        raise EvidenceProjectionError(
            "PROJECTION_SENSITIVITY_MISMATCH",
            "classification evidence contains conflicting sensitivity declarations",
        )
    return declared[0]


def _classification_fact_rows(projection: Mapping[str, Any]) -> tuple[dict[str, object], ...]:
    """Turn evidence fields into bounded rows; keep C0 proof as control metadata.

    C0 envelope/projection and server identity are independently bound control
    evidence.  They are carried in the response but are not counted as user
    evidence rows for the consumer's token budget.  This keeps the declared
    budget about the facts a consumer may read, while still requiring the
    control identity to be present and validated upstream.
    """

    rows: list[dict[str, object]] = []
    for field in sorted(projection):
        if field in _CLASSIFICATION_CONTROL_FIELDS:
            continue
        kind = "diagnostics" if field in _CLASSIFICATION_DIAGNOSTIC_FIELDS else "classification"
        rows.append(
            {
                "fact_id": f"classification:{field}",
                "fact_kind": kind,
                "value": projection[field],
            }
        )
    return tuple(rows)


def _contract_ref_tuple(value: object, name: str) -> tuple[ContractRefV1, ...]:
    if not isinstance(value, (list, tuple)):
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_CONTRACT_MISMATCH",
            f"{name} must be an array of typed contract references",
        )
    refs: list[ContractRefV1] = []
    for raw_ref in value:
        if type(raw_ref) is ContractRefV1:
            refs.append(raw_ref)
            continue
        if isinstance(raw_ref, Mapping):
            try:
                refs.append(ContractRefV1.from_dict(raw_ref))
            except (ContractRefError, TypeError, ValueError) as exc:
                raise EvidenceProjectionError(
                    "PROJECTION_SOURCE_CONTRACT_MISMATCH",
                    f"{name} contains an invalid contract reference",
                ) from exc
            continue
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_CONTRACT_MISMATCH",
            f"{name} contains an invalid contract reference",
        )
    return tuple(refs)


def _declared_artifact_refs(container: Mapping[str, Any], *names: str) -> tuple[ContractRefV1, ...] | None:
    """Read optional producer-declared refs without inventing them.

    v1.8.9 classification packets carry the typed evidence schema but predate
    an explicit serialized evidence/envelope-ref field.  If a producer does
    declare one, it must be typed and is checked exactly; absence remains an
    empty declaration rather than a guessed ref.
    """

    for name in names:
        if name not in container:
            continue
        value = container[name]
        if name.endswith("_ref"):
            value = [value]
        return _contract_ref_tuple(value, name)
    return None


def _validate_source_contract(
    artifact: Mapping[str, Any],
    binding: ProviderProjectionBindingV1,
    source_contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate the server-built source contract before projecting facts.

    The source contract is intentionally separate from the consumer catalog
    binding.  It binds the persisted payload contract and the actual typed
    evidence schema, then requires the source's declared contract refs to be
    the exact refs admitted by the same server-owned catalog join.
    """

    if not isinstance(source_contract, Mapping):
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_CONTRACT_REQUIRED",
            "classification projection requires a server-built source contract",
        )
    expected_fields = frozenset(
        {
            "payload_contract",
            "evidence_schema_ref",
            "evidence_contract_refs",
            "envelope_contract_refs",
        }
    )
    if set(source_contract) != expected_fields:
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_CONTRACT_MISMATCH",
            "source contract fields are not the closed v1 contract",
        )
    expected_payload_contract = {
        "payload_schema": "workbench.prediction.classification-artifacts",
        "schema_version": 1,
    }
    evidence = artifact.get("evidence")
    if (
        source_contract.get("payload_contract") != expected_payload_contract
        or artifact.get("payload_schema") != expected_payload_contract["payload_schema"]
        or artifact.get("schema_version") != expected_payload_contract["schema_version"]
        or not isinstance(evidence, Mapping)
        or source_contract.get("evidence_schema_ref") != evidence.get("payload_schema")
        or source_contract.get("evidence_schema_ref") != CLASSIFICATION_EVIDENCE_SCHEMA
    ):
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_CONTRACT_MISMATCH",
            "source payload or typed evidence schema does not match the persisted artifact",
        )

    evidence_refs = _contract_ref_tuple(
        source_contract.get("evidence_contract_refs"),
        "evidence_contract_refs",
    )
    envelope_refs = _contract_ref_tuple(
        source_contract.get("envelope_contract_refs"),
        "envelope_contract_refs",
    )
    if (
        not evidence_refs
        or not set(evidence_refs).issubset(set(binding.evidence_contract_refs))
        or not set(envelope_refs).issubset(set(binding.envelope_contract_refs))
    ):
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_CONTRACT_MISMATCH",
            "source contract refs are not admitted by the provider catalog binding",
        )
    if any(ref.kind != "evidence" for ref in evidence_refs):
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_CONTRACT_MISMATCH",
            "source evidence refs are not evidence contracts",
        )
    if any(ref.kind != "envelope" for ref in envelope_refs):
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_CONTRACT_MISMATCH",
            "source envelope refs are not envelope contracts",
        )

    declared_evidence_refs = _declared_artifact_refs(
        evidence,
        "evidence_contract_refs",
        "evidence_contract_ref",
    )
    if declared_evidence_refs is not None and declared_evidence_refs != evidence_refs:
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_CONTRACT_MISMATCH",
            "serialized evidence refs do not match the source contract",
        )
    declared_envelope_refs = _declared_artifact_refs(
        evidence,
        "envelope_contract_refs",
        "envelope_contract_ref",
    )
    if declared_envelope_refs is not None and declared_envelope_refs != envelope_refs:
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_CONTRACT_MISMATCH",
            "serialized envelope refs do not match the source contract",
        )
    if envelope_refs and declared_envelope_refs is None:
        raise EvidenceProjectionError(
            "PROJECTION_SOURCE_CONTRACT_MISMATCH",
            "a non-empty catalog envelope contract must be declared by the source",
        )

    return {
        "payload_contract": dict(expected_payload_contract),
        "evidence_schema_ref": CLASSIFICATION_EVIDENCE_SCHEMA,
        "evidence_contract_refs": evidence_refs,
        "envelope_contract_refs": envelope_refs,
    }


# A caller can construct a value-equivalent registry, but only this module's
# catalog factory records the exact server-owned catalog and sealed binding
# digest needed by the central adapter.
_TRUSTED_REGISTRIES: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _trusted_catalog_for_registry(
    registry: ProviderProjectionRegistryV1,
) -> ProviderCatalogV1 | None:
    record = _TRUSTED_REGISTRIES.get(registry)
    if record is None:
        return None
    catalog, issued_bindings_digest = record
    try:
        if _registry_bindings_digest(registry.bindings) != issued_bindings_digest:
            return None
        if type(catalog) is not ProviderCatalogV1 or not is_server_owned_catalog(catalog):
            return None
    except Exception:
        return None
    return catalog


def _resolve_catalog_ref(catalog: ProviderCatalogV1, ref: ContractRefV1, name: str) -> None:
    try:
        resolved = catalog.contract_resolver.resolve(ref)
    except ContractRefError as exc:
        raise EvidenceProjectionError("PROJECTION_CATALOG_REF_INVALID", f"{name} is not server-resolved") from exc
    if resolved != ref:
        raise EvidenceProjectionError("PROJECTION_CATALOG_REF_INVALID", f"{name} identity differs")


def provider_projection_registry_from_catalog(
    catalog: ProviderCatalogV1 | None = None,
) -> ProviderProjectionRegistryV1:
    catalog = load_builtin_catalog() if catalog is None else catalog
    if type(catalog) is not ProviderCatalogV1 or not is_server_owned_catalog(catalog):
        raise EvidenceProjectionError("PROJECTION_CATALOG_UNTRUSTED", "projection registry requires a server-owned catalog")

    return ProviderProjectionRegistryV1._sealed_from_catalog(
        catalog,
        _bindings_from_catalog(catalog),
    )


def _bindings_from_catalog(
    catalog: ProviderCatalogV1,
) -> tuple[ProviderProjectionBindingV1, ...]:
    """Replay every provider/path/consumer declaration from one catalog."""

    bindings: list[ProviderProjectionBindingV1] = []
    for provider in catalog.providers:
        provider_digest = sha256_canonical(provider.to_dict())
        paths = {path.path_id: path for path in provider.exposure_paths}
        declarations = {
            (declaration.path_id, declaration.consumer_id): declaration
            for declaration in provider.projection_declarations
        }
        for path in provider.exposure_paths:
            for consumer_id, path_projection_ref in sorted(path.projection_refs.items()):
                declaration = declarations.get((path.path_id, consumer_id))
                if declaration is None:
                    raise EvidenceProjectionError(
                        "PROJECTION_DECLARATION_REQUIRED",
                        f"missing declaration for {provider.provider_id}:{path.path_id}:{consumer_id}",
                    )
                if paths.get(declaration.path_id) is not path or declaration.projection_ref != path_projection_ref:
                    raise EvidenceProjectionError("PROJECTION_DECLARATION_IDENTITY_MISMATCH", f"{path.path_id}:{consumer_id}")
                if declaration.projection_ref not in provider.projection_refs:
                    raise EvidenceProjectionError("PROJECTION_REF_INVALID", "projection ref is not provider-owned")
                if declaration.policy_ref not in provider.policy_refs:
                    raise EvidenceProjectionError("PROJECTION_REF_INVALID", "policy ref is not provider-owned")
                if declaration.renderer_ref not in provider.renderer_refs:
                    raise EvidenceProjectionError("PROJECTION_REF_INVALID", "renderer ref is not provider-owned")
                if any(ref not in path.evidence_contract_refs for ref in declaration.evidence_contract_refs):
                    raise EvidenceProjectionError("PROJECTION_REF_INVALID", "evidence ref is not path-owned")
                for ref in (
                    declaration.projection_ref,
                    *declaration.evidence_contract_refs,
                    *declaration.envelope_contract_refs,
                    declaration.policy_ref,
                    declaration.renderer_ref,
                ):
                    _resolve_catalog_ref(catalog, ref, f"{provider.provider_id}:{path.path_id}:{consumer_id}")
                bindings.append(
                    ProviderProjectionBindingV1(
                        provider_id=provider.provider_id,
                        provider_version=provider.semantic_version,
                        provider_digest=provider_digest,
                        catalog_digest=catalog.catalog_digest,
                        exposure_path=path.path_id,
                        exposure_version=path.semantic_version,
                        consumer_id=consumer_id,
                        semantic_version=declaration.projection_ref.semantic_version,
                        projection_ref=declaration.projection_ref,
                        policy_ref=declaration.policy_ref,
                        renderer_ref=declaration.renderer_ref,
                        evidence_contract_refs=declaration.evidence_contract_refs,
                        envelope_contract_refs=declaration.envelope_contract_refs,
                        fact_kinds=declaration.fact_kinds,
                        max_token_budget=declaration.max_token_budget,
                        max_row_budget=declaration.max_row_budget,
                        allowed_sensitivity=declaration.allowed_sensitivity,
                        ordering=declaration.ordering,
                        coverage_status=declaration.coverage_status,
                        exemption_reason=declaration.exemption_reason,
                    )
                )
    return tuple(bindings)


class ClassificationProjectionAdapterV1:
    """Central classification adapter that binds facts to catalog identity."""

    def __init__(self, registry: ProviderProjectionRegistryV1) -> None:
        if type(registry) is not ProviderProjectionRegistryV1:
            raise EvidenceProjectionError("PROJECTION_REGISTRY_INVALID", "classification adapter requires scoped registry")
        if _trusted_catalog_for_registry(registry) is None:
            raise EvidenceProjectionError(
                "PROJECTION_REGISTRY_UNTRUSTED",
                "classification adapter requires a sealed registry issued from the server catalog",
            )
        self._registry = registry

    def require_binding(
        self,
        provider_id: str,
        exposure_path: str,
        consumer_id: str,
        *,
        projection_ref: ContractRefV1 | None = None,
        policy_ref: ContractRefV1 | None = None,
        renderer_ref: ContractRefV1 | None = None,
    ) -> ProviderProjectionBindingV1:
        if provider_id != CLASSIFICATION_PROVIDER_ID or exposure_path != CLASSIFICATION_EXPOSURE_PATH or consumer_id not in CLASSIFICATION_CONSUMERS:
            raise EvidenceProjectionError("PROJECTION_DECLARATION_REQUIRED", "classification binding is outside the closed scope")
        binding = self._registry.require_for(
            provider_id,
            exposure_path,
            consumer_id,
            projection_ref=projection_ref,
            policy_ref=policy_ref,
            renderer_ref=renderer_ref,
        )
        if binding.coverage_status != "required":
            raise EvidenceProjectionError("PROJECTION_COVERAGE_UNAVAILABLE", binding.exemption_reason or "projection is exempt")
        return binding

    def unavailable(self, consumer_id: str, code: str) -> dict[str, Any]:
        binding = self.require_binding(CLASSIFICATION_PROVIDER_ID, CLASSIFICATION_EXPOSURE_PATH, consumer_id)
        return {
            "payload_schema": CLASSIFICATION_EVIDENCE_SCHEMA,
            "schema_version": 1,
            "status": "unavailable",
            "consumer": consumer_id,
            "provider_id": binding.provider_id,
            "exposure_path": binding.exposure_path,
            "projection_ref": binding.projection_ref.to_dict(),
            "policy_ref": binding.policy_ref.to_dict(),
            "renderer_ref": binding.renderer_ref.to_dict(),
            "catalog_digest": binding.catalog_digest,
            "provider_digest": binding.provider_digest,
            "coverage_status": binding.coverage_status,
            "blocked_reasons": [code],
        }

    def project_artifact(
        self,
        source: ClassificationSourceSnapshotV1,
        *,
        consumer_id: str,
    ) -> dict[str, Any]:
        binding = self.require_binding(CLASSIFICATION_PROVIDER_ID, CLASSIFICATION_EXPOSURE_PATH, consumer_id)
        from workbench.predictive_research.consumer_projection import _project_classification_evidence

        source_record = _source_snapshot_record(source)
        artifact = source_record.artifact
        validated_source_contract = _validate_source_contract(
            artifact,
            binding,
            source_record.source_contract,
        )
        observed_sensitivity = _observed_sensitivity(artifact)
        if observed_sensitivity not in binding.allowed_sensitivity:
            raise EvidenceProjectionError(
                "PROJECTION_SENSITIVITY_NOT_ALLOWED",
                "classification evidence sensitivity is not admitted by the catalog policy",
            )
        projection = _project_classification_evidence(artifact, consumer=consumer_id)
        _reject_raw_fields(projection)
        rows = _classification_fact_rows(projection)
        observed_fact_kinds = tuple(sorted({str(row["fact_kind"]) for row in rows}))
        if any(row["fact_kind"] not in binding.fact_kinds for row in rows):
            raise EvidenceProjectionError(
                "PROJECTION_FACT_KIND_NOT_ALLOWED",
                "classification projection contains a fact kind outside the catalog declaration",
            )
        if binding.ordering == ("fact_id",) and tuple(row["fact_id"] for row in rows) != tuple(
            sorted(row["fact_id"] for row in rows)
        ):
            raise EvidenceProjectionError(
                "PROJECTION_ORDERING_INVALID",
                "classification projection fact ids are not in the declared order",
            )
        if len(rows) > binding.max_row_budget:
            raise EvidenceProjectionError(
                "PROJECTION_ROW_BUDGET_EXCEEDED",
                "classification projection exceeds the catalog row budget",
            )
        token_count = sum(_projection_token_cost(row) for row in rows)
        if token_count > binding.max_token_budget:
            raise EvidenceProjectionError(
                "PROJECTION_TOKEN_BUDGET_EXCEEDED",
                "classification projection exceeds the catalog token budget",
            )
        if not binding.evidence_contract_refs:
            raise EvidenceProjectionError(
                "PROJECTION_EVIDENCE_REF_REQUIRED",
                "classification projection has no catalog-bound evidence contract",
            )
        if any(ref.kind != "evidence" for ref in binding.evidence_contract_refs):
            raise EvidenceProjectionError(
                "PROJECTION_EVIDENCE_REF_INVALID",
                "classification projection evidence refs are not evidence contracts",
            )
        if any(ref.kind != "envelope" for ref in binding.envelope_contract_refs):
            raise EvidenceProjectionError(
                "PROJECTION_ENVELOPE_REF_INVALID",
                "classification projection envelope refs are not envelope contracts",
            )
        return {
            "payload_schema": CLASSIFICATION_EVIDENCE_SCHEMA,
            "schema_version": 1,
            **projection,
            "provider_id": binding.provider_id,
            "exposure_path": binding.exposure_path,
            "projection_ref": binding.projection_ref.to_dict(),
            "policy_ref": binding.policy_ref.to_dict(),
            "renderer_ref": binding.renderer_ref.to_dict(),
            "catalog_digest": binding.catalog_digest,
            "provider_digest": binding.provider_digest,
            "coverage_status": binding.coverage_status,
            "projection_constraints": {
                "policy_ref": binding.policy_ref.to_dict(),
                "max_token_budget": binding.max_token_budget,
                "max_row_budget": binding.max_row_budget,
                "allowed_sensitivity": list(binding.allowed_sensitivity),
                "observed_sensitivity": observed_sensitivity,
                "ordering": list(binding.ordering),
                "fact_kinds": list(binding.fact_kinds),
                "observed_fact_kinds": list(observed_fact_kinds),
                "row_count": len(rows),
                "token_count": token_count,
                "accepted_evidence_refs": [ref.to_dict() for ref in binding.evidence_contract_refs],
                "accepted_envelope_refs": [ref.to_dict() for ref in binding.envelope_contract_refs],
                "source_contract": {
                    "payload_contract": validated_source_contract["payload_contract"],
                    "evidence_schema_ref": validated_source_contract["evidence_schema_ref"],
                    "evidence_contract_refs": [
                        ref.to_dict() for ref in validated_source_contract["evidence_contract_refs"]
                    ],
                    "envelope_contract_refs": [
                        ref.to_dict() for ref in validated_source_contract["envelope_contract_refs"]
                    ],
                },
            },
        }


def default_provider_projection_registry() -> ProviderProjectionRegistryV1:
    return provider_projection_registry_from_catalog()


__all__ = [
    "CLASSIFICATION_CONSUMERS",
    "CLASSIFICATION_EVIDENCE_SCHEMA",
    "CLASSIFICATION_EXPOSURE_PATH",
    "CLASSIFICATION_PROVIDER_ID",
    "ClassificationProjectionAdapterV1",
    "ProviderProjectionBindingV1",
    "ProviderProjectionRegistryV1",
    "default_provider_projection_registry",
    "provider_projection_registry_from_catalog",
]
