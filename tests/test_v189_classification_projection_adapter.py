from __future__ import annotations

import pytest
from dataclasses import replace

from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.evidence.consumer_adapters import default_projection_registry
from workbench.evidence.provider_projection_adapters import (
    ClassificationProjectionAdapterV1,
    ProviderProjectionRegistryV1,
    _authorize_classification_source_receipt,
    _issue_classification_source_snapshot,
    provider_projection_registry_from_catalog,
)
from workbench.evidence.consumer_adapters import EvidenceProjectionError
from workbench.providers.catalog import load_builtin_catalog
from test_v189_classification_central_consumer import (
    _materialize_run,
    _server_capability,
    _tamper_indexed_artifact_after_snapshot,
)


def _classification_provider(catalog):
    return next(
        provider
        for provider in catalog.providers
        if provider.provider_id == "workbench.classification_ml"
    )


def _classification_path(catalog):
    return _classification_provider(catalog).exposure_paths[0]


def _source_contract(adapter: ClassificationProjectionAdapterV1) -> dict[str, object]:
    binding = adapter.require_binding(
        "workbench.classification_ml",
        "workbench.classification_ml.direct",
        "report",
    )
    return {
        "payload_contract": {
            "payload_schema": "workbench.prediction.classification-artifacts",
            "schema_version": 1,
        },
        "evidence_schema_ref": "workbench.prediction.classification-evidence",
        "evidence_contract_refs": binding.evidence_contract_refs,
        "envelope_contract_refs": binding.envelope_contract_refs,
    }


def _source_snapshot(
    adapter: ClassificationProjectionAdapterV1,
    artifact: dict[str, object],
    source_contract: dict[str, object] | None = None,
) -> object:
    return _issue_classification_source_snapshot(
        artifact,
        source_contract or _source_contract(adapter),
        authorization=_authorize_classification_source_receipt(
            {
                "artifact_id": str(artifact.get("artifact_id", "test-artifact")),
                "artifact_sha256": "a" * 64,
                "receipt_digest": "b" * 64,
                "server_identity": {"run_id": "test-run"},
            }
        ),
        metadata={
            "artifact_id": str(artifact.get("artifact_id", "test-artifact")),
            "artifact_sha256": "a" * 64,
            "receipt_digest": "b" * 64,
            "server_identity": {"run_id": "test-run"},
        },
    )


def test_classification_join_is_exactly_provider_path_consumer_scoped() -> None:
    catalog = load_builtin_catalog()
    registry = provider_projection_registry_from_catalog(catalog)

    binding = registry.resolve_for(
        "workbench.classification_ml",
        "workbench.classification_ml.direct",
        "report",
    )

    assert binding is not None
    assert binding.provider_id == "workbench.classification_ml"
    assert binding.exposure_path == "workbench.classification_ml.direct"
    assert binding.consumer_id == "report"
    assert binding.projection_ref.logical_id == "workbench.classification_ml.report"
    assert binding.policy_ref.logical_id == "workbench.classification_ml.policy"
    assert binding.renderer_ref.logical_id == "workbench.classification_ml.report"
    assert registry.resolve_for(
        "workbench.consumer_projection",
        "workbench.classification_ml.direct",
        "report",
    ) is None


@pytest.mark.parametrize(
    ("provider_id", "exposure_path", "consumer_id"),
    [
        ("workbench.classification_ml", "workbench.classification_ml.direct", "missing"),
        ("workbench.classification_ml", "other.path", "report"),
        ("other.provider", "workbench.classification_ml.direct", "report"),
    ],
)
def test_classification_missing_exact_declaration_fails_closed(
    provider_id: str,
    exposure_path: str,
    consumer_id: str,
) -> None:
    registry = provider_projection_registry_from_catalog(load_builtin_catalog())

    assert registry.resolve_for(provider_id, exposure_path, consumer_id) is None
    with pytest.raises(ValueError):
        ClassificationProjectionAdapterV1(registry).require_binding(
            provider_id,
            exposure_path,
            consumer_id,
        )


def test_forged_catalog_is_rejected_before_projection_binding() -> None:
    catalog = load_builtin_catalog()
    forged = catalog._replace(catalog_digest="0" * 64)

    with pytest.raises(ValueError):
        provider_projection_registry_from_catalog(forged)


