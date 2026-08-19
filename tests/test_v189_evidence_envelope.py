from __future__ import annotations

import json
import hashlib
import hmac
import multiprocessing
import os
import pickle
import copy
import socket
import threading
import time
from itertools import count
from pathlib import Path
from unittest.mock import patch

import pytest

from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.contracts.common.envelope import ContractError
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.evidence.envelope import EvidenceEnvelopeV1
from workbench.contracts.evidence.persistence import EvidenceCommitRequestV1
from workbench.evidence.contracts import (
    ArtifactAdmissionV1,
    EvidenceEnvelopeFacadeV1,
    EvidenceCoreContractError,
    artifact_content_hash,
)
from workbench.evidence.persistence import (
    EvidencePacketStoreV1,
    EvidencePersistenceAdmissionV1,
    EvidencePersistenceError,
)
from workbench.evidence.authority import (
    EvidenceHostAuthorityError,
    HostAuthorityEndpointConfigV1,
    admit_host_authority_endpoint,
    admit_host_authority_fd,
    build_authority_request,
    issue_host_proof,
    validate_host_proof,
)
import workbench.evidence.authority as authority_module
from workbench.evidence.projection import (
    EvidenceProjectionError,
    EvidenceProjectionV1,
    EvidenceProjectionViewV1,
)
from workbench.evidence.registry import (
    EvidenceRegistryError,
    EvidenceRegistryV1 as _EvidenceRegistryV1,
    create_server_evidence_registry,
)


# All normal test fixtures must use an external host channel.  The mapping is
# test-owned plumbing so persistence tests can pass the same host handle that
# admitted the registry; production Evidence never uses this fallback.
_TEST_AUTHORITY_BY_REGISTRY: dict[int, object] = {}


def _test_registry_factory(*, scope_ref: str):
    host = _ExternalHostAuthority(scope_ref)
    registry = create_server_evidence_registry(scope_ref=scope_ref, authority_handle=host.channel)
    _TEST_AUTHORITY_BY_REGISTRY[id(registry)] = host.channel
    return registry


def _host_for(registry: object) -> object:
    return _TEST_AUTHORITY_BY_REGISTRY[id(registry)]


def _admit_store(root: Path, registry: object):
    return EvidencePacketStoreV1.admit(
        root,
        authority_handle=_host_for(registry),
        scope_ref=registry.scope_ref,  # type: ignore[attr-defined]
    )


EvidenceRegistryV1 = _test_registry_factory


def _admit_test_host_endpoint(
    channel: socket.socket,
    config: HostAuthorityEndpointConfigV1,
):
    """Model supervisor-owned configuration without widening production API."""

    with patch.object(
        authority_module,
        "_deployment_config_from_supervisor",
        return_value=config,
    ):
        return admit_host_authority_endpoint(channel)


def _admit_test_host_fd(
    fd: int,
    config: HostAuthorityEndpointConfigV1,
):
    """Model a supervisor-passed descriptor and resolver snapshot."""

    with patch.object(
        authority_module,
        "_deployment_config_from_supervisor",
        return_value=config,
    ):
        return admit_host_authority_fd(fd)


FIXTURE = Path(__file__).parent / "fixtures" / "contracts" / "v189" / "evidence_envelope.json"
CORRUPT_FIXTURE = (
    Path(__file__).parent / "fixtures" / "contracts" / "v189" / "evidence_corrupt.json"
)


def _load(path: Path = FIXTURE) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _reasons(code: str) -> list[dict[str, object]]:
    return [{"code": code, "message": f"{code} is explicit.", "source_refs": [f"source:{code}"]}]


def _blocked_payload() -> dict[str, object]:
    payload = _load()
    payload.update(
        {
            "execution_status": "blocked",
            "availability": "not_available",
            "completeness_status": "insufficient",
            "execution_reasons": _reasons("POLICY_BLOCK"),
            "availability_reasons": _reasons("EVIDENCE_UNAVAILABLE"),
            "degradation_reasons": _reasons("EVIDENCE_INSUFFICIENT"),
            "numeric_facts": [],
            "figures": [],
            "validation_summary": {
                "levels_present": [],
                "minimum_required": "none",
                "requirement_status": "not_applicable",
            },
        }
    )
    return payload


def _admit(
    registry: EvidenceRegistryV1,
    payload: dict[str, object] | None = None,
    *,
    artifact_id: str = "artifact:evidence:1",
    scope_ref: str = "scope:project:1",
    source_ref: str = "source:dataset:1",
    validator_ref: object = "validator:evidence-envelope:1",
    execution_ref: str = "execution:run:1",
    contract_digest: str = "c" * 64,
):
    return registry.admit_artifact(
        artifact_id=artifact_id,
        artifact_type="evidence-envelope",
        scope_ref=scope_ref,
        content=_load() if payload is None else payload,
        source_ref=source_ref,
        validator_ref=validator_ref,
        execution_ref=execution_ref,
        contract_digest=contract_digest,
    )


def test_strict_facade_roundtrips_canonically_and_preserves_locked_contract() -> None:
    payload = _load()
    facade = EvidenceEnvelopeFacadeV1.from_dict(payload)

    assert type(facade.envelope) is EvidenceEnvelopeV1
    assert facade.to_dict() == payload
    assert facade.canonical_bytes() == canonical_json_v1(payload).encode("utf-8")
    assert facade.content_hash == sha256_canonical(payload)
    assert EvidenceEnvelopeFacadeV1.from_bytes(facade.canonical_bytes()) == facade

    with pytest.raises(EvidenceCoreContractError):
        EvidenceEnvelopeFacadeV1.from_dict({**payload, "unknown": "must fail"})
    with pytest.raises(EvidenceCoreContractError):
        EvidenceEnvelopeFacadeV1.from_bytes(b'{"execution_status":"completed"}')


def test_numeric_fact_contract_requires_denominator_scale_inference_and_source() -> None:
    fact = _load()["numeric_facts"][0]  # type: ignore[index]
    for field in ("denominator", "scale", "reference_distribution", "source_selector"):
        missing = dict(fact)
        missing.pop(field)
        with pytest.raises(ContractError):
            EvidenceEnvelopeV1.from_dict({**_load(), "numeric_facts": [missing]})


def test_registry_admits_immutable_identity_and_keeps_family_and_bindings() -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    payload = _load()
    record = _admit(registry, payload)

    assert record.artifact_id == "artifact:evidence:1"
    assert record.scope_ref == "scope:project:1"
    assert record.content_hash == artifact_content_hash(
        artifact_id=record.artifact_id,
        artifact_type=record.artifact_type,
        scope_ref=record.scope_ref,
        source_ref=record.source_ref,
        validator_ref=record.validator_ref,
        execution_ref=record.execution_ref,
        contract_digest=record.contract_digest,
        envelope=record.envelope,
    )
    assert record.content_hash != sha256_canonical(payload)
    assert record.source_ref == "source:dataset:1"
    assert record.validator_ref == "validator:evidence-envelope:1"
    assert record.execution_ref == "execution:run:1"
    assert record.contract_digest == "c" * 64
    assert record.family_evidence["model_family"] == "ols"
    assert registry.resolve(record.artifact_id) is record

    payload["family_evidence"]["model_family"] = "forged"  # type: ignore[index]
    assert registry.resolve(record.artifact_id).family_evidence["model_family"] == "ols"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: {**payload, "result_identity": {**payload["result_identity"], "result_id": "forged"}},  # type: ignore[index]
        lambda payload: {**payload, "numeric_facts": []},
        lambda payload: {**payload, "family_evidence": {"model_family": "other"}},
    ],
)
def test_registry_rejects_mutation_of_an_existing_immutable_identity(mutation) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    _admit(registry)

    with pytest.raises(EvidenceRegistryError):
        _admit(registry, mutation(_load()))


