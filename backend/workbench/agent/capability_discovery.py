"""Bounded two-stage capability discovery over a fixed manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from ..canonical import canonical_json_v1, sha256_canonical
from .authority import HostAuthorityChannelError, HostAuthorityHandleV1
from .capability_manifest import CapabilityManifestEntryV1, CapabilityManifestV1
from .failure_contract import CompilationFailure, failure
from .planning_contracts import ScopeAuthorityResolverV1, ServerScopeBindingV1


_KNOWN_SCOPE_PREFIXES = ("project:", "workspace:", "notebook:", "scope:")
_RECEIPT_ADMISSIONS: dict[str, tuple[object, HostAuthorityHandleV1]] = {}
_SELECTION_ADMISSIONS: dict[str, tuple[object, HostAuthorityHandleV1]] = {}
_ADMISSIONS_LOCK = RLock()


def _scope(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(token in value for token in ("/", "\\", "..", "://"))
    ):
        raise failure("PATH_LIKE_INPUT", stage="discovery")
    if not value.startswith(_KNOWN_SCOPE_PREFIXES) or not value.partition(":")[2]:
        raise failure("CROSS_SCOPE", stage="discovery")
    return value


@dataclass(frozen=True)
class DiscoveryLimitsV1:
    max_query_results: int = 16
    max_query_bytes: int = 256
    max_result_bytes: int = 32_768

    def __post_init__(self) -> None:
        if type(self.max_query_results) is not int or not 1 <= self.max_query_results <= 256:
            raise ValueError("max_query_results is invalid")
        if type(self.max_query_bytes) is not int or not 1 <= self.max_query_bytes <= 16_384:
            raise ValueError("max_query_bytes is invalid")
        if type(self.max_result_bytes) is not int or not 1024 <= self.max_result_bytes <= 1_000_000:
            raise ValueError("max_result_bytes is invalid")


@dataclass(frozen=True)
class CapabilityDiscoveryResultV1:
    query: str
    scope_ref: str
    items: tuple[CapabilityManifestEntryV1, ...]
    manifest_digest: str
    bounded: bool = True
    receipt_digest: str = ""
    authority_binding_digest: str = ""
    _receipt_id: str = field(default="", init=False, repr=False, compare=False)
    _authority_handle: HostAuthorityHandleV1 | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def _issue(
        cls,
        *,
        issuer_token: object,
        query: str,
        scope_ref: str,
        items: tuple[CapabilityManifestEntryV1, ...],
        manifest_digest: str,
        authority_binding_digest: str,
    ) -> "CapabilityDiscoveryResultV1":
        raise ValueError("host authority handle is required")

    @classmethod
    def _from_host(
        cls,
        *,
        handle: HostAuthorityHandleV1,
        receipt_id: str,
        query: str,
        scope_ref: str,
        items: tuple[CapabilityManifestEntryV1, ...],
        manifest_digest: str,
        authority_binding_digest: str,
    ) -> "CapabilityDiscoveryResultV1":
        if type(handle) is not HostAuthorityHandleV1 or type(receipt_id) is not str:
            raise ValueError("host authority handle is required")
        try:
            handle._assert_live()
        except (AttributeError, HostAuthorityChannelError) as exc:
            raise ValueError("host authority handle is required") from exc
        value = cls(
            query=query,
            scope_ref=scope_ref,
            items=items,
            manifest_digest=manifest_digest,
            authority_binding_digest=authority_binding_digest,
        )
        object.__setattr__(value, "_receipt_id", receipt_id)
        object.__setattr__(value, "_authority_handle", handle)
        with _ADMISSIONS_LOCK:
            previous = _RECEIPT_ADMISSIONS.get(receipt_id)
            if previous is not None:
                raise ValueError("discovery receipt identity is already admitted")
            _RECEIPT_ADMISSIONS[receipt_id] = (value, handle)
        return value

    @classmethod
    def _require_admitted(cls, value: object) -> "CapabilityDiscoveryResultV1":
        if type(value) is not cls:
            raise HostAuthorityChannelError("FORGED_AUTHORITY")
        try:
            receipt_id = value._receipt_id
            handle = value._authority_handle
        except AttributeError as exc:
            raise HostAuthorityChannelError("FORGED_AUTHORITY") from exc
        with _ADMISSIONS_LOCK:
            record = _RECEIPT_ADMISSIONS.get(receipt_id)
        if record is None or record[0] is not value or record[1] is not handle:
            raise HostAuthorityChannelError("FORGED_AUTHORITY")
        return value

    def __post_init__(self) -> None:
        if type(self.query) is not str or type(self.scope_ref) is not str:
            raise ValueError("discovery receipt text is invalid")
        _scope(self.scope_ref)
        if not isinstance(self.items, (tuple, list)) or any(
            type(item) is not CapabilityManifestEntryV1 for item in self.items
        ):
            raise ValueError("discovery receipt items are invalid")
        object.__setattr__(self, "items", tuple(self.items))
        if type(self.manifest_digest) is not str or len(self.manifest_digest) != 64:
            raise ValueError("discovery receipt manifest digest is invalid")
        if self.authority_binding_digest and (
            type(self.authority_binding_digest) is not str
            or len(self.authority_binding_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.authority_binding_digest)
        ):
            raise ValueError("discovery receipt authority digest is invalid")
        if type(self.bounded) is not bool or not self.bounded:
            raise ValueError("discovery receipt must be bounded")
        expected = sha256_canonical(self._receipt_payload())
        if self.receipt_digest and self.receipt_digest != expected:
            raise ValueError("discovery receipt digest does not match receipt")
        object.__setattr__(self, "receipt_digest", expected)

    def _receipt_payload(self) -> dict[str, object]:
        return {
            "schema_version": "capability-discovery-result.v1",
            "query": self.query,
            "scope_ref": self.scope_ref,
            "items": [item.to_dict() for item in self.items],
            "manifest_digest": self.manifest_digest,
            "bounded": self.bounded,
            "authority_binding_digest": self.authority_binding_digest,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._receipt_payload(),
            "receipt_digest": self.receipt_digest,
        }

    def __copy__(self) -> "CapabilityDiscoveryResultV1":
        raise TypeError("discovery receipts cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> "CapabilityDiscoveryResultV1":
        raise TypeError("discovery receipts cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("discovery receipts cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> tuple[object, ...]:
        raise TypeError("discovery receipts cannot be serialized")


@dataclass(frozen=True)
class CapabilitySelectionV1:
    capability_id: str
    scope_ref: str
    manifest_digest: str
    entry: CapabilityManifestEntryV1
    receipt_digest: str
    authority_binding_digest: str = ""
    _selection_id: str = field(default="", init=False, repr=False, compare=False)
    _authority_handle: HostAuthorityHandleV1 | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def _issue(
        cls,
        *,
        issuer_token: object,
        capability_id: str,
        scope_ref: str,
        manifest_digest: str,
        entry: CapabilityManifestEntryV1,
        receipt_digest: str,
        authority_binding_digest: str,
    ) -> "CapabilitySelectionV1":
        raise ValueError("host authority handle is required")

    @classmethod
    def _from_host(
        cls,
        *,
        handle: HostAuthorityHandleV1,
        selection_id: str,
        capability_id: str,
        scope_ref: str,
        manifest_digest: str,
        entry: CapabilityManifestEntryV1,
        receipt_digest: str,
        authority_binding_digest: str,
    ) -> "CapabilitySelectionV1":
        if type(handle) is not HostAuthorityHandleV1 or type(selection_id) is not str:
            raise ValueError("host authority handle is required")
        try:
            handle._assert_live()
        except (AttributeError, HostAuthorityChannelError) as exc:
            raise ValueError("host authority handle is required") from exc
        value = cls(
            capability_id=capability_id,
            scope_ref=scope_ref,
            manifest_digest=manifest_digest,
            entry=entry,
            receipt_digest=receipt_digest,
            authority_binding_digest=authority_binding_digest,
        )
        object.__setattr__(value, "_selection_id", selection_id)
        object.__setattr__(value, "_authority_handle", handle)
        with _ADMISSIONS_LOCK:
            previous = _SELECTION_ADMISSIONS.get(selection_id)
            if previous is not None:
                raise ValueError("capability selection identity is already admitted")
            _SELECTION_ADMISSIONS[selection_id] = (value, handle)
        return value

    @classmethod
    def _require_admitted(cls, value: object) -> "CapabilitySelectionV1":
        if type(value) is not cls:
            raise HostAuthorityChannelError("FORGED_AUTHORITY")
        try:
            selection_id = value._selection_id
            handle = value._authority_handle
        except AttributeError as exc:
            raise HostAuthorityChannelError("FORGED_AUTHORITY") from exc
        with _ADMISSIONS_LOCK:
            record = _SELECTION_ADMISSIONS.get(selection_id)
        if record is None or record[0] is not value or record[1] is not handle:
            raise HostAuthorityChannelError("FORGED_AUTHORITY")
        return value

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "capability-selection.v1",
            "capability_id": self.capability_id,
            "scope_ref": self.scope_ref,
            "manifest_digest": self.manifest_digest,
            "receipt_digest": self.receipt_digest,
            "authority_binding_digest": self.authority_binding_digest,
            "entry": self.entry.to_dict(),
        }

    def __copy__(self) -> "CapabilitySelectionV1":
        raise TypeError("capability selections cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> "CapabilitySelectionV1":
        raise TypeError("capability selections cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("capability selections cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> tuple[object, ...]:
        raise TypeError("capability selections cannot be serialized")


class CapabilityDiscovery:
    """Stage 1 searches metadata; stage 2 resolves one manifest entry."""

    def __init__(
        self,
        manifest: CapabilityManifestV1,
        *,
        limits: DiscoveryLimitsV1 | None = None,
        authority_resolver: ScopeAuthorityResolverV1 | None = None,
        authority_handle: HostAuthorityHandleV1 | None = None,
    ) -> None:
        if type(manifest) is not CapabilityManifestV1:
            raise TypeError("discovery requires a CapabilityManifestV1")
        self.manifest = manifest
        self.limits = limits or DiscoveryLimitsV1()
        if type(self.limits) is not DiscoveryLimitsV1:
            raise TypeError("limits must be DiscoveryLimitsV1")
        if authority_resolver is not None and type(authority_resolver) is not ScopeAuthorityResolverV1:
            raise TypeError("authority_resolver must be a ScopeAuthorityResolverV1")
        if authority_resolver is not None and authority_handle is not None:
            raise TypeError("provide one host authority source")
        if authority_handle is not None and type(authority_handle) is not HostAuthorityHandleV1:
            raise TypeError("authority_handle must be a HostAuthorityHandleV1")
        if authority_handle is not None:
            try:
                authority_handle._assert_live()
            except (AttributeError, HostAuthorityChannelError) as exc:
                raise ValueError("host authority handle is required") from exc
        self.authority_handle = authority_handle or (
            authority_resolver.host_handle if authority_resolver is not None else None
        )
        self.authority_resolver = authority_resolver or (
            ScopeAuthorityResolverV1.from_host_handle(authority_handle)
            if authority_handle is not None
            else None
        )

    def _authority(
        self,
        *,
        scope_ref: str,
        principal_ref: str,
        session_ref: str,
        project_ref: str,
    ) -> ServerScopeBindingV1:
        if self.authority_resolver is None:
            raise failure("FORGED_AUTHORITY", stage="discovery")
        try:
            return self.authority_resolver.resolve(
                scope_ref=scope_ref,
                principal_ref=principal_ref,
                session_ref=session_ref,
                project_ref=project_ref,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise failure("FORGED_AUTHORITY", stage="discovery") from exc

    def query(
        self,
        query: str,
        *,
        scope_ref: str,
        principal_ref: str = "principal:unknown",
        session_ref: str = "session:unknown",
        project_ref: str | None = None,
    ) -> CapabilityDiscoveryResultV1:
        if type(query) is not str:
            raise failure("DRAFT_INVALID", stage="discovery")
        query_bytes = len(canonical_json_v1({"query": query}).encode("utf-8"))
        if query_bytes > self.limits.max_query_bytes:
            raise failure("DISCOVERY_QUERY_LIMIT", stage="discovery")
        selected_scope = _scope(scope_ref)
        if any(token in query for token in ("/", "\\", "..", "://")):
            raise failure("PATH_LIKE_INPUT", stage="discovery")
        binding = self._authority(
            scope_ref=selected_scope,
            principal_ref=principal_ref,
            session_ref=session_ref,
            project_ref=project_ref or selected_scope,
        )
        needle = query.casefold().strip()
        matches = tuple(
            entry
            for entry in self.manifest.entries
            if entry.natural_language_enabled
            if not needle
            or needle in entry.capability_id.casefold()
            or needle in entry.summary.casefold()
        )
        if len(matches) > self.limits.max_query_results:
            raise failure("DISCOVERY_QUERY_LIMIT", stage="discovery")
        result_without_id = CapabilityDiscoveryResultV1(
            query=query,
            scope_ref=selected_scope,
            items=matches,
            manifest_digest=self.manifest.manifest_digest,
            authority_binding_digest=binding.binding_digest,
        )
        if self.authority_handle is None:
            raise failure("FORGED_AUTHORITY", stage="discovery")
        try:
            receipt_claim = self.authority_handle.issue_discovery_receipt(
                binding_id=binding._binding_id,
                query=query,
                manifest_digest=self.manifest.manifest_digest,
                capability_ids=(entry.capability_id for entry in matches),
                receipt_digest=result_without_id.receipt_digest,
            )
            receipt_id = receipt_claim["receipt_id"]
        except (AttributeError, HostAuthorityChannelError, KeyError, TypeError, ValueError) as exc:
            raise failure("FORGED_AUTHORITY", stage="discovery") from exc
        result = CapabilityDiscoveryResultV1._from_host(
            handle=self.authority_handle,
            receipt_id=receipt_id,
            query=query,
            scope_ref=selected_scope,
            items=matches,
            manifest_digest=self.manifest.manifest_digest,
            authority_binding_digest=binding.binding_digest,
        )
        if len(canonical_json_v1(result.to_dict()).encode("utf-8")) > self.limits.max_result_bytes:
            raise failure("DISCOVERY_QUERY_LIMIT", stage="discovery")
        return result

    def resolve(
        self,
        capability_id: str,
        *,
        scope_ref: str,
        principal_ref: str = "principal:unknown",
        session_ref: str = "session:unknown",
        project_ref: str | None = None,
        receipt: CapabilityDiscoveryResultV1 | None = None,
    ) -> CapabilitySelectionV1:
        selected_scope = _scope(scope_ref)
        binding = self._authority(
            scope_ref=selected_scope,
            principal_ref=principal_ref,
            session_ref=session_ref,
            project_ref=project_ref or selected_scope,
        )
        if type(receipt) is not CapabilityDiscoveryResultV1:
            raise failure("FORGED_AUTHORITY", stage="discovery")
        try:
            CapabilityDiscoveryResultV1._require_admitted(receipt)
        except (AttributeError, HostAuthorityChannelError, TypeError, ValueError) as exc:
            raise failure("FORGED_AUTHORITY", stage="discovery") from exc
        if self.authority_handle is None or type(receipt._receipt_id) is not str or not receipt._receipt_id:
            raise failure("FORGED_AUTHORITY", stage="discovery")
        if receipt._authority_handle is not self.authority_handle:
            raise failure("FORGED_AUTHORITY", stage="discovery")
        try:
            host_receipt = self.authority_handle.validate_discovery_receipt(receipt._receipt_id)
        except (AttributeError, HostAuthorityChannelError, KeyError, TypeError, ValueError) as exc:
            raise failure("FORGED_AUTHORITY", stage="discovery") from exc
        if (
            host_receipt.get("scope_ref") != selected_scope
            or host_receipt.get("query") != receipt.query
            or host_receipt.get("manifest_digest") != self.manifest.manifest_digest
            or host_receipt.get("receipt_digest") != receipt.receipt_digest
            or host_receipt.get("binding_id") != binding._binding_id
            or tuple(host_receipt.get("capability_ids", ()))
            != tuple(item.capability_id for item in receipt.items)
            or receipt.scope_ref != selected_scope
            or receipt.manifest_digest != self.manifest.manifest_digest
            or receipt.receipt_digest != sha256_canonical(receipt._receipt_payload())
            or receipt.authority_binding_digest != binding.binding_digest
            or len(receipt.items) > self.limits.max_query_results
        ):
            raise failure("FORGED_AUTHORITY", stage="discovery")
        try:
            entry = self.manifest.require(capability_id)
        except KeyError as exc:
            raise failure("UNKNOWN_CAPABILITY", stage="discovery") from exc
        if not entry.natural_language_enabled:
            raise failure("NATURAL_LANGUAGE_DISABLED", stage="discovery")
        if not any(
            item.capability_id == entry.capability_id and item.to_dict() == entry.to_dict()
            for item in receipt.items
        ):
            raise failure("FORGED_AUTHORITY", stage="discovery")
        try:
            selection_claim = self.authority_handle.issue_selection(
                receipt_id=receipt._receipt_id,
                capability_id=entry.capability_id,
                binding_id=binding._binding_id,
                manifest_digest=self.manifest.manifest_digest,
            )
            selection_id = selection_claim["selection_id"]
        except (AttributeError, HostAuthorityChannelError, KeyError, TypeError, ValueError) as exc:
            raise failure("FORGED_AUTHORITY", stage="discovery") from exc
        return CapabilitySelectionV1._from_host(
            handle=self.authority_handle,
            selection_id=selection_id,
            capability_id=entry.capability_id,
            scope_ref=selected_scope,
            manifest_digest=self.manifest.manifest_digest,
            entry=entry,
            receipt_digest=receipt.receipt_digest,
            authority_binding_digest=binding.binding_digest,
        )


CapabilityDiscoveryV1 = CapabilityDiscovery
DiscoveryResultV1 = CapabilityDiscoveryResultV1
CapabilitySelection = CapabilitySelectionV1


__all__ = [
    "CapabilityDiscovery",
    "CapabilityDiscoveryResultV1",
    "CapabilityDiscoveryV1",
    "CapabilitySelection",
    "CapabilitySelectionV1",
    "DiscoveryLimitsV1",
    "DiscoveryResultV1",
]