def test_wrong_projection_policy_or_renderer_identity_is_rejected() -> None:
    catalog = load_builtin_catalog()
    binding = provider_projection_registry_from_catalog(catalog).require_for(
        "workbench.classification_ml",
        "workbench.classification_ml.direct",
        "report",
    )
    wrong = ContractRefV1(
        kind="projection",
        logical_id="forged.projection",
        semantic_version="1.0",
        contract_digest="0" * 64,
    )
    adapter = ClassificationProjectionAdapterV1(
        provider_projection_registry_from_catalog(catalog)
    )

    with pytest.raises(ValueError):
        adapter.require_binding(
            binding.provider_id,
            binding.exposure_path,
            binding.consumer_id,
            projection_ref=wrong,
        )
    with pytest.raises(ValueError):
        adapter.require_binding(
            binding.provider_id,
            binding.exposure_path,
            binding.consumer_id,
            policy_ref=wrong,
        )
    with pytest.raises(ValueError):
        adapter.require_binding(
            binding.provider_id,
            binding.exposure_path,
            binding.consumer_id,
            renderer_ref=wrong,
        )


def test_generic_consumer_projection_legacy_resolution_remains_compatible() -> None:
    registry = default_projection_registry()

    assert registry.resolve("report") is not None
    assert registry.resolve("report").projection_ref.logical_id == (
        "workbench.consumer_projection.report"
    )


def test_manually_constructed_registry_is_not_a_trusted_catalog_registry() -> None:
    scoped = provider_projection_registry_from_catalog(load_builtin_catalog())
    binding = scoped.require_for(
        "workbench.classification_ml",
        "workbench.classification_ml.direct",
        "report",
    )
    manually_constructed = ProviderProjectionRegistryV1([binding])

    with pytest.raises(ValueError, match="PROJECTION_REGISTRY_UNTRUSTED"):
        ClassificationProjectionAdapterV1(manually_constructed)


def test_private_registry_issuance_revalidates_forged_binding() -> None:
    catalog = load_builtin_catalog()
    scoped = provider_projection_registry_from_catalog(catalog)
    binding = scoped.require_for(
        "workbench.classification_ml",
        "workbench.classification_ml.direct",
        "report",
    )
    forged = replace(binding, provider_digest="0" * 64)

    with pytest.raises(ValueError, match="PROJECTION_REGISTRY_ISSUANCE_INVALID"):
        ProviderProjectionRegistryV1._sealed_from_catalog(catalog, [forged])


