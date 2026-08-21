from __future__ import annotations

from dataclasses import replace

import pytest

from workbench.agent.operations import OperationRecord
from workbench.canonical import sha256_canonical
from workbench.data_operations import DataColumnCastEffect, _mark_server_owned_effect
from workbench.providers.catalog import load_builtin_catalog


def _record(
    *,
    record_id: str = "record:data-host",
    project_ref: str = "project:data-host",
    session_ref: str = "session:data-host",
) -> OperationRecord:
    return OperationRecord(
        record_id=record_id,
        operation_id="data.column.cast",
        operation_version="v1",
        proposal_id="proposal:data-host",
        proposal_revision=1,
        proposal_fingerprint="a" * 64,
        agent_session_id=session_ref,
        chain_id="chain:data-host",
        command_id="command:data-host",
        target={
            "project_ref": project_ref,
            "data_snapshot_ref": "snapshot:data-host",
            "data_snapshot_digest": "b" * 64,
            "source_run_id": "run:data-host",
            "source_node_id": "node:data-host",
            "source_artifact_id": "artifact:source-data-host",
        },
        preconditions={"project_ref": project_ref, "session_ref": session_ref},
        actor_type="human_ui",
        status="completed",
        confirmation={"confirmed": True},
        execution={
            "execution_key": "execution:data-host",
            "bindings": {
                "child_node_id": "node:child-data-host",
                "artifact_id": "artifact:derived-data-host",
                "recipe_artifact_id": "artifact:recipe-data-host",
            },
        },
        outputs={},
        effect_status="committed",
        projection_status="committed",
    )


def _output(record: OperationRecord):
    import workbench.data_operation_manifest as manifest

    effect = _mark_server_owned_effect(
        DataColumnCastEffect(
            execution_key="execution:data-host",
            artifact_id="artifact:derived-data-host",
            artifact_path="derived/data-host.csv",
            recipe_artifact_id="artifact:recipe-data-host",
            recipe_path="derived/data-host.recipe.json",
            child_node_id="node:child-data-host",
        )
    )
    derived = manifest.DataConsumerDerivedPortV1.from_server(
        effect, _issuer=manifest._SERVER_OWNED_ISSUER
    )
    evidence = manifest.DataConsumerServerEvidenceV1.from_server(
        "data.column.cast",
        {"method": "data.column.cast"},
        record_id=record.record_id,
        operation_id=record.operation_id,
        execution_key="execution:data-host",
        bindings={"child_node_id": "node:child-data-host"},
        _issuer=manifest._SERVER_OWNED_ISSUER,
    )
    evidence_port = manifest.DataConsumerEvidencePortV1.from_server(
        "data.column.cast", evidence, _issuer=manifest._SERVER_OWNED_ISSUER
    )
    return manifest.DataConsumerOutputPortsV1.from_server(
        record,
        derived,
        evidence_port,
        _issuer=manifest._SERVER_OWNED_ISSUER,
    )


def _request(**overrides):
    value = {
        "project_ref": "project:data-host",
        "session_ref": "session:data-host",
        "snapshot_ref": "snapshot:data-host",
        "snapshot_digest": "b" * 64,
        "operation_id": "data.column.cast",
        "operation_version": "v1",
        "source_run_id": "run:data-host",
        "source_node_id": "node:data-host",
        "source_artifact_id": "artifact:source-data-host",
    }
    value.update(overrides)
    return value


def _typed_request(**overrides):
    import workbench.data_operation_manifest as manifest

    return manifest.DataConsumerHostOperationRequestV1(**_request(**overrides))


def _authority(*records: OperationRecord):
    import workbench.data_operation_manifest as manifest

    issued = {record.record_id: record for record in records}
    return manifest.DataConsumerRecordAuthorityV1.from_server(
        issued,
        _issuer=manifest._SERVER_OWNED_ISSUER,
    )


def _port(resolve, record_authority):
    import workbench.data_operation_manifest as manifest

    return manifest.DataConsumerHostOperationPortV1.from_server(
        resolve,
        record_authority=record_authority,
        catalog_digest=load_builtin_catalog().catalog_digest,
        project_ref="project:data-host",
        session_ref="session:data-host",
        snapshot_ref="snapshot:data-host",
        snapshot_digest="b" * 64,
        operation_id="data.column.cast",
        operation_version="v1",
        source_run_id="run:data-host",
        source_node_id="node:data-host",
        source_artifact_id="artifact:source-data-host",
        _issuer=manifest._SERVER_OWNED_ISSUER,
    )


