from __future__ import annotations

import copy
import multiprocessing
import pickle

import pytest

from workbench.contracts.agent import planning as planning_module
from workbench.contracts.agent.planning import (
    CompilationRecordReferenceV1,
    CompilationRecordStoreV1,
    HostCompilationReceiptV1,
    ServerCompilationRecordReferenceV1,
    ServerCompilationRecordIssuerV1,
)
from workbench.contracts.common.envelope import ContractError


def test_public_legacy_issuer_cannot_be_constructed_without_host_receipt() -> None:
    with pytest.raises(ContractError, match="authority|host|receipt"):
        ServerCompilationRecordIssuerV1()


def test_public_legacy_alias_cannot_restore_the_signing_path() -> None:
    legacy_alias = planning_module.ServerCompilationRecordIssuerV1

    with pytest.raises(ContractError, match="authority|host|receipt"):
        legacy_alias()

    assert "ServerCompilationRecordIssuerV1" not in planning_module.__all__


def test_historical_record_is_readable_but_cannot_be_upgraded() -> None:
    from tests.contracts.test_v189_contract_lock import _fixture
    from workbench.contracts.agent.planning import CompilationRecordV1

    historical = CompilationRecordV1.from_dict(_fixture("compilation_record.json"))
    assert historical.record_id.startswith("compilation-record:")

    with pytest.raises(ContractError, match="authority|compiler|server"):
        CompilationRecordStoreV1().issue(historical)


def test_forged_legacy_issuer_cannot_execute_any_compilation_stage() -> None:
    from tests.contracts.test_v189_contract_lock import _task3_plan

    issuer = object.__new__(ServerCompilationRecordIssuerV1)
    operations = (
        lambda: issuer.register_draft(_task3_plan()),
        lambda: issuer.compile_workflow(None),
        lambda: issuer.compile_record(None),
        lambda: issuer.issue(None),
    )

    for operation in operations:
        with pytest.raises(ContractError, match="authority|host|receipt|compiler"):
            operation()


def test_caller_scope_metadata_never_admits_the_retired_issuer() -> None:
    with pytest.raises(ContractError, match="authority|host|receipt"):
        ServerCompilationRecordIssuerV1(CompilationRecordStoreV1())


def test_caller_created_reference_and_receipt_cannot_make_c0_store_resolve() -> None:
    record_ref = CompilationRecordReferenceV1(
        record_id="compilation-record:attacker",
        record_digest="a" * 64,
        semantic_plan_hash="b" * 64,
    )
    receipt = HostCompilationReceiptV1(
        receipt_id="receipt:attacker",
        compilation_record_ref=record_ref,
        scope_ref="project:attacker",
        principal_ref="principal:attacker",
        session_ref="session:attacker",
        project_ref="project:attacker",
        semantic_plan_hash=record_ref.semantic_plan_hash,
        issued_at="2026-08-16T13:00:00+00:00",
        expires_at="2026-08-16T14:00:00+00:00",
    )
    assert receipt.to_dict()["schema_version"] == "host-compilation-receipt.v1"

    server_ref = ServerCompilationRecordReferenceV1(
        record_id=record_ref.record_id,
        record_digest=record_ref.record_digest,
        semantic_plan_hash=record_ref.semantic_plan_hash,
    )
    with pytest.raises(ContractError, match="authority|host|integration"):
        CompilationRecordStoreV1().resolve(server_ref)


def test_host_compilation_receipt_wire_parse_remains_untrusted() -> None:
    record_ref = CompilationRecordReferenceV1(
        record_id="compilation-record:wire",
        record_digest="c" * 64,
        semantic_plan_hash="d" * 64,
    )
    receipt = HostCompilationReceiptV1(
        receipt_id="receipt:wire",
        compilation_record_ref=record_ref,
        scope_ref="project:wire",
        principal_ref="principal:wire",
        session_ref="session:wire",
        project_ref="project:wire",
        semantic_plan_hash=record_ref.semantic_plan_hash,
        issued_at="2026-08-16T13:00:00+00:00",
        expires_at="2026-08-16T14:00:00+00:00",
    )

    parsed = HostCompilationReceiptV1.from_dict(receipt.to_dict())
    assert parsed == receipt
    with pytest.raises(ContractError, match="authority|host|integration"):
        CompilationRecordStoreV1().resolve(
            ServerCompilationRecordReferenceV1(
                record_id=record_ref.record_id,
                record_digest=record_ref.record_digest,
                semantic_plan_hash=record_ref.semantic_plan_hash,
            )
        )


def test_copy_and_serialization_cannot_reactivate_a_forged_legacy_issuer() -> None:
    issuer = object.__new__(ServerCompilationRecordIssuerV1)
    candidates = (
        copy.copy(issuer),
        copy.deepcopy(issuer),
        pickle.loads(pickle.dumps(issuer)),
    )

    for candidate in candidates:
        with pytest.raises(ContractError, match="authority|host|receipt|compiler"):
            candidate.compile_workflow(None)


def _forked_legacy_issuer_probe(result_queue: object) -> None:
    issuer = object.__new__(ServerCompilationRecordIssuerV1)
    try:
        issuer.register_draft(None)
    except ContractError:
        result_queue.put("rejected")  # type: ignore[attr-defined]
    else:
        result_queue.put("accepted")  # type: ignore[attr-defined]


def test_forked_legacy_issuer_cannot_reuse_a_local_authority() -> None:
    context = multiprocessing.get_context("fork")
    result_queue = context.Queue()
    process = context.Process(target=_forked_legacy_issuer_probe, args=(result_queue,))
    process.start()
    process.join(timeout=5)

    assert process.exitcode == 0
    assert result_queue.get(timeout=1) == "rejected"