def test_classification_projection_requires_actual_source_contract_identity(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    import json

    artifact = json.loads((run_root / "classification_artifacts.json").read_text())
    adapter = ClassificationProjectionAdapterV1(
        provider_projection_registry_from_catalog(load_builtin_catalog())
    )
    binding = adapter.require_binding(
        "workbench.classification_ml",
        "workbench.classification_ml.direct",
        "report",
    )
    source_contract = _source_contract(adapter)

    projection = adapter.project_artifact(
        _source_snapshot(adapter, artifact, source_contract),
        consumer_id="report",
    )
    assert projection["provider_id"] == "workbench.classification_ml"

    forged_source = dict(source_contract)
    forged_source["evidence_contract_refs"] = ()
    with pytest.raises(EvidenceProjectionError) as error:
        adapter.project_artifact(
            _source_snapshot(adapter, artifact, forged_source),
            consumer_id="report",
        )
    assert error.value.code == "PROJECTION_SOURCE_CONTRACT_MISMATCH"


def test_classification_projection_rejects_missing_source_contract(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    import json

    artifact = json.loads((run_root / "classification_artifacts.json").read_text())
    adapter = ClassificationProjectionAdapterV1(
        provider_projection_registry_from_catalog(load_builtin_catalog())
    )

    with pytest.raises(EvidenceProjectionError) as error:
        adapter.project_artifact(artifact, consumer_id="report")
    assert error.value.code == "PROJECTION_SOURCE_SNAPSHOT_REQUIRED"

 
def test_unavailable_projection_fail_closed() -> None:
    scoped = provider_projection_registry_from_catalog(load_builtin_catalog())
    unavailable = ClassificationProjectionAdapterV1(scoped).unavailable(
        "report",
        "classification index unavailable",
    )
    assert unavailable["payload_schema"] == "workbench.prediction.classification-evidence"
    assert unavailable["status"] == "unavailable"
    assert unavailable["blocked_reasons"] == ["classification index unavailable"]
    assert unavailable["projection_ref"]["logical_id"] == "workbench.classification_ml.report"


def test_classification_projection_rejects_serialized_budget_overrun(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    import json

    artifact = json.loads((run_root / "classification_artifacts.json").read_text())
    artifact["evidence"]["metrics"]["forged_oversized_payload"] = "x" * 100_000
    adapter = ClassificationProjectionAdapterV1(
        provider_projection_registry_from_catalog(load_builtin_catalog())
    )

    with pytest.raises(EvidenceProjectionError) as error:
        adapter.project_artifact(
            _source_snapshot(adapter, artifact),
            consumer_id="report",
        )

    assert error.value.code == "PROJECTION_TOKEN_BUDGET_EXCEEDED"


@pytest.mark.parametrize("sensitivity", ["restricted", "unknown"])
def test_classification_projection_rejects_unknown_or_disallowed_sensitivity(
    tmp_path,
    sensitivity: str,
) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    import json

    artifact = json.loads((run_root / "classification_artifacts.json").read_text())
    artifact["evidence"]["sensitivity"] = sensitivity
    adapter = ClassificationProjectionAdapterV1(
        provider_projection_registry_from_catalog(load_builtin_catalog())
    )

    with pytest.raises(EvidenceProjectionError) as error:
        adapter.project_artifact(
            _source_snapshot(adapter, artifact),
            consumer_id="report",
        )

    assert error.value.code == "PROJECTION_SENSITIVITY_NOT_ALLOWED"


def test_classification_projection_emits_enforced_catalog_constraints(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    import json

    artifact = json.loads((run_root / "classification_artifacts.json").read_text())
    adapter = ClassificationProjectionAdapterV1(
        provider_projection_registry_from_catalog(load_builtin_catalog())
    )

    projection = adapter.project_artifact(
        _source_snapshot(adapter, artifact),
        consumer_id="report",
    )
    constraints = projection["projection_constraints"]

    assert constraints["observed_sensitivity"] == "public"
    assert constraints["row_count"] <= constraints["max_row_budget"] == 64
    assert constraints["token_count"] <= constraints["max_token_budget"] == 4096
    assert set(constraints["observed_fact_kinds"]).issubset(
        set(constraints["fact_kinds"])
    )
    assert constraints["accepted_evidence_refs"]
    assert constraints["accepted_envelope_refs"] == []


def test_classification_projection_rejects_raw_evidence_fields(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    import json

    artifact = json.loads((run_root / "classification_artifacts.json").read_text())
    artifact["evidence"]["metrics"]["raw_secret"] = "not for a consumer"
    adapter = ClassificationProjectionAdapterV1(
        provider_projection_registry_from_catalog(load_builtin_catalog())
    )

    with pytest.raises(EvidenceProjectionError) as error:
        adapter.project_artifact(
            _source_snapshot(adapter, artifact),
            consumer_id="report",
        )

    assert error.value.code == "PROJECTION_RAW_FIELDS_REJECTED"


def test_central_classification_projection_carries_scoped_identity(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    from workbench.services.classification_consumer_service import (
        read_classification_consumer_projection,
    )

    projection = read_classification_consumer_projection(
        _server_capability(project_root, run_root.name),
        "report",
    )

    assert projection["payload_schema"] == "workbench.prediction.classification-evidence"
    assert projection["schema_version"] == 1
    assert projection["consumer"] == "report"
    assert projection["projection_ref"]["logical_id"] == "workbench.classification_ml.report"
    assert projection["policy_ref"]["logical_id"] == "workbench.classification_ml.policy"
    assert projection["renderer_ref"]["logical_id"] == "workbench.classification_ml.report"
    assert projection["provider_id"] == "workbench.classification_ml"
    assert projection["exposure_path"] == "workbench.classification_ml.direct"


def test_report_unavailable_surface_keeps_adapter_bound_identity(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "missing-index"
    run_root.mkdir(parents=True)
    from workbench.services.classification_consumer_service import (
        read_classification_report_evidence,
    )

    report = read_classification_report_evidence(
        _server_capability(project_root, run_root.name)
    )

    assert report["status"] == "unavailable"
    assert report["projection_ref"]["logical_id"] == "workbench.classification_ml.report"
    assert report["policy_ref"]["logical_id"] == "workbench.classification_ml.policy"
    assert report["renderer_ref"]["logical_id"] == "workbench.classification_ml.report"
    assert report["provider_id"] == "workbench.classification_ml"


def test_report_error_surface_keeps_adapter_bound_identity(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    _tamper_indexed_artifact_after_snapshot(run_root)

    from workbench.services.classification_consumer_service import (
        read_classification_report_evidence,
    )

    report = read_classification_report_evidence(
        _server_capability(project_root, run_root.name)
    )

    assert report["status"] == "unavailable"
    assert report["reason"] == "CLASSIFICATION_PERSISTED_RECEIPT_INVALID"
    assert report["provider_id"] == "workbench.classification_ml"
    assert report["exposure_path"] == "workbench.classification_ml.direct"
    assert report["catalog_digest"]
    assert report["provider_digest"]
    assert "projection" not in report
