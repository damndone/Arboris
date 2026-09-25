from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.agent.capability_discovery import (
    CapabilityDiscovery,
    DiscoveryLimitsV1,
)
from workbench.agent.capability_manifest import (
    CapabilityManifestLimitsV1,
    build_capability_manifest,
)
from workbench.agent.failure_contract import CompilationFailure
from workbench.agent.port_types import PortTypeV1, PortCompatibilityError
from workbench.agent.operations import OperationRegistry
from workbench.providers.catalog import load_builtin_catalog
from test_v189_agent_compiler import _ExternalHostAuthority


def test_manifest_is_registry_derived_deterministic_and_does_not_publish_execution_authority() -> None:
    first = build_capability_manifest()
    second = build_capability_manifest()

    assert first.to_dict() == second.to_dict()
    assert first.manifest_digest == second.manifest_digest
    assert first.entries == tuple(sorted(first.entries, key=lambda item: item.capability_id))
    assert first.entries
    assert {item.operation_id for item in first.entries} <= set(OperationRegistry().operation_ids())
    for entry in first.entries:
        payload = entry.to_dict()
        assert "executor" not in payload
        assert "provider" not in payload
        assert "model" not in payload
        assert "execution_key" not in payload
        assert entry.capability_ref.kind == "capability"


def test_manifest_budget_fails_closed_instead_of_silently_truncating_authority() -> None:
    with pytest.raises(CompilationFailure) as exc_info:
        build_capability_manifest(CapabilityManifestLimitsV1(max_entries=1))

    assert exc_info.value.code == "MANIFEST_LIMIT_EXCEEDED"
    assert exc_info.value.envelope.retryable is False


def test_two_stage_discovery_is_bounded_and_sorted() -> None:
    manifest = build_capability_manifest()
    server = _ExternalHostAuthority(manifest)
    try:
        handle = server.open_handle()
        discovery = CapabilityDiscovery(
            manifest,
            limits=DiscoveryLimitsV1(max_query_results=3, max_query_bytes=128),
            authority_handle=handle,
        )

        result = discovery.query("data.columns.cast", scope_ref="project:alpha")
        assert len(result.items) <= 3
        assert result.items == tuple(sorted(result.items, key=lambda item: item.capability_id))
        assert all("provider" not in item.to_dict() for item in result.items)

        selected = discovery.resolve(
            result.items[0].capability_id,
            scope_ref="project:alpha",
            receipt=result,
        )
        assert selected.capability_id == result.items[0].capability_id
        assert selected.manifest_digest == manifest.manifest_digest
    finally:
        handle.close()
        server.close()


@pytest.mark.parametrize("query", ["/tmp/agent", "../escape", "https://evil.example/plan"])
def test_discovery_rejects_path_like_queries(query: str) -> None:
    discovery = CapabilityDiscovery(build_capability_manifest())

    with pytest.raises(CompilationFailure) as exc_info:
        discovery.query(query, scope_ref="project:alpha")

    assert exc_info.value.code == "PATH_LIKE_INPUT"


def test_discovery_rejects_oversized_query_budget() -> None:
    discovery = CapabilityDiscovery(
        build_capability_manifest(),
        limits=DiscoveryLimitsV1(max_query_results=3, max_query_bytes=8),
    )

    with pytest.raises(CompilationFailure) as exc_info:
        discovery.query("model", scope_ref="project:alpha")

    assert exc_info.value.code == "DISCOVERY_QUERY_LIMIT"


def test_port_compatibility_is_closed_and_directional() -> None:
    source = PortTypeV1(kind="table", schema_ref="schema:dataset", nullable=False)
    compatible_target = PortTypeV1(kind="table", schema_ref="schema:dataset", nullable=False)
    wrong_schema = PortTypeV1(kind="table", schema_ref="schema:model", nullable=False)

    assert source.is_compatible_with(compatible_target)
    assert not source.is_compatible_with(wrong_schema)
    with pytest.raises(PortCompatibilityError) as exc_info:
        source.require_compatible(wrong_schema)
    assert exc_info.value.code == "PORT_SCHEMA_MISMATCH"


@pytest.mark.parametrize(
    "source,target,code",
    [
        (
            PortTypeV1("table", "schema:dataset", nullable=False, collection=False),
            PortTypeV1("table", "schema:dataset", nullable=True, collection=False),
            "PORT_NULLABILITY_MISMATCH",
        ),
        (
            PortTypeV1("table", "schema:dataset", nullable=False, collection=False),
            PortTypeV1("table", "schema:dataset", nullable=False, collection=True),
            "PORT_KIND_MISMATCH",
        ),
        (
            PortTypeV1("table", "schema:dataset", nullable=False, collection=False),
            PortTypeV1("model", "schema:model", nullable=False, collection=False),
            "PORT_KIND_MISMATCH",
        ),
    ],
)
def test_port_compatibility_rejects_every_identity_mismatch(
    source: PortTypeV1,
    target: PortTypeV1,
    code: str,
) -> None:
    with pytest.raises(PortCompatibilityError) as exc_info:
        source.require_compatible(target)
    assert exc_info.value.code == code


def test_manifest_ports_and_policy_are_contract_derived_and_budgeted() -> None:
    manifest = build_capability_manifest()
    model_entry = manifest.require("model.genesis")
    code_entry = manifest.require("code.execute")

    assert model_entry.input_port_refs == ("port:model.genesis:v1:input:0",)
    assert model_entry.output_port_refs == ("port:model.genesis:v1:output:0",)
    assert model_entry.input_ports[0].schema_ref != "schema:dataset"
    assert model_entry.output_ports[0].schema_ref != "schema:model"
    assert model_entry.resource_budget == {"cpu_ms": 1000, "memory_mb": 128}
    assert code_entry.risk_authorization_policy == "explicit_single_use"
    assert code_entry.resource_budget["cpu_ms"] < model_entry.resource_budget["cpu_ms"]
    assert code_entry.policy_snapshot_ref != model_entry.policy_snapshot_ref


def test_builtin_agent_compiler_provider_manifest_is_declaration_only() -> None:
    path = Path(__file__).resolve().parents[1] / "backend" / "workbench" / "providers" / "builtin" / "agent_compiler.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["provider_id"] == "agent.compiler"
    assert payload["projection_declarations"][0]["fact_kinds"] == ["compiler_receipt"]

    def has_key(value: object, key: str) -> bool:
        if isinstance(value, dict):
            return key in value or any(has_key(child, key) for child in value.values())
        if isinstance(value, list):
            return any(has_key(child, key) for child in value)
        return False

    for forbidden_field in (
        "execution_key",
        "server_authority",
        "provider_choice",
        "model_choice",
        "receipt",
        "client_receipt",
        "code",
    ):
        assert not has_key(payload, forbidden_field)
    assert "agent.compiler" in load_builtin_catalog().provider_ids
