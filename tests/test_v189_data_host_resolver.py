from __future__ import annotations

from dataclasses import replace

import pytest

from workbench.agent.operations import OperationRecord
from workbench.agent.storage import append_jsonl_atomic
from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1
from workbench.canonical import sha256_canonical
from workbench.providers.catalog import load_builtin_catalog
from workbench.services.data_consumer_host_resolver import (
    DataConsumerHostResolverError,
    ServerOwnedDataConsumerHostResolverV1,
    build_server_owned_data_consumer_execution_port,
)


def _record(*, record_id: str = "oprec_data_host", operation_id: str = "data.column.cast") -> OperationRecord:
    execution_key = f"execution:{record_id}"
    derived = {
        "execution_key": execution_key,
        "artifact_id": f"artifact:{record_id}",
        "recipe_artifact_id": f"recipe:{record_id}",
        "child_node_id": f"node:{record_id}",
    }
    evidence = {
        "method": operation_id,
        "record_id": record_id,
        "operation_id": operation_id,
        "execution_key": execution_key,
        "child_node_id": derived["child_node_id"],
    }
    catalog_digest = load_builtin_catalog().catalog_digest
    return OperationRecord(
        record_id=record_id,
        operation_id=operation_id,
        operation_version="v1",
        proposal_id=f"proposal:{record_id}",
        proposal_revision=1,
        proposal_fingerprint="a" * 64,
        agent_session_id="session:data-host",
        chain_id="chain:data-host",
        command_id=f"command:{record_id}",
        target={
            "project_ref": "project:data-host",
            "run_id": "run:data-host",
            "node_ref": "source-node:data-host",
            "artifact_id": "source-artifact:data-host",
            "data_snapshot_ref": "snapshot:data-host",
            "source_run_id": "run:data-host",
            "source_node_id": "source-node:data-host",
            "source_artifact_id": "source-artifact:data-host",
        },
        preconditions={
            "project_ref": "project:data-host",
            "data_snapshot_ref": "snapshot:data-host",
        },
        actor_type="agent",
        status="completed",
        confirmation={"confirmed": True},
        execution={"execution_key": execution_key, "bindings": {
            "artifact_id": derived["artifact_id"],
            "recipe_artifact_id": derived["recipe_artifact_id"],
            "child_node_id": derived["child_node_id"],
        }},
        outputs={
            "ports": {
                "derived": derived,
                "operation_record": {
                    "record_id": record_id,
                    "operation_id": operation_id,
                    "operation_version": "v1",
                },
                "evidence": evidence,
            },
            "consumer_slots": {
                "data.agent": {"record_id": record_id, "port": "derived"},
                "data.notebook": {"record_id": record_id, "port": "derived"},
                "data.report": {"record_id": record_id, "port": "evidence"},
            },
            "catalog_digest": catalog_digest,
        },
        diff_ref={"kind": "data-consumer-effect.v1"},
        verification={"passed": True},
        effect_status="committed",
        projection_status="committed",
    )


def _write_record(root, record: OperationRecord) -> None:
    path = root / "workbench" / "operation-records" / f"{record.record_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl_atomic(path, record.to_dict())


def _context(*, project_ref: str = "project:data-host", session_ref: str = "session:data-host"):
    return ProviderRuntimeContextV1(
        compilation_record_id="compilation:data-host",
        execution_instance_hash="execution-instance:data-host",
        actor_ref="principal:data-host",
        session_ref=session_ref,
        project_ref=project_ref,
        effect="read_only",
        evidence_required=True,
    )


def _request(**overrides):
    request = {
        "capability_id": "workbench.data_consumer.capability",
        "target_ref": "run:data-host",
        "data_snapshot_ref": "snapshot:data-host",
        "source_text_digest": "source-text:data-host",
        "operation_id": "data.column.cast",
        "source_run_id": "run:data-host",
        "source_node_id": "source-node:data-host",
        "source_artifact_id": "source-artifact:data-host",
    }
    request.update(overrides)
    return request


