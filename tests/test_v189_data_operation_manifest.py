from __future__ import annotations

import json
from pathlib import Path

from workbench.agent.operations import OperationRegistry
from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
from workbench.contracts.agent.planning import DraftAgentPlanV1
from workbench.providers.catalog import load_builtin_catalog


EXPECTED_OPERATION_IDS = (
    "data.append",
    "data.column.cast",
    "data.columns.cast",
    "data.feature_recipe",
    "data.merge",
    "data.reshape",
    "data.subset",
)


def _descriptors():
    from workbench.data_operation_manifest import build_data_operation_manifest

    manifest = build_data_operation_manifest()
    return manifest, {item.operation_id: item for item in manifest.operations}


def test_manifest_is_derived_from_the_single_live_data_operation_surface() -> None:
    from workbench.data_operation_manifest import DATA_OPERATION_MANIFEST_VERSION

    manifest, descriptors = _descriptors()

    assert DATA_OPERATION_MANIFEST_VERSION == "data-operation-manifest.v1"
    assert manifest.schema_version == DATA_OPERATION_MANIFEST_VERSION
    assert tuple(sorted(descriptors)) == EXPECTED_OPERATION_IDS
    assert tuple(item.operation_id for item in manifest.operations) == EXPECTED_OPERATION_IDS

    registry = OperationRegistry()
    for operation_id in EXPECTED_OPERATION_IDS:
        definition = registry.require(operation_id)
        descriptor = descriptors[operation_id]
        contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(operation_id)

        assert descriptor.operation_version == definition.operation_version
        assert descriptor.effect_level == definition.effect_level == "mutation"
        assert descriptor.risk_level == definition.risk_level == "mutating"
        assert descriptor.confirmation_policy == definition.confirmation_policy
        assert descriptor.executor_key == definition.executor_key
        assert descriptor.reconciler_key == definition.reconciler_key
        assert descriptor.validator_key == (
            contract.semantic_validator_key if contract is not None else operation_id
        )
        assert descriptor.request_schema["additionalProperties"] is False
        assert set(("source_run_id", "source_node_id", "source_artifact_id")) <= set(
            descriptor.request_schema["properties"]
        )


def test_manifest_and_rows_have_stable_json_safe_round_trips() -> None:
    from workbench.data_operation_manifest import (
        DataOperationDescriptorV1,
        DataOperationManifestV1,
    )

    manifest, descriptors = _descriptors()
    payload = manifest.to_dict()
    restored = DataOperationManifestV1.from_dict(payload)

    assert restored.to_dict() == payload
    assert [item["operation_id"] for item in payload["operations"]] == list(
        EXPECTED_OPERATION_IDS
    )
    for operation_id, descriptor in descriptors.items():
        row = DataOperationDescriptorV1.from_dict(descriptor.to_dict())
        assert row.to_dict() == descriptor.to_dict()
        assert json.loads(json.dumps(row.to_dict(), sort_keys=True)) == row.to_dict()
        assert any(
            item["operation_id"] == operation_id for item in payload["operations"]
        )


def test_builtin_provider_payload_is_c0_shaped_and_matches_repository_fixture() -> None:
    from workbench.data_operation_manifest import build_builtin_provider_payload

    payload = build_builtin_provider_payload()
    fixture_path = (
        Path(__file__).parents[1]
        / "backend"
        / "workbench"
        / "providers"
        / "builtin"
        / "data_consumer.json"
    )

    assert set(payload) == {
        "provider_id",
        "semantic_version",
        "contracts",
        "exposure_paths",
        "adapter_declarations",
        "projection_refs",
        "renderer_refs",
        "policy_refs",
    }
    assert "operations" not in payload
    assert json.loads(fixture_path.read_text(encoding="utf-8")) == payload


def test_manifest_reuses_live_closed_field_schemas_for_cast_recipe_and_filters() -> None:
    _, descriptors = _descriptors()
    registry = OperationRegistry()

    cast = descriptors["data.column.cast"]
    assert cast.request_schema["properties"]["target_dtype"] == registry.require(
        "data.column.cast"
    ).editable_schema["properties"]["target_dtype"]

    recipe = descriptors["data.feature_recipe"]
    recipe_contract = WORKFLOW_STEP_SPEC_CONTRACTS["data.feature_recipe"]
    assert recipe.request_schema["properties"]["recipe_operation_id"]["enum"] == list(
        recipe_contract.field_enums["recipe_operation_id"]
    )
    assert recipe.request_schema["properties"]["parameters"] == dict(
        recipe_contract.field_schemas["parameters"]
    )

    subset = descriptors["data.subset"]
    subset_contract = WORKFLOW_STEP_SPEC_CONTRACTS["data.subset"]
    filter_schema = subset.request_schema["properties"]["filters"]["items"]
    live_filter_schema = subset_contract.field_schemas["filters"]["items"]
    assert filter_schema["properties"]["op"]["enum"] == live_filter_schema["properties"]["op"][
        "enum"
    ]
    assert set(filter_schema["properties"]["op"]["enum"]) == {
        "eq",
        "ne",
        "gt",
        "ge",
        "lt",
        "le",
        "in",
        "not_in",
        "between",
        "is_missing",
        "not_missing",
    }
    assert not {"python", "query", "eval", "regex"} & set(
        filter_schema["properties"]["op"]["enum"]
    )


