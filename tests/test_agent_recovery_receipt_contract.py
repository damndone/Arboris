"""Original tool receipt WAL is distinct from already-committed domain evidence."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib
import importlib.util
import json
from dataclasses import dataclass

import pytest

from tests.test_read_only_analysis import FINGERPRINT, _Fixture, _t_test
from workbench import analysis_ledger
from workbench.agent import permissions, read_only_policy
from workbench.agent.chains import ChainStore
from workbench.agent.context import ContextBuilder
from workbench.agent.core import AgentRunBudget
from workbench.agent.execution import execution_key
from workbench.agent.operation_requests import OperationRequest
from workbench.agent.proposals import ProposalAdmissionNeedsReconciliation, ProposalInvocation
from workbench.agent.tools import ToolResult
from workbench.agent.session import EntryRef, JsonlSessionRepository


def receipt_module():
    assert importlib.util.find_spec("workbench.agent.tool_receipts"), "original tool receipt WAL is missing"
    return importlib.import_module("workbench.agent.tool_receipts")


def wal_arguments(case):
    return {"session_id": "chain-session", "command_id": "command-recovery",
            "provider_step": case.invocation.provider_step, "tool_call_id": case.invocation.tool_call_id,
            "invocation_id": case.invocation.invocation_id, "tool_call": {
                "tool_call_id": case.invocation.tool_call_id, "tool_id": "run_operation",
                "arguments": {"operation_id": case.request.operation_id,
                              "target": case.request.target, "preconditions": case.request.preconditions,
                              "changes": case.request.changes, "evidence_refs": list(case.request.evidence_refs),
                              "expected_effect": list(case.request.expected_effect), "risks": list(case.request.risks)},
                "provider_metadata": {"nested": [1, 2]},
            }}


@dataclass
class Case:
    fixture: _Fixture
    request: OperationRequest
    invocation: ProposalInvocation
    proposal: object

    def admit(self):
        return self.fixture.orchestrator.admit_operation_request(
            self.request, chain_id="chain-a", session_id="chain-session",
            command_id="command-recovery", invocation=self.invocation,
        ).proposal

    def run_until_tool_return(self):
        output = asyncio.run(self.fixture.orchestrator._run_or_await_confirmation(
            self.proposal, session_id="chain-session"))
        # Stop at the real tool return / Core session append boundary.
        return ToolResult(tool_call_id=self.invocation.tool_call_id,
                          tool_id="run_operation", ok=True, output=output).to_payload()

    def run_actual_tool_return(self):
        orchestrator = self.fixture.orchestrator
        from tests.test_data_column_cast import _register_source_node_identity
        _register_source_node_identity(self.fixture.project_root, self.fixture.run_id)

        async def runner(proposal):
            fingerprint = proposal.preconditions["context_fingerprint"]
            record = orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
                fingerprint=proposal.fingerprint, actor_type=read_only_policy.ACTOR,
                current_context_fingerprint=fingerprint, current_active_head_run_id=self.fixture.run_id)
            return await orchestrator.execute_confirmed_operation(record.record_id,
                project_root=self.fixture.project_root, current_context_fingerprint=fingerprint,
                current_active_head_run_id=self.fixture.run_id)

        orchestrator.read_only_runner = runner
        arguments = wal_arguments(self)
        result = asyncio.run(orchestrator.tool_registry("chain-a").execute(
            arguments["tool_call"], session_id="chain-session", metadata={
                key: arguments[key] for key in ("command_id", "provider_step", "tool_call_id", "invocation_id")}))
        assert result.ok, result
        return result.to_payload()


def prepared_case(tmp_path, *, fails=False, admit=True):
    fixture = _Fixture(tmp_path)
    steps = [_t_test("tt")]
    if fails:
        class FailBeforeEffect:
            def hit(self, point, record):
                if point == "before_child_effect":
                    raise RuntimeError("fixture operation failed before effect")
        fixture.orchestrator.failpoint = FailBeforeEffect()
    request = OperationRequest(
        operation_id="operation.multi_step",
        target={"run_id": fixture.run_id, "node_ref": "stage:source", "artifact_id": fixture.artifact_id},
        preconditions={"context_version": "node-operation-context/v1", "context_fingerprint": FINGERPRINT,
                       "active_head_run_id": fixture.run_id, "owner_resolution": "single_candidate"},
        changes={"steps": steps}, evidence_refs=["profile:fixture"],
        expected_effect=["answer the question"], risks=[],
    )
    case = Case(fixture, request, ProposalInvocation("invocation-recovery", 1, "call-recovery"), None)
    if admit:
        case.proposal = case.admit()
    return case


def snapshot(case):
    root = case.fixture.project_root
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*")
            if path.is_file() and path.suffix in {".json", ".jsonl"}}


def test_completed_domain_effect_survives_without_a_tool_result_session_entry(tmp_path):
    case = prepared_case(tmp_path)
    receipt = case.run_until_tool_return()
    assert receipt["output"]["operation"]["status"] == "completed"
    store = case.fixture.orchestrator.operation_store
    prepared_key = hashlib.sha256(case.invocation.invocation_id.encode()).hexdigest()
    prepared = json.loads((case.fixture.orchestrator.proposal_store.proposals_dir
                           / "prepared" / f"{prepared_key}.jsonl").read_text())
    assert prepared["invocation"] == case.invocation.to_dict()
    assert prepared["request"]["command_id"] == "command-recovery"
    assert prepared["request"]["session_id"] == "chain-session"
    assert prepared["request"]["chain_id"] == "chain-a"
    assert prepared["request"]["target"] == case.request.target
    assert prepared["request"]["preconditions"] == case.request.preconditions
    assert prepared["request"]["changes"] == case.request.changes
    records = [record for record in store.list_records()
               if record.proposal_id == prepared["revision"]["proposal_id"]
               and record.proposal_revision == prepared["revision"]["revision"]
               and record.proposal_fingerprint == prepared["revision"]["fingerprint"]
               and record.workflow_step_id is None]
    assert len(records) == 1
    [record] = records
    assert record.record_id == receipt["output"]["operation"]["record_id"]
    proposal = case.proposal
    assert prepared["revision"] == proposal.to_dict()
    assert (record.proposal_id, record.proposal_revision, record.proposal_fingerprint) == (
        proposal.proposal_id, proposal.revision, proposal.fingerprint)
    assert (record.agent_session_id, record.chain_id, record.command_id) == (
        "chain-session", "chain-a", "command-recovery")
    assert record.execution["execution_key"] == execution_key(
        proposal_id=proposal.proposal_id, revision=proposal.revision, fingerprint=proposal.fingerprint)
    assert record.effect_status == "committed" and record.projection_status == "complete"
    assert receipt["output"]["results"]
    run_root = case.fixture.project_root / "runs" / case.fixture.run_id
    index = json.loads((run_root / "artifacts_index.json").read_text())
    registered = {item["artifact_id"]: item for item in index["artifacts"]}
    artifact_ids = record.outputs["workflow_state"]["steps"]["tt"]["artifact_ids"]
    assert artifact_ids
    for artifact_id in artifact_ids:
        artifact = registered[artifact_id]
        path = (run_root / artifact["path"]).resolve()
        path.relative_to(run_root.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
    assert len(analysis_ledger.read(case.fixture.project_root)) == 1
    assert not any(entry.payload.get("role") == "tool"
                   for entry in case.fixture.repository.get_branch("chain-session"))
    notifications = [entry for entry in case.fixture.repository.get_branch("chain-session")
                     if entry.idempotency and entry.idempotency["key"] == case.invocation.invocation_id
                     and entry.idempotency["stage"] == "operation_proposal"]
    assert len(notifications) == 1
    assert notifications[0].payload["proposal"] == prepared["revision"]
    before = snapshot(case)
    assert receipt_module().read(case.fixture.repository, **wal_arguments(case)) is None
    assert snapshot(case) == before  # A committed effect does not fabricate a missing receipt.
    with pytest.raises(ProposalAdmissionNeedsReconciliation):
        case.admit()
    assert snapshot(case) == before


@pytest.mark.parametrize("status", ["pending", "denied", "completed", "failed"])
def test_original_tool_return_is_persisted_read_and_repaired_without_reexecution(tmp_path, status, monkeypatch):
    case = prepared_case(tmp_path, fails=status == "failed", admit=False)
    if status == "pending":
        case.fixture.orchestrator.execution_policy = "proposal_only"
    if status == "denied":
        case.fixture.orchestrator.permission_rules = permissions.Rules(
            deny=(permissions.Rule(permissions.PermissionClass.ANALYZE),))
    receipt = case.run_actual_tool_return()
    output = receipt["output"]
    if status == "pending":
        assert output["requires_confirmation"] is True
    elif status == "denied":
        assert output["denied"] is True and output["executed"] is False
    else:
        assert output["executed"] is True
        assert output["operation"]["status"] == status
    # Core owns these final annotations; WAL must preserve them, not derive them.
    agent = case.fixture.orchestrator._chain("chain-a")[1]
    agent._budget, agent._steps_used = AgentRunBudget(max_steps=6), 5
    final_payload = agent._annotate_step_budget({**receipt, "already_answered_this_turn": True})
    module = receipt_module()
    arguments = wal_arguments(case)
    repository = case.fixture.repository
    entry = module.persist(repository, payload=final_payload, **arguments)
    assert entry.entry_type == "tool_receipt"
    assert entry.idempotency["stage"] == "original_tool_receipt"
    assert entry.payload["tool_result"] == final_payload
    assert module.persist(repository, payload=final_payload, **arguments) == entry
    assert entry.entry_id not in ContextBuilder(repository).build("chain-session").source_entry_ids

    def forbidden(*args, **kwargs):
        raise AssertionError("receipt recovery must not re-enter admission, confirmation or execution")

    for name in ("admit_operation_request", "confirm_proposal", "execute_confirmed_operation", "_run_or_await_confirmation"):
        monkeypatch.setattr(case.fixture.orchestrator, name, forbidden)
    rebuilt = JsonlSessionRepository(repository.root)
    assert module.read(rebuilt, **arguments) == entry
    message = module.repair_message(rebuilt, **arguments)
    assert message.payload == {"role": "tool", "tool_call_id": arguments["tool_call_id"],
        "name": "run_operation", "command_id": arguments["command_id"],
        "content": json.dumps(final_payload, ensure_ascii=False, sort_keys=True)}
    assert module.repair_message(rebuilt, **arguments) == message
    assert len([e for e in rebuilt.get_branch("chain-session") if e.entry_type == "tool_receipt"]) == 1


def test_denied_and_not_yet_processed_pending_have_indistinguishable_domain_records(tmp_path):
    case = prepared_case(tmp_path)
    before = snapshot(case)
    case.fixture.orchestrator.permission_rules = permissions.Rules(
        deny=(permissions.Rule(permissions.PermissionClass.ANALYZE),))
    receipt = case.run_until_tool_return()
    assert receipt["output"]["denied"] is True
    assert case.fixture.orchestrator.proposal_store.latest_status(case.proposal.proposal_id) == "pending"
    assert case.fixture.orchestrator.operation_store.list_records() == []
    assert snapshot(case) == before


@pytest.mark.parametrize("transition", ["edited", "declined", "confirmed", "running"])
def test_advanced_proposal_is_not_re_admitted_as_pending(tmp_path, transition):
    case = prepared_case(tmp_path)
    orchestrator, proposal = case.fixture.orchestrator, case.proposal
    if transition == "edited":
        orchestrator.proposal_store.revise(proposal.proposal_id, base_revision=1, changes=proposal.changes)
    elif transition == "declined":
        orchestrator.proposal_store.decline(proposal.proposal_id, actor_type="user")
    else:
        record = orchestrator.confirm_proposal(proposal.proposal_id, revision=1, fingerprint=proposal.fingerprint,
            actor_type="user", current_context_fingerprint=FINGERPRINT,
            current_active_head_run_id=case.fixture.run_id)
        if transition == "running":
            orchestrator.operation_store.claim_execution(record.record_id, execution_key=execution_key(
                proposal_id=proposal.proposal_id, revision=1, fingerprint=proposal.fingerprint), lease_owner="old-worker")
            orchestrator.operation_store.append_status(record.record_id, "running")
    before = snapshot(case)
    with pytest.raises(ProposalAdmissionNeedsReconciliation):
        case.admit()
    assert snapshot(case) == before


def test_current_ledger_and_advanced_head_are_not_original_receipt_inputs(tmp_path):
    case = prepared_case(tmp_path)
    receipt = case.run_until_tool_return()
    output = receipt["output"]
    assert output["inferential_tests_run_this_session"] == 1
    prior_now = analysis_ledger.inferential_count(
        analysis_ledger.read(case.fixture.project_root), session_id="chain-session")
    budget = read_only_policy.decide(case.request.operation_id, case.request.changes,
                                   prior_inferential_steps=prior_now)
    assert prior_now + budget.inferential_steps == 2  # Recomputing the original tool field would double count.
    ChainStore(case.fixture.project_root / "workbench").activate("chain-a", active_head_run_id="later-run")
    record = case.fixture.orchestrator.operation_store.get(output["operation"]["record_id"])
    assert record.status == "completed" and record.target["run_id"] == case.fixture.run_id
    assert record.preconditions["active_head_run_id"] == case.fixture.run_id
    assert case.request.preconditions["context_fingerprint"] == FINGERPRINT


@pytest.fixture
def wal_case(tmp_path):
    repository = JsonlSessionRepository(tmp_path)
    repository.create_session("session", chain_id="chain", role="chain")
    arguments = {"session_id": "session", "command_id": "command", "provider_step": 1,
                 "tool_call_id": "", "invocation_id": "invocation-wal", "tool_call": {
                     "tool_call_id": "", "tool_id": "inspect", "arguments": {"nested": [1, {"a": 2}]}}}
    return repository, arguments, {"ok": True, "output": {"value": 3}, "error": None, "steps_remaining": 1}


def test_missing_receipt_cannot_be_repaired_from_domain_or_arguments(wal_case):
    repository, arguments, _payload = wal_case
    module = receipt_module()
    before = repository._session_path("session").read_bytes()
    assert module.read(repository, **arguments) is None
    with pytest.raises(module.ToolReceiptError, match="missing"):
        module.repair_message(repository, **arguments)
    assert repository._session_path("session").read_bytes() == before


@pytest.mark.parametrize("field", ["command_id", "provider_step", "tool_call", "payload"])
def test_wal_rejects_changed_identity_full_raw_call_and_final_payload(wal_case, field):
    repository, arguments, payload = wal_case
    module = receipt_module()
    module.persist(repository, payload=payload, **arguments)
    changed = copy.deepcopy(arguments)
    if field == "command_id": changed[field] = "different"
    if field == "provider_step": changed[field] = 2
    if field == "tool_call": changed[field]["arguments"]["nested"][1]["a"] = 2.0
    with pytest.raises(ValueError):
        if field == "payload":
            module.persist(repository, payload={**payload, "steps_remaining": 0}, **changed)
        else:
            module.read(repository, **changed)


def test_historical_off_branch_wal_is_refused_instead_of_returning_missing(wal_case):
    repository, arguments, payload = wal_case
    module = receipt_module()
    anchor = repository.append("session", "message", {"role": "user", "content": "anchor"})
    module.persist(repository, payload=payload, **arguments)
    repository.rewind("session", EntryRef("session", anchor.entry_id))
    for action in (lambda: module.read(repository, **arguments),
                   lambda: module.persist(repository, payload=payload, **arguments),
                   lambda: module.repair_message(repository, **arguments)):
        with pytest.raises(ValueError, match="off-branch"):
            action()


@pytest.mark.parametrize("after_log", [False, True])
def test_message_write_crash_is_repaired_from_original_wal(wal_case, monkeypatch, after_log):
    repository, arguments, payload = wal_case
    module = receipt_module()
    entry = module.persist(repository, payload=payload, **arguments)
    original = repository._atomic_append

    def interrupt(path, value):
        if value["entry_type"] == "message":
            if after_log: original(path, value)
            raise OSError("message append interrupted")
        return original(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(repository, "_atomic_append", interrupt)
        with pytest.raises(OSError, match="interrupted"):
            module.repair_message(repository, **arguments)
    rebuilt = JsonlSessionRepository(repository.root)
    assert module.read(rebuilt, **arguments) == entry
    repaired = module.repair_message(rebuilt, **arguments)
    assert json.loads(repaired.payload["content"]) == payload
    assert module.repair_message(rebuilt, **arguments) == repaired


@pytest.mark.parametrize("corruption", ["duplicate", "nan", "payload_type", "digest"])
def test_wal_strict_read_rejects_corruption_without_repair(wal_case, corruption):
    repository, arguments, payload = wal_case
    module = receipt_module()
    module.persist(repository, payload=payload, **arguments)
    path = repository._session_path("session")
    row = json.loads(path.read_text())
    if corruption == "duplicate":
        raw = json.dumps(row).replace('"provider_step": 1', '"provider_step": 1, "provider_step": 1')
    else:
        if corruption == "nan": row["payload"]["tool_result"]["output"] = float("nan")
        if corruption == "payload_type": row["payload"]["tool_result"]["ok"] = 1
        if corruption == "digest": row["payload"]["tool_call_sha256"] = "0" * 64
        raw = json.dumps(row)
    path.write_text(raw + "\n")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        module.read(repository, **arguments)
    assert path.read_bytes() == before


@pytest.mark.parametrize("invalid", ["bool_step", "numeric_call", "call_nan", "result_nan"])
def test_invalid_wal_input_is_refused_before_persistence(wal_case, invalid):
    repository, arguments, payload = wal_case
    module = receipt_module()
    if invalid == "bool_step": arguments["provider_step"] = True
    if invalid == "numeric_call": arguments["tool_call"]["tool_call_id"] = 1
    if invalid == "call_nan": arguments["tool_call"]["arguments"]["missing"] = float("nan")
    if invalid == "result_nan": payload["output"] = float("nan")
    before = repository._session_path("session").read_bytes()
    with pytest.raises(ValueError):
        module.persist(repository, payload=payload, **arguments)
    assert repository._session_path("session").read_bytes() == before


def test_duplicate_wal_identity_is_refused_even_if_one_entry_is_on_branch(wal_case):
    repository, arguments, payload = wal_case
    module = receipt_module()
    entry = module.persist(repository, payload=payload, **arguments)
    duplicate = {**entry.to_dict(), "entry_id": "duplicate-wal"}
    repository._atomic_append(repository._session_path("session"), duplicate)
    with pytest.raises(module.ToolReceiptError, match="duplicate"):
        module.read(repository, **arguments)


def test_logged_wal_with_unfinished_branch_pointer_requires_explicit_intent_recovery(wal_case, monkeypatch):
    repository, arguments, payload = wal_case
    module = receipt_module()
    original = repository._atomic_write_json

    def interrupt(path, value):
        if path == repository._metadata_path("session"):
            raise OSError("WAL metadata commit interrupted")
        return original(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(repository, "_atomic_write_json", interrupt)
        with pytest.raises(OSError, match="interrupted"):
            module.persist(repository, payload=payload, **arguments)
    rebuilt = JsonlSessionRepository(repository.root)
    with pytest.raises(module.ToolReceiptError, match="pending"):
        module.read(rebuilt, **arguments)
    recovered = rebuilt.recover_append_once("session")
    assert module.read(rebuilt, **arguments) == recovered
    assert json.loads(module.repair_message(rebuilt, **arguments).payload["content"]) == payload
