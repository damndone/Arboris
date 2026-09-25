from datetime import UTC, datetime, timedelta
import base64
import inspect

import pytest

try:
    from workbench.services import provider_egress as api
except ImportError:
    api = None
from tests.test_v189_evidence_envelope import _authorized_registry


@pytest.fixture
def host():
    assert api is not None, "host-owned provider egress authority is not implemented"
    _, channel = _authorized_registry("scope:project:egress")
    now = [datetime(2026, 9, 18, tzinfo=UTC)]
    authority = api.ProviderEgressAuthorityV1.from_host(
        authority_handle=channel.channel, scope_ref="scope:project:egress",
        project_ref="project:egress", actor_ref="principal:local:operator", clock=lambda: now[0],
    )
    yield authority, channel.channel, now
    authority.close()


def _grant(host, **changes):
    authority, handle, now = host
    arguments = dict(authority_handle=handle, provider_ref="provider:example",
        purpose_ref="purpose:analysis", categories=("user_text",),
        allowed_sensitivity=("public",), expires_at=now[0] + timedelta(minutes=5))
    return authority.grant(**(arguments | changes))


SOURCES = (("message:1", "a" * 64, "user_text"),)
SCOPE = dict(project_ref="project:egress", provider_ref="provider:example", purpose_ref="purpose:analysis")


def test_authority_does_not_export_mutable_records_or_admin_capability(host):
    authority, _, _ = host
    # Match C0's closure-owned state boundary: a holder of the consumer
    # capability must not recover host administration or edit admitted bytes.
    for name in ("_state", "_validated_admission", "_AUTHORITIES", "_ADMISSIONS", "_ASSEMBLIES"):
        assert not hasattr(api, name), f"authority backing state is exported: {name}"
    assert not hasattr(authority, "_admin")


def test_final_send_requires_exact_receipt_bound_bytes(host):
    _classify(host)
    _grant(host)
    admission = _prepare(host)
    check = getattr(api, "require_provider_send", None)
    assert callable(check), "final serialized body validation is missing"
    raw = api.provider_payload_bytes(_payload())
    check(admission, body=raw, **SCOPE)
    for bad in (raw + b" ", raw.replace(b"hello", b"other"), bytearray(raw), raw.decode("utf-8")):
        with pytest.raises(api.ProviderEgressError, match="EGRESS_PAYLOAD_MISMATCH"):
            check(admission, body=bad, **SCOPE)


