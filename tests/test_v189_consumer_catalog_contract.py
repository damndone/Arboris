from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest


def _ref(kind: str, logical_id: str):
    from workbench.contracts.common.contract_ref import ContractRefV1

    return ContractRefV1(
        kind=kind,
        logical_id=logical_id,
        semantic_version="1.0",
        contract_digest=(kind + logical_id).encode().hex().ljust(64, "0")[:64],
    )


def _declaration(**overrides):
    from workbench.contracts.common.provider import ConsumerProjectionDeclarationV1

    values = {
        "path_id": "future.path",
        "consumer_id": "agent",
        "projection_ref": _ref("projection", "future.projection"),
        "evidence_contract_refs": (_ref("evidence", "future.evidence"),),
        "envelope_contract_refs": (),
        "fact_kinds": ("numeric_fact",),
        "policy_ref": _ref("policy", "future.policy"),
        "renderer_ref": _ref("renderer", "future.renderer"),
        "max_token_budget": 100,
        "max_row_budget": 4,
        "allowed_sensitivity": ("public", "internal"),
        "ordering": ("fact_id",),
        "coverage_status": "required",
        "exemption_reason": None,
    }
    values.update(overrides)
    return ConsumerProjectionDeclarationV1(**values)


def test_declaration_is_immutable_and_serializes_all_consumer_policy() -> None:
    declaration = _declaration()

    assert declaration.coverage_status == "required"
    assert declaration.to_dict() == {
        "path_id": "future.path",
        "consumer_id": "agent",
        "projection_ref": declaration.projection_ref.to_dict(),
        "evidence_contract_refs": [ref.to_dict() for ref in declaration.evidence_contract_refs],
        "envelope_contract_refs": [],
        "fact_kinds": ["numeric_fact"],
        "policy_ref": declaration.policy_ref.to_dict(),
        "renderer_ref": declaration.renderer_ref.to_dict(),
        "max_token_budget": 100,
        "max_row_budget": 4,
        "allowed_sensitivity": ["public", "internal"],
        "ordering": ["fact_id"],
        "coverage_status": "required",
        "exemption_reason": None,
    }
    with pytest.raises(AttributeError):
        declaration.consumer_id = "report"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("fact_kinds", (), "fact_kinds"),
        ("max_token_budget", 0, "max_token_budget"),
        ("max_row_budget", 0, "max_row_budget"),
        ("coverage_status", "unknown", "coverage_status"),
        ("exemption_reason", None, "exemption_reason"),
    ],
)
def test_declaration_rejects_incomplete_policy_fields(field, value, message) -> None:
    if field == "exemption_reason":
        with pytest.raises(ValueError, match=message):
            _declaration(coverage_status="exempt", exemption_reason=value)
        return
    with pytest.raises(ValueError, match=message):
        _declaration(**{field: value})


def test_exempt_declaration_requires_a_human_readable_reason() -> None:
    with pytest.raises(ValueError, match="exemption_reason"):
        _declaration(coverage_status="exempt", exemption_reason=None)

    declaration = _declaration(
        coverage_status="exempt",
        exemption_reason="provider has no consumer-safe projection by design",
    )
    assert declaration.coverage_status == "exempt"


def test_builtin_catalog_has_path_bound_consumer_declarations() -> None:
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    assert len(catalog.providers) == 8
    for provider in catalog.providers:
        path_by_id = {path.path_id: path for path in provider.exposure_paths}
        declarations = provider.projection_declarations
        assert len({(item.path_id, item.consumer_id) for item in declarations}) == len(declarations)
        for declaration in declarations:
            path = path_by_id[declaration.path_id]
            assert path.projection_refs[declaration.consumer_id] == declaration.projection_ref
            assert declaration.policy_ref in provider.policy_refs
            assert declaration.renderer_ref in provider.renderer_refs
            assert all(ref in path.evidence_contract_refs for ref in declaration.evidence_contract_refs)


def test_core_projection_registry_uses_catalog_declared_policy_values() -> None:
    from workbench.evidence.consumer_adapters import projection_registry_from_catalog
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    provider = next(item for item in catalog.providers if item.provider_id == "workbench.consumer_projection")
    declaration = next(item for item in provider.projection_declarations if item.consumer_id == "agent")
    spec = projection_registry_from_catalog(catalog).resolve("agent")

    assert spec is not None
    assert spec.projection_ref == declaration.projection_ref
    assert spec.policy_ref == declaration.policy_ref
    assert spec.renderer_key == declaration.renderer_ref.logical_id
    assert spec.max_token_budget == declaration.max_token_budget
    assert spec.max_row_budget == declaration.max_row_budget
    assert spec.ordering == declaration.ordering
    assert spec.fact_kinds == declaration.fact_kinds
    assert spec.accepted_evidence_refs == declaration.evidence_contract_refs
    assert spec.accepted_envelope_refs == declaration.envelope_contract_refs