def test_registry_fails_closed_for_missing_corrupt_unknown_and_cross_scope_artifacts() -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    with pytest.raises(EvidenceRegistryError):
        registry.resolve("artifact:missing")
    with pytest.raises(EvidenceRegistryError):
        _admit(registry, _load(CORRUPT_FIXTURE))

    record = _admit(registry)
    with pytest.raises(EvidenceRegistryError):
        registry.resolve(record.artifact_id, scope_ref="scope:project:other")
    with pytest.raises(EvidenceRegistryError):
        registry.admit_artifact(
            artifact_id="artifact:other-scope",
            artifact_type="evidence-envelope",
            scope_ref="scope:project:other",
            content=_load(),
            source_ref="source:dataset:1",
            validator_ref="validator:evidence-envelope:1",
            execution_ref="execution:run:1",
            contract_digest="c" * 64,
        )


def test_projection_never_guesses_or_reexecutes_and_preserves_all_status_axes() -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry)
    projection = EvidenceProjectionV1(registry)

    view = projection.project(record.artifact_id)
    assert view.success is True
    assert view.execution_status == "completed"
    assert view.availability == "available"
    assert view.completeness_status == "complete"
    assert view.family_evidence == {"model_family": "ols"}
    assert view.source_ref == record.source_ref
    assert view.validator_ref == record.validator_ref
    assert view.execution_ref == record.execution_ref
    assert view.contract_digest == record.contract_digest
    assert view.facts[0]["value"] == 2.0
    assert view.facts[0]["validation_level"] == "same_library_regression"
    assert view.facts[0]["oracle_checks"][0]["basis"] == "same_library_regression"  # type: ignore[index]
    assert view.facts[1]["validation_level"] == "independent_implementation"


def test_degraded_is_completeness_only_and_fact_validation_does_not_promote_envelope() -> None:
    payload = _load()
    payload.update(
        {
            "completeness_status": "degraded",
            "degradation_reasons": _reasons("MISSING_DIAGNOSTIC"),
        }
    )
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, payload, artifact_id="artifact:degraded")
    view = EvidenceProjectionV1(registry).project(record.artifact_id)

    assert view.success is True
    assert view.execution_status == "completed"
    assert view.availability == "available"
    assert view.completeness_status == "degraded"
    assert view.validation_summary["minimum_required"] == "same_library_regression"
    assert view.validation_summary["requirement_status"] == "met"


def test_fact_validation_does_not_upgrade_partial_execution() -> None:
    payload = _load()
    payload.update(
        {
            "execution_status": "partial",
            "execution_reasons": _reasons("MISSING_EXECUTION_STAGE"),
            "completeness_status": "degraded",
            "degradation_reasons": _reasons("MISSING_DIAGNOSTIC"),
        }
    )
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, payload, artifact_id="artifact:partial")

    assert record.envelope.numeric_facts[1].validation_level == "independent_implementation"
    with pytest.raises(EvidenceProjectionError) as exc_info:
        EvidenceProjectionV1(registry).project(record.artifact_id)
    assert exc_info.value.code == "EVIDENCE_EXECUTION_PARTIAL"


def test_blocked_evidence_cannot_project_as_success() -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, _blocked_payload(), artifact_id="artifact:blocked")
    projection = EvidenceProjectionV1(registry)

    with pytest.raises(EvidenceProjectionError):
        projection.project(record.artifact_id)
    outcome = projection.try_project(record.artifact_id)
    assert outcome.success is False
    assert outcome.status == "blocked"
    assert outcome.failure_receipt is not None


def test_corrupt_evidence_is_rejected_before_projection() -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")

    with pytest.raises(EvidenceRegistryError) as exc_info:
        _admit(registry, _load(CORRUPT_FIXTURE), artifact_id="artifact:corrupt")

    assert exc_info.value.code == "EVIDENCE_CORRUPT"


def test_persistence_is_admission_gated_fd_safe_canonical_and_idempotent(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry)

    with _admit_store(tmp_path, registry) as store:
        receipt = registry.persistence_receipt(record)
        binding = store.commit(record, receipt=receipt)
        replay = store.commit(record, receipt=receipt)
        assert replay == binding

        packet_files = sorted((tmp_path / "packets").glob("*.json"))
        assert len(packet_files) == 1
        packet_bytes = packet_files[0].read_bytes()
        assert packet_bytes == canonical_json_v1(json.loads(packet_bytes)).encode("utf-8")
        assert b"source_path" not in packet_bytes
        assert b"/tmp" not in packet_bytes

        index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
        assert all("path" not in item and "source_path" not in item for item in index["artifacts"])
        assert store.load(binding.commit_id, registry=registry, receipt=receipt) == binding
        assert store.load_packet(binding.commit_id, registry=registry, receipt=receipt) == record

    with pytest.raises(EvidencePersistenceError):
        EvidencePacketStoreV1(tmp_path)  # type: ignore[arg-type]


def test_persistence_rejects_replay_conflict_and_packet_tampering(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry)

    with _admit_store(tmp_path, registry) as store:
        binding = store.commit(record, receipt=registry.persistence_receipt(record))
        packet_path = next((tmp_path / "packets").glob("*.json"))
        original_packet = packet_path.read_bytes()
        packet_path.write_bytes(original_packet.replace(b'"complete"', b'"degraded"', 1))
        with pytest.raises(EvidencePersistenceError):
            store.commit(record, receipt=registry.persistence_receipt(record))
        packet_path.write_bytes(original_packet)

        index_path = tmp_path / "index.json"
        original_index = index_path.read_bytes()
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["artifacts"][0]["artifact_id"] = "artifact:forged"  # type: ignore[index]
        index_path.write_text(canonical_json_v1(index), encoding="utf-8")
        with pytest.raises(EvidencePersistenceError) as index_exc:
            store.load(binding.commit_id, registry=registry, receipt=registry.persistence_receipt(record))
        assert index_exc.value.code == "EVIDENCE_PERSISTENCE_INDEX_TAMPERED"
        index_path.write_bytes(original_index)

        packet_path.write_bytes(packet_path.read_bytes().replace(b'"complete"', b'"degraded"', 1))
        with pytest.raises(EvidencePersistenceError):
            store.load(binding.commit_id, registry=registry, receipt=registry.persistence_receipt(record))


def test_independent_store_instances_preserve_index_under_a_controlled_race(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    first = _admit(registry, artifact_id="artifact:evidence:first")
    second = _admit(registry, artifact_id="artifact:evidence:second")
    first_store = _admit_store(tmp_path, registry)
    second_store = _admit_store(tmp_path, registry)
    first_loaded = threading.Event()
    second_loaded = threading.Event()
    release_first = threading.Event()
    original_load_index = EvidencePacketStoreV1._load_index

    def controlled_load_index(store: EvidencePacketStoreV1):
        value = original_load_index(store)
        if store is first_store:
            first_loaded.set()
            assert release_first.wait(timeout=5)
        elif store is second_store:
            second_loaded.set()
        return value

    errors: list[BaseException] = []

    def commit(store: EvidencePacketStoreV1, record) -> None:
        try:
            store.commit(record, receipt=registry.persistence_receipt(record))
        except BaseException as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)

    try:
        with patch.object(EvidencePacketStoreV1, "_load_index", controlled_load_index):
            first_thread = threading.Thread(target=commit, args=(first_store, first))
            second_thread = threading.Thread(target=commit, args=(second_store, second))
            first_thread.start()
            assert first_loaded.wait(timeout=5)
            second_thread.start()
            second_reached_load = second_loaded.wait(timeout=0.5)
            if second_reached_load:
                second_thread.join(timeout=5)
            release_first.set()
            first_thread.join(timeout=5)
            second_thread.join(timeout=5)
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert errors == []
        index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
        assert {row["artifact_id"] for row in index["artifacts"]} == {
            first.artifact_id,
            second.artifact_id,
        }
    finally:
        first_store.close()
        second_store.close()


def _process_commit(root: str, artifact_id: str, result_queue) -> None:
    try:
        registry = EvidenceRegistryV1(scope_ref="scope:project:1")
        record = _admit(registry, artifact_id=artifact_id)
        with _admit_store(Path(root), registry) as store:
            store.commit(record, receipt=registry.persistence_receipt(record))
        result_queue.put(None)
    except BaseException as exc:  # pragma: no cover - surfaced by the parent
        result_queue.put(f"{type(exc).__name__}:{exc}")