def _port(root):
    return build_server_owned_data_consumer_execution_port(
        project_root=root,
        project_ref="project:data-host",
        session_ref="session:data-host",
        catalog_digest=load_builtin_catalog().catalog_digest,
    )


def test_server_owned_default_resolver_rehydrates_only_the_durable_typed_projection(tmp_path) -> None:
    _write_record(tmp_path, _record())

    result = _port(tmp_path).execute(_context(), _request())

    assert result.to_dict() == {
        "record_id": "oprec_data_host",
        "operation_id": "data.column.cast",
        "operation_version": "v1",
        "execution_key": "execution:oprec_data_host",
        "child_node_id": "node:oprec_data_host",
        "artifact_ids": ["artifact:oprec_data_host", "recipe:oprec_data_host"],
        "evidence_digest": sha256_canonical(result.to_dict() and {
            "method": "data.column.cast",
            "record_id": "oprec_data_host",
            "operation_id": "data.column.cast",
            "execution_key": "execution:oprec_data_host",
            "child_node_id": "node:oprec_data_host",
        }),
        "catalog_digest": load_builtin_catalog().catalog_digest,
    }


@pytest.mark.parametrize(
    ("context", "request_value", "code"),
    [
        (_context(project_ref="project:foreign"), _request(), "DATA_CONSUMER_HOST_SCOPE_MISMATCH"),
        (_context(), _request(rows=[{"x": 1}]), "DATA_CONSUMER_HOST_REQUEST_INVALID"),
        (_context(), _request(data_snapshot_ref="snapshot:stale"), "DATA_CONSUMER_HOST_RESULT_UNAVAILABLE"),
    ],
)
def test_default_resolver_fails_closed_for_scope_raw_and_stale_inputs(tmp_path, context, request_value, code) -> None:
    _write_record(tmp_path, _record())

    with pytest.raises(DataConsumerHostResolverError, match=code):
        _port(tmp_path).execute(context, request_value)


def test_default_resolver_rejects_ambiguous_durable_results(tmp_path) -> None:
    _write_record(tmp_path, _record())
    _write_record(tmp_path, replace(_record(record_id="oprec_data_host_2"), proposal_fingerprint="b" * 64))

    with pytest.raises(DataConsumerHostResolverError, match="DATA_CONSUMER_HOST_RESULT_AMBIGUOUS"):
        _port(tmp_path).execute(_context(), _request())


def test_default_resolver_rejects_malformed_or_uncommitted_output(tmp_path) -> None:
    record = _record()
    malformed = replace(record, outputs={"ports": {}, "consumer_slots": {}, "catalog_digest": record.outputs["catalog_digest"]})
    _write_record(tmp_path, malformed)

    with pytest.raises(DataConsumerHostResolverError, match="DATA_CONSUMER_HOST_RECORD_INVALID"):
        _port(tmp_path).execute(_context(), _request())


def test_resolver_factory_requires_the_server_issuer_and_absolute_root(tmp_path) -> None:
    import workbench.services.data_consumer_host_resolver as module
    from workbench.data_operation_manifest import _SERVER_OWNED_CAPABILITY

    with pytest.raises(TypeError, match="issuer"):
        ServerOwnedDataConsumerHostResolverV1.from_server(
            project_root=tmp_path,
            project_ref="project:data-host",
            session_ref="session:data-host",
            catalog_digest=load_builtin_catalog().catalog_digest,
        )
    with pytest.raises(ValueError, match="absolute"):
        ServerOwnedDataConsumerHostResolverV1(
            project_root=module.Path("relative"),
            project_ref="project:data-host",
            session_ref="session:data-host",
            catalog_digest=load_builtin_catalog().catalog_digest,
            _capability=_SERVER_OWNED_CAPABILITY,
        )
