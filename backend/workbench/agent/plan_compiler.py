"""Server-owned, fail-closed compilation of typed draft agent plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any

from ..canonical import canonical_json_v1, sha256_canonical
from ..contracts.agent.planning import (
    CompiledWorkflowV1,
    CompilationRecordV1,
    DraftAgentPlanV1,
    PlanningContractError,
    ServerCompilationRecordReferenceV1,
)
from ..contracts.common.contract_ref import ContractRefV1
from ..contracts.common.envelope import ContractError
from .authority import HostAuthorityChannelError, HostAuthorityHandleV1
from .capability_discovery import CapabilityDiscovery, CapabilitySelectionV1
from .capability_manifest import CapabilityManifestV1, build_capability_manifest
from .compilation_store import CompilationStore
from .failure_contract import CompilationFailure, failure
from .planning_contracts import (
    AnalysisIntentV1,
    HostCompilationAuthorityPortV1,
    HostCompilationRequestV1,
    HostCompilationResultV1,
    ScopeAuthorityResolverV1,
    ServerScopeBindingV1,
)
from .port_types import PortCompatibilityError


_FORBIDDEN_KEYS = frozenset(
    {
        "code",
        "execution_key",
        "executor",
        "import",
        "model",
        "model_choice",
        "model_id",
        "module",
        "network",
        "provider",
        "provider_choice",
        "provider_id",
        "receipt",
        "server_authority",
        "shell",
    }
)


def _safe_scope(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.startswith(("project:", "workspace:", "notebook:", "scope:"))
        or any(token in value for token in ("/", "\\", "..", "://"))
    ):
        raise failure("CROSS_SCOPE", stage="compile")
    return value


def _scan(value: object, *, reject_paths: bool = True) -> None:
    seen: set[int] = set()

    def visit(node: object) -> None:
        if isinstance(node, Mapping):
            marker = id(node)
            if marker in seen:
                raise failure("RECURSIVE_INPUT", stage="compile")
            seen.add(marker)
            for key, item in node.items():
                if type(key) is not str:
                    raise failure("DRAFT_INVALID", stage="compile")
                if key.casefold() in _FORBIDDEN_KEYS:
                    raise failure("MODEL_PROVIDER_INJECTION", stage="compile")
                visit(item)
            seen.remove(marker)
            return
        if isinstance(node, (list, tuple)):
            marker = id(node)
            if marker in seen:
                raise failure("RECURSIVE_INPUT", stage="compile")
            seen.add(marker)
            for item in node:
                visit(item)
            seen.remove(marker)
            return
        if type(node) is str and reject_paths and any(token in node for token in ("/", "\\", "..", "://")):
            raise failure("PATH_LIKE_INPUT", stage="compile")

    visit(value)


def _map_contract_error(exc: Exception) -> CompilationFailure:
    code = getattr(exc, "code", "")
    if code in {"PLANNING_DUPLICATE_ID", "CONTRACT_DUPLICATE"}:
        return failure("DUPLICATE_IDENTITY", stage="compile")
    return failure("DRAFT_INVALID", stage="compile")


def _budget_within(requested: Mapping[str, Any], declared: Mapping[str, Any]) -> bool:
    if not isinstance(requested, Mapping) or not isinstance(declared, Mapping):
        return False
    if set(requested) != set(declared):
        return False
    for key, value in requested.items():
        ceiling = declared.get(key)
        if (
            type(key) is not str
            or type(value) not in {int, float}
            or isinstance(value, bool)
            or type(ceiling) not in {int, float}
            or isinstance(ceiling, bool)
            or value < 0
            or value > ceiling
        ):
            return False
    return True


def _effect_allowed(effect: object, declared_effect: object) -> bool:
    return type(effect) is str and type(declared_effect) is str and effect == declared_effect


def _risk_rank(value: object) -> int | None:
    return {
        "none": 0,
        "low": 0,
        "mutating": 1,
        "medium": 1,
        "high": 2,
        "restricted": 3,
    }.get(value) if type(value) is str else None


@dataclass(frozen=True)
class CompilationRequestV1:
    draft: object
    intent: AnalysisIntentV1
    scope_ref: str
    principal_ref: str = "principal:unknown"
    session_ref: str = "session:unknown"
    project_ref: str = "project:unknown"
    source_commitments: Mapping[str, Any] | None = None
    authority_binding: ServerScopeBindingV1 | None = None
    selection: CapabilitySelectionV1 | None = None
    _internal_proof: object | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def _for_registry(
        cls,
        *,
        draft: object,
        intent: AnalysisIntentV1,
        scope_ref: str,
        source_commitments: Mapping[str, Any],
    ) -> "CompilationRequestV1":
        value = cls(
            draft=draft,
            intent=intent,
            scope_ref=scope_ref,
            principal_ref="principal:unknown",
            session_ref="session:unknown",
            project_ref=scope_ref,
            source_commitments=source_commitments,
        )
        return value

    def __post_init__(self) -> None:
        if type(self.intent) is not AnalysisIntentV1:
            raise TypeError("intent must be AnalysisIntentV1")
        _safe_scope(self.scope_ref)
        for name in ("principal_ref", "session_ref", "project_ref"):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"{name} is invalid")
        commitments = self.source_commitments or {}
        if type(commitments) is not dict:
            raise TypeError("source_commitments must be a dict")
        object.__setattr__(self, "source_commitments", dict(commitments))
        if self.authority_binding is not None and type(self.authority_binding) is not ServerScopeBindingV1:
            raise TypeError("authority_binding must be a ServerScopeBindingV1")
        if self.selection is not None and type(self.selection) is not CapabilitySelectionV1:
            raise TypeError("selection must be a CapabilitySelectionV1")


@dataclass(frozen=True)
class CompilationResultV1:
    idempotency_key: str
    compiled_plan: CompiledWorkflowV1
    record: CompilationRecordV1
    reference: ServerCompilationRecordReferenceV1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "agent-compilation-result.v1",
            "idempotency_key": self.idempotency_key,
            "compiled_plan": self.compiled_plan.to_dict(),
            "record": self.record.to_dict(),
            "reference": self.reference.to_dict(),
        }


class PlanCompiler:
    """The P0 admission boundary for host-created compiled workflows."""

    def __init__(
        self,
        *,
        manifest: CapabilityManifestV1,
        store: CompilationStore,
        authority_resolver: ScopeAuthorityResolverV1 | None = None,
        authority_handle: HostAuthorityHandleV1 | None = None,
        host_compiler: HostCompilationAuthorityPortV1 | None = None,
        max_input_bytes: int = 8_192,
    ) -> None:
        if type(manifest) is not CapabilityManifestV1:
            raise TypeError("manifest must be CapabilityManifestV1")
        if type(store) is not CompilationStore:
            raise TypeError("store must be CompilationStore")
        if type(max_input_bytes) is not int or not 1024 <= max_input_bytes <= 1_000_000:
            raise ValueError("max_input_bytes is invalid")
        self.manifest = manifest
        self.store = store
        self.max_input_bytes = max_input_bytes
        if authority_resolver is not None and type(authority_resolver) is not ScopeAuthorityResolverV1:
            raise TypeError("authority_resolver must be a ScopeAuthorityResolverV1")
        if authority_resolver is not None and authority_handle is not None:
            raise TypeError("provide one host authority source")
        if authority_handle is not None and type(authority_handle) is not HostAuthorityHandleV1:
            raise TypeError("authority_handle must be a HostAuthorityHandleV1")
        if authority_resolver is not None:
            authority_handle = authority_resolver.host_handle
        if authority_handle is not None:
            try:
                authority_handle._assert_live()
            except (AttributeError, HostAuthorityChannelError) as exc:
                raise ValueError("host authority handle is required") from exc
        if host_compiler is not None and not callable(getattr(host_compiler, "compile", None)):
            raise TypeError("host_compiler must implement the host compilation port")
        self.authority_resolver = authority_resolver
        self.authority_handle = authority_handle
        self.host_compiler = host_compiler
        self._registry_manifest_digest = build_capability_manifest().manifest_digest

    def compile(
        self,
        draft_or_request: object,
        *,
        intent: AnalysisIntentV1 | None = None,
        scope_ref: str | None = None,
        principal_ref: str = "principal:unknown",
        session_ref: str = "session:unknown",
        project_ref: str | None = None,
        source_commitments: Mapping[str, Any] | None = None,
        selection: CapabilitySelectionV1 | None = None,
    ) -> CompilationResultV1:
        try:
            request = self._bind_authority(
                self._request(
                    draft_or_request,
                    intent=intent,
                    scope_ref=scope_ref,
                    principal_ref=principal_ref,
                    session_ref=session_ref,
                    project_ref=project_ref,
                    source_commitments=source_commitments,
                    selection=selection,
                )
            )
            draft = self._draft(request.draft)
            self._validate(draft, request)
            idempotency_key = sha256_canonical(
                {
                    "schema_version": "agent-compilation-key.v1",
                    "manifest_digest": self.manifest.manifest_digest,
                    "draft_hash": draft.semantic_plan_hash,
                    "intent": request.intent.to_dict(),
                    "scope_ref": request.scope_ref,
                    "principal_ref": request.principal_ref,
                    "session_ref": request.session_ref,
                    "project_ref": request.project_ref,
                    "source_commitments": dict(request.source_commitments or {}),
                    "authority_binding_digest": request.authority_binding.binding_digest,
                }
            )
        except CompilationFailure:
            raise
        except (AttributeError, HostAuthorityChannelError) as exc:
            raise failure("FORGED_AUTHORITY", stage="compile") from exc
        except (ContractError, PlanningContractError, RecursionError, TypeError, ValueError) as exc:
            raise failure("DRAFT_INVALID", stage="compile") from exc
        if not self.store.durable_reservation_available:
            raise failure("DURABLE_RESERVATION_REQUIRED", stage="store")
        with self.store.reservation(idempotency_key) as replay:
            if replay is not None:
                return replay
            try:
                if self.host_compiler is None:
                    raise failure("HOST_COMPILER_INTEGRATION_REQUIRED", stage="compile")
                host_request = HostCompilationRequestV1(
                    draft=draft,
                    intent=request.intent,
                    scope_ref=request.scope_ref,
                    principal_ref=request.principal_ref,
                    session_ref=request.session_ref,
                    project_ref=request.project_ref,
                    source_commitments=dict(request.source_commitments or {}),
                    selection=request.selection,
                    idempotency_key=idempotency_key,
                )
                host_result = self.host_compiler.compile(host_request)
                self._validate_host_result(
                    host_result,
                    idempotency_key=idempotency_key,
                    draft=draft,
                    request=request,
                )
                result = CompilationResultV1(
                    idempotency_key=idempotency_key,
                    compiled_plan=host_result.compiled_plan,
                    record=host_result.record,
                    reference=host_result.reference,
                )
                return self.store.save_result(idempotency_key, result)
            except CompilationFailure:
                raise
            except (AttributeError, HostAuthorityChannelError) as exc:
                raise failure("FORGED_AUTHORITY", stage="compile") from exc
            except (OSError, TimeoutError) as exc:
                raise failure("HOST_COMPILER_INTEGRATION_REQUIRED", stage="compile") from exc
            except (ContractError, PlanningContractError, RecursionError, TypeError, ValueError) as exc:
                if getattr(exc, "code", "") == "HOST_COMPILER_INTEGRATION_REQUIRED":
                    raise failure("HOST_COMPILER_INTEGRATION_REQUIRED", stage="compile") from exc
                raise failure("HOST_COMPILER_RESULT_INVALID", stage="compile") from exc

    @staticmethod
    def _validate_host_result(
        host_result: object,
        *,
        idempotency_key: str,
        draft: DraftAgentPlanV1,
        request: CompilationRequestV1,
    ) -> None:
        if type(host_result) is not HostCompilationResultV1:
            raise failure("HOST_COMPILER_RESULT_INVALID", stage="compile")
        if (
            host_result.compiled_plan is not host_result.record.compiled_workflow
            or host_result.record.record_id != f"compilation-record:{idempotency_key}"
            or host_result.record.principal_ref != request.principal_ref
            or host_result.record.session_ref != request.session_ref
            or host_result.record.project_ref != request.project_ref
            or dict(host_result.record.source_commitments)
            != dict(request.source_commitments or {})
            or host_result.record.compiler_version != host_result.compiled_plan.compiler_version
            or host_result.record.contract_snapshot_refs != host_result.compiled_plan.contract_snapshot_refs
            or host_result.record.catalog_snapshot_ref != host_result.compiled_plan.catalog_snapshot_ref
            or host_result.record.policy_snapshot_ref != host_result.compiled_plan.policy_snapshot_ref
            or host_result.record.semantic_plan_hash != draft.semantic_plan_hash
            or host_result.reference.to_dict() != host_result.record.reference.to_dict()
            or host_result.reference.semantic_plan_hash != draft.semantic_plan_hash
        ):
            raise failure("HOST_COMPILER_RESULT_INVALID", stage="compile")

    def server_selection(
        self,
        capability_id: str,
        *,
        scope_ref: str,
        principal_ref: str = "principal:unknown",
        session_ref: str = "session:unknown",
        project_ref: str | None = None,
    ) -> CapabilitySelectionV1:
        """Issue a selection through the server discovery boundary."""

        discovery = CapabilityDiscovery(
            self.manifest,
            authority_resolver=self.authority_resolver,
            authority_handle=self.authority_handle if self.authority_resolver is None else None,
        )
        receipt = discovery.query(
            capability_id,
            scope_ref=scope_ref,
            principal_ref=principal_ref,
            session_ref=session_ref,
            project_ref=project_ref,
        )
        return discovery.resolve(
            capability_id,
            scope_ref=scope_ref,
            principal_ref=principal_ref,
            session_ref=session_ref,
            project_ref=project_ref,
            receipt=receipt,
        )

    def _compile_for_registry(
        self,
        draft: object,
        *,
        intent: AnalysisIntentV1,
        scope_ref: str,
        source_commitments: Mapping[str, Any] | None = None,
    ) -> CompilationResultV1:
        """Internal non-natural-language seam for registry-derived QA only."""

        selection = self.server_selection(
            intent.capability_ids[0],
            scope_ref=scope_ref,
        )
        request = CompilationRequestV1._for_registry(
            draft=draft,
            intent=intent,
            scope_ref=scope_ref,
            source_commitments=source_commitments or {},
        )
        object.__setattr__(request, "selection", selection)
        return self.compile(request)

    def _request(
        self,
        value: object,
        *,
        intent: AnalysisIntentV1 | None,
        scope_ref: str | None,
        principal_ref: str,
        session_ref: str,
        project_ref: str | None,
        source_commitments: Mapping[str, Any] | None,
        selection: CapabilitySelectionV1 | None,
    ) -> CompilationRequestV1:
        if type(value) is CompilationRequestV1:
            if any(item is not None for item in (intent, scope_ref, source_commitments, selection)):
                raise failure("DRAFT_INVALID", stage="compile")
            return value
        if intent is None:
            raise failure("DRAFT_INVALID", stage="compile")
        selected_scope = scope_ref or intent.scope_ref
        return CompilationRequestV1(
            draft=value,
            intent=intent,
            scope_ref=selected_scope,
            principal_ref=principal_ref,
            session_ref=session_ref,
            project_ref=project_ref or selected_scope,
            source_commitments=source_commitments or {},
            selection=selection,
        )

    def _bind_authority(self, request: CompilationRequestV1) -> CompilationRequestV1:
        if self.authority_resolver is None:
            raise failure("FORGED_AUTHORITY", stage="compile")
        try:
            binding = (
                self.authority_resolver.require(request.authority_binding)
                if request.authority_binding is not None
                else self.authority_resolver.resolve(
                    scope_ref=request.scope_ref,
                    principal_ref=request.principal_ref,
                    session_ref=request.session_ref,
                    project_ref=request.project_ref,
                )
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise failure("FORGED_AUTHORITY", stage="compile") from exc
        if (
            request.scope_ref != binding.scope_ref
            or request.principal_ref != binding.principal_ref
            or request.session_ref != binding.session_ref
            or request.project_ref != binding.project_ref
        ):
            raise failure("CROSS_SCOPE", stage="compile")
        bound = CompilationRequestV1(
            draft=request.draft,
            intent=request.intent,
            scope_ref=binding.scope_ref,
            principal_ref=binding.principal_ref,
            session_ref=binding.session_ref,
            project_ref=binding.project_ref,
            source_commitments=request.source_commitments,
            authority_binding=binding,
            selection=request.selection,
        )
        return bound

    def _draft(self, value: object) -> DraftAgentPlanV1:
        if type(value) is CompiledWorkflowV1:
            raise failure("FORGED_AUTHORITY", stage="compile")
        if type(value) is DraftAgentPlanV1:
            raw = value.to_dict()
        elif type(value) is dict:
            raw = value
        else:
            raise failure("DRAFT_TYPE_REQUIRED", stage="compile")
        try:
            _scan(raw)
            encoded = canonical_json_v1(raw).encode("utf-8")
            if len(encoded) > self.max_input_bytes:
                raise failure("INPUT_LIMIT", stage="compile")
            if type(value) is DraftAgentPlanV1:
                return value
            return DraftAgentPlanV1.from_dict(raw)
        except CompilationFailure:
            raise
        except RecursionError as exc:
            raise failure("RECURSIVE_INPUT", stage="compile") from exc
        except (ContractError, PlanningContractError, TypeError, ValueError) as exc:
            raise _map_contract_error(exc) from exc

    def _validate(self, draft: DraftAgentPlanV1, request: CompilationRequestV1) -> None:
        if request.scope_ref != request.intent.scope_ref or request.project_ref != request.scope_ref:
            raise failure("CROSS_SCOPE", stage="compile")
        if self.manifest.manifest_digest != self._registry_manifest_digest:
            raise failure("CONTRACT_DIGEST_MISMATCH", stage="compile")
        if draft.intent_ref != request.intent.intent_ref:
            raise failure("INTENT_MISMATCH", stage="compile")
        if request.intent.contract_digest != self.manifest.manifest_digest:
            raise failure("CONTRACT_DIGEST_MISMATCH", stage="compile")
        if draft.catalog_snapshot_ref != f"catalog:{self.manifest.manifest_digest}":
            raise failure("CONTRACT_DIGEST_MISMATCH", stage="compile")
        commitments = dict(request.source_commitments or {})
        if "dataset" in commitments and commitments["dataset"] != request.intent.source_digest:
            raise failure("SOURCE_DIGEST_MISMATCH", stage="compile")
        _scan(commitments)
        if len(draft.capability_refs) != len({(ref.kind, ref.logical_id, ref.semantic_version) for ref in draft.capability_refs}):
            raise failure("DUPLICATE_IDENTITY", stage="compile")
        entries = []
        for reference in draft.capability_refs:
            try:
                entry = self.manifest.require(reference.logical_id)
            except KeyError as exc:
                raise failure("UNKNOWN_CAPABILITY", stage="compile") from exc
            if reference != entry.capability_ref:
                raise failure("UNKNOWN_CAPABILITY", stage="compile")
            if not entry.natural_language_enabled:
                raise failure("NATURAL_LANGUAGE_DISABLED", stage="compile")
            entries.append(entry)
        self._validate_selection(request, draft)
        if set(request.intent.capability_ids) != {entry.capability_id for entry in entries}:
            raise failure("UNKNOWN_CAPABILITY", stage="compile")
        if request.selection.capability_id not in {entry.capability_id for entry in entries}:
            raise failure("FORGED_AUTHORITY", stage="compile")
        operation_id = draft.method_ref.removeprefix("method:")
        try:
            operation = self.manifest.require(operation_id)
        except KeyError as exc:
            raise failure("UNKNOWN_OPERATION", stage="compile") from exc
        if operation.operation_id != operation_id:
            raise failure("UNKNOWN_OPERATION", stage="compile")
        if any(entry.operation_id != operation_id for entry in entries):
            raise failure("UNKNOWN_OPERATION", stage="compile")
        if operation.contract_ref not in draft.contract_snapshot_refs:
            raise failure("CONTRACT_DIGEST_MISMATCH", stage="compile")
        if not _effect_allowed(draft.effect.value, operation.declared_effect):
            raise failure("SAFETY_POLICY", stage="compile")
        registry_risk = _risk_rank(operation.risk_level)
        draft_risk = _risk_rank(draft.risk_level.value)
        if registry_risk is None or draft_risk is None or draft_risk < registry_risk:
            raise failure("SAFETY_POLICY", stage="compile")
        if draft.policy_snapshot_ref != operation.policy_snapshot_ref:
            raise failure("SAFETY_POLICY", stage="compile")
        if not _budget_within(draft.resource_budget, operation.resource_budget):
            raise failure("SAFETY_POLICY", stage="compile")
        self._validate_ports(draft, operation)
        if operation.confirmation_policy == "required" and not operation.policy_snapshot_ref:
            raise failure("SAFETY_POLICY", stage="compile")

    def _validate_selection(
        self,
        request: CompilationRequestV1,
        draft: DraftAgentPlanV1,
    ) -> None:
        selection = request.selection
        if type(selection) is not CapabilitySelectionV1:
            raise failure("FORGED_AUTHORITY", stage="compile")
        if self.authority_handle is None or request.authority_binding is None:
            raise failure("FORGED_AUTHORITY", stage="compile")
        try:
            CapabilitySelectionV1._require_admitted(selection)
            selection_id = selection._selection_id
            if type(selection_id) is not str or not selection_id.startswith("selection:"):
                raise failure("FORGED_AUTHORITY", stage="compile")
            if selection._authority_handle is not self.authority_handle:
                raise failure("FORGED_AUTHORITY", stage="compile")
            host_selection = self.authority_handle.validate_selection(selection_id)
        except CompilationFailure:
            raise
        except (AttributeError, HostAuthorityChannelError, KeyError, TypeError, ValueError) as exc:
            raise failure("FORGED_AUTHORITY", stage="compile") from exc
        if (
            host_selection.get("capability_id") != selection.capability_id
            or host_selection.get("scope_ref") != selection.scope_ref
            or host_selection.get("manifest_digest") != selection.manifest_digest
            or host_selection.get("receipt_digest") != selection.receipt_digest
            or host_selection.get("binding_id") != request.authority_binding._binding_id
            or selection.manifest_digest != self.manifest.manifest_digest
            or selection.scope_ref != request.scope_ref
            or selection.authority_binding_digest != request.authority_binding.binding_digest
            or selection.capability_id not in request.intent.capability_ids
        ):
            raise failure("FORGED_AUTHORITY", stage="compile")
        try:
            entry = self.manifest.require(selection.capability_id)
        except KeyError as exc:
            raise failure("UNKNOWN_CAPABILITY", stage="compile") from exc
        if not entry.natural_language_enabled:
            raise failure("NATURAL_LANGUAGE_DISABLED", stage="compile")
        if selection.entry.to_dict() != entry.to_dict():
            raise failure("FORGED_AUTHORITY", stage="compile")

    @staticmethod
    def _validate_ports(draft: DraftAgentPlanV1, operation: object) -> None:
        input_ports = tuple(getattr(operation, "input_ports", ()))
        output_ports = tuple(getattr(operation, "output_ports", ()))
        input_refs = tuple(getattr(operation, "input_port_refs", ()))
        output_refs = tuple(getattr(operation, "output_port_refs", ()))
        if len(input_ports) != len(input_refs) or len(output_ports) != len(output_refs):
            raise failure("PORT_TYPE_INVALID", stage="compile")
        inputs = dict(zip(input_refs, input_ports, strict=True))
        outputs = dict(zip(output_refs, output_ports, strict=True))
        for connection in draft.connections:
            if type(connection) is not dict or set(connection) != {"source_port", "target_port"}:
                raise failure("PORT_TYPE_INVALID", stage="compile")
            source = connection.get("source_port")
            target = connection.get("target_port")
            if type(source) is not str or type(target) is not str:
                raise failure("PORT_TYPE_INVALID", stage="compile")
            if source not in outputs:
                if source in inputs:
                    raise failure("PORT_DIRECTION_MISMATCH", stage="compile")
                raise failure("PORT_TYPE_INVALID", stage="compile")
            if target not in inputs:
                if target in outputs:
                    raise failure("PORT_DIRECTION_MISMATCH", stage="compile")
                raise failure("PORT_TYPE_INVALID", stage="compile")
            try:
                outputs[source].require_compatible(inputs[target])
            except PortCompatibilityError as exc:
                raise failure(exc.code, stage="compile") from exc


__all__ = [
    "CompilationRequestV1",
    "CompilationResultV1",
    "PlanCompiler",
]