def _process_load_without_receipt(root: str, commit_id: str, result_queue) -> None:
    try:
        registry = EvidenceRegistryV1(scope_ref="scope:project:1")
        with _admit_store(Path(root), registry) as store:
            store.load(commit_id, registry=registry)
        result_queue.put("accepted")
    except EvidencePersistenceError as exc:
        result_queue.put(exc.code)
    except BaseException as exc:  # pragma: no cover - surfaced by the assertion below
        result_queue.put(f"{type(exc).__name__}:{exc}")


def _process_use_parent_admission(admission, result_queue) -> None:
    try:
        EvidencePacketStoreV1(admission)
        result_queue.put("accepted")
    except EvidencePersistenceError as exc:
        result_queue.put(exc.code)
    except BaseException as exc:  # pragma: no cover - surfaced by the assertion below
        result_queue.put(f"{type(exc).__name__}:{exc}")


def test_independent_processes_preserve_every_index_entry(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_process_commit,
            args=(str(tmp_path), f"artifact:process:{index}", result_queue),
        )
        for index in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
    assert all(process.exitcode == 0 for process in processes)
    assert [result_queue.get(timeout=2) for _ in processes] == [None] * len(processes)
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert {row["artifact_id"] for row in index["artifacts"]} == {
        f"artifact:process:{index}" for index in range(4)
    }


def test_persistence_admission_proof_cannot_cross_process_owner(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    admission = EvidencePersistenceAdmissionV1.admit(
        tmp_path,
        authority_handle=_host_for(registry),
        scope_ref=registry.scope_ref,
    )
    context = multiprocessing.get_context("fork")
    result_queue = context.Queue()
    process = context.Process(target=_process_use_parent_admission, args=(admission, result_queue))
    try:
        process.start()
        process.join(timeout=10)
        assert process.exitcode == 0
        assert result_queue.get(timeout=2) == "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"
    finally:
        admission.close()


def test_commit_and_packet_binding_cannot_be_pairwise_forged(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry)

    with _admit_store(tmp_path, registry) as store:
        binding = store.commit(record, receipt=registry.persistence_receipt(record))
        digest = binding.commit_id.removeprefix("commit:evidence:")
        forged_request = EvidenceCommitRequestV1(
            artifact_admission_ref=binding.artifact_admission_ref,
            projector_ref=binding.projector_ref,
            envelope_digest=binding.envelope_digest,
            idempotency_key="forged-idempotency",
            supersedes_ref=binding.supersedes_ref,
            invalidation_refs=binding.invalidation_refs,
        )
        commit_path = tmp_path / "commits" / f"{digest}.json"
        packet_path = tmp_path / "packets" / f"{digest}.json"
        commit = json.loads(commit_path.read_text(encoding="utf-8"))
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        commit["idempotency_key"] = forged_request.idempotency_key
        commit["request_digest"] = forged_request.request_digest
        packet["payload"]["binding"]["idempotency_key"] = forged_request.idempotency_key
        packet["payload"]["binding"]["request_digest"] = forged_request.request_digest
        commit_path.write_text(canonical_json_v1(commit), encoding="utf-8")
        packet_path.write_text(canonical_json_v1(packet), encoding="utf-8")

        with pytest.raises(EvidencePersistenceError) as exc_info:
            store.load(binding.commit_id, registry=registry, receipt=registry.persistence_receipt(record))
        assert exc_info.value.code == "EVIDENCE_PERSISTENCE_PACKET_TAMPERED"


def test_persistence_rejects_publicly_constructed_record_without_registry_receipt(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    admitted = _admit(registry)
    direct = ArtifactAdmissionV1(
        artifact_id=admitted.artifact_id,
        artifact_type=admitted.artifact_type,
        scope_ref=admitted.scope_ref,
        content_hash=admitted.content_hash,
        source_ref=admitted.source_ref,
        validator_ref=admitted.validator_ref,
        execution_ref=admitted.execution_ref,
        contract_digest=admitted.contract_digest,
        envelope=admitted.envelope,
    )

    with _admit_store(tmp_path, registry) as store:
        with pytest.raises(EvidencePersistenceError) as exc_info:
            store.commit(direct)
    assert exc_info.value.code == "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"


def test_registry_receipt_rejects_wrong_registry_and_forged_token(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry)
    receipt = registry.persistence_receipt(record)

    other_registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    other_record = _admit(other_registry)
    wrong_receipt = other_registry.persistence_receipt(other_record)

    with _admit_store(tmp_path, registry) as store:
        with pytest.raises(EvidencePersistenceError) as wrong_exc:
            store.commit(record, receipt=wrong_receipt)
        assert wrong_exc.value.code == "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"
        with pytest.raises(EvidencePersistenceError) as forged_exc:
            store.commit(record, receipt=object())
        assert forged_exc.value.code == "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"
        store.commit(record, receipt=receipt)


def test_persistence_load_requires_the_owning_registry_and_receipt(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, artifact_id="artifact:load-authority")
    receipt = registry.persistence_receipt(record)

    with _admit_store(tmp_path, registry) as store:
        binding = store.commit(record, receipt=receipt)
        with pytest.raises(EvidencePersistenceError) as missing_exc:
            store.load(binding.commit_id)
        assert missing_exc.value.code == "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"

        wrong_registry = EvidenceRegistryV1(scope_ref="scope:project:1")
        with pytest.raises(EvidencePersistenceError) as wrong_exc:
            store.load(binding.commit_id, registry=wrong_registry, receipt=receipt)
        assert wrong_exc.value.code == "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"

        with pytest.raises(EvidencePersistenceError) as forged_exc:
            store.load(binding.commit_id, registry=registry, receipt=object())
        assert forged_exc.value.code == "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"

        assert store.load(binding.commit_id, registry=registry, receipt=receipt) == binding
        assert store.load_packet(binding.commit_id, registry=registry, receipt=receipt) == record


def test_registry_receipt_cannot_be_reconstructed_as_a_cross_process_credential() -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, artifact_id="artifact:receipt-boundary")
    receipt = registry.persistence_receipt(record)

    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.dumps(receipt)


def test_load_without_a_process_local_receipt_fails_closed(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, artifact_id="artifact:cross-process-load")
    with _admit_store(tmp_path, registry) as store:
        binding = store.commit(record, receipt=registry.persistence_receipt(record))

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_process_load_without_receipt,
        args=(str(tmp_path), binding.commit_id, result_queue),
    )
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 0
    assert result_queue.get(timeout=2) == "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"


@pytest.mark.parametrize("field", [
    "artifact_id",
    "artifact_type",
    "scope_ref",
    "source_ref",
    "validator_ref",
    "execution_ref",
    "contract_digest",
])
def test_packet_metadata_tampering_is_rejected_on_load(tmp_path: Path, field: str) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry)

    with _admit_store(tmp_path, registry) as store:
        binding = store.commit(record, receipt=registry.persistence_receipt(record))
        packet_path = next((tmp_path / "packets").glob("*.json"))
        original = packet_path.read_bytes()
        packet = json.loads(original)
        artifact = packet["payload"]["artifact"]
        artifact[field] = {
            "artifact_id": "artifact:forged",
            "artifact_type": "forged-type",
            "scope_ref": "scope:project:forged",
            "source_ref": "source:forged",
            "validator_ref": "validator:forged",
            "execution_ref": "execution:forged",
            "contract_digest": "d" * 64,
        }[field]
        packet_path.write_bytes(canonical_json_v1(packet).encode("utf-8"))
        with pytest.raises(EvidencePersistenceError) as exc_info:
            store.load_packet(binding.commit_id, registry=registry, receipt=registry.persistence_receipt(record))
        assert exc_info.value.code == "EVIDENCE_PERSISTENCE_PACKET_TAMPERED"
        packet_path.write_bytes(original)