def test_manifest_declares_identity_bound_ports_effects_and_metadata_effects() -> None:
    _, descriptors = _descriptors()

    for descriptor in descriptors.values():
        source = next(port for port in descriptor.input_ports if port.name == "source")
        output = next(port for port in descriptor.output_ports if port.name == "derived")
        assert source.port_type == "dataset"
        assert source.cardinality == "one"
        assert source.required is True
        assert source.identity_fields == (
            "source_run_id",
            "source_node_id",
            "source_artifact_id",
        )
        assert output.port_type == "dataset"
        assert output.dataset_kind == "derived_data"
        assert output.cardinality == "one"
        assert descriptor.metadata_effect
        assert descriptor.metadata_risk
        assert descriptor.output_kind == "derived_data"

    for operation_id in ("data.merge", "data.append"):
        secondary = next(
            port for port in descriptors[operation_id].input_ports if port.name == "secondary"
        )
        assert secondary.identity_fields == (
            "secondary_run_id",
            "secondary_node_id",
            "secondary_artifact_id",
        )
        assert secondary.required is True

    for descriptor in descriptors.values():
        output = next(port for port in descriptor.output_ports if port.name == "derived")
        assert output.identity_fields == (
            "source_run_id",
            "child_node_id",
            "artifact_id",
            "recipe_artifact_id",
            "execution_key",
        )


def test_manifest_declares_preview_confirmation_replay_and_clarification_refs() -> None:
    _, descriptors = _descriptors()

    for descriptor in descriptors.values():
        assert descriptor.preview_ref.startswith("/data-operations/")
        assert descriptor.preview_ref.endswith("/preview")
        assert descriptor.confirm_ref.startswith("/data-operations/")
        assert descriptor.confirm_ref.endswith("/confirm")
        assert descriptor.confirm_requires == ("preview_fingerprint",)
        assert descriptor.replay.recipe_kind == "typed_operation_request"
        assert descriptor.replay.request_identity_fields
        assert "request_sha256" in descriptor.replay.request_identity_fields
        assert descriptor.replay.source_fingerprint_field == "source_sha256"
        assert descriptor.replay.request_digest_field == "request_sha256"
        assert len(descriptor.request_schema_digest) == 64
        assert descriptor.clarification_requirements

    assert descriptors["data.columns.cast"].request_schema["properties"]["output_format"][
        "enum"
    ] == ["csv", "xlsx"]

    assert any(
        "join" in item.lower() or "cardinality" in item.lower()
        for item in descriptors["data.merge"].clarification_requirements
    )
    assert any(
        "direction" in item.lower()
        for item in descriptors["data.reshape"].clarification_requirements
    )
    assert any(
        "filter" in item.lower()
        for item in descriptors["data.subset"].clarification_requirements
    )


def test_data_consumer_provider_is_catalog_discoverable_without_runtime_switch() -> None:
    before = OperationRegistry().operation_ids()
    catalog = load_builtin_catalog()
    after = OperationRegistry().operation_ids()

    assert before == after
    provider = next(
        item for item in catalog.providers if item.provider_id == "workbench.data_consumer"
    )
    assert provider.semantic_version == "1.0"
    assert any(
        path.path_id == "workbench.data_consumer.operations"
        for path in provider.exposure_paths
    )
    assert any(
        adapter.adapter_id == "workbench.data_consumer.adapter"
        and adapter.executor_ref == "executor:workbench.data_consumer.adapter"
        for adapter in provider.adapter_declarations
    )
    refs = [*provider.contract_refs]
    assert all(ref.logical_id.startswith("workbench.data_consumer.") for ref in refs)
    assert len({ref.contract_digest for ref in refs}) == len(refs)
    assert "data_operation_manifest" not in provider.provider_id


def test_agent_notebook_composition_fixtures_are_draft_planning_only() -> None:
    from workbench.data_operation_manifest import draft_agent_notebook_composition_fixtures

    fixtures = draft_agent_notebook_composition_fixtures()
    assert fixtures
    assert {fixture.consumer for fixture in fixtures} == {"agent", "notebook"}

    for fixture in fixtures:
        assert fixture.mode == "draft"
        assert fixture.execution_allowed is False
        assert fixture.confirmation_ref is None
        assert isinstance(fixture.plan, DraftAgentPlanV1)
        assert fixture.plan.to_dict()["schema_version"] == "draft-agent-plan.v1"
        assert fixture.plan.nodes
        assert all("name" in node for node in fixture.plan.nodes)
        assert all(
            node["name"] in EXPECTED_OPERATION_IDS for node in fixture.plan.nodes
        )
        assert not hasattr(fixture, "execute")
