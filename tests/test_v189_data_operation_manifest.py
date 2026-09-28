from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.agent.operations import OperationRegistry
from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
from workbench.contracts.agent.planning import DraftAgentPlanV1
from workbench.providers.catalog import load_builtin_catalog


EXPECTED_OPERATION_IDS = (
    "data.aggregate",
    "data.append",
    "data.column.cast",
    "data.columns.cast",
    "data.feature_recipe",
    "data.merge",
    "data.metadata.update",
    "data.recode",
    "data.rename",
    "data.reshape",
    "data.sort",
    "data.split",
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
        descriptor = descriptors[operation_id]
        if operation_id in {
            "data.metadata.update",
            "data.sort",
            "data.split",
            "data.recode",
            "data.rename",
        }:
            assert descriptor.operation_version == "v1"
            assert descriptor.effect_level == "mutation"
            assert descriptor.risk_level == "mutating"
            assert descriptor.confirmation_policy == "required"
            assert descriptor.executor_key.startswith("executor:workbench.data_consumer.")
            assert descriptor.reconciler_key.startswith("reconciler:workbench.data_consumer.")
            assert descriptor.validator_key == operation_id
            assert descriptor.request_schema["additionalProperties"] is False
            assert set(("source_run_id", "source_node_id", "source_artifact_id")) <= set(
                descriptor.request_schema["properties"]
            )
            continue
        definition = registry.require(operation_id)
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


def test_manifest_advertises_only_real_data_consumer_extensions() -> None:
    manifest, descriptors = _descriptors()

    assert {
        "data.metadata.update",
        "data.sort",
        "data.split",
        "data.recode",
    } <= set(descriptors)
    for operation_id in ("data.metadata.update", "data.sort", "data.split", "data.recode"):
        descriptor = descriptors[operation_id]
        assert descriptor.preview_ref.endswith("/preview")
        assert descriptor.confirm_ref.endswith("/confirm")
        assert descriptor.request_schema["additionalProperties"] is False
        assert descriptor.request_schema["properties"]["source_artifact_id"]["type"] == "string"

    from workbench.data_interchange import interchange_capability

    unavailable = manifest.to_dict().get("unavailable", [])
    native_items = {
        item["operation_id"]: item
        for item in unavailable
        if item["operation_id"] in {
            "data.interchange.sav",
            "data.interchange.zsav",
            "data.interchange.dta",
        }
    }
    assert set(native_items) == {
        "data.interchange.sav",
        "data.interchange.zsav",
        "data.interchange.dta",
    }
    for operation_id, item in native_items.items():
        capability = interchange_capability(operation_id.rsplit(".", 1)[-1])
        assert item["status"] == "unavailable"
        assert item["reason_code"] == capability.reason_code


def test_manifest_fails_closed_when_pyreadstat_import_is_broken(monkeypatch) -> None:
    import importlib

    from workbench import data_operation_manifest as api
    from workbench import data_interchange

    real_import_module = importlib.import_module
    original_has_module = data_interchange._has_module

    monkeypatch.setattr(
        data_interchange,
        "_has_module",
        lambda name: True if name == "pyreadstat" else original_has_module(name),
    )

    def broken_import(name: str, package: str | None = None):
        if name == "pyreadstat":
            raise ModuleNotFoundError("pyreadstat is installed but cannot be imported")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", broken_import)

    manifest = api.build_data_operation_manifest()
    unavailable = manifest.to_dict().get("unavailable", [])

    native_items = {
        item["operation_id"]: item
        for item in unavailable
        if item["operation_id"] in {
            "data.interchange.sav",
            "data.interchange.zsav",
            "data.interchange.dta",
        }
    }
    assert set(native_items) == {
        "data.interchange.sav",
        "data.interchange.zsav",
        "data.interchange.dta",
    }
    for operation_id, item in native_items.items():
        capability = data_interchange.interchange_capability(
            operation_id.rsplit(".", 1)[-1]
        )
        assert item["status"] == "unavailable"
        assert item["reason_code"] == capability.reason_code == "optional_dependency"


def test_manifest_fails_closed_when_callable_pyreadstat_runtime_probe_is_broken(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from workbench import data_interchange
    from workbench.data_operation_manifest import build_data_operation_manifest

    def broken(*_args, **_kwargs):
        raise RuntimeError("adapter operation failed")

    broken_module = SimpleNamespace(
        read_sav=broken,
        write_sav=broken,
        read_dta=broken,
        write_dta=broken,
    )
    original_verified_import = data_interchange._verified_import
    monkeypatch.setattr(
        data_interchange,
        "_verified_import",
        lambda name: broken_module if name == "pyreadstat" else original_verified_import(name),
    )

    manifest = build_data_operation_manifest().to_dict()
    native_items = {
        item["operation_id"]: item
        for item in manifest["unavailable"]
        if item["operation_id"] in {
            "data.interchange.sav",
            "data.interchange.zsav",
            "data.interchange.dta",
        }
    }
    assert set(native_items) == {
        "data.interchange.sav",
        "data.interchange.zsav",
        "data.interchange.dta",
    }
    assert all(item["status"] == "unavailable" for item in native_items.values())
    assert all(item["reason_code"] == "optional_dependency" for item in native_items.values())


def test_manifest_fails_closed_when_zsav_probe_mode_is_broken(monkeypatch) -> None:
    from pathlib import Path
    from types import SimpleNamespace

    import pandas as pd

    from workbench import data_interchange
    from workbench.data_operation_manifest import build_data_operation_manifest

    def write_sav(frame, path, *, compress=False):
        Path(path).write_bytes(b"sav")
        if compress:
            raise RuntimeError("ZSAV mode is unavailable")

    def read_sav(_path):
        return frame.copy(), None

    def write_dta(_frame, path, *, version):
        Path(path).write_bytes(b"dta")

    def read_dta(_path):
        return frame.copy(), None

    frame = pd.DataFrame({"code": [1]})
    broken_zsav_module = SimpleNamespace(
        read_sav=read_sav,
        write_sav=write_sav,
        read_dta=read_dta,
        write_dta=write_dta,
    )
    original_verified_import = data_interchange._verified_import
    monkeypatch.setattr(
        data_interchange,
        "_verified_import",
        lambda name: broken_zsav_module
        if name == "pyreadstat"
        else original_verified_import(name),
    )

    manifest = build_data_operation_manifest().to_dict()
    native_items = {
        item["operation_id"]: item
        for item in manifest["unavailable"]
        if item["operation_id"] in {
            "data.interchange.sav",
            "data.interchange.zsav",
            "data.interchange.dta",
        }
    }
    assert set(native_items) == {
        "data.interchange.sav",
        "data.interchange.zsav",
        "data.interchange.dta",
    }
    assert all(item["status"] == "unavailable" for item in native_items.values())
    assert all(item["reason_code"] == "optional_dependency" for item in native_items.values())


def test_package_runtime_adapter_joins_live_catalog_and_exposes_record_evidence_ports() -> None:
    from workbench.data_operation_manifest import build_data_consumer_runtime_adapter

    adapter = build_data_consumer_runtime_adapter()
    catalog = load_builtin_catalog()
    provider = next(
        item for item in catalog.providers if item.provider_id == "workbench.data_consumer"
    )
    declaration = next(
        item
        for item in provider.adapter_declarations
        if item.adapter_id == "workbench.data_consumer.adapter"
    )

    assert adapter.provider_id == provider.provider_id
    assert adapter.adapter_id == declaration.adapter_id
    assert adapter.catalog_digest == catalog.catalog_digest
    assert adapter.executor_ref == declaration.executor_ref
    assert {"data.agent", "data.notebook", "data.report"} <= set(adapter.consumer_slots)
    assert {"derived", "operation_record", "evidence"} <= set(adapter.output_ports)
    assert callable(adapter.adapt_operation_record)


def test_package_runtime_contribution_joins_live_declaration_and_fails_closed_without_host_input() -> None:
    from workbench.agent.trusted_executor_registry import (
        ProviderRuntimeContextV1,
        ProviderRuntimeContributionV1,
    )
    from workbench.data_operation_manifest import (
        build_data_consumer_runtime_adapter,
        build_data_consumer_runtime_contribution,
    )

    catalog = load_builtin_catalog()
    provider = next(item for item in catalog.providers if item.provider_id == "workbench.data_consumer")
    declaration = next(
        item
        for item in provider.adapter_declarations
        if item.adapter_id == "workbench.data_consumer.adapter"
    )
    adapter = build_data_consumer_runtime_adapter()

    contribution = build_data_consumer_runtime_contribution(catalog)

    assert type(contribution) is ProviderRuntimeContributionV1
    assert contribution.provider_id == provider.provider_id
    assert contribution.adapter_id == declaration.adapter_id
    assert contribution.executor_ref == declaration.executor_ref
    assert contribution.request_contract_ref == declaration.request_schema_ref
    assert contribution.result_contract_refs == declaration.output_refs
    assert contribution.metadata["output_ports"] == list(adapter.output_ports)
    assert contribution.metadata["typed_authority"] == "DataConsumerOutputPortsV1"

    context = ProviderRuntimeContextV1(
        compilation_record_id="compile:data-consumer-test",
        execution_instance_hash="exec:data-consumer-test",
        actor_ref="principal:data-consumer-test",
        session_ref="session:data-consumer-test",
        project_ref="project:data-consumer-test",
        effect="read_only",
    )
    result = contribution.executor(
        context,
        {
            "operation_id": "data.sort",
            "source_run_id": "run:data-consumer-test",
            "source_node_id": "node:data-consumer-test",
            "source_artifact_id": "artifact:data-consumer-test",
            "operation": "sort",
        },
    )

    assert result["status"] == "unavailable"
    assert result["reason_code"] == "DATA_CONSUMER_HOST_DATA_STORE_UNAVAILABLE"
    assert result["operation_id"] == "data.sort"
    assert "rows" not in result
    assert "path" not in result
    assert "evidence" not in result
    with pytest.raises((TypeError, ValueError), match="completed|typed|output|OperationRecord"):
        contribution.result_validator(
            {
                "status": "completed",
                "operation_id": "data.sort",
                "rows": [{"caller": "fake-success"}],
            }
        )


def test_package_runtime_adapter_rejects_caller_authored_operation_record_mapping() -> None:
    from workbench.data_operation_manifest import build_data_consumer_runtime_adapter

    adapter = build_data_consumer_runtime_adapter()

    with pytest.raises((TypeError, ValueError), match="typed|OperationRecord|server"):
        adapter.adapt_operation_record(
            {
                "record_id": "caller-record",
                "operation_id": "data.sort",
                "outputs": {
                    "ports": {
                        "derived": {"child_node_id": "caller-child"},
                        "operation_record": {"record_id": "caller-record"},
                        "evidence": {"method": "caller-authored"},
                    },
                    "consumer_slots": {
                        "data.agent": {"record_id": "caller-record"},
                        "data.notebook": {"record_id": "caller-record"},
                        "data.report": {"record_id": "caller-record"},
                    },
                },
            }
        )


def test_package_runtime_adapter_rejects_caller_authored_evidence_mapping() -> None:
    from workbench.data_operation_manifest import DataConsumerEvidencePortV1

    with pytest.raises(TypeError, match="typed|server"):
        DataConsumerEvidencePortV1.from_server(
            "caller-authored",
            {"weight_consumed": True},
        )


def test_package_runtime_adapter_rejects_invalid_executor_identity() -> None:
    from workbench.data_operation_manifest import DataConsumerRuntimeAdapterV1

    with pytest.raises(ValueError, match="executor"):
        DataConsumerRuntimeAdapterV1(
            provider_id="workbench.data_consumer",
            adapter_id="workbench.data_consumer.adapter",
            catalog_digest="a" * 64,
            executor_ref="python:caller.authored",
            consumer_slots=("data.agent",),
            output_ports=("derived", "operation_record", "evidence"),
            operation_ids=("data.sort",),
        )


def test_server_evidence_and_derived_ports_cannot_be_caller_constructed() -> None:
    from workbench.data_operation_manifest import (
        DataConsumerDerivedPortV1,
        DataConsumerServerEvidenceV1,
    )

    with pytest.raises((TypeError, ValueError), match="server|factory|capability"):
        DataConsumerServerEvidenceV1(method="data.sort", payload={})

    with pytest.raises((TypeError, ValueError), match="server|factory|capability"):
        DataConsumerDerivedPortV1(effect=object())


def test_from_server_rejects_caller_authored_typed_effect_and_evidence() -> None:
    from workbench.data_operation_manifest import (
        DataConsumerDerivedPortV1,
        DataConsumerServerEvidenceV1,
    )
    from workbench.data_operations import DataColumnCastEffect

    effect = DataColumnCastEffect(
        execution_key="caller-execution",
        artifact_id="caller-artifact",
        artifact_path="derived/caller.csv",
        recipe_artifact_id="caller-recipe",
        recipe_path="derived/caller.recipe.json",
        child_node_id="caller-child",
    )
    with pytest.raises((TypeError, ValueError), match="server|issuer|factory|capability"):
        DataConsumerDerivedPortV1.from_server(effect)

    with pytest.raises((TypeError, ValueError), match="server|issuer|factory|capability"):
        DataConsumerServerEvidenceV1.from_server(
            "caller-authored",
            {},
            record_id="caller-record",
            operation_id="data.sort",
            execution_key="caller-execution",
            bindings={},
        )


def test_public_executor_registry_cannot_be_replaced_by_caller() -> None:
    import workbench.data_operation_manifest as manifest_module

    with pytest.raises((TypeError, AttributeError), match="immutable|item|mapping|read-only"):
        manifest_module.SERVER_OWNED_EXECUTOR_REGISTRY[
            "executor:workbench.data_consumer.adapter"
        ] = lambda record, outputs: outputs


def test_runtime_adapter_rejects_unregistered_executor_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.data_operation_manifest as manifest_module

    with pytest.raises((TypeError, AttributeError), match="immutable|item|mapping|read-only"):
        manifest_module.SERVER_OWNED_EXECUTOR_REGISTRY[
            "executor:workbench.data_consumer.adapter"
        ] = None
    adapter = manifest_module.build_data_consumer_runtime_adapter()
    assert adapter.executor_ref == "executor:workbench.data_consumer.adapter"


def test_package_runtime_adapter_rejects_duck_typed_fake_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.providers.catalog as catalog_module
    from workbench.data_operation_manifest import build_data_consumer_runtime_adapter

    class FakeDeclaration:
        adapter_id = "workbench.data_consumer.adapter"
        executor_ref = "executor:workbench.data_consumer.adapter"

    class FakeProvider:
        provider_id = "workbench.data_consumer"
        adapter_declarations = (FakeDeclaration(),)

    class FakeCatalog:
        providers = (FakeProvider(),)
        catalog_digest = "fake-catalog"

    monkeypatch.setattr(catalog_module, "load_builtin_catalog", lambda: FakeCatalog())

    with pytest.raises((TypeError, ValueError), match="catalog|server-owned|typed"):
        build_data_consumer_runtime_adapter()


def test_catalog_fixture_digest_is_recomputed_from_live_provider_catalog() -> None:
    from workbench.canonical import sha256_canonical

    catalog = load_builtin_catalog()
    provider = next(
        item for item in catalog.providers if item.provider_id == "workbench.data_consumer"
    )
    assert catalog.catalog_digest == sha256_canonical(catalog.digest_payload())
    assert provider.to_dict()["adapter_declarations"][0]["executor_ref"] == (
        "executor:workbench.data_consumer.adapter"
    )
