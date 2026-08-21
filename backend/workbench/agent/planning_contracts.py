"""Trust-separated planning contracts for the agent compiler boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..canonical import sha256_canonical
from ..contracts.agent.planning import (
    CompiledWorkflowV1,
    CompilationRecordReferenceV1,
    CompilationRecordStoreV1,
    CompilationRecordV1,
    DraftAgentPlanV1,
    FailureEnvelopeV1,
    PlanEffectV1,
    PlanRiskLevelV1,
    PlanningContractError,
    ServerCompilationRecordReferenceV1,
    ServerDraftPlanReferenceV1,
)
from ..contracts.common.contract_ref import ContractRefV1
from .authority import HostAuthorityChannelError, HostAuthorityHandleV1


_SHA256 = re.compile(r"[0-9a-f]{64}")
# Kept as a legacy import sentinel only.  It is deliberately not accepted by
# any constructor or bootstrap method and carries no authority.
_SERVER_SCOPE_AUTHORITY_PROOF = object()
_SCOPE_BINDING_FIELDS = frozenset(
    {"scope_ref", "principal_ref", "session_ref", "project_ref"}
)


def _safe_ref(value: object, prefix: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.startswith(prefix)
        or not value.partition(":")[2]
        or any(token in value for token in ("/", "\\", "..", "://"))
    ):
        raise ValueError("invalid opaque reference")
    return value


def _safe_scope(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("invalid scope reference")
    if not value.startswith(("project:", "workspace:", "notebook:", "scope:")):
        raise ValueError("invalid scope reference")
    if any(token in value for token in ("/", "\\", "..", "://")):
        raise ValueError("invalid scope reference")
    if not value.partition(":")[2]:
        raise ValueError("invalid scope reference")
    return value


@dataclass(frozen=True)
class AnalysisIntentV1:
    """A user/request-scoped analysis intent, never a compiled plan."""

    intent_ref: str
    scope_ref: str
    capability_ids: tuple[str, ...]
    source_digest: str
    contract_digest: str

    def __post_init__(self) -> None:
        _safe_ref(self.intent_ref, "intent:")
        _safe_scope(self.scope_ref)
        if not isinstance(self.capability_ids, (tuple, list)) or not self.capability_ids:
            raise ValueError("capability_ids must be non-empty")
        ids = tuple(self.capability_ids)
        if any(
            type(item) is not str
            or not item
            or item != item.strip()
            or any(token in item for token in ("/", "\\", "..", "://"))
            for item in ids
        ):
            raise ValueError("capability_ids contain an invalid identity")
        if len(set(ids)) != len(ids):
            raise ValueError("capability_ids contain duplicate identities")
        object.__setattr__(self, "capability_ids", ids)
        for name, value in (("source_digest", self.source_digest), ("contract_digest", self.contract_digest)):
            if _SHA256.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "analysis-intent.v1",
            "intent_ref": self.intent_ref,
            "scope_ref": self.scope_ref,
            "capability_ids": list(self.capability_ids),
            "source_digest": self.source_digest,
            "contract_digest": self.contract_digest,
            "intent_digest": self.intent_digest,
        }

    @property
    def intent_digest(self) -> str:
        return sha256_canonical(
            {
                "schema_version": "analysis-intent.v1",
                "intent_ref": self.intent_ref,
                "scope_ref": self.scope_ref,
                "capability_ids": list(self.capability_ids),
                "source_digest": self.source_digest,
                "contract_digest": self.contract_digest,
            }
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AnalysisIntentV1":
        if type(value) is not dict or set(value) != {
            "schema_version",
            "intent_ref",
            "scope_ref",
            "capability_ids",
            "source_digest",
            "contract_digest",
            "intent_digest",
        }:
            raise ValueError("analysis intent shape is invalid")
        result = cls(
            intent_ref=value["intent_ref"],
            scope_ref=value["scope_ref"],
            capability_ids=tuple(value["capability_ids"]),
            source_digest=value["source_digest"],
            contract_digest=value["contract_digest"],
        )
        if value["schema_version"] != "analysis-intent.v1" or value["intent_digest"] != result.intent_digest:
            raise ValueError("analysis intent digest is invalid")
        return result


@dataclass(frozen=True)
class ServerScopeBindingV1:
    """An issuer-bound host identity snapshot for compiler admission."""

    scope_ref: str
    principal_ref: str
    session_ref: str
    project_ref: str
    _binding_id: str = field(default="", init=False, repr=False, compare=False)
    _authority_handle: HostAuthorityHandleV1 | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _safe_scope(self.scope_ref)
        _safe_ref(self.principal_ref, "principal:")
        _safe_ref(self.session_ref, "session:")
        _safe_scope(self.project_ref)

    @classmethod
    def _issue(
        cls,
        *,
        scope_ref: str,
        principal_ref: str,
        session_ref: str,
        project_ref: str,
        issuer_token: object,
    ) -> "ServerScopeBindingV1":
        """Reject the removed in-process issuer seam."""

        raise ValueError("host authority handle is required")

    @classmethod
    def _from_host_claim(
        cls,
        *,
        handle: HostAuthorityHandleV1,
        claim: Mapping[str, Any],
    ) -> "ServerScopeBindingV1":
        if type(handle) is not HostAuthorityHandleV1 or type(claim) is not dict:
            raise ValueError("host authority handle is required")
        try:
            handle._assert_live()
        except (AttributeError, HostAuthorityChannelError) as exc:
            raise ValueError("host authority handle is required") from exc
        binding_id = claim.get("binding_id")
        if type(binding_id) is not str or not binding_id.startswith("binding:"):
            raise ValueError("host binding claim is invalid")
        try:
            value = cls(
                scope_ref=claim["scope_ref"],
                principal_ref=claim["principal_ref"],
                session_ref=claim["session_ref"],
                project_ref=claim["project_ref"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("host binding claim is invalid") from exc
        object.__setattr__(value, "_binding_id", binding_id)
        object.__setattr__(value, "_authority_handle", handle)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ServerScopeBindingV1":
        """Reject wire re-issuance; host identity must be resolved again."""

        raise ValueError("server-owned scope binding cannot be reconstructed from JSON")

    @property
    def binding_digest(self) -> str:
        return sha256_canonical(
            {
                "schema_version": "server-scope-binding.v1",
                "scope_ref": self.scope_ref,
                "principal_ref": self.principal_ref,
                "session_ref": self.session_ref,
                "project_ref": self.project_ref,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "server-scope-binding.v1",
            "scope_ref": self.scope_ref,
            "principal_ref": self.principal_ref,
            "session_ref": self.session_ref,
            "project_ref": self.project_ref,
            "binding_digest": self.binding_digest,
        }

    def __copy__(self) -> "ServerScopeBindingV1":
        raise TypeError("scope authority proofs cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> "ServerScopeBindingV1":
        raise TypeError("scope authority proofs cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("scope authority proofs cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> tuple[object, ...]:
        raise TypeError("scope authority proofs cannot be serialized")


class ScopeAuthorityResolverV1:
    """Resolver facade over a host-issued authority channel."""

    def __init__(
        self,
        host_handle: HostAuthorityHandleV1 | None = None,
        *,
        bindings: tuple[ServerScopeBindingV1, ...] = (),
    ) -> None:
        if type(host_handle) is not HostAuthorityHandleV1:
            raise ValueError("host authority handle is required")
        if bindings:
            raise ValueError("scope snapshots cannot be supplied by the caller")
        try:
            host_handle._assert_live()
        except (AttributeError, HostAuthorityChannelError) as exc:
            raise ValueError("host authority handle is required") from exc
        self._host_handle = host_handle
        self._bindings: dict[tuple[str, str, str, str], ServerScopeBindingV1] = {}

    @classmethod
    def from_host_handle(cls, host_handle: HostAuthorityHandleV1) -> "ScopeAuthorityResolverV1":
        return cls(host_handle)

    @property
    def host_handle(self) -> HostAuthorityHandleV1:
        try:
            self._host_handle._assert_live()
        except (AttributeError, HostAuthorityChannelError) as exc:
            raise ValueError("host authority handle is required") from exc
        return self._host_handle

    @classmethod
    def _from_server_snapshots(
        cls,
        snapshots: tuple[Mapping[str, Any], ...],
        *,
        _server_proof: object | None = None,
    ) -> "ScopeAuthorityResolverV1":
        """Reject the historical caller-reachable snapshot bootstrap."""

        raise ValueError("host authority handle is required")

    @staticmethod
    def _key(binding: ServerScopeBindingV1) -> tuple[str, str, str, str]:
        return (
            binding.scope_ref,
            binding.principal_ref,
            binding.session_ref,
            binding.project_ref,
        )

    def issue(self, binding: ServerScopeBindingV1) -> ServerScopeBindingV1:
        if type(binding) is not ServerScopeBindingV1:
            raise ValueError("scope binding is invalid")
        return self.require(binding)

    def resolve(
        self,
        *,
        scope_ref: str,
        principal_ref: str,
        session_ref: str,
        project_ref: str,
    ) -> ServerScopeBindingV1:
        try:
            claim = self._host_handle.bind_scope(
                scope_ref=scope_ref,
                principal_ref=principal_ref,
                session_ref=session_ref,
                project_ref=project_ref,
            )
            binding = ServerScopeBindingV1._from_host_claim(handle=self._host_handle, claim=claim)
        except (AttributeError, HostAuthorityChannelError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("scope and principal are not server-bound") from exc
        self._bindings[self._key(binding)] = binding
        return self.require(binding)

    def require(self, binding: ServerScopeBindingV1) -> ServerScopeBindingV1:
        if type(binding) is not ServerScopeBindingV1:
            raise ValueError("scope binding was not issued by this resolver")
        try:
            binding_id = binding._binding_id
        except AttributeError as exc:
            raise ValueError("scope binding was not issued by this resolver") from exc
        if type(binding_id) is not str or not binding_id.startswith("binding:"):
            raise ValueError("scope binding was not issued by this resolver")
        try:
            key = self._key(binding)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("scope binding was not issued by this resolver") from exc
        if self._bindings.get(key) is not binding:
            raise ValueError("scope binding was not issued by this resolver")
        try:
            claim = self._host_handle.validate_binding(binding_id)
            canonical = ServerScopeBindingV1._from_host_claim(
                handle=self._host_handle,
                claim=claim,
            )
        except (AttributeError, HostAuthorityChannelError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("scope binding was not issued by this resolver") from exc
        if canonical.to_dict() != binding.to_dict():
            raise ValueError("scope binding was not issued by this resolver")
        self._bindings[self._key(binding)] = binding
        return binding

    def __copy__(self) -> "ScopeAuthorityResolverV1":
        raise TypeError("scope authority resolvers cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> "ScopeAuthorityResolverV1":
        raise TypeError("scope authority resolvers cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("scope authority resolvers cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> tuple[object, ...]:
        raise TypeError("scope authority resolvers cannot be serialized")


class DeploymentIdentityResolverV1:
    """Adapt authenticated host identity to the external scope authority.

    The callback only supplies the deployment's authenticated identity
    snapshot.  It does not issue a scope binding.  Every invocation is
    re-bound and revalidated through ``ScopeAuthorityResolverV1`` so a stale
    request assertion cannot become Agent/Notebook authority.
    """

    def __init__(
        self,
        scope_resolver: ScopeAuthorityResolverV1,
        authenticated_identity_resolver: Any,
    ) -> None:
        if type(scope_resolver) is not ScopeAuthorityResolverV1:
            raise ValueError("scope authority resolver is required")
        if not callable(authenticated_identity_resolver):
            raise ValueError("authenticated identity resolver is required")
        self._scope_resolver = scope_resolver
        self._authenticated_identity_resolver = authenticated_identity_resolver

    @classmethod
    def from_host_handle(
        cls,
        host_handle: HostAuthorityHandleV1,
        authenticated_identity_resolver: Any,
    ) -> "DeploymentIdentityResolverV1":
        if type(host_handle) is not HostAuthorityHandleV1:
            raise ValueError("host authority handle is required")
        try:
            scope_resolver = ScopeAuthorityResolverV1.from_host_handle(host_handle)
        except (AttributeError, HostAuthorityChannelError, TypeError, ValueError) as exc:
            raise ValueError("host authority handle is required") from exc
        return cls(scope_resolver, authenticated_identity_resolver)

    def __call__(
        self,
        request: Any,
        project_ref: str,
        claimed_session_ref: str | None,
        notebook_id: str | None,
    ) -> tuple[str, str, str]:
        try:
            asserted = self._authenticated_identity_resolver(
                request,
                project_ref,
                claimed_session_ref,
                notebook_id,
            )
        except Exception as exc:
            raise ValueError("authenticated identity is unavailable") from exc
        if type(asserted) is not tuple or len(asserted) not in {2, 3}:
            raise ValueError("authenticated identity binding is invalid")
        principal_ref, session_ref = asserted[:2]
        _safe_ref(principal_ref, "principal:")
        _safe_ref(session_ref, "session:")
        canonical_project_ref = project_ref
        if len(asserted) == 3:
            asserted_project_ref = asserted[2]
            if asserted_project_ref != project_ref:
                raise ValueError("authenticated project scope does not match request scope")
            canonical_project_ref = asserted_project_ref
        _safe_scope(canonical_project_ref)
        try:
            binding = self._scope_resolver.resolve(
                scope_ref=canonical_project_ref,
                principal_ref=principal_ref,
                session_ref=session_ref,
                project_ref=canonical_project_ref,
            )
        except (AttributeError, HostAuthorityChannelError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("scope and principal are not server-bound") from exc
        if type(binding) is not ServerScopeBindingV1:
            raise ValueError("scope authority returned an invalid binding")
        if (
            binding.scope_ref != canonical_project_ref
            or binding.principal_ref != principal_ref
            or binding.session_ref != session_ref
            or binding.project_ref != canonical_project_ref
        ):
            raise ValueError("scope authority returned a mismatched binding")
        return binding.principal_ref, binding.session_ref, binding.project_ref

    def __copy__(self) -> "DeploymentIdentityResolverV1":
        raise TypeError("deployment identity resolvers cannot be copied")

    def __deepcopy__(self, _memo: dict[str, object]) -> "DeploymentIdentityResolverV1":
        raise TypeError("deployment identity resolvers cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("deployment identity resolvers cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> tuple[object, ...]:
        raise TypeError("deployment identity resolvers cannot be serialized")


CompiledAgentPlanV1 = CompiledWorkflowV1
CompiledAgentPlan = CompiledWorkflowV1
CompilationRecord = CompilationRecordV1
DraftAgentPlan = DraftAgentPlanV1
AnalysisIntent = AnalysisIntentV1


@dataclass(frozen=True)
class HostCompilationRequestV1:
    """Typed request handed to the deployment-owned compiler host.

    The request is descriptive input only.  It carries no local issuer token,
    record store, or authority proof; the host must bind it to its own
    supervisor/OS authority before returning a result.
    """

    draft: DraftAgentPlanV1
    intent: AnalysisIntentV1
    scope_ref: str
    principal_ref: str
    session_ref: str
    project_ref: str
    source_commitments: Mapping[str, Any]
    selection: object
    idempotency_key: str

    def __post_init__(self) -> None:
        if type(self.draft) is not DraftAgentPlanV1:
            raise ValueError("host compilation request draft is invalid")
        if type(self.intent) is not AnalysisIntentV1:
            raise ValueError("host compilation request intent is invalid")
        for name, value in (
            ("scope_ref", self.scope_ref),
            ("project_ref", self.project_ref),
        ):
            _safe_scope(value)
        for name, value in (
            ("principal_ref", self.principal_ref),
            ("session_ref", self.session_ref),
        ):
            _safe_ref(value, f"{name.split('_')[0]}:")
        if type(self.source_commitments) is not dict:
            raise ValueError("host compilation request commitments are invalid")
        if type(self.idempotency_key) is not str or _SHA256.fullmatch(self.idempotency_key) is None:
            raise ValueError("host compilation request idempotency key is invalid")


@dataclass(frozen=True)
class HostCompilationResultV1:
    """Typed result returned by a host compiler authority port.

    The values remain untrusted until ``PlanCompiler`` checks their identity,
    scope and semantic hash and the replay store accepts the result.  This
    carrier deliberately has no constructor for local authority objects beyond
    ordinary data validation.
    """

    compiled_plan: CompiledWorkflowV1
    record: CompilationRecordV1
    reference: ServerCompilationRecordReferenceV1

    def __post_init__(self) -> None:
        if type(self.compiled_plan) is not CompiledWorkflowV1:
            raise ValueError("host compilation result plan is invalid")
        if type(self.record) is not CompilationRecordV1:
            raise ValueError("host compilation result record is invalid")
        if type(self.reference) is not ServerCompilationRecordReferenceV1:
            raise ValueError("host compilation result reference is invalid")


class HostCompilationAuthorityPortV1(Protocol):
    """Explicit seam for a supervisor-backed host compiler.

    There is intentionally no in-process implementation in this package.  A
    production adapter must be supplied by the deployment integration and must
    return a host-issued result, otherwise the public compiler fails closed.
    """

    def compile(self, request: HostCompilationRequestV1) -> HostCompilationResultV1: ...


__all__ = [
    "AnalysisIntentV1",
    "AnalysisIntent",
    "CompiledAgentPlan",
    "CompiledAgentPlanV1",
    "CompiledWorkflowV1",
    "CompilationRecord",
    "CompilationRecordReferenceV1",
    "CompilationRecordStoreV1",
    "CompilationRecordV1",
    "ContractRefV1",
    "DraftAgentPlan",
    "DraftAgentPlanV1",
    "FailureEnvelopeV1",
    "PlanEffectV1",
    "PlanRiskLevelV1",
    "PlanningContractError",
    "HostCompilationAuthorityPortV1",
    "HostCompilationRequestV1",
    "HostCompilationResultV1",
    "ServerCompilationRecordReferenceV1",
    "ServerDraftPlanReferenceV1",
    "ScopeAuthorityResolverV1",
    "ServerScopeBindingV1",
    "DeploymentIdentityResolverV1",
]
