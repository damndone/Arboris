"""Host-owned classification/grants and exact provider-payload admission.

Wire dictionaries, API keys and local evidence receipts cannot create this
authority. Administrative methods require the original live host handle.
Admissions are process-local and revocation is checked again at send time.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4
from weakref import WeakKeyDictionary

from ..canonical import sha256_canonical
from ..contracts.common.contract_ref import ContractRefV1
from ..contracts.agent.context_egress import (
    ContextEgressGatewayV1, ContextEgressPolicyV1, ContextEgressReceiptIssuerV1,
    ContextMaterializationStoreV1, SensitivityClassV1, require_context_egress_receipt,
)
from ..evidence.authority import build_authority_request, issue_host_proof, validate_host_proof


class ProviderEgressError(ValueError):
    pass


_CATEGORIES = frozenset({"user_text", "workspace_evidence", "public_contract", "conversation"})


def _text(value):
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise ProviderEgressError("EGRESS_IDENTITY_INVALID")
    return value


def _digest(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ProviderEgressError("EGRESS_SOURCE_DIGEST_INVALID")
    return value


def provider_payload_bytes(payload):
    """Exact transport representation; deliberately does not normalize Unicode."""
    if type(payload) is not dict:
        raise ProviderEgressError("EGRESS_PAYLOAD_INVALID")
    try:
        return json.dumps(payload, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProviderEgressError("EGRESS_PAYLOAD_INVALID") from exc


def _ref(kind, name):
    return ContractRefV1(kind=kind, logical_id=name, semantic_version="1.0",
                        contract_digest=sha256_canonical({"contract": name, "version": 1}))


def _make_provider_egress():
    """Keep host handles and authoritative records inside the C0-style boundary."""
    _LOCK = RLock()
    _AUTHORITIES = WeakKeyDictionary()
    _ADMISSIONS = WeakKeyDictionary()
    _ASSEMBLIES = WeakKeyDictionary()

    def _admin(authority, handle):
        state = _state(authority)
        if handle is not state["handle"]:
            raise ProviderEgressError("EGRESS_ADMIN_AUTHORITY_REQUIRED")
        return state


    def _state(authority):
        with _LOCK:
            state = _AUTHORITIES.get(authority) if type(authority) is ProviderEgressAuthorityV1 else None
        if state is None:
            raise ProviderEgressError("EGRESS_HOST_AUTHORITY_REQUIRED")
        try:
            validate_host_proof(state["handle"], state["request"], state["proof"])
        except Exception as exc:
            raise ProviderEgressError("EGRESS_HOST_AUTHORITY_REQUIRED") from exc
        return state


    def _now(state):
        value = state["clock"]()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ProviderEgressError("EGRESS_CLOCK_INVALID")
        return value.astimezone(UTC)


    def _source_classifications(state, sources):
        """Snapshot source/commit sensitivity, category membership and revision."""
        with _LOCK:
            records = tuple(state["classifications"].get(source[:2]) for source in sources)
            if any(record is None or record[0] is SensitivityClassV1.UNKNOWN or source[2] not in record[1]
                   for source, record in zip(sources, records)):
                raise ProviderEgressError("EGRESS_SOURCE_CLASSIFICATION_REQUIRED")
            return records


    class ProviderRequestAdmissionV1:
        __slots__ = ("__weakref__",)

        def __init__(self):
            raise TypeError("provider admissions are host-issued")


    class TrustedProviderAssemblyV1:
        """Opaque host attestation, not automatic proof of payload provenance."""
        __slots__ = ("__weakref__",)

        def __init__(self):
            raise TypeError("provider assemblies require trusted host assembly")


    class ProviderEgressAuthorityV1:
        __slots__ = ("__weakref__",)

        def __init__(self):
            raise TypeError("provider authority requires live host admission")

        @classmethod
        def from_host(cls, *, authority_handle, scope_ref, project_ref, actor_ref, clock=None):
            if cls is not ProviderEgressAuthorityV1:
                raise ProviderEgressError("EGRESS_HOST_AUTHORITY_REQUIRED")
            identity = {"scope_ref": _text(scope_ref), "project_ref": _text(project_ref),
                        "actor_ref": _text(actor_ref)}
            result = object.__new__(cls)
            try:
                request = build_authority_request(authority_handle, purpose="evidence.provider.egress",
                    scope_ref=scope_ref, subject_id=id(result), payload_digest=sha256_canonical(identity))
                proof = issue_host_proof(authority_handle, request)
                validate_host_proof(authority_handle, request, proof)
            except Exception as exc:
                raise ProviderEgressError("EGRESS_HOST_AUTHORITY_REQUIRED") from exc
            with _LOCK:
                _AUTHORITIES[result] = dict(identity, handle=authority_handle, request=request, proof=proof,
                    clock=clock or (lambda: datetime.now(UTC)), classifications={}, grants={},
                    materializer=ContextMaterializationStoreV1(
                        materializer_ref=_ref("policy", "provider-host-materializer.v1"),
                        redaction_policy_ref=_ref("policy", "provider-host-explicit-selection.v1")))
            return result

        def classify(self, *, authority_handle, source_ref, source_digest, category, sensitivity):
            state = _admin(self, authority_handle)
            if category not in _CATEGORIES:
                raise ProviderEgressError("EGRESS_CATEGORY_INVALID")
            try:
                level = SensitivityClassV1(sensitivity)
            except (ValueError, TypeError) as exc:
                raise ProviderEgressError("EGRESS_SENSITIVITY_INVALID") from exc
            with _LOCK:
                identity = (_text(source_ref), _digest(source_digest))
                previous = state["classifications"].get(identity)
                categories = (previous[1] if previous else frozenset()) | {category}
                revision = previous[2] + 1 if previous else 1
                # Sensitivity belongs to the source/commit, never to a selectable
                # category. Every admin reclassification invalidates old snapshots,
                # even if a later call restores the previous sensitivity.
                state["classifications"][identity] = (level, categories, revision)

        def grant(self, *, authority_handle, provider_ref, purpose_ref, categories,
                  allowed_sensitivity, expires_at, max_bytes=32768, max_rows=64, timeout_ms=90000,
                  max_materialization_bytes=32768, max_materialization_tokens=8192):
            """Grant independent raw transport, admitted-row and materialization caps.

            Materialization includes base64 and all metadata. C0 token accounting
            conservatively charges one unit per serialized UTF-8 byte, NOT bytes/4
            and NOT a provider-specific tokenizer measurement. Ceilings are explicit
            host policy; none grow automatically to fit the request.
            """
            state = _admin(self, authority_handle)
            if (not isinstance(expires_at, datetime) or expires_at.tzinfo is None
                    or expires_at <= _now(state)):
                raise ProviderEgressError("EGRESS_GRANT_EXPIRY_INVALID")
            if (type(categories) is not tuple or not categories or len(set(categories)) != len(categories)
                    or any(c not in _CATEGORIES for c in categories)):
                raise ProviderEgressError("EGRESS_CATEGORY_INVALID")
            try:
                levels = tuple(SensitivityClassV1(v) for v in allowed_sensitivity)
            except (ValueError, TypeError) as exc:
                raise ProviderEgressError("EGRESS_SENSITIVITY_INVALID") from exc
            if not levels or SensitivityClassV1.UNKNOWN in levels:
                raise ProviderEgressError("EGRESS_SENSITIVITY_INVALID")
            if any(type(v) is not int or not 0 < v <= (1 << 53) - 1 for v in
                   (max_bytes, max_rows, timeout_ms, max_materialization_bytes, max_materialization_tokens)):
                raise ProviderEgressError("EGRESS_BUDGET_INVALID")
            grant_id = "grant:" + uuid4().hex
            with _LOCK:
                state["grants"][grant_id] = (_text(provider_ref), _text(purpose_ref), categories,
                    levels, expires_at.astimezone(UTC), max_bytes, max_rows, timeout_ms,
                    max_materialization_bytes, max_materialization_tokens)
            return grant_id

        def revoke(self, *, authority_handle, grant_id):
            state = _admin(self, authority_handle)
            with _LOCK:
                state["grants"].pop(grant_id, None)

        def close(self):
            with _LOCK:
                _AUTHORITIES.pop(self, None)

        def mint_trusted_assembly(self, *, authority_handle, project_ref, payload, sources, admitted_rows):
            """TRUSTED ASSEMBLY BOUNDARY: attest exact bytes and their source association.

            Only the original live admin handle may call this method. The host must
            resolve ALL sources (including historical messages/tool results), assemble
            the payload and determine actual admitted data-row usage beforehand. This
            primitive does NOT resolve sources, prove provenance, or count arbitrary
            payload rows. Never forward model/wire assertions into this admin call.
            Zero rows means no admitted data rows, not zero source references.
            """
            state = _admin(self, authority_handle)
            if project_ref != state["project_ref"]:
                raise ProviderEgressError("EGRESS_SCOPE_MISMATCH")
            if type(admitted_rows) is not int or admitted_rows < 0:
                raise ProviderEgressError("EGRESS_ROW_USAGE_INVALID")
            if type(sources) is not tuple or not sources:
                raise ProviderEgressError("EGRESS_SOURCE_CLASSIFICATION_REQUIRED")
            for source in sources:
                if type(source) is not tuple or len(source) != 3:
                    raise ProviderEgressError("EGRESS_SOURCE_CLASSIFICATION_REQUIRED")
                _text(source[0]); _digest(source[1])
                if source[2] not in _CATEGORIES:
                    raise ProviderEgressError("EGRESS_CATEGORY_INVALID")
            raw = provider_payload_bytes(payload)
            with _LOCK:
                classifications = _source_classifications(state, sources)
                assembly = object.__new__(TrustedProviderAssemblyV1)
                _ASSEMBLIES[assembly] = dict(authority=self, project_ref=project_ref, raw=raw,
                    sources=sources, classifications=classifications, admitted_rows=admitted_rows)
            return assembly

        def prepare(self, *, project_ref, provider_ref, purpose_ref, assembly):
            state = _state(self)
            if project_ref != state["project_ref"]:
                raise ProviderEgressError("EGRESS_SCOPE_MISMATCH")
            with _LOCK:
                assembled = _ASSEMBLIES.get(assembly) if type(assembly) is TrustedProviderAssemblyV1 else None
            if assembled is None:
                raise ProviderEgressError("EGRESS_ASSEMBLY_REQUIRED")
            if assembled["authority"] is not self or assembled["project_ref"] != project_ref:
                raise ProviderEgressError("EGRESS_SCOPE_MISMATCH")
            raw, sources = assembled["raw"], assembled["sources"]
            admitted_rows = assembled["admitted_rows"]
            with _LOCK:
                candidates = [(key, value) for key, value in state["grants"].items()
                    if value[0] == provider_ref and value[1] == purpose_ref and value[4] > _now(state)
                    and {s[2] for s in sources}.issubset(value[2])]
            if not candidates:
                raise ProviderEgressError("EGRESS_GRANT_REQUIRED")
            classifications = _source_classifications(state, sources)
            if classifications != assembled["classifications"]:
                raise ProviderEgressError("EGRESS_SOURCE_CLASSIFICATION_REQUIRED")
            levels = tuple(record[0] for record in classifications)
            candidates = [(key, grant) for key, grant in candidates if set(levels).issubset(grant[3])]
            if not candidates:
                raise ProviderEgressError("EGRESS_SENSITIVITY_DENIED")
            candidates = [(key, grant) for key, grant in candidates
                          if len(raw) <= grant[5] and admitted_rows <= grant[6]]
            if not candidates:
                raise ProviderEgressError("EGRESS_BUDGET_EXCEEDED")
            for grant_id, grant in candidates:
                context = {"source:provider-request": {"wire_sha256": hashlib.sha256(raw).hexdigest(),
                    "wire_utf8_base64": "",
                    "project_ref": project_ref, "provider_ref": provider_ref, "purpose_ref": purpose_ref,
                    "grant_id": grant_id, "sources": [list(source) for source in sources],
                    "admitted_rows": admitted_rows}}
                # Standard base64 is ASCII with no JSON escaping. Bound the exact
                # expanded representation BEFORE allocating it or invoking C0.
                materialization_bytes = len(provider_payload_bytes(context)) + 4 * ((len(raw) + 2) // 3)
                materialization_tokens = materialization_bytes
                if materialization_bytes <= grant[8] and materialization_tokens <= grant[9]:
                    break
            else:
                raise ProviderEgressError("EGRESS_BUDGET_EXCEEDED")
            context["source:provider-request"]["wire_utf8_base64"] = base64.b64encode(raw).decode("ascii")
            admission = object.__new__(ProviderRequestAdmissionV1)
            with _LOCK:
                _ADMISSIONS[admission] = dict(authority=self, grant_id=grant_id, grant=grant,
                    raw=raw, context=context, sources=sources, levels=levels, gateway=None,
                    classifications=classifications, receipt=None, issuer=None)
            # This authority owns one C0 store. Reserve/write its snapshot and
            # issue the matching receipt atomically: C0 reference allocation is
            # not itself a concurrent reservation. Reentrant admission checks
            # inside materialization use this same lock.
            with _LOCK:
                materialized = state["materializer"].materialize_provider_request(admission)
                level = materialized.observed_sensitivity
                policy = ContextEgressPolicyV1(policy_ref=_ref("policy", "provider-explicit-host-grant.v1"),
                    destination="remote", provider_ref=provider_ref, allowed_sensitivity=grant[3],
                    max_token_budget=grant[9],
                    max_row_budget=grant[6], max_time_budget_ms=grant[7])
                issuer = ContextEgressReceiptIssuerV1(policy, materializer_store=state["materializer"], clock=state["clock"])
                gateway = ContextEgressGatewayV1.from_materialization_result(materialized,
                    request_id="provider-request:" + uuid4().hex, destination="remote", provider_ref=provider_ref,
                    sensitivity_policy_ref=policy.policy_ref, sensitivity=level,
                    # C0 budgets are positive ceilings, not measured usage. Exact (possibly
                    # zero) admitted_rows is bound in context and checked against this cap.
                    token_budget=materialization_tokens, row_budget=grant[6], time_budget_ms=grant[7],
                    purpose_ref=purpose_ref, requested_at=_now(state).isoformat(), expires_at=grant[4].isoformat())
                receipt = issuer.issue(gateway)
                _ADMISSIONS[admission].update(gateway=gateway, receipt=receipt, issuer=issuer)
            return admission

        def require(self, admission, *, payload, project_ref, provider_ref, purpose_ref):
            record, state = _validated_admission(admission)
            if record["authority"] is not self:
                raise ProviderEgressError("EGRESS_SCOPE_MISMATCH")
            _require_body(record, state, body=provider_payload_bytes(payload),
                project_ref=project_ref, provider_ref=provider_ref, purpose_ref=purpose_ref)


    def _validated_admission(admission):
        with _LOCK:
            record = _ADMISSIONS.get(admission) if type(admission) is ProviderRequestAdmissionV1 else None
        if record is None:
            raise ProviderEgressError("EGRESS_ADMISSION_REQUIRED")
        state = _state(record["authority"])
        if (state["grants"].get(record["grant_id"]) != record["grant"]
                or _now(state) >= record["grant"][4]):
            raise ProviderEgressError("EGRESS_GRANT_REQUIRED")
        classifications = _source_classifications(state, record["sources"])
        if classifications != record["classifications"]:
            raise ProviderEgressError("EGRESS_SOURCE_CLASSIFICATION_REQUIRED")
        return record, state


    def validate_provider_request_admission(admission):
        """Materializer-only validation; returned values cannot grant authority."""
        record, _ = _validated_admission(admission)
        rank = {SensitivityClassV1.PUBLIC: 0, SensitivityClassV1.INTERNAL: 1,
                SensitivityClassV1.RESTRICTED: 2}
        # Return a defensive copy: callers cannot mutate the admission snapshot.
        return json.loads(json.dumps(record["context"])), max(record["levels"], key=rank.__getitem__)


    def _require_body(record, state, *, body, project_ref, provider_ref, purpose_ref):
        if project_ref != state["project_ref"] or (provider_ref, purpose_ref) != record["grant"][:2]:
            raise ProviderEgressError("EGRESS_SCOPE_MISMATCH")
        if type(body) is not bytes or body != record["raw"]:
            raise ProviderEgressError("EGRESS_PAYLOAD_MISMATCH")
        try:
            require_context_egress_receipt(record["gateway"], record["receipt"], issuer=record["issuer"])
            # Compare the ACTUAL bytes against the C0-issued immutable snapshot,
            # not merely a mutable backing record with an otherwise valid receipt.
            snapshot = record["issuer"].materializer_store.resolve(
                record["gateway"].materialization_result_ref).materialized_context["source:provider-request"]
            if (snapshot["wire_sha256"] != hashlib.sha256(body).hexdigest()
                    or snapshot["wire_utf8_base64"] != base64.b64encode(body).decode("ascii")
                    or snapshot["project_ref"] != project_ref
                    or snapshot["provider_ref"] != provider_ref
                    or snapshot["purpose_ref"] != purpose_ref
                    or snapshot["grant_id"] != record["grant_id"]):
                raise ProviderEgressError("EGRESS_RECEIPT_REQUIRED")
        except Exception as exc:
            raise ProviderEgressError("EGRESS_RECEIPT_REQUIRED") from exc


    def require_provider_send(admission, *, body, project_ref, provider_ref, purpose_ref):
        """Validate exact bytes and return the remaining bounded send lease.

        The returned duration is a transport limit, not an authority capability.
        Callers must revalidate at dispatch after any awaited client acquisition.
        """
        record, state = _validated_admission(admission)
        _require_body(record, state, body=body, project_ref=project_ref,
            provider_ref=provider_ref, purpose_ref=purpose_ref)
        remaining = (record["grant"][4] - _now(state)).total_seconds()
        if remaining <= 0:
            raise ProviderEgressError("EGRESS_GRANT_REQUIRED")
        return min(record["grant"][7] / 1000, remaining)

    return (ProviderEgressAuthorityV1, ProviderRequestAdmissionV1,
            TrustedProviderAssemblyV1, validate_provider_request_admission,
            require_provider_send)


(ProviderEgressAuthorityV1, ProviderRequestAdmissionV1, TrustedProviderAssemblyV1,
 validate_provider_request_admission, require_provider_send) = _make_provider_egress()
del _make_provider_egress