def test_concurrent_admissions_keep_distinct_receipt_snapshots(host, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, BrokenBarrierError
    from workbench.contracts.agent import context_egress as c0

    _classify(host)
    _grant(host)
    payloads = [_payload(), {"messages": [{"role": "user", "content": "second synthetic request"}]}]
    assemblies = [_mint(host, payload=payload) for payload in payloads]
    rendezvous = Barrier(2)
    encode = c0.canonical_json_v1

    def delay_after_reference_allocation(value, *args, **kwargs):
        if isinstance(value, dict) and value.get("schema_version") == c0.MATERIALIZATION_SCHEMA_V1:
            # Before the fix both threads have already selected reference 1.
            # With atomic issuance the first bounded wait expires; the second
            # can then allocate its own reference without blocking the test.
            try:
                rendezvous.wait(timeout=0.2)
            except BrokenBarrierError:
                pass
        return encode(value, *args, **kwargs)

    monkeypatch.setattr(c0, "canonical_json_v1", delay_after_reference_allocation)
    authority, _, _ = host
    with ThreadPoolExecutor(max_workers=2) as pool:
        admissions = list(pool.map(lambda assembly: authority.prepare(assembly=assembly, **SCOPE), assemblies))
    for admission, payload in zip(admissions, payloads):
        api.require_provider_send(admission, body=api.provider_payload_bytes(payload), **SCOPE)


def _payload():
    return {"messages": [{"role": "user", "content": "hello e\u0301"}]}


def _classify(host, *, category="user_text", sensitivity="public", digest="a" * 64):
    authority, handle, _ = host
    authority.classify(authority_handle=handle, source_ref="message:1", source_digest=digest,
                       category=category, sensitivity=sensitivity)


def _mint(host, **changes):
    authority, handle, _ = host
    mint = getattr(authority, "mint_trusted_assembly", None)
    assert callable(mint), "exact payload/source association must be minted by trusted host assembly"
    arguments = dict(authority_handle=handle, project_ref="project:egress", payload=_payload(),
                     sources=SOURCES, admitted_rows=0)
    return mint(**(arguments | changes))


def _prepare(host, **changes):
    authority, _, _ = host
    return authority.prepare(**(SCOPE | dict(assembly=_mint(host)) | changes))


def test_missing_host_and_missing_grant_do_not_mint_admission(host):
    with pytest.raises(api.ProviderEgressError):
        api.ProviderEgressAuthorityV1.from_host(authority_handle=object(), scope_ref="scope:project:egress",
            project_ref="project:egress", actor_ref="principal:local:operator")
    _classify(host)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_GRANT_REQUIRED"):
        _prepare(host)


def test_unknown_classification_is_not_public_even_with_grant(host):
    _grant(host)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SOURCE_CLASSIFICATION_REQUIRED"):
        _prepare(host)


def test_real_host_grant_exact_payload_and_revocation(host):
    authority, handle, _ = host
    grant = _grant(host)
    authority.classify(authority_handle=handle, source_ref="message:1", source_digest="a" * 64,
                       category="user_text", sensitivity="public")
    admission = _prepare(host)
    payload = {"messages": [{"role": "user", "content": "hello e\u0301"}]}
    authority.require(admission, payload=payload, provider_ref="provider:example",
                      project_ref="project:egress", purpose_ref="purpose:analysis")
    with pytest.raises(api.ProviderEgressError, match="EGRESS_PAYLOAD_MISMATCH"):
        authority.require(admission, payload={"messages": [{"role": "user", "content": "hello é"}]},
            provider_ref="provider:example", project_ref="project:egress", purpose_ref="purpose:analysis")
    authority.revoke(authority_handle=handle, grant_id=grant)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_GRANT_REQUIRED"):
        authority.require(admission, payload=payload, provider_ref="provider:example",
                          project_ref="project:egress", purpose_ref="purpose:analysis")


def test_expired_grant_and_forged_admission_fail(host):
    authority, handle, now = host
    _grant(host)
    authority.classify(authority_handle=handle, source_ref="message:1", source_digest="a" * 64,
                       category="user_text", sensitivity="public")
    admission = _prepare(host)
    now[0] += timedelta(minutes=5)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_GRANT_REQUIRED"):
        authority.require(admission, payload=_payload(), **SCOPE)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_GRANT_REQUIRED"):
        _prepare(host)
    with pytest.raises(api.ProviderEgressError):
        authority.require(object(), payload={}, provider_ref="provider:example",
                          project_ref="project:egress", purpose_ref="purpose:analysis")


def test_foreign_scope_and_admin_handle_reject(host):
    authority, _, _ = host
    with pytest.raises(api.ProviderEgressError):
        authority.classify(authority_handle=object(), source_ref="message:1", source_digest="a" * 64,
                           category="user_text", sensitivity="public")
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SCOPE_MISMATCH"):
        authority.prepare(project_ref="project:foreign", provider_ref="provider:example",
                          purpose_ref="purpose:analysis", assembly=None)


def test_raw_source_tuple_cannot_claim_unrelated_payload(host):
    authority, _, _ = host
    _grant(host)
    _classify(host)
    with pytest.raises((TypeError, api.ProviderEgressError)):
        authority.prepare(**SCOPE, payload={"private": "unrelated historical tool result"}, sources=SOURCES)


def test_trusted_assembly_requires_original_live_admin_handle(host):
    _classify(host)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_ADMIN_AUTHORITY_REQUIRED"):
        _mint(host, authority_handle=object())
    host[0].close()
    with pytest.raises(api.ProviderEgressError, match="EGRESS_HOST_AUTHORITY_REQUIRED"):
        _mint(host)


def test_forged_assembly_is_not_an_admission(host):
    authority, _, _ = host
    _grant(host)
    _classify(host)
    assembly = _mint(host)
    for forged in (None, {"payload": _payload(), "sources": SOURCES, "admitted_rows": 0},
                   object.__new__(type(assembly))):
        with pytest.raises(api.ProviderEgressError, match="EGRESS_ASSEMBLY_REQUIRED"):
            authority.prepare(**SCOPE, assembly=forged)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_ADMISSION_REQUIRED"):
        authority.require(assembly, **SCOPE, payload=_payload())


def test_assembly_binds_exact_bytes_and_defensively_snapshots_payload(host):
    authority, _, _ = host
    _grant(host)
    _classify(host)
    payload = _payload()
    assembly = _mint(host, payload=payload)
    payload["messages"][0]["content"] = "unrelated replacement"
    admission = authority.prepare(**SCOPE, assembly=assembly)
    authority.require(admission, **SCOPE, payload=_payload())
    for changed in (payload, {"messages": [{"role": "user", "content": "hello é"}]}):
        with pytest.raises(api.ProviderEgressError, match="EGRESS_PAYLOAD_MISMATCH"):
            authority.require(admission, **SCOPE, payload=changed)
    context, _ = api.validate_provider_request_admission(admission)
    context["source:provider-request"]["wire_utf8_base64"] = "tampered"
    authority.require(admission, **SCOPE, payload=_payload())


def test_assembly_cannot_cross_authority_or_project(host):
    authority, handle, now = host
    _classify(host)
    assembly = _mint(host)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SCOPE_MISMATCH"):
        _mint(host, project_ref="project:foreign")
    other = api.ProviderEgressAuthorityV1.from_host(authority_handle=handle,
        scope_ref="scope:project:egress", project_ref="project:egress",
        actor_ref="principal:local:operator", clock=lambda: now[0])
    try:
        with pytest.raises(api.ProviderEgressError, match="EGRESS_SCOPE_MISMATCH"):
            other.prepare(**SCOPE, assembly=assembly)
    finally:
        other.close()


@pytest.mark.parametrize("rows", [-1, True, 1.5, "1"])
def test_assembly_rejects_invalid_admitted_rows(host, rows):
    _classify(host)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_ROW_USAGE_INVALID"):
        _mint(host, admitted_rows=rows)


def test_actual_admitted_rows_not_source_count_bound_grant(host):
    authority, _, _ = host
    _classify(host)
    payload = {"rows": list(range(100))}
    assembly = _mint(host, payload=payload, admitted_rows=100)
    _grant(host, max_rows=1)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_BUDGET_EXCEEDED"):
        authority.prepare(**SCOPE, assembly=assembly)
    _grant(host, max_rows=100)
    admission = authority.prepare(**SCOPE, assembly=assembly)
    authority.require(admission, **SCOPE, payload=payload)
    context, _ = api.validate_provider_request_admission(admission)
    assert context["source:provider-request"]["admitted_rows"] == 100


@pytest.mark.parametrize("category", ["user_text", "conversation"])
def test_identity_reclassification_invalidates_assembly_and_receipt(host, category):
    authority, _, _ = host
    _grant(host, allowed_sensitivity=("public", "restricted"))
    _classify(host)
    assembly = _mint(host)
    admission = authority.prepare(**SCOPE, assembly=assembly)
    _classify(host, category=category, sensitivity="restricted")
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SOURCE_CLASSIFICATION_REQUIRED"):
        authority.require(admission, **SCOPE, payload=_payload())
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SOURCE_CLASSIFICATION_REQUIRED"):
        authority.prepare(**SCOPE, assembly=assembly)
    # Restoring a sensitivity must not resurrect previously invalidated objects.
    _classify(host, category=category, sensitivity="public")
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SOURCE_CLASSIFICATION_REQUIRED"):
        authority.require(admission, **SCOPE, payload=_payload())
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SOURCE_CLASSIFICATION_REQUIRED"):
        authority.prepare(**SCOPE, assembly=assembly)
    fresh = _prepare(host)
    authority.require(fresh, **SCOPE, payload=_payload())


def test_category_cannot_select_weaker_sensitivity_for_same_identity(host):
    authority, _, _ = host
    _classify(host)
    _classify(host, category="conversation", sensitivity="restricted")
    _grant(host)
    assembly = _mint(host)  # user_text is a valid member, but sensitivity is now restricted.
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SENSITIVITY_DENIED"):
        authority.prepare(**SCOPE, assembly=assembly)
    _grant(host, allowed_sensitivity=("restricted",))
    admission = authority.prepare(**SCOPE, assembly=assembly)
    _, sensitivity = api.validate_provider_request_admission(admission)
    assert sensitivity.value == "restricted"
    authority.require(admission, **SCOPE, payload=_payload())


@pytest.mark.parametrize("sources", [
    (("message:1", "a" * 64, "conversation"),),
    (("message:1", "b" * 64, "user_text"),),
    (("message:foreign", "a" * 64, "user_text"),),
])
def test_assembly_requires_registered_category_and_exact_source_identity(host, sources):
    _classify(host)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SOURCE_CLASSIFICATION_REQUIRED"):
        _mint(host, sources=sources)


def test_explicit_unknown_reclassification_denies_old_and_new_assembly(host):
    authority, _, _ = host
    _classify(host)
    _grant(host)
    admission = _prepare(host)
    _classify(host, category="conversation", sensitivity="unknown")
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SOURCE_CLASSIFICATION_REQUIRED"):
        authority.require(admission, **SCOPE, payload=_payload())
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SOURCE_CLASSIFICATION_REQUIRED"):
        _mint(host)


def test_historical_digest_keeps_its_own_classification(host):
    authority, _, _ = host
    _classify(host)
    _grant(host)
    admission = _prepare(host)
    _classify(host, digest="b" * 64, sensitivity="restricted")
    authority.require(admission, **SCOPE, payload=_payload())


def _bounded_grant(host, **changes):
    parameters = inspect.signature(host[0].grant).parameters
    assert "max_materialization_bytes" in parameters, "materialization needs its own fixed byte ceiling"
    assert "max_materialization_tokens" in parameters, "materialization needs its own fixed token ceiling"
    return _grant(host, **changes)


def test_grant_defaults_are_fixed_and_not_enlarged(host):
    parameters = inspect.signature(host[0].grant).parameters
    for name, expected in (("max_bytes", 32768), ("max_rows", 64), ("timeout_ms", 90000),
                           ("max_materialization_bytes", 32768), ("max_materialization_tokens", 8192)):
        assert name in parameters, f"missing independent grant bound: {name}"
        assert parameters[name].default == expected


def test_materialization_budget_counts_base64_and_metadata(host):
    authority, _, _ = host
    _classify(host)
    payload = {"messages": [{"role": "user", "content": "x" * 1000}]}
    raw = api.provider_payload_bytes(payload)
    assembly = _mint(host, payload=payload)
    _bounded_grant(host, max_bytes=len(raw), max_materialization_bytes=len(raw),
                   max_materialization_tokens=10000)
    # Raw bytes fit exactly; base64 plus the admitted source/row/scope envelope do not.
    with pytest.raises(api.ProviderEgressError, match="EGRESS_BUDGET_EXCEEDED"):
        authority.prepare(**SCOPE, assembly=assembly)
    _bounded_grant(host, max_bytes=len(raw), max_materialization_bytes=10000,
                   max_materialization_tokens=10000)
    admission = authority.prepare(**SCOPE, assembly=assembly)
    context, _ = api.validate_provider_request_admission(admission)
    assert len(api.provider_payload_bytes(context)) > len(raw)
    assert base64.b64decode(context["source:provider-request"]["wire_utf8_base64"]) == raw
    authority.require(admission, **SCOPE, payload=payload)


@pytest.mark.parametrize("bound", ["max_materialization_bytes", "max_materialization_tokens"])
def test_materialization_exact_budget_boundary(host, bound):
    authority, handle, _ = host
    _classify(host)
    assembly = _mint(host)
    generous = _bounded_grant(host, max_materialization_bytes=10000, max_materialization_tokens=10000)
    admission = authority.prepare(**SCOPE, assembly=assembly)
    context, _ = api.validate_provider_request_admission(admission)
    # C0 accounting deliberately charges one token unit per UTF-8 byte, not a
    # provider-specific tokenizer measurement or the unsafe bytes/4 estimate.
    usage = len(api.provider_payload_bytes(context))
    authority.revoke(authority_handle=handle, grant_id=generous)
    _bounded_grant(host, **{bound: usage - 1})
    with pytest.raises(api.ProviderEgressError, match="EGRESS_BUDGET_EXCEEDED"):
        authority.prepare(**SCOPE, assembly=assembly)
    _bounded_grant(host, **{bound: usage})
    exact = authority.prepare(**SCOPE, assembly=assembly)
    authority.require(exact, **SCOPE, payload=_payload())


def test_outgoing_raw_byte_limit_remains_independent(host):
    authority, _, _ = host
    _classify(host)
    assembly = _mint(host)
    _grant(host, max_bytes=len(api.provider_payload_bytes(_payload())) - 1)
    with pytest.raises(api.ProviderEgressError, match="EGRESS_BUDGET_EXCEEDED"):
        authority.prepare(**SCOPE, assembly=assembly)
    _grant(host, max_bytes=len(api.provider_payload_bytes(_payload())))
    authority.require(authority.prepare(**SCOPE, assembly=assembly), **SCOPE, payload=_payload())


@pytest.mark.parametrize("bound", ["max_materialization_bytes", "max_materialization_tokens"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_materialization_limits_require_positive_integers(host, bound, value):
    with pytest.raises(api.ProviderEgressError, match="EGRESS_BUDGET_INVALID"):
        _bounded_grant(host, **{bound: value})


def test_new_materialization_ceiling_does_not_expand_with_payload(host):
    authority, _, _ = host
    _classify(host)
    payload = {"content": "x" * 25000}
    assembly = _mint(host, payload=payload)
    _grant(host)  # Fits the unchanged raw 32768-byte ceiling, not encoded defaults.
    with pytest.raises(api.ProviderEgressError, match="EGRESS_BUDGET_EXCEEDED"):
        authority.prepare(**SCOPE, assembly=assembly)


@pytest.mark.parametrize("field,value", [
    ("project_ref", "project:foreign"),
    ("provider_ref", "provider:foreign"),
    ("purpose_ref", "purpose:foreign"),
])
def test_actual_send_scope_must_match_admission(host, field, value):
    authority, _, _ = host
    _classify(host)
    _grant(host)
    admission = _prepare(host)
    authority.require(admission, **SCOPE, payload=_payload())
    with pytest.raises(api.ProviderEgressError, match="EGRESS_SCOPE_MISMATCH"):
        authority.require(admission, **(SCOPE | {field: value}), payload=_payload())


def test_grant_category_does_not_expand_to_other_registered_membership(host):
    authority, _, _ = host
    _classify(host)
    _classify(host, category="conversation")
    _grant(host)
    assembly = _mint(host, sources=(("message:1", "a" * 64, "conversation"),))
    with pytest.raises(api.ProviderEgressError, match="EGRESS_GRANT_REQUIRED"):
        authority.prepare(**SCOPE, assembly=assembly)
    _grant(host, categories=("conversation",))
    admission = authority.prepare(**SCOPE, assembly=assembly)
    authority.require(admission, **SCOPE, payload=_payload())