def test_registry_rejects_a_core_path_without_a_required_declaration() -> None:
    from workbench.evidence.consumer_adapters import projection_registry_from_catalog
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    provider_index = next(
        index for index, item in enumerate(catalog.providers)
        if item.provider_id == "workbench.consumer_projection"
    )
    provider = catalog.providers[provider_index]
    forged_provider = provider._replace(projection_declarations=())
    forged_catalog = catalog._replace(
        providers=catalog.providers[:provider_index] + (forged_provider,) + catalog.providers[provider_index + 1 :]
    )

    with pytest.raises(ValueError, match="PROJECTION_CATALOG_UNTRUSTED"):
        projection_registry_from_catalog(forged_catalog)


def test_provider_wire_rejects_legacy_projection_payload_in_current_catalog_contract() -> None:
    from workbench.contracts.common.provider import ProviderContractError, ProviderContributionV1
    from workbench.providers.catalog import load_builtin_catalog

    provider = next(
        item for item in load_builtin_catalog().providers
        if item.provider_id == "workbench.consumer_projection"
    )
    legacy_payload = provider.to_dict()
    legacy_payload.pop("projection_declarations")

    with pytest.raises(ProviderContractError, match="contribution fields"):
        ProviderContributionV1.from_dict(legacy_payload)


def test_projection_registry_rejects_an_unissued_catalog_object() -> None:
    from types import SimpleNamespace

    from workbench.evidence.consumer_adapters import projection_registry_from_catalog
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    with pytest.raises(ValueError, match="PROJECTION_CATALOG"):
        projection_registry_from_catalog(
            SimpleNamespace(providers=catalog.providers)
        )


def test_catalog_authority_digest_binds_contract_resolver_state() -> None:
    from workbench.contracts.common.contract_ref import ContractRefResolverV1
    from workbench.evidence.consumer_adapters import projection_registry_from_catalog
    from workbench.providers.catalog import is_server_owned_catalog, load_builtin_catalog

    catalog = load_builtin_catalog()
    forged = catalog._replace(contract_resolver=ContractRefResolverV1(()))

    assert not is_server_owned_catalog(forged)
    with pytest.raises(ValueError, match="PROJECTION_CATALOG_UNTRUSTED"):
        projection_registry_from_catalog(forged)


def test_central_projection_authority_rejects_provider_expanded_budget_and_sensitivity() -> None:
    from workbench.evidence.consumer_adapters import projection_registry_from_catalog
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    provider_index = next(
        index for index, item in enumerate(catalog.providers)
        if item.provider_id == "workbench.consumer_projection"
    )
    provider = catalog.providers[provider_index]
    declaration = provider.projection_declarations[0]
    forged_declaration = declaration._replace(
        max_token_budget=4_097,
        max_row_budget=65,
        allowed_sensitivity=("restricted",),
        ordering=("raw_rows",),
    )
    forged_provider = provider._replace(
        projection_declarations=(forged_declaration, *provider.projection_declarations[1:])
    )
    forged_catalog = catalog._replace(
        providers=(
            *catalog.providers[:provider_index],
            forged_provider,
            *catalog.providers[provider_index + 1 :],
        )
    )

    with pytest.raises(ValueError, match="PROJECTION_CATALOG"):
        projection_registry_from_catalog(forged_catalog)


def test_declaration_projection_identity_cannot_be_replaced_by_same_consumer_ref() -> None:
    from workbench.contracts.common.provider import ProviderContractError

    with pytest.raises(ProviderContractError, match="projection_ref"):
        _declaration(projection_ref=_ref("renderer", "wrong.kind"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("projection_ref", _ref("renderer", "wrong.projection.kind")),
        ("policy_ref", _ref("projection", "wrong.policy.kind")),
        ("renderer_ref", _ref("policy", "wrong.renderer.kind")),
        ("evidence_contract_refs", (_ref("renderer", "wrong.evidence.kind"),)),
        ("envelope_contract_refs", (_ref("renderer", "wrong.envelope.kind"),)),
        ("allowed_sensitivity", ("public", "public")),
        ("ordering", ("fact_id", "fact_id")),
    ],
)
def test_declaration_rejects_wrong_reference_kinds_and_duplicate_policy_values(field, value) -> None:
    with pytest.raises(ValueError, match=field.split("_")[0] if field.endswith("_refs") else field):
        _declaration(**{field: value})