def test_server_host_port_resolves_typed_operation_to_bounded_projection() -> None:
    import workbench.data_operation_manifest as manifest

    record = _record()
    port = _port(lambda request: _output(record), _authority(record))

    result = port.resolve(manifest.DataConsumerHostOperationRequestV1(**_request()))

    assert result.to_dict() == {
        "record_id": "record:data-host",
        "operation_id": "data.column.cast",
        "operation_version": "v1",
        "execution_key": "execution:data-host",
        "child_node_id": "node:child-data-host",
        "artifact_ids": [
            "artifact:derived-data-host",
            "artifact:recipe-data-host",
        ],
        "evidence_digest": sha256_canonical(_output(record).evidence.to_dict()),
        "catalog_digest": load_builtin_catalog().catalog_digest,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"operation_id": "data.unknown"},
        {"snapshot_digest": "c" * 64},
        {"snapshot_ref": "snapshot:stale"},
        {"project_ref": "project:foreign"},
        {"session_ref": "session:foreign"},
        {"source_artifact_id": "artifact:foreign"},
    ],
)
def test_server_host_port_rejects_unknown_stale_or_foreign_identity(overrides) -> None:
    record = _record()
    port = _port(lambda request: _output(record), _authority(record))

    with pytest.raises((TypeError, ValueError), match="operation|snapshot|scope|source"):
        port.resolve(_request(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"operation_id": "data.sort"},
        {"source_run_id": "run:foreign"},
        {"source_node_id": "node:foreign"},
        {"source_artifact_id": "artifact:foreign"},
    ],
)
def test_host_port_rejects_known_but_foreign_operation_or_source_identity(overrides) -> None:
    record = _record()
    port = _port(lambda request: _output(record), _authority(record))

    with pytest.raises((TypeError, ValueError), match="foreign|operation|source"):
        port.resolve(_typed_request(**overrides))


def test_host_port_rejects_raw_inputs_and_caller_authored_output() -> None:
    record = _record()
    port = _port(
        lambda request: {"rows": [{"x": 1}], "path": "/tmp/data.csv"},
        _authority(record),
    )

    with pytest.raises((TypeError, ValueError), match="typed|raw|output|server"):
        port.resolve({**_request(), "path": "/tmp/data.csv"})
    with pytest.raises((TypeError, ValueError), match="typed|raw|output|server"):
        port.resolve(_request())


def test_host_port_requires_a_server_record_authority() -> None:
    import workbench.data_operation_manifest as manifest

    record = _record()
    with pytest.raises(TypeError, match="authority|validator"):
        manifest.DataConsumerHostOperationPortV1.from_server(
            lambda request: _output(record),
            catalog_digest=load_builtin_catalog().catalog_digest,
            project_ref="project:data-host",
            session_ref="session:data-host",
            snapshot_ref="snapshot:data-host",
            snapshot_digest="b" * 64,
            operation_id="data.column.cast",
            operation_version="v1",
            source_run_id="run:data-host",
            source_node_id="node:data-host",
            source_artifact_id="artifact:source-data-host",
            _issuer=manifest._SERVER_OWNED_ISSUER,
        )

    with pytest.raises(TypeError, match="authority|server"):
        manifest.DataConsumerHostOperationPortV1.from_server(
            lambda request: _output(record),
            record_authority=lambda record_id: record,
            catalog_digest=load_builtin_catalog().catalog_digest,
            project_ref="project:data-host",
            session_ref="session:data-host",
            snapshot_ref="snapshot:data-host",
            snapshot_digest="b" * 64,
            operation_id="data.column.cast",
            operation_version="v1",
            source_run_id="run:data-host",
            source_node_id="node:data-host",
            source_artifact_id="artifact:source-data-host",
            _issuer=manifest._SERVER_OWNED_ISSUER,
        )


def test_host_port_rejects_an_unregistered_operation_record() -> None:
    record = _record()
    port = _port(lambda request: _output(record), _authority())

    with pytest.raises((TypeError, ValueError), match="authority|issued|registered|provenance"):
        port.resolve(_typed_request())


def test_host_port_rejects_a_registered_foreign_operation_record() -> None:
    issued = _record()
    foreign = _record(
        record_id="record:foreign",
        project_ref="project:foreign",
        session_ref="session:foreign",
    )
    port = _port(lambda request: _output(foreign), _authority(issued, foreign))

    with pytest.raises((TypeError, ValueError), match="identity|foreign|scope|source"):
        port.resolve(_typed_request())


def test_host_port_rejects_a_caller_authored_record_copy() -> None:
    issued = _record()
    caller_authored = replace(
        issued,
        target=dict(issued.target),
        preconditions=dict(issued.preconditions),
    )
    port = _port(lambda request: _output(caller_authored), _authority(issued))

    with pytest.raises((TypeError, ValueError), match="authority|issued|provenance|exact"):
        port.resolve(_typed_request())