@pytest.mark.parametrize("field", [
    "artifact_id",
    "artifact_type",
    "scope_ref",
    "source_ref",
    "validator_ref",
    "execution_ref",
    "contract_digest",
])
def test_index_metadata_tampering_is_rejected_on_load(tmp_path: Path, field: str) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry)

    with _admit_store(tmp_path, registry) as store:
        binding = store.commit(record, receipt=registry.persistence_receipt(record))
        index_path = tmp_path / "index.json"
        original = index_path.read_bytes()
        index = json.loads(original)
        row = index["artifacts"][0]
        row[field] = {
            "artifact_id": "artifact:forged",
            "artifact_type": "forged-type",
            "scope_ref": "scope:project:forged",
            "source_ref": "source:forged",
            "validator_ref": "validator:forged",
            "execution_ref": "execution:forged",
            "contract_digest": "d" * 64,
        }[field]
        index_path.write_bytes(canonical_json_v1(index).encode("utf-8"))
        with pytest.raises(EvidencePersistenceError) as exc_info:
            store.load(binding.commit_id, registry=registry, receipt=registry.persistence_receipt(record))
        assert exc_info.value.code == "EVIDENCE_PERSISTENCE_INDEX_TAMPERED"
        index_path.write_bytes(original)


@pytest.mark.parametrize("source_ref", [
    "/Users/secret/raw.csv",
    "relative/path.csv",
    r"relative\\path.csv",
    "https://example.com/data.csv",
    "../data.csv",
    "relative.csv",
])
def test_path_like_source_refs_are_rejected_before_persistence(source_ref: str) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    with pytest.raises(EvidenceRegistryError):
        _admit(registry, source_ref=source_ref)


@pytest.mark.parametrize(
    "reference",
    [
        "/tmp/oracle.json",
        "relative/oracle.json",
        r"relative\\oracle.json",
        "https://example.com/oracle.json",
        "oracle.json",
        "www.example.com",
    ],
)
def test_oracle_check_reference_uses_the_closed_opaque_grammar(reference: str) -> None:
    payload = _load()
    payload["numeric_facts"][0]["oracle_checks"][0]["reference"] = reference  # type: ignore[index]

    with pytest.raises(EvidenceRegistryError):
        _admit(EvidenceRegistryV1(scope_ref="scope:project:1"), payload, artifact_id="artifact:oracle-ref")


@pytest.mark.parametrize(
    "logical_id",
    [
        "validator/path",
        r"validator\\path",
        "https://example.com/validator",
        "../validator",
        "relative.csv",
        "www.example.com",
    ],
)
def test_path_like_contract_ref_provenance_is_rejected_before_persistence(logical_id: str) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    validator_ref = ContractRefV1(
        kind="validator",
        logical_id=logical_id,
        semantic_version="1.0",
        contract_digest="d" * 64,
    )
    with pytest.raises(EvidenceRegistryError):
        _admit(registry, validator_ref=validator_ref)


def test_nested_structured_reference_uses_the_same_closed_opaque_grammar() -> None:
    payload = _load()
    payload["dependencies"][0]["validator_ref"] = {  # type: ignore[index]
        "kind": "validator",
        "logical_id": "relative.csv",
        "semantic_version": "1.0",
        "contract_digest": "d" * 64,
    }
    with pytest.raises(EvidenceRegistryError):
        _admit(EvidenceRegistryV1(scope_ref="scope:project:1"), payload, artifact_id="artifact:nested-ref")


def test_c0_original_path_provenance_is_rejected_before_persistence() -> None:
    payload = _load()
    payload["input_provenance"]["original_path"] = "/Users/secret/raw.csv"  # type: ignore[index]
    with pytest.raises(EvidenceRegistryError):
        _admit(EvidenceRegistryV1(scope_ref="scope:project:1"), payload)


def test_root_fd_lock_cannot_be_split_by_replacing_the_lock_path(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    first = _admit(registry, artifact_id="artifact:lock:first")
    second = _admit(registry, artifact_id="artifact:lock:second")
    first_store = _admit_store(tmp_path, registry)
    second_store = _admit_store(tmp_path, registry)
    first_loaded = threading.Event()
    second_loaded = threading.Event()
    release_first = threading.Event()
    original_load_index = EvidencePacketStoreV1._load_index
    errors: list[BaseException] = []

    def controlled_load_index(store: EvidencePacketStoreV1):
        value = original_load_index(store)
        if store is first_store:
            first_loaded.set()
            assert release_first.wait(timeout=5)
        elif store is second_store:
            second_loaded.set()
        return value

    def commit(store: EvidencePacketStoreV1, record) -> None:
        try:
            store.commit(record, receipt=registry.persistence_receipt(record))
        except BaseException as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)

    try:
        with patch.object(EvidencePacketStoreV1, "_load_index", controlled_load_index):
            first_thread = threading.Thread(target=commit, args=(first_store, first))
            second_thread = threading.Thread(target=commit, args=(second_store, second))
            first_thread.start()
            assert first_loaded.wait(timeout=5)

            lock_path = tmp_path / ".evidence-index.lock"
            lock_path.unlink(missing_ok=True)
            lock_path.write_text("attacker-owned lock domain", encoding="utf-8")

            second_thread.start()
            assert not second_loaded.wait(timeout=0.75)
            release_first.set()
            first_thread.join(timeout=5)
            second_thread.join(timeout=5)

        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert errors == []
        index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
        assert {row["artifact_id"] for row in index["artifacts"]} == {
            first.artifact_id,
            second.artifact_id,
        }
    finally:
        release_first.set()
        first_store.close()
        second_store.close()


def test_failed_index_admission_rolls_back_new_packet_and_commit(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, artifact_id="artifact:index-rollback")
    receipt = registry.persistence_receipt(record)

    with _admit_store(tmp_path, registry) as store:
        with patch.object(
            EvidencePacketStoreV1,
            "_replace_index",
            side_effect=EvidencePersistenceError("EVIDENCE_PERSISTENCE_WRITE_FAILED"),
        ):
            with pytest.raises(EvidencePersistenceError) as exc_info:
                store.commit(record, receipt=receipt)
        assert exc_info.value.code == "EVIDENCE_PERSISTENCE_WRITE_FAILED"
        assert not list((tmp_path / "packets").glob("*.json"))
        assert not list((tmp_path / "commits").glob("*.json"))
        with pytest.raises(EvidencePersistenceError):
            store.load(
                f"commit:evidence:{record.content_hash}",
                registry=registry,
                receipt=receipt,
            )


@pytest.mark.parametrize("container", ["packet", "index"])
@pytest.mark.parametrize("version_field", ["contract_version", "producer_version"])
def test_persistence_rejects_forged_packet_and_index_versions(
    tmp_path: Path, container: str, version_field: str
) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry)

    with _admit_store(tmp_path, registry) as store:
        binding = store.commit(record, receipt=registry.persistence_receipt(record))
        path = (
            next((tmp_path / "packets").glob("*.json"))
            if container == "packet"
            else tmp_path / "index.json"
        )
        original = path.read_bytes()
        value = json.loads(original)
        value[version_field] = "9.9-forged"
        path.write_bytes(canonical_json_v1(value).encode("utf-8"))
        with pytest.raises(EvidencePersistenceError):
            store.load(
                binding.commit_id,
                registry=registry,
                receipt=registry.persistence_receipt(record),
            )
        path.write_bytes(original)


def test_invalid_artifact_id_becomes_stable_projection_failure() -> None:
    projection = EvidenceProjectionV1(EvidenceRegistryV1(scope_ref="scope:project:1"))
    outcome = projection.try_project("../not-an-artifact")
    assert outcome.success is False
    assert outcome.status == "unknown_artifact"
    assert outcome.failure_receipt is not None
    assert outcome.failure_receipt.artifact_id is None


def test_projection_is_deeply_immutable() -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry)
    view = EvidenceProjectionV1(registry).project(record.artifact_id)

    with pytest.raises(TypeError):
        view.facts[0]["oracle_checks"][0]["status"] = "fail"  # type: ignore[index]
    with pytest.raises(TypeError):
        view.facts[0]["source_selector"]["artifact_ref"] = "artifact:forged"  # type: ignore[index]
    with pytest.raises(TypeError):
        view.figures[0]["numeric_source_fact_ids"][0] = "fact:forged"  # type: ignore[index]


def test_public_projection_view_constructor_cannot_forge_a_successful_result() -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry)
    view = EvidenceProjectionV1(registry).project(record.artifact_id)
    values = {name: getattr(view, name) for name in view.__dataclass_fields__ if not name.startswith("_")}

    with pytest.raises(TypeError):
        EvidenceProjectionViewV1(**values)


def test_public_persistence_admission_constructor_cannot_bypass_server_admission(tmp_path: Path) -> None:
    raw_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        with pytest.raises(EvidencePersistenceError) as exc_info:
            EvidencePersistenceAdmissionV1(raw_fd)
        assert exc_info.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        os.close(raw_fd)


def test_public_registry_constructor_and_object_new_cannot_issue_durable_authority() -> None:
    with pytest.raises(EvidenceRegistryError) as direct_exc:
        _EvidenceRegistryV1(scope_ref="scope:project:1")
    assert direct_exc.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"

    forged = object.__new__(_EvidenceRegistryV1)
    object.__setattr__(forged, "_scope_ref", "scope:project:1")
    with pytest.raises(EvidenceRegistryError) as forged_exc:
        forged.admit_artifact(
            artifact_id="artifact:forged-registry",
            artifact_type="evidence-envelope",
            scope_ref="scope:project:1",
            content=_load(),
            source_ref="source:dataset:1",
            validator_ref="validator:evidence-envelope:1",
            execution_ref="execution:run:1",
            contract_digest="c" * 64,
        )
    assert forged_exc.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"


def test_forged_registry_cannot_load_a_self_consistent_packet_before_durable_read(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, artifact_id="artifact:forged-registry-load")
    receipt = registry.persistence_receipt(record)

    with _admit_store(tmp_path, registry) as store:
        binding = store.commit(record, receipt=receipt)
        forged = object.__new__(_EvidenceRegistryV1)
        for name in _EvidenceRegistryV1.__slots__:
            if hasattr(registry, name):
                object.__setattr__(forged, name, getattr(registry, name))

        with patch.object(
            EvidencePacketStoreV1,
            "_read_bytes",
            side_effect=AssertionError("forged registry must be rejected before durable read"),
        ):
            with pytest.raises(EvidencePersistenceError) as exc_info:
                store.load(binding.commit_id, registry=forged, receipt=receipt)
        assert exc_info.value.code == "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"


def test_object_new_persistence_admission_cannot_write_even_with_copied_fields(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, artifact_id="artifact:forged-admission")
    real_admission = EvidencePersistenceAdmissionV1.admit(
        tmp_path,
        authority_handle=_host_for(registry),
        scope_ref=registry.scope_ref,
    )
    forged = object.__new__(EvidencePersistenceAdmissionV1)
    try:
        for name in EvidencePersistenceAdmissionV1.__slots__:
            if hasattr(real_admission, name):
                value = getattr(real_admission, name)
                if name == "_root_fd":
                    value = os.dup(value)
                object.__setattr__(forged, name, value)

        with pytest.raises(EvidencePersistenceError) as exc_info:
            EvidencePacketStoreV1(forged).commit(
                record,
                receipt=registry.persistence_receipt(record),
            )
        assert exc_info.value.code == "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"
        assert not list(tmp_path.rglob("*.json"))
    finally:
        forged.close()
        real_admission.close()


def test_malformed_registry_receipt_is_typed_and_rejected_before_packet_read(tmp_path: Path) -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, artifact_id="artifact:malformed-receipt")
    receipt = registry.persistence_receipt(record)

    with _admit_store(tmp_path, registry) as store:
        binding = store.commit(record, receipt=receipt)
        malformed = object.__new__(type(receipt))
        with patch.object(
            EvidencePacketStoreV1,
            "_read_bytes",
            side_effect=AssertionError("malformed receipt must be rejected before durable read"),
        ):
            with pytest.raises(EvidencePersistenceError) as exc_info:
                store.load(binding.commit_id, registry=registry, receipt=malformed)
        assert exc_info.value.code == "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED"


def test_recomputed_projection_receipt_cannot_forge_an_available_view() -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, artifact_id="artifact:recomputed-projection")
    view = EvidenceProjectionV1(registry).project(record.artifact_id)
    forged_values = {
        name: getattr(view, name)
        for name in view.__dataclass_fields__
        if not name.startswith("_")
    }
    forged_values["artifact_id"] = "artifact:forged-available"
    forged_payload = view.to_dict()
    forged_payload["artifact_id"] = forged_values["artifact_id"]
    forged_receipt = object.__new__(type(view._receipt))
    for name in type(view._receipt).__slots__:
        if hasattr(view._receipt, name):
            object.__setattr__(forged_receipt, name, getattr(view._receipt, name))

    with pytest.raises(TypeError):
        EvidenceProjectionViewV1(**forged_values, _receipt=forged_receipt)


def test_object_new_projection_outcome_cannot_claim_success_without_server_receipt() -> None:
    registry = EvidenceRegistryV1(scope_ref="scope:project:1")
    record = _admit(registry, artifact_id="artifact:forged-outcome")
    outcome = EvidenceProjectionV1(registry).try_project(record.artifact_id)
    forged = object.__new__(type(outcome))
    object.__setattr__(forged, "success", True)
    object.__setattr__(forged, "status", "available")
    object.__setattr__(forged, "view", outcome.view)
    object.__setattr__(forged, "failure_receipt", None)

    with pytest.raises(TypeError):
        forged.to_dict()


def test_registry_and_projection_reject_unknown_artifact_without_rerun() -> None:
    projection = EvidenceProjectionV1(EvidenceRegistryV1(scope_ref="scope:project:1"))
    with pytest.raises(EvidenceProjectionError):
        projection.project("artifact:unknown")
    outcome = projection.try_project("artifact:unknown")
    assert outcome.success is False
    assert outcome.status == "unknown_artifact"
    assert "rerun" not in outcome.failure_receipt.message.lower()


def test_provider_manifest_is_declaration_only_and_loads_with_builtin_catalog() -> None:
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    provider = next(item for item in catalog.providers if item.provider_id == "evidence.core")
    assert provider.provider_id == "evidence.core"
    assert provider.exposure_paths[0].projection_refs
    assert provider.adapter_declarations[0].executor_ref.startswith("executor:")


class _ForgedStructuralHost:
    """A caller-created object that must not count as a host channel."""

    session_ref = "forged-session"

    def issue_evidence_proof(self, request: object) -> object:
        return object()

    def validate_evidence_proof(self, request: object, proof: object) -> bool:
        return True