@pytest.mark.parametrize(
    "missing_claim",
    [
        "project_ref",
        "session_ref",
        "data_snapshot_ref",
        "data_snapshot_digest",
        "source_run_id",
        "source_node_id",
        "source_artifact_id",
    ],
)
def test_host_port_rejects_operation_records_with_missing_identity_claim(missing_claim) -> None:
    original = _record()
    target = dict(original.target)
    preconditions = dict(original.preconditions)
    target.pop(missing_claim, None)
    preconditions.pop(missing_claim, None)
    record = replace(original, target=target, preconditions=preconditions)
    port = _port(lambda request: _output(record), _authority(record))

    with pytest.raises((TypeError, ValueError), match="claim|identity|missing|OperationRecord"):
        port.resolve(_typed_request())


def test_host_port_requires_server_issuer_and_preserves_unavailable_without_port() -> None:
    import workbench.data_operation_manifest as manifest

    with pytest.raises(TypeError, match="issuer|server"):
        manifest.DataConsumerHostOperationPortV1.from_server(
            lambda request: None,
            catalog_digest=load_builtin_catalog().catalog_digest,
            project_ref="project:data-host",
            session_ref="session:data-host",
            snapshot_ref="snapshot:data-host",
            snapshot_digest="b" * 64,
            operation_id="data.column.cast",
            operation_version="v1",
            source_run_id="run:data-host",
            source_node_id="node:data-host",
            source_artifact_id="artifact:source-data-host",
        )

    unavailable = manifest.build_data_consumer_runtime_contribution(load_builtin_catalog())
    assert unavailable.execution_allowed is False
    assert unavailable.metadata["status"] == "unavailable"


def test_host_port_execution_port_adapts_the_shared_runtime_request() -> None:
    from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1

    record = _record()
    port = _port(lambda request: _output(record), _authority(record))
    execution_port = port.as_execution_port()

    result = execution_port.execute(
        ProviderRuntimeContextV1(
            compilation_record_id="record:data-host",
            execution_instance_hash="execution-instance:data-host",
            actor_ref="principal:data-host",
            session_ref="session:data-host",
            project_ref="project:data-host",
            effect="read_only",
            evidence_required=True,
        ),
        {
            "capability_id": "workbench.data_consumer.capability",
            "target_ref": "run:data-host",
            "data_snapshot_ref": "snapshot:data-host",
            "source_text_digest": "source-text:data-host",
            "options": {"operation_id": "data.column.cast"},
        },
    )

    assert result.operation_id == "data.column.cast"
    assert result.record_id == "record:data-host"


def test_host_port_rejects_nested_raw_data_in_shared_runtime_options() -> None:
    from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1

    record = _record()
    port = _port(lambda request: _output(record), _authority(record))
    execution_port = port.as_execution_port()

    with pytest.raises(ValueError, match="raw data|rows"):
        execution_port.execute(
            ProviderRuntimeContextV1(
                compilation_record_id="record:data-host",
                execution_instance_hash="execution-instance:data-host",
                actor_ref="principal:data-host",
                session_ref="session:data-host",
                project_ref="project:data-host",
                effect="read_only",
                evidence_required=True,
            ),
            {
                "target_ref": "run:data-host",
                "data_snapshot_ref": "snapshot:data-host",
                "options": {
                    "operation_id": "data.column.cast",
                    "nested": {"rows": [{"x": 1}]},
                },
            },
        )


def test_host_port_is_reached_through_the_trusted_runtime_dispatch() -> None:
    from workbench.agent.trusted_executor_registry import (
        ProviderRuntimeContextV1,
        TrustedExecutorRegistry,
    )
    from workbench.agent.provider_runtime_contributions import build_builtin_runtime_contributions
    import workbench.data_operation_manifest as manifest

    catalog = load_builtin_catalog()
    record = _record()
    host_port = _port(lambda request: _output(record), _authority(record))
    contributions = build_builtin_runtime_contributions(
        catalog,
        data_consumer_execution_port=host_port.as_execution_port(),
    )
    registry = TrustedExecutorRegistry(contributions)
    registry.bind_catalog(catalog)

    result = registry.dispatch(
        "executor:workbench.data_consumer.adapter",
        ProviderRuntimeContextV1(
            compilation_record_id="record:data-host",
            execution_instance_hash="execution-instance:data-host",
            actor_ref="principal:data-host",
            session_ref="session:data-host",
            project_ref="project:data-host",
            effect="read_only",
            evidence_required=True,
        ),
        {
            "capability_id": "workbench.data_consumer.capability",
            "target_ref": "run:data-host",
            "data_snapshot_ref": "snapshot:data-host",
            "source_text_digest": "source-text:data-host",
            "options": {"operation_id": "data.column.cast"},
        },
        catalog_digest=catalog.catalog_digest,
    )

    assert result["status"] == "completed"
    assert result["output"]["record_id"] == "record:data-host"