class _TestAuthorityServer:
    """A pathname Unix peer standing in for the real host authority runtime."""

    _FIELDS = (
        "purpose",
        "scope_ref",
        "owner_pid",
        "session_ref",
        "root_fd",
        "root_device",
        "root_inode",
        "subject_id",
        "payload_digest",
    )

    def __init__(self, path: str | None = None, *, hang_operations: set[str] | None = None) -> None:
        self.directory = (
            os.path.dirname(path)
            if path is not None
            else f"/private/tmp/workbench-evidence-authority-{os.getpid()}"
        )
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self.path = path or os.path.join(self.directory, "authority.sock")
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.path)
        self.listener.listen(16)
        endpoint_stat = os.lstat(self.path)
        self.endpoint_device = int(endpoint_stat.st_dev)
        self.endpoint_inode = int(endpoint_stat.st_ino)
        self.shared_secret = bytes.fromhex("11" * 32)
        self.session_ref = f"session:test:{os.getpid()}"
        self.hang_operations = frozenset(hang_operations or ())
        self.stop_event = threading.Event()
        self.issued: dict[tuple[object, ...], str] = {}
        self._proof_counter = count(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @classmethod
    def _key(cls, request: object) -> tuple[object, ...]:
        if type(request) is not dict:
            raise ValueError("authority request must be an object")
        return tuple(request[field] for field in cls._FIELDS)

    @staticmethod
    def _read_frame(channel: socket.socket) -> dict[str, object] | None:
        raw = bytearray()
        while True:
            chunk = channel.recv(4096)
            if not chunk:
                return None
            raw.extend(chunk)
            if b"\n" not in chunk:
                continue
            frame, _, _tail = bytes(raw).partition(b"\n")
            value = json.loads(frame.decode("utf-8"))
            if type(value) is not dict:
                raise ValueError("authority message must be an object")
            return value

    @staticmethod
    def _send_frame(channel: socket.socket, response: dict[str, object]) -> None:
        channel.sendall(canonical_json_v1(response).encode("utf-8") + b"\n")

    def _serve_client(self, channel: socket.socket) -> None:
        try:
            while True:
                message = self._read_frame(channel)
                if message is None:
                    return
                operation = message.get("operation")
                if operation in self.hang_operations:
                    self.stop_event.wait(timeout=5)
                    return
                try:
                    if operation == "session":
                        request = message.get("request")
                        if type(request) is not dict:
                            raise ValueError("session request must be an object")
                        challenge = request.get("challenge")
                        endpoint = request.get("endpoint")
                        owner_pid = request.get("owner_pid")
                        if (
                            type(challenge) is not str
                            or type(endpoint) is not dict
                            or type(owner_pid) is not int
                        ):
                            raise ValueError("session request is malformed")
                        attestation = hmac.new(
                            self.shared_secret,
                            canonical_json_v1(
                                {
                                    "challenge": challenge,
                                    "endpoint": endpoint,
                                    "owner_pid": owner_pid,
                                    "session_ref": self.session_ref,
                                }
                            ).encode("utf-8"),
                            hashlib.sha256,
                        ).hexdigest()
                        response = {
                            "ok": True,
                            "session_ref": self.session_ref,
                            "attestation": attestation,
                        }
                    elif operation == "issue":
                        key = self._key(message.get("request"))
                        proof = f"test-proof:{next(self._proof_counter)}"
                        self.issued[key] = proof
                        response = {"ok": True, "proof": proof}
                    elif operation == "validate":
                        key = self._key(message.get("request"))
                        response = {
                            "ok": True,
                            "accepted": self.issued.get(key) == message.get("proof"),
                        }
                    else:
                        response = {"ok": False}
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    response = {"ok": False}
                self._send_frame(channel, response)
        except OSError:
            return
        finally:
            channel.close()

    def _serve(self) -> None:
        try:
            while True:
                channel, _address = self.listener.accept()
                threading.Thread(target=self._serve_client, args=(channel,), daemon=True).start()
        except OSError:
            return

    def close(self) -> None:
        self.stop_event.set()
        self.listener.close()
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        try:
            os.rmdir(self.directory)
        except OSError:
            pass


class _ExternalHostAuthority:
    """Test facade for a host process; production receives only ``channel``."""

    _server: _TestAuthorityServer | None = None
    _server_pid: int | None = None
    _server_lock = threading.Lock()

    def __init__(self, scope_ref: str) -> None:
        self.scope_ref = scope_ref
        server = self._get_server()
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(server.path)
        config = HostAuthorityEndpointConfigV1(
            endpoint_path=server.path,
            endpoint_device=server.endpoint_device,
            endpoint_inode=server.endpoint_inode,
            peer_uid=os.getuid(),
            peer_pid=os.getpid(),
            scope_ref=scope_ref,
            session_ref=server.session_ref,
            shared_secret=server.shared_secret.hex(),
        )
        self.channel = _admit_test_host_endpoint(client, config)
        self.session_ref = server.session_ref
        self.issued = server.issued

    @classmethod
    def _get_server(cls) -> _TestAuthorityServer:
        with cls._server_lock:
            if cls._server is None or cls._server_pid != os.getpid():
                cls._server = _TestAuthorityServer()
                cls._server_pid = os.getpid()
            return cls._server


def _raw_host_client(server: _TestAuthorityServer) -> socket.socket:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(server.path)
    return client


def _host_config(
    server: _TestAuthorityServer,
    *,
    scope_ref: str,
    endpoint_path: str | None = None,
    endpoint_device: int | None = None,
    endpoint_inode: int | None = None,
    peer_uid: int | None = None,
    peer_pid: int | None = None,
    session_ref: str | None = None,
    shared_secret: str | None = None,
) -> HostAuthorityEndpointConfigV1:
    return HostAuthorityEndpointConfigV1(
        endpoint_path=server.path if endpoint_path is None else endpoint_path,
        endpoint_device=server.endpoint_device if endpoint_device is None else endpoint_device,
        endpoint_inode=server.endpoint_inode if endpoint_inode is None else endpoint_inode,
        peer_uid=os.getuid() if peer_uid is None else peer_uid,
        peer_pid=os.getpid() if peer_pid is None else peer_pid,
        scope_ref=scope_ref,
        session_ref=server.session_ref if session_ref is None else session_ref,
        shared_secret=server.shared_secret.hex() if shared_secret is None else shared_secret,
    )


def _authorized_registry(scope_ref: str = "scope:project:1"):
    host = _ExternalHostAuthority(scope_ref)
    registry = create_server_evidence_registry(scope_ref=scope_ref, authority_handle=host.channel)
    _TEST_AUTHORITY_BY_REGISTRY[id(registry)] = host.channel
    return registry, host


def _process_host_boundary_probe(registry, artifact_id: str, view, outcome, admission, result_queue) -> None:
    results: dict[str, str] = {}
    try:
        registry.resolve(artifact_id)
        results["registry"] = "accepted"
    except EvidenceRegistryError as exc:
        results["registry"] = exc.code
    try:
        view.to_dict()
        results["view"] = "accepted"
    except TypeError:
        results["view"] = "typed_rejection"
    try:
        outcome.to_dict()
        results["outcome"] = "accepted"
    except TypeError:
        results["outcome"] = "typed_rejection"
    try:
        EvidencePacketStoreV1(admission)
        results["persistence"] = "accepted"
    except EvidencePersistenceError as exc:
        results["persistence"] = exc.code
    result_queue.put(results)


def test_host_authority_rejects_copy_pickle_json_and_fork_replays_for_three_rounds(tmp_path: Path) -> None:
    context = multiprocessing.get_context("fork")
    for round_index in range(3):
        registry, _host = _authorized_registry()
        record = _admit(registry, artifact_id=f"artifact:fork-boundary:{round_index}")
        view = EvidenceProjectionV1(registry).project(record.artifact_id)
        outcome = EvidenceProjectionV1(registry).try_project(record.artifact_id)
        store = _admit_store(tmp_path, registry)
        admission = store.admission
        try:
            for value in (registry, view, outcome, admission):
                with pytest.raises(TypeError):
                    copy.copy(value)
                with pytest.raises(TypeError):
                    copy.deepcopy(value)
                with pytest.raises(TypeError):
                    pickle.dumps(value)
                with pytest.raises(TypeError):
                    json.dumps(value)

            result_queue = context.Queue()
            process = context.Process(
                target=_process_host_boundary_probe,
                args=(registry, record.artifact_id, view, outcome, admission, result_queue),
            )
            process.start()
            process.join(timeout=10)
            assert process.exitcode == 0
            assert result_queue.get(timeout=2) == {
                "registry": "EVIDENCE_HOST_AUTHORITY_REQUIRED",
                "view": "typed_rejection",
                "outcome": "typed_rejection",
                "persistence": "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
            }
        finally:
            store.close()


def test_public_evidence_factories_require_external_host_authority_and_do_not_expose_keys(tmp_path: Path) -> None:
    with pytest.raises(EvidenceRegistryError) as registry_exc:
        create_server_evidence_registry(scope_ref="scope:project:no-host")
    assert registry_exc.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"

    with pytest.raises(EvidencePersistenceError) as persistence_exc:
        EvidencePacketStoreV1.admit(tmp_path)
    assert persistence_exc.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"

    import workbench.evidence.persistence as persistence_module
    import workbench.evidence.projection as projection_module
    import workbench.evidence.registry as registry_module

    assert not hasattr(registry_module, "_REGISTRY_PROOF_SECRET")
    assert not hasattr(registry_module, "_REGISTRY_CONSTRUCTION_KEY")
    assert not hasattr(persistence_module, "_ADMISSION_PROOF_SECRET")
    assert not hasattr(persistence_module, "_ADMISSION_CONSTRUCTION_KEY")
    assert not hasattr(projection_module, "_PROJECTION_PROOF_SECRET")
    assert not hasattr(projection_module, "_PROJECTION_RECEIPT_KEY")
    assert not hasattr(projection_module, "_PROJECTION_OUTCOME_KEY")


def test_structural_python_object_cannot_impersonate_the_external_host_channel() -> None:
    with pytest.raises(EvidenceRegistryError) as exc_info:
        create_server_evidence_registry(
            scope_ref="scope:project:forged-host",
            authority_handle=_ForgedStructuralHost(),
        )
    assert exc_info.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"


def test_external_host_authority_binds_scope_owner_session_root_and_purpose(tmp_path: Path) -> None:
    registry, host = _authorized_registry()
    record = _admit(registry, artifact_id="artifact:host-authority")

    with EvidencePacketStoreV1.admit(
        tmp_path,
        authority_handle=host.channel,
        scope_ref=registry.scope_ref,
    ) as store:
        binding = store.commit(record, receipt=registry.persistence_receipt(record))
        assert store.load(binding.commit_id, registry=registry, receipt=registry.persistence_receipt(record)) == binding
        assert store.load_packet(binding.commit_id, registry=registry, receipt=registry.persistence_receipt(record)) == record

    view = EvidenceProjectionV1(registry).project(record.artifact_id)
    assert view.success is True
    purposes = {key[0] for key in host.issued}
    assert purposes >= {
        "evidence.registry",
        "evidence.registry.receipt",
        "evidence.persistence",
        "evidence.projection.view",
    }
    assert all(key[2] == os.getpid() for key in host.issued)
    assert all(key[3] == host.session_ref for key in host.issued)


def test_copied_pickled_json_and_object_new_evidence_authority_fail_closed(tmp_path: Path) -> None:
    registry, host = _authorized_registry()
    record = _admit(registry, artifact_id="artifact:host-copy-boundary")

    with pytest.raises(TypeError):
        copy.copy(registry)

    with pytest.raises(TypeError):
        pickle.dumps(registry)

    forged_registry = object.__new__(_EvidenceRegistryV1)
    for name in _EvidenceRegistryV1.__slots__:
        if hasattr(registry, name):
            object.__setattr__(forged_registry, name, getattr(registry, name))
    with pytest.raises(EvidenceRegistryError) as forged_exc:
        forged_registry.resolve(record.artifact_id)
    assert forged_exc.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"

    with pytest.raises(EvidencePersistenceError):
        EvidencePacketStoreV1.admit(
            tmp_path,
            authority_handle=object(),
            scope_ref=registry.scope_ref,
        )

    assert json.loads(json.dumps({"scope_ref": registry.scope_ref})) == {
        "scope_ref": registry.scope_ref
    }


def test_host_endpoint_admission_rejects_wrong_path_peer_and_handshake() -> None:
    server = _TestAuthorityServer(
        path=f"/private/tmp/workbench-evidence-authority-negative-{os.getpid()}/authority.sock"
    )
    try:
        cases = (
            _host_config(server, scope_ref="scope:project:negative", endpoint_path=server.path + ".wrong"),
            _host_config(server, scope_ref="scope:project:negative", peer_uid=os.getuid() + 1),
            _host_config(server, scope_ref="scope:project:negative", peer_pid=os.getpid() + 1),
            _host_config(server, scope_ref="scope:project:negative", shared_secret="22" * 32),
        )
        for config in cases:
            client = _raw_host_client(server)
            try:
                with pytest.raises(EvidenceHostAuthorityError):
                    _admit_test_host_endpoint(client, config)
            finally:
                client.close()
    finally:
        server.close()


def test_caller_created_path_socket_without_deployment_attestation_fails_closed() -> None:
    directory = f"/private/tmp/workbench-evidence-fake-{os.getpid()}"
    path = os.path.join(directory, "authority.sock")
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    listener.listen(1)
    endpoint_stat = os.lstat(path)

    def serve_self_authored_path() -> None:
        try:
            channel, _address = listener.accept()
            _TestAuthorityServer._read_frame(channel)
            _TestAuthorityServer._send_frame(
                channel,
                {"ok": True, "session_ref": "session:self-authored-path"},
            )
            channel.close()
        except OSError:
            return

    thread = threading.Thread(target=serve_self_authored_path, daemon=True)
    thread.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(path)
    try:
        config = HostAuthorityEndpointConfigV1(
            endpoint_path=path,
            endpoint_device=int(endpoint_stat.st_dev),
            endpoint_inode=int(endpoint_stat.st_ino),
            peer_uid=os.getuid(),
            peer_pid=os.getpid(),
            scope_ref="scope:project:self-authored-path",
            session_ref="session:self-authored-path",
            shared_secret="33" * 32,
        )
        with pytest.raises(EvidenceHostAuthorityError):
            _admit_test_host_endpoint(client, config)
    finally:
        client.close()
        listener.close()
        thread.join(timeout=2)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        try:
            os.rmdir(directory)
        except OSError:
            pass


def test_pre_admitted_fd_still_requires_the_configured_path_identity() -> None:
    server = _TestAuthorityServer(
        path=f"/private/tmp/workbench-evidence-authority-fd-{os.getpid()}/authority.sock"
    )
    client = _raw_host_client(server)
    fd = client.detach()
    endpoint = None
    try:
        endpoint = _admit_test_host_fd(
            fd,
            _host_config(server, scope_ref="scope:project:fd"),
        )
        assert endpoint.scope_ref == "scope:project:fd"
    finally:
        os.close(fd)
        if endpoint is not None:
            endpoint.close()
        server.close()


def test_host_endpoint_rechecks_path_inode_after_endpoint_swap() -> None:
    server = _TestAuthorityServer(
        path=f"/private/tmp/workbench-evidence-authority-swap-{os.getpid()}/authority.sock"
    )
    endpoint = _admit_test_host_endpoint(
        _raw_host_client(server),
        _host_config(server, scope_ref="scope:project:swap"),
    )
    replacement: socket.socket | None = None
    try:
        os.unlink(server.path)
        replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        replacement.bind(server.path)
        replacement.listen(1)
        with pytest.raises(EvidenceHostAuthorityError):
            endpoint.scope_ref
    finally:
        endpoint._channel.close()
        if replacement is not None:
            replacement.close()
        try:
            os.unlink(server.path)
        except FileNotFoundError:
            pass
        server.close()


def _process_endpoint_reuse(endpoint: object, result_queue) -> None:
    try:
        endpoint.scope_ref  # type: ignore[attr-defined]
        result_queue.put("accepted")
    except EvidenceHostAuthorityError as exc:
        result_queue.put(exc.code)
    except BaseException as exc:  # pragma: no cover - surfaced by assertion
        result_queue.put(f"{type(exc).__name__}:{exc}")


def test_host_endpoint_handle_cannot_be_copied_rebuilt_or_fork_reused() -> None:
    host = _ExternalHostAuthority("scope:project:endpoint-boundary")
    endpoint = host.channel
    try:
        with pytest.raises(TypeError):
            copy.copy(endpoint)
        with pytest.raises(TypeError):
            copy.deepcopy(endpoint)
        with pytest.raises(TypeError):
            pickle.dumps(endpoint)
        with pytest.raises(TypeError):
            json.dumps(endpoint)

        forged = object.__new__(type(endpoint))
        for name in type(endpoint).__slots__:
            if name != "__weakref__" and hasattr(endpoint, name):
                object.__setattr__(forged, name, getattr(endpoint, name))
        with pytest.raises(EvidenceHostAuthorityError):
            forged.scope_ref

        config = endpoint._config
        original_scope = config.scope_ref
        object.__setattr__(config, "scope_ref", "scope:attacker")
        with pytest.raises(EvidenceHostAuthorityError):
            endpoint.scope_ref
        object.__setattr__(config, "scope_ref", original_scope)

        context = multiprocessing.get_context("fork")
        result_queue = context.Queue()
        process = context.Process(target=_process_endpoint_reuse, args=(endpoint, result_queue))
        process.start()
        process.join(timeout=10)
        assert process.exitcode == 0
        assert result_queue.get(timeout=2) == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        endpoint.close()


def test_self_authored_socketpair_protocol_is_not_a_host_endpoint() -> None:
    """A caller-created socketpair and matching protocol is not host identity."""

    client, peer = socket.socketpair()
    stop = threading.Event()

    def serve_self_authored_protocol() -> None:
        try:
            while not stop.is_set():
                message = peer.recv(4096)
                if not message:
                    return
                peer.sendall(b'{"ok":true,"session_ref":"session:self-authored"}\n')
        except OSError:
            return

    thread = threading.Thread(target=serve_self_authored_protocol, daemon=True)
    thread.start()
    try:
        with pytest.raises(EvidenceRegistryError) as exc_info:
            create_server_evidence_registry(
                scope_ref="scope:project:self-authored",
                authority_handle=client,
            )
        assert exc_info.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        stop.set()
        client.close()
        peer.close()
        thread.join(timeout=2)


def test_fake_or_malformed_endpoint_fails_before_protocol_io() -> None:
    """Unconfigured and malformed handles cannot make Evidence read or write."""

    client, peer = socket.socketpair()
    peer.settimeout(0.2)
    try:
        with pytest.raises(EvidenceHostAuthorityError):
            admit_host_authority_endpoint(client, deployment_config=object())
        with pytest.raises(EvidenceRegistryError) as exc_info:
            create_server_evidence_registry(
                scope_ref="scope:project:no-io",
                authority_handle=client,
            )
        assert exc_info.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
        with pytest.raises(socket.timeout):
            peer.recv(1)
    finally:
        client.close()
        peer.close()


def test_caller_selected_endpoint_config_is_not_a_trust_root() -> None:
    """A caller-created server plus caller-created config must not be admitted."""

    server = _TestAuthorityServer(
        path=f"/private/tmp/workbench-evidence-authority-caller-config-{os.getpid()}/authority.sock"
    )
    client = _raw_host_client(server)
    try:
        config = _host_config(server, scope_ref="scope:project:caller-selected")
        with pytest.raises(EvidenceHostAuthorityError) as exc_info:
            admit_host_authority_endpoint(client, deployment_config=config)
        assert exc_info.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        client.close()
        server.close()


def test_caller_selected_fd_and_config_are_not_a_trust_root() -> None:
    """A raw FD is not trusted merely because the caller supplies matching fields."""

    server = _TestAuthorityServer(
        path=f"/private/tmp/workbench-evidence-authority-caller-fd-{os.getpid()}/authority.sock"
    )
    client = _raw_host_client(server)
    fd = client.detach()
    try:
        config = _host_config(server, scope_ref="scope:project:caller-selected-fd")
        with pytest.raises(EvidenceHostAuthorityError) as exc_info:
            admit_host_authority_fd(fd, deployment_config=config)
        assert exc_info.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        os.close(fd)
        server.close()


def test_admit_host_authority_fd_closes_duplicate_when_socket_wrap_fails(monkeypatch) -> None:
    config = HostAuthorityEndpointConfigV1(
        endpoint_path="/private/tmp/workbench-evidence-authority-wrap-failure/authority.sock",
        endpoint_device=1,
        endpoint_inode=1,
        peer_uid=os.getuid(),
        peer_pid=os.getpid(),
        scope_ref="scope:project:wrap-failure",
        session_ref="session:wrap-failure",
        shared_secret="44" * 32,
    )
    closed: list[int] = []
    monkeypatch.setattr(authority_module, "_admission_config", lambda _candidate: config)
    monkeypatch.setattr(authority_module.os, "dup", lambda _fd: 733)
    monkeypatch.setattr(authority_module.os, "close", lambda fd: closed.append(fd))

    def fail_socket(*, fileno):
        raise OSError(f"cannot wrap {fileno}")

    monkeypatch.setattr(authority_module.socket, "socket", fail_socket)
    with pytest.raises(EvidenceHostAuthorityError):
        admit_host_authority_fd(12)
    assert 733 in closed


def test_authority_read_frame_rejects_newline_tail_instead_of_swallowing_it() -> None:
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(b'{"ok":true}\nextra-frame\n')
        with pytest.raises(EvidenceHostAuthorityError):
            authority_module._read_frame(receiver)
    finally:
        sender.close()
        receiver.close()


def test_authority_rpc_timeout_is_bounded_and_typed() -> None:
    """An unresponsive admitted endpoint must return a stable timeout error."""

    host = _ExternalHostAuthority("scope:project:timeout")
    endpoint = host.channel
    request = build_authority_request(
        endpoint,
        purpose="evidence.timeout",
        scope_ref=host.scope_ref,
        subject_id=1,
        payload_digest="d" * 64,
    )
    try:
        with patch.object(authority_module, "_read_frame", side_effect=socket.timeout("timed out")):
            with pytest.raises(EvidenceHostAuthorityError) as exc_info:
                issue_host_proof(endpoint, request)
        assert exc_info.value.code == "EVIDENCE_HOST_AUTHORITY_TIMEOUT"
    finally:
        endpoint.close()


def test_unresponsive_host_rpc_returns_before_unbounded_wait() -> None:
    """A real unresponsive host is cut off by the fixed authority timeout."""

    server = _TestAuthorityServer(
        path=f"/private/tmp/workbench-evidence-authority-timeout-{os.getpid()}/authority.sock",
        hang_operations={"issue"},
    )
    endpoint = _admit_test_host_endpoint(
        _raw_host_client(server),
        _host_config(server, scope_ref="scope:project:real-timeout"),
    )
    request = build_authority_request(
        endpoint,
        purpose="evidence.timeout",
        scope_ref="scope:project:real-timeout",
        subject_id=2,
        payload_digest="e" * 64,
    )
    started = time.monotonic()
    try:
        with pytest.raises(EvidenceHostAuthorityError) as exc_info:
            issue_host_proof(endpoint, request)
        elapsed = time.monotonic() - started
        assert exc_info.value.code == "EVIDENCE_HOST_AUTHORITY_TIMEOUT"
        assert elapsed < 2.0
    finally:
        endpoint.close()
        server.close()


def test_unavailable_host_rpc_returns_stable_unavailable_code() -> None:
    """Transport failure is not confused with missing deployment authority."""

    host = _ExternalHostAuthority("scope:project:unavailable")
    endpoint = host.channel
    request = build_authority_request(
        endpoint,
        purpose="evidence.unavailable",
        scope_ref=host.scope_ref,
        subject_id=3,
        payload_digest="f" * 64,
    )
    try:
        with patch.object(authority_module, "_read_frame", side_effect=OSError("closed")):
            with pytest.raises(EvidenceHostAuthorityError) as exc_info:
                issue_host_proof(endpoint, request)
        assert exc_info.value.code == "EVIDENCE_HOST_AUTHORITY_UNAVAILABLE"
    finally:
        endpoint.close()


def test_malformed_authority_requests_fail_with_typed_errors() -> None:
    """Malformed request objects cannot escape as AttributeError or I/O."""

    host = _ExternalHostAuthority("scope:project:malformed-request")
    endpoint = host.channel
    try:
        with pytest.raises(EvidenceHostAuthorityError):
            issue_host_proof(endpoint, object())  # type: ignore[arg-type]
        with pytest.raises(EvidenceHostAuthorityError):
            validate_host_proof(endpoint, object(), object())  # type: ignore[arg-type]
    finally:
        endpoint.close()
