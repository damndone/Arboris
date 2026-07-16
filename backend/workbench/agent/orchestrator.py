"""Workbench-specific orchestration around the generic AgentCore."""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from ..services.rerun_service import (
    RerunReconciliationRequest,
    RerunService,
    RerunSubmissionRequest,
)
from ..code_execution import (
    CodeExecuteSpecV1,
    CodeExecuteValidationError,
    NondeterministicCodeError,
    apply_code_execute,
    preview_code_execute,
)
from ..data_operations import (
    DataCastItem,
    DataColumnCastSpecV1,
    DataColumnsCastSpecV1,
    apply_data_column_cast,
    apply_data_columns_cast,
    preview_data_column_cast,
    preview_data_columns_cast,
)
from ..lineage.run_inputs import read_run_inputs
from .chains import (
    ChainStore,
    ForkStore,
    RerunExecutionRequest,
    RerunExecutionResult,
    RerunExecutor,
)
from .context_tools import WorkbenchContextProvider
from .core import AgentCore
from .execution import (
    ChainExecutionLease,
    InjectedOperationCrash,
    NoopFailpoint,
    OperationEffect,
    OperationFailpoint,
    WorkbenchOperationLifecycle,
    execution_key,
    merge_execution,
)
from .events import AgentEventStream
from .operations import OperationRecord, OperationRecordStore, OperationRegistry
from .proposals import (
    ProposalConfirmationError,
    ProposalDecision,
    ProposalRevision,
    ProposalStaleError,
    ProposalStore,
)
from .session import EntryRef, JsonlSessionRepository
from .tools import ToolDefinition, ToolRegistry

# Operations whose effect is a derived data child node rather than a child
# chain, so completing without a child_chain_id is correct rather than a bug.
_DATA_CHILD_NODE_OPERATIONS = frozenset(
    {"data.column.cast", "data.columns.cast", "code.execute"}
)


@dataclass(frozen=True)
class AgentCommand:
    """A durable Main Agent to Chain Agent dispatch envelope."""

    command_id: str
    dispatch_seq: int
    child_agent_id: str
    chain_id: str
    objective: str
    allowed_operations: tuple[str, ...]
    budget: dict[str, Any]
    context_fingerprint: str | None = None
    command_type: str = "inspect"

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "dispatch_seq": self.dispatch_seq,
            "child_agent_id": self.child_agent_id,
            "chain_id": self.chain_id,
            "objective": self.objective,
            "allowed_operations": list(self.allowed_operations),
            "budget": dict(self.budget),
            "context_fingerprint": self.context_fingerprint,
            "command_type": self.command_type,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentCommand":
        return cls(
            command_id=str(value["command_id"]),
            dispatch_seq=int(value["dispatch_seq"]),
            child_agent_id=str(value["child_agent_id"]),
            chain_id=str(value["chain_id"]),
            objective=str(value["objective"]),
            allowed_operations=tuple(str(item) for item in value.get("allowed_operations", [])),
            budget=dict(value.get("budget") or {}),
            context_fingerprint=value.get("context_fingerprint"),
            command_type=str(value.get("command_type", "inspect")),
        )


class _OrchestratorOperationHandler:
    """Provide only operation-specific hooks to the shared lifecycle."""

    def __init__(
        self,
        orchestrator: "WorkbenchOrchestrator",
        *,
        executor_key: str,
        project_root: Path | str,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
        rerun_executor: RerunExecutor | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.executor_key = executor_key
        self.project_root = project_root
        self.current_context_fingerprint = current_context_fingerprint
        self.current_active_head_run_id = current_active_head_run_id
        self.rerun_executor = rerun_executor

    @staticmethod
    def _effect(record: OperationRecord) -> OperationEffect:
        return OperationEffect(
            outputs=dict(record.outputs),
            diff_ref=record.diff_ref,
            verification=dict(record.verification),
            bindings={
                str(key): str(value)
                for key, value in (record.execution.get("bindings") or {}).items()
            },
            status=record.status,
            error=record.error,
        )

    async def validate(self, record: OperationRecord) -> None:
        self.orchestrator.proposal_store.validate_confirmation_preconditions(
            record.proposal_id,
            current_context_fingerprint=self.current_context_fingerprint,
            current_active_head_run_id=self.current_active_head_run_id,
        )
        if self.executor_key == "graph.fork":
            source_session_entry_id = str(record.target["source_session_entry_id"])
            branch = self.orchestrator.repository.get_branch(record.agent_session_id)
            if source_session_entry_id not in {entry.entry_id for entry in branch}:
                raise ValueError("source session entry is outside the current branch")
        if self.executor_key == "data.column.cast":
            spec = self.orchestrator._data_column_cast_spec(record)
            preview = preview_data_column_cast(self.project_root, spec)
            if preview.fingerprint != record.preconditions.get("context_fingerprint"):
                raise ProposalStaleError("data column cast preview is stale")
        if self.executor_key == "data.columns.cast":
            spec = self.orchestrator._data_columns_cast_spec(record)
            preview = preview_data_columns_cast(self.project_root, spec)
            if preview.fingerprint != record.preconditions.get("context_fingerprint"):
                raise ProposalStaleError("data columns cast preview is stale")
        # code.execute intentionally does NOT re-preview here: previewing means
        # really running the user's code, and this hook runs on every attempt.
        # Its staleness check lives in _prepare_code_execute_effect, which can
        # tell "the source changed" apart from "the code isn't deterministic".

    def acquire_domain_lease(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
    ) -> ChainExecutionLease:
        lease = ChainExecutionLease(
            self.orchestrator.repository.root,
            chain_id=record.chain_id,
            active_head_run_id=str(record.preconditions["active_head_run_id"]),
            execution_key=execution_key,
        )
        lease.acquire()
        return lease

    def release_domain_lease(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
        lease: ChainExecutionLease,
    ) -> None:
        lease.release()

    async def prepare(self, record, *, execution_key, failpoint) -> OperationEffect:
        if self.executor_key == "model.rerun":
            return await self.orchestrator._prepare_rerun_effect(
                record,
                execution_key=execution_key,
                executor=None,
            )
        if self.executor_key == "graph.fork":
            prepared = await self.orchestrator._prepare_fork_effect(
                record,
                execution_key=execution_key,
            )
            return OperationEffect(execution=prepared.execution, status="submitted")
        if self.executor_key == "data.column.cast":
            return await self.orchestrator._prepare_data_column_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=False,
            )
        if self.executor_key == "data.columns.cast":
            return await self.orchestrator._prepare_data_columns_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=False,
            )
        if self.executor_key == "code.execute":
            return await self.orchestrator._prepare_code_execute_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=False,
            )
        raise ValueError(f"no executor registered for {self.executor_key}")

    async def execute(self, record, *, execution_key, failpoint) -> OperationEffect:
        if self.executor_key == "model.rerun":
            executor = self.rerun_executor or self.orchestrator.model_rerun_executor(
                self.project_root
            )
            return await self.orchestrator._prepare_rerun_effect(
                record,
                execution_key=execution_key,
                executor=executor,
            )
        elif self.executor_key == "graph.fork":
            return await self.orchestrator._prepare_fork_effect(
                record,
                execution_key=execution_key,
            )
        elif self.executor_key == "data.column.cast":
            return await self.orchestrator._prepare_data_column_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        elif self.executor_key == "data.columns.cast":
            return await self.orchestrator._prepare_data_columns_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        elif self.executor_key == "code.execute":
            return await self.orchestrator._prepare_code_execute_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        raise ValueError(f"no executor registered for {self.executor_key}")

    async def reconcile(self, record, *, execution_key, failpoint) -> OperationEffect:
        if self.executor_key == "model.rerun":
            return await self.orchestrator._reconcile_rerun_effect(
                record,
                project_root=self.project_root,
            )
        elif self.executor_key == "graph.fork":
            return await self.orchestrator._reconcile_fork_effect(
                record,
                execution_key=execution_key,
            )
        elif self.executor_key == "data.column.cast":
            return await self.orchestrator._prepare_data_column_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        elif self.executor_key == "data.columns.cast":
            return await self.orchestrator._prepare_data_columns_cast_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        elif self.executor_key == "code.execute":
            return await self.orchestrator._prepare_code_execute_effect(
                record,
                project_root=self.project_root,
                execution_key=execution_key,
                materialize=True,
            )
        raise ValueError(f"no reconciler registered for {self.executor_key}")

    async def commit_domain_state(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
        effect: OperationEffect,
    ) -> OperationEffect:
        return await self.orchestrator._commit_domain_state(
            record,
            effect=effect,
        )

    def publish_state(self, record: OperationRecord, *, phase: str) -> None:
        execution = dict(record.execution)
        payload = {
            "record_id": record.record_id,
            "status": record.status,
            **execution,
            **record.outputs,
        }
        if phase == "submitted":
            self.orchestrator.events.emit(
                record.agent_session_id,
                "operation_submitted",
                payload,
                command_id=record.command_id,
            )
            return
        if phase == "running":
            self.orchestrator.events.emit(
                record.agent_session_id,
                "operation_running",
                payload,
                command_id=record.command_id,
            )
            return
        if phase == "completed":
            if record.operation_id == "graph.fork":
                self.orchestrator.events.emit(
                    record.agent_session_id,
                    "fork_created",
                    payload,
                    command_id=record.command_id,
                )
            self.orchestrator._append_operation_result(
                self._result_session_id(record),
                record,
                outputs=record.outputs,
                status="completed",
            )
            self.orchestrator.events.emit(
                record.agent_session_id,
                "operation_completed",
                payload,
                command_id=record.command_id,
            )
            return
        if phase == "failed":
            self.orchestrator._append_operation_result(
                self._result_session_id(record),
                record,
                outputs=record.outputs,
                status="failed",
                error=record.error,
            )
            self.orchestrator.events.emit(
                record.agent_session_id,
                "operation_failed",
                {
                    "record_id": record.record_id,
                    "error": record.error,
                    **execution,
                },
                command_id=record.command_id,
            )

    def _result_session_id(self, record: OperationRecord) -> str:
        child_session_id = record.execution.get("child_session_id")
        if isinstance(child_session_id, str) and (
            self.orchestrator.repository.root
            / "agent-sessions"
            / f"{child_session_id}.meta.json"
        ).exists():
            return child_session_id
        return record.agent_session_id


def _overrides_from_proposal_changes(changes: dict[str, Any]) -> dict[str, Any]:
    """Translate proposal old/new evidence into the rerun wire payload."""

    return {
        key: value["new"]
        if isinstance(value, dict) and "new" in value
        else value
        for key, value in changes.items()
    }


class WorkbenchOrchestrator:
    """Bind Main/Chain roles to AgentCore without leaking Workbench state into it."""

    def __init__(
        self,
        repository: JsonlSessionRepository,
        events: AgentEventStream,
        *,
        main_session_id: str,
        proposal_store: ProposalStore | None = None,
        operation_store: OperationRecordStore | None = None,
        operation_registry: OperationRegistry | None = None,
        context_provider: WorkbenchContextProvider | None = None,
        failpoint: OperationFailpoint | None = None,
    ) -> None:
        self.repository = repository
        self.events = events
        self.main_session_id = main_session_id
        self.proposal_store = proposal_store or ProposalStore(repository.root)
        self.operation_store = operation_store or OperationRecordStore(repository.root)
        self.operation_registry = operation_registry or OperationRegistry()
        self.context_provider = context_provider
        self.failpoint = failpoint or NoopFailpoint()
        self.chain_store = ChainStore(repository.root)
        self.fork_store = ForkStore(repository.root)
        self._chains: dict[str, tuple[str, AgentCore]] = {}
        self._tool_registries: dict[str, ToolRegistry] = {}
        self._commands: dict[str, AgentCommand] = {}
        self._execution_locks: dict[str, asyncio.Lock] = {}
        self._operation_locks: dict[str, asyncio.Lock] = {}
        self._lease_owner = f"agent:{uuid4().hex}"

    def create_proposal(
        self,
        *,
        chain_id: str,
        operation_id: str,
        target: dict[str, Any],
        preconditions: dict[str, Any],
        changes: dict[str, Any],
        evidence_refs: Iterable[str],
        expected_effect: Iterable[str],
        risks: Iterable[str],
        operation_version: str = "v1",
        command_id: str | None = None,
        proposal_id: str | None = None,
    ) -> ProposalRevision:
        session_id, _agent = self._chain(chain_id)
        definition = self.operation_registry.require(operation_id, operation_version)
        definition.validate(target=target, preconditions=preconditions, changes=changes)
        proposal = self.proposal_store.create(
            session_id=session_id,
            chain_id=chain_id,
            operation_id=operation_id,
            operation_version=operation_version,
            target=target,
            preconditions=preconditions,
            changes=changes,
            evidence_refs=evidence_refs,
            expected_effect=expected_effect,
            risks=risks,
            command_id=command_id,
            proposal_id=proposal_id,
        )
        self.repository.append(
            session_id,
            "custom_message",
            {
                "message_type": "operation_proposal",
                "audience": "model",
                "content": json.dumps(proposal.to_dict(), ensure_ascii=False, sort_keys=True),
                "proposal": proposal.to_dict(),
            },
        )
        self.events.emit(
            session_id,
            "proposal_ready",
            proposal.to_dict(),
            command_id=command_id,
        )
        self.events.emit(
            session_id,
            "needs_confirmation",
            {"proposal_id": proposal.proposal_id, "revision": proposal.revision},
            command_id=command_id,
        )
        return proposal

    def revise_proposal(
        self,
        proposal_id: str,
        *,
        base_revision: int,
        changes: dict[str, Any],
        expected_effect: Iterable[str] | None = None,
        risks: Iterable[str] | None = None,
    ) -> ProposalRevision:
        latest = self.proposal_store.latest_revision(proposal_id)
        definition = self.operation_registry.require(
            latest.operation_id,
            latest.operation_version,
        )
        definition.validate(
            target=latest.target,
            preconditions=latest.preconditions,
            changes=changes,
        )
        revised = self.proposal_store.revise(
            proposal_id,
            base_revision=base_revision,
            changes=changes,
            expected_effect=expected_effect,
            risks=risks,
        )
        self.repository.append(
            revised.session_id,
            "custom_message",
            {
                "message_type": "operation_proposal_revision",
                "audience": "model",
                "content": json.dumps(revised.to_dict(), ensure_ascii=False, sort_keys=True),
                "proposal": revised.to_dict(),
            },
        )
        self.events.emit(
            revised.session_id,
            "proposal_revision",
            revised.to_dict(),
            command_id=revised.command_id,
        )
        return revised

    def decline_proposal(
        self,
        proposal_id: str,
        *,
        actor_type: str,
        reason: str | None = None,
    ) -> ProposalDecision:
        decision = self.proposal_store.decline(
            proposal_id,
            actor_type=actor_type,
            reason=reason,
        )
        self.repository.append(
            decision.session_id,
            "custom_message",
            {
                "message_type": "operation_proposal_declined",
                "audience": "model",
                "content": json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True),
                "proposal_id": decision.proposal_id,
                "decision": decision.to_dict(),
            },
        )
        self.events.emit(
            decision.session_id,
            "proposal_declined",
            decision.to_dict(),
            command_id=decision.command_id,
        )
        return decision

    def confirm_proposal(
        self,
        proposal_id: str,
        *,
        revision: int,
        fingerprint: str,
        actor_type: str,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
    ) -> OperationRecord:
        latest = self.proposal_store.latest_revision(proposal_id)
        try:
            confirmation = self.proposal_store.confirm(
                proposal_id,
                revision=revision,
                fingerprint=fingerprint,
                actor_type=actor_type,
                current_context_fingerprint=current_context_fingerprint,
                current_active_head_run_id=current_active_head_run_id,
            )
        except ProposalStaleError:
            self.events.emit(
                latest.session_id,
                "proposal_stale",
                {"proposal_id": proposal_id, "revision": revision},
                command_id=latest.command_id,
            )
            raise

        record = self.operation_store.create_pending(
            confirmation,
            command_id=confirmation.command_id,
        )
        self.repository.append(
            confirmation.session_id,
            "custom_message",
            {
                "message_type": "operation_confirmation",
                "audience": "model",
                "content": json.dumps(confirmation.to_dict(), ensure_ascii=False, sort_keys=True),
                "confirmation": confirmation.to_dict(),
                "operation_record_id": record.record_id,
            },
        )
        self.events.emit(
            confirmation.session_id,
            "proposal_confirmed",
            {
                "proposal_id": confirmation.proposal_id,
                "revision": confirmation.revision,
                "fingerprint": confirmation.fingerprint,
                "operation_record_id": record.record_id,
            },
            command_id=confirmation.command_id,
        )
        return record

    @staticmethod
    def _deterministic_effect_ids(
        record: OperationRecord,
        execution_key_value: str,
    ) -> tuple[str, str, str]:
        suffix = execution_key_value.removeprefix("exec_")
        fork_id = str(record.execution.get("fork_id") or f"fork_{suffix}")
        child_chain_id = str(
            record.execution.get("child_chain_id") or f"chain_{suffix}"
        )
        child_session_id = str(
            record.execution.get("child_session_id") or f"session_{child_chain_id}"
        )
        return fork_id, child_chain_id, child_session_id

    def _operation_execution_key(self, record: OperationRecord) -> str:
        return execution_key(
            proposal_id=record.proposal_id,
            revision=record.proposal_revision,
            fingerprint=record.proposal_fingerprint,
        )

    @staticmethod
    def _data_column_cast_spec(record: OperationRecord) -> DataColumnCastSpecV1:
        target = record.target
        changes = record.outputs.get("typed_changes") or {}
        proposal_changes = changes or {}
        # The typed target is authoritative; changes are retained in the
        # proposal for audit and must match it through the registry validator.
        return DataColumnCastSpecV1(
            source_run_id=str(target["run_id"]),
            source_node_id=str(target["node_ref"]),
            source_artifact_id=str(target["artifact_id"]),
            column=str(target["column"]),
            target_dtype=str(target["target_dtype"]),
        )

    async def _prepare_data_column_cast_effect(
        self,
        record: OperationRecord,
        *,
        project_root: Path | str,
        execution_key: str,
        materialize: bool,
    ) -> OperationEffect:
        spec = self._data_column_cast_spec(record)
        preview = preview_data_column_cast(project_root, spec)
        expected_fingerprint = record.preconditions.get("context_fingerprint")
        if preview.fingerprint != expected_fingerprint:
            raise ProposalStaleError("data column cast preview is stale")
        execution = {
            **record.execution,
            "source_run_id": spec.source_run_id,
            "source_node_ref": spec.source_node_id,
            "source_artifact_id": spec.source_artifact_id,
            "column": spec.column,
            "target_dtype": spec.target_dtype,
            "data_preview_fingerprint": preview.fingerprint,
            "source_sha256": preview.source_sha256,
        }
        if not materialize:
            return OperationEffect(execution=execution, status="submitted")
        effect = apply_data_column_cast(
            project_root,
            spec,
            preview,
            execution_key_value=execution_key,
        )
        return OperationEffect(
            outputs={
                "status": "completed",
                "source_run_id": spec.source_run_id,
                "source_node_id": spec.source_node_id,
                "source_artifact_id": spec.source_artifact_id,
                "artifact_id": effect.artifact_id,
                "artifact_path": effect.artifact_path,
                "recipe_artifact_id": effect.recipe_artifact_id,
                "recipe_path": effect.recipe_path,
                "child_node_id": effect.child_node_id,
                "preview_fingerprint": preview.fingerprint,
            },
            diff_ref={
                "kind": "data.schema_diff.v1",
                "source_fingerprint": preview.schema_fingerprint_before,
                "result_fingerprint": preview.schema_fingerprint_after,
                "column": spec.column,
                "before_dtype": preview.before_dtype,
                "after_dtype": preview.after_dtype,
            },
            verification={
                "passed": True,
                "status": "completed",
                "checks": {
                    "source_immutable": True,
                    "artifact_registered": True,
                    "graph_child": True,
                    "preview_matches_effect": True,
                    "downstream_rerun_required": list(preview.downstream_invalidation),
                },
            },
            bindings={
                "data_artifact_id": effect.artifact_id,
                "data_child_node_id": effect.child_node_id,
                "data_recipe_artifact_id": effect.recipe_artifact_id,
            },
            execution=execution,
            status="completed",
        )

    @staticmethod
    def _data_columns_cast_spec(record: OperationRecord) -> DataColumnsCastSpecV1:
        target = record.target
        casts = target.get("casts") or []
        return DataColumnsCastSpecV1(
            source_run_id=str(target["run_id"]),
            source_node_id=str(target["node_ref"]),
            source_artifact_id=str(target["artifact_id"]),
            casts=tuple(
                DataCastItem(str(item["column"]), str(item["target_dtype"]))
                for item in casts
            ),
            output_format=str(target.get("output_format", "csv")),
        )

    async def _prepare_data_columns_cast_effect(
        self,
        record: OperationRecord,
        *,
        project_root: Path | str,
        execution_key: str,
        materialize: bool,
    ) -> OperationEffect:
        spec = self._data_columns_cast_spec(record)
        preview = preview_data_columns_cast(project_root, spec)
        expected_fingerprint = record.preconditions.get("context_fingerprint")
        if preview.fingerprint != expected_fingerprint:
            raise ProposalStaleError("data columns cast preview is stale")
        execution = {
            **record.execution,
            "source_run_id": spec.source_run_id,
            "source_node_ref": spec.source_node_id,
            "source_artifact_id": spec.source_artifact_id,
            "casts": [item.to_dict() for item in spec.casts],
            "data_preview_fingerprint": preview.fingerprint,
            "source_sha256": preview.source_sha256,
        }
        if not materialize:
            return OperationEffect(execution=execution, status="submitted")
        effect = apply_data_columns_cast(
            project_root,
            spec,
            preview,
            execution_key_value=execution_key,
        )
        return OperationEffect(
            outputs={
                "status": "completed",
                "source_run_id": spec.source_run_id,
                "source_node_id": spec.source_node_id,
                "source_artifact_id": spec.source_artifact_id,
                "artifact_id": effect.artifact_id,
                "artifact_path": effect.artifact_path,
                "recipe_artifact_id": effect.recipe_artifact_id,
                "recipe_path": effect.recipe_path,
                "child_node_id": effect.child_node_id,
                "preview_fingerprint": preview.fingerprint,
            },
            diff_ref={
                "kind": "data.schema_diff.v1",
                "source_fingerprint": preview.schema_fingerprint_before,
                "result_fingerprint": preview.schema_fingerprint_after,
                "casts": [
                    {
                        "column": item.column,
                        "before_dtype": item.before_dtype,
                        "after_dtype": item.after_dtype,
                    }
                    for item in preview.items
                ],
            },
            verification={
                "passed": True,
                "status": "completed",
                "checks": {
                    "source_immutable": True,
                    "artifact_registered": True,
                    "graph_child": True,
                    "preview_matches_effect": True,
                    "columns_cast": [item.column for item in spec.casts],
                    "downstream_rerun_required": list(preview.downstream_invalidation),
                },
            },
            bindings={
                "data_artifact_id": effect.artifact_id,
                "data_child_node_id": effect.child_node_id,
                "data_recipe_artifact_id": effect.recipe_artifact_id,
            },
            execution=execution,
            status="completed",
        )

    @staticmethod
    def _code_execute_spec(record: OperationRecord) -> CodeExecuteSpecV1:
        target = record.target
        return CodeExecuteSpecV1(
            source_run_id=str(target["run_id"]),
            source_node_id=str(target["node_ref"]),
            source_artifact_id=str(target["artifact_id"]),
            code=str(target["code"]),
            language=str(target.get("language", "python")),
            output_format=str(target.get("output_format", "csv")),
        )

    async def _prepare_code_execute_effect(
        self,
        record: OperationRecord,
        *,
        project_root: Path | str,
        execution_key: str,
        materialize: bool,
    ) -> OperationEffect:
        spec = self._code_execute_spec(record)
        preview = preview_code_execute(project_root, spec)
        expected_fingerprint = record.preconditions.get("context_fingerprint")
        if preview.fingerprint != expected_fingerprint:
            # Distinguish the two ways this happens, because they need opposite
            # responses: a changed source means re-propose against the new data;
            # a stable source means the code itself is not deterministic and
            # re-proposing would just fail again.
            if preview.status != "ready":
                raise CodeExecuteValidationError(
                    f"code failed when re-run for execution: {preview.error or 'unknown error'}"
                )
            if preview.source_sha256 != record.preconditions.get("source_sha256", preview.source_sha256):
                raise ProposalStaleError("code execute preview is stale")
            raise NondeterministicCodeError(
                "the code produced a different result than the one confirmed; it is "
                "not a deterministic transform, so nothing was written"
            )
        execution = {
            **record.execution,
            "source_run_id": spec.source_run_id,
            "source_node_ref": spec.source_node_id,
            "source_artifact_id": spec.source_artifact_id,
            "language": spec.language,
            "code_sha256": spec.code_sha256,
            "data_preview_fingerprint": preview.fingerprint,
            "source_sha256": preview.source_sha256,
        }
        if not materialize:
            return OperationEffect(execution=execution, status="submitted")
        effect = apply_code_execute(
            project_root,
            spec,
            preview,
            execution_key_value=execution_key,
        )
        return OperationEffect(
            outputs={
                "status": "completed",
                "source_run_id": spec.source_run_id,
                "source_node_id": spec.source_node_id,
                "source_artifact_id": spec.source_artifact_id,
                "artifact_id": effect.artifact_id,
                "artifact_path": effect.artifact_path,
                "recipe_artifact_id": effect.recipe_artifact_id,
                "recipe_path": effect.recipe_path,
                "child_node_id": effect.child_node_id,
                "preview_fingerprint": preview.fingerprint,
                "stdout": preview.stdout,
            },
            diff_ref={
                "kind": "data.schema_diff.v1",
                "source_fingerprint": preview.schema_fingerprint_before,
                "result_fingerprint": preview.schema_fingerprint_after,
                "columns_added": list(preview.columns_added),
                "columns_removed": list(preview.columns_removed),
                "dtype_changes": [change.to_dict() for change in preview.dtype_changes],
                "row_count_before": preview.row_count_before,
                "row_count_after": preview.row_count_after,
            },
            verification={
                "passed": True,
                "status": "completed",
                "checks": {
                    "source_immutable": True,
                    "artifact_registered": True,
                    "graph_child": True,
                    "preview_matches_effect": True,
                    "sandboxed": True,
                    "deterministic": True,
                    "downstream_rerun_required": list(preview.downstream_invalidation),
                },
            },
            bindings={
                "data_artifact_id": effect.artifact_id,
                "data_child_node_id": effect.child_node_id,
                "data_recipe_artifact_id": effect.recipe_artifact_id,
            },
            execution=execution,
            status="completed",
        )

    def _find_rerun_child_run_id(
        self,
        record: OperationRecord,
        execution_key_value: str,
    ) -> str | None:
        """Find an already materialized child before retrying submission.

        The run input is the durable effect witness. If a process dies after
        the rerun service creates the child but before the operation record
        binds it, retry must bind this witness instead of submitting another
        child run.
        """

        runs_root = self.repository.root.parent / "runs"
        matches: list[str] = []
        if not runs_root.exists():
            return None
        for run_root in sorted(path for path in runs_root.iterdir() if path.is_dir()):
            try:
                inputs = read_run_inputs(run_root)
            except (FileNotFoundError, OSError, ValueError):
                continue
            context = inputs.get("workbench_context")
            if not isinstance(context, dict):
                continue
            if context.get("operation_record_id") != record.record_id:
                continue
            witness_key = context.get("execution_key")
            if witness_key is not None and witness_key != execution_key_value:
                continue
            matches.append(run_root.name)
        if len(matches) > 1:
            raise ValueError("multiple_child_runs_for_operation")
        return matches[0] if matches else None

    def _has_fork_context(self, session_id: str, fork_id: str) -> bool:
        try:
            branch = self.repository.get_branch(session_id)
        except (KeyError, ValueError):
            return False
        return any(
            entry.entry_type == "custom_message"
            and entry.payload.get("message_type") == "fork_context"
            and (entry.payload.get("metadata") or {}).get("fork_id") == fork_id
            for entry in branch
        )

    def model_rerun_executor(self, project_root: Path | str) -> RerunExecutor:
        """Build the Agent adapter over the request-independent rerun service."""

        service = RerunService(project_root)

        async def execute(request: RerunExecutionRequest) -> RerunExecutionResult:
            workbench_context = {
                "operation_id": request.operation_id,
                "operation_version": request.operation_version,
                "operation_record_id": request.operation_record_id,
                "proposal_id": request.proposal_id,
                "source_chain_id": request.source_chain_id,
                "source_session_id": request.source_session_id,
                "source_run_id": request.source_run_id,
                "source_node_ref": request.source_node_ref,
                "context_version": request.context_version,
                "context_fingerprint": request.context_fingerprint,
                "owner_run_id": request.owner_run_id,
                "op_node_id": request.op_node_id,
                "node_hash": request.node_hash,
                "forest_node_key": request.forest_node_key,
                "owner_resolution": request.owner_resolution,
                "active_head_run_id": request.active_head_run_id,
                "fork_id": request.fork_id,
                "child_chain_id": request.child_chain_id,
                "child_session_id": request.child_session_id,
            }
            if request.execution_key:
                workbench_context["execution_key"] = request.execution_key
            submission = service.submit(
                RerunSubmissionRequest(
                    source_run_id=request.source_run_id,
                    from_node=request.source_node_ref,
                    op_overrides=_overrides_from_proposal_changes(request.changes),
                    rerun_reason="agent_confirmed",
                    rerun_from={
                        "owner_run_id": request.source_run_id,
                        "op_node_id": request.source_node_ref,
                        "node_hash": request.node_hash,
                        "forest_node_key": request.forest_node_key,
                    },
                    workbench_context=workbench_context,
                )
            )
            return RerunExecutionResult(
                target_run_id=submission.run_id,
                outputs={"status": submission.status},
            )

        return execute

    async def _prepare_rerun_effect(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
        executor: RerunExecutor | None,
    ) -> OperationEffect:
        """Create or discover the rerun effect without lifecycle bookkeeping."""

        source_session_id = record.agent_session_id
        source_metadata = self.repository.get_metadata(source_session_id)
        source_leaf_id = source_metadata.get("leaf_entry_id")
        if not isinstance(source_leaf_id, str) or not source_leaf_id:
            raise ValueError("source session has no stable leaf")

        source_run_id = str(record.target["run_id"])
        source_node_ref = str(record.target["node_ref"])
        fork_id, child_chain_id, child_session_id = self._deterministic_effect_ids(
            record,
            execution_key,
        )
        run_family_id = str(
            record.preconditions.get("run_family_id")
            or f"legacy-family:{source_run_id}"
        )
        execution = {
            **record.execution,
            "source_run_id": source_run_id,
            "source_node_ref": source_node_ref,
            "source_session_id": source_session_id,
            "source_session_entry_id": source_leaf_id,
            "active_head_run_id": str(record.preconditions["active_head_run_id"]),
            "run_family_id": run_family_id,
            "fork_id": fork_id,
            "child_chain_id": child_chain_id,
            "child_session_id": child_session_id,
        }
        self._ensure_child_context(
            record=record,
            source_session_entry_id=source_leaf_id,
            source_session_id=source_session_id,
            source_run_id=source_run_id,
            source_node_ref=source_node_ref,
            run_family_id=run_family_id,
            fork_id=fork_id,
            child_chain_id=child_chain_id,
            child_session_id=child_session_id,
            context_fingerprint=str(record.preconditions["context_fingerprint"]),
            append_fork_context=False,
        )
        request = RerunExecutionRequest(
            operation_id=record.operation_id,
            operation_version=record.operation_version,
            operation_record_id=record.record_id,
            proposal_id=record.proposal_id,
            source_chain_id=record.chain_id,
            source_session_id=source_session_id,
            source_run_id=source_run_id,
            source_node_ref=source_node_ref,
            context_version=str(record.preconditions["context_version"]),
            context_fingerprint=str(record.preconditions["context_fingerprint"]),
            owner_run_id=str(record.target["run_id"]),
            op_node_id=str(record.target["node_ref"]),
            node_hash=str(record.target["node_hash"]),
            forest_node_key=str(record.target["forest_node_key"]),
            owner_resolution=str(record.preconditions["owner_resolution"]),
            active_head_run_id=str(record.preconditions["active_head_run_id"]),
            changes=dict(self.proposal_store.latest_revision(record.proposal_id).changes),
            fork_id=fork_id,
            child_chain_id=child_chain_id,
            child_session_id=child_session_id,
            execution_key=execution_key,
        )
        if executor is None:
            return OperationEffect(execution=execution, status="submitted")
        bound_child_run_id = (record.execution.get("bindings") or {}).get(
            "child_run_id"
        )
        witnessed_child_run_id = self._find_rerun_child_run_id(record, execution_key)
        if bound_child_run_id:
            if witnessed_child_run_id != bound_child_run_id:
                raise ValueError("bound_child_run_witness_missing")
            result = RerunExecutionResult(
                target_run_id=str(bound_child_run_id),
                outputs={"status": "submitted"},
            )
        elif witnessed_child_run_id:
            result = RerunExecutionResult(
                target_run_id=witnessed_child_run_id,
                outputs={"status": "submitted"},
            )
        else:
            result = executor(request)
            if inspect.isawaitable(result):
                result = await result
        if not isinstance(result, RerunExecutionResult):
            raise TypeError("rerun executor returned an invalid result")

        result_status = str(result.outputs.get("status", "completed"))
        if result_status in {"running", "submitted"}:
            operation_status = "running"
        elif result_status == "completed":
            operation_status = "completed"
        else:
            raise RuntimeError(
                f"rerun executor returned unexpected status: {result_status}"
            )
        return OperationEffect(
            outputs={**result.outputs, "target_run_id": result.target_run_id},
            diff_ref=result.diff_ref,
            verification=result.verification,
            bindings={
                "fork_id": fork_id,
                "child_chain_id": child_chain_id,
                "child_session_id": child_session_id,
                "child_run_id": result.target_run_id,
            },
            execution=execution,
            status=operation_status,
        )

    async def _reconcile_rerun_effect(
        self,
        record: OperationRecord,
        *,
        project_root: Path | str,
    ) -> OperationEffect:
        """Rebuild rerun outputs from the immutable child-run witness."""

        target_run_id = (record.execution.get("bindings") or {}).get(
            "child_run_id"
        ) or record.outputs.get("target_run_id")
        if not isinstance(target_run_id, str) or not target_run_id:
            raise ValueError("operation record has no target run")
        source_run_id = str(record.target["run_id"])
        source_node_ref = str(record.target["node_ref"])
        execution = record.execution
        workbench_context = {
            "operation_id": record.operation_id,
            "operation_version": record.operation_version,
            "operation_record_id": record.record_id,
            "proposal_id": record.proposal_id,
            "source_chain_id": record.chain_id,
            "source_session_id": record.agent_session_id,
            "source_run_id": source_run_id,
            "source_node_ref": source_node_ref,
            "context_version": str(record.preconditions["context_version"]),
            "context_fingerprint": str(record.preconditions["context_fingerprint"]),
            "owner_run_id": str(record.target["run_id"]),
            "op_node_id": str(record.target["node_ref"]),
            "node_hash": str(record.target["node_hash"]),
            "forest_node_key": str(record.target["forest_node_key"]),
            "owner_resolution": str(record.preconditions["owner_resolution"]),
            "active_head_run_id": execution["active_head_run_id"],
            "fork_id": execution["fork_id"],
            "child_chain_id": execution["child_chain_id"],
            "child_session_id": execution["child_session_id"],
            "execution_key": execution.get("execution_key"),
        }
        request = RerunReconciliationRequest(
            source_run_id=source_run_id,
            target_run_id=target_run_id,
            from_node=source_node_ref,
            op_overrides=_overrides_from_proposal_changes(
                self.proposal_store.latest_revision(record.proposal_id).changes
            ),
            workbench_context=workbench_context,
        )
        try:
            reconciliation = RerunService(project_root).reconcile_submission(request)
        except Exception as exc:
            return OperationEffect(
                outputs=dict(record.outputs),
                bindings={
                    str(key): str(value)
                    for key, value in (record.execution.get("bindings") or {}).items()
                },
                execution=execution,
                status="failed",
                error={"type": type(exc).__name__},
            )

        outputs = {
            **record.outputs,
            **reconciliation.outputs,
            "target_run_id": target_run_id,
        }
        if reconciliation.status in {"running", "submitted"}:
            status = "running"
        elif (
            reconciliation.status == "completed"
            and reconciliation.verification.get("passed") is True
        ):
            status = "completed"
        else:
            status = "failed"
        return OperationEffect(
            outputs=outputs,
            diff_ref=reconciliation.diff_ref,
            verification=reconciliation.verification,
            bindings={
                str(key): str(value)
                for key, value in (record.execution.get("bindings") or {}).items()
            },
            execution=execution,
            status=status,
            error=reconciliation.error,
        )

    async def _prepare_fork_effect(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
    ) -> OperationEffect:
        """Create or discover a graph fork without lifecycle bookkeeping."""

        source_session_id = record.agent_session_id
        source_session_entry_id = str(record.target["source_session_entry_id"])
        source_run_id = str(record.target["run_id"])
        source_node_ref = str(record.target["node_ref"])
        fork_id, child_chain_id, child_session_id = self._deterministic_effect_ids(
            record,
            execution_key,
        )
        run_family_id = str(
            record.preconditions.get("run_family_id")
            or f"legacy-family:{source_run_id}"
        )
        execution = {
            **record.execution,
            "source_run_id": source_run_id,
            "source_node_ref": source_node_ref,
            "source_session_id": source_session_id,
            "source_session_entry_id": source_session_entry_id,
            "active_head_run_id": str(record.preconditions["active_head_run_id"]),
            "run_family_id": run_family_id,
            "fork_id": fork_id,
            "child_chain_id": child_chain_id,
            "child_session_id": child_session_id,
            "graph_fork_node_id": f"fork:{fork_id}",
        }
        self._ensure_child_context(
            record=record,
            source_session_entry_id=source_session_entry_id,
            source_session_id=source_session_id,
            source_run_id=source_run_id,
            source_node_ref=source_node_ref,
            run_family_id=run_family_id,
            fork_id=fork_id,
            child_chain_id=child_chain_id,
            child_session_id=child_session_id,
            context_fingerprint=str(record.preconditions["context_fingerprint"]),
            append_fork_context=True,
        )
        return OperationEffect(
            outputs={
                "fork_id": fork_id,
                "child_chain_id": child_chain_id,
                "child_session_id": child_session_id,
                "graph_fork_node_id": f"fork:{fork_id}",
                "status": "active",
            },
            verification={
                "passed": True,
                "status": "completed",
                "checks": {
                    "fork_record": True,
                    "child_chain": True,
                    "child_session": True,
                },
            },
            bindings={
                "fork_id": fork_id,
                "child_chain_id": child_chain_id,
                "child_session_id": child_session_id,
            },
            execution=execution,
            status="completed",
        )

    async def _reconcile_fork_effect(
        self,
        record: OperationRecord,
        *,
        execution_key: str,
    ) -> OperationEffect:
        return await self._prepare_fork_effect(record, execution_key=execution_key)

    async def _commit_domain_state(
        self,
        record: OperationRecord,
        *,
        effect: OperationEffect,
    ) -> OperationEffect:
        """Commit or fail domain state after the effect identity is durable."""

        execution = merge_execution(record.execution, effect.execution)
        bindings = {**(record.execution.get("bindings") or {}), **effect.bindings}
        if effect.status == "failed":
            error = effect.error or {"type": "OperationFailed"}
            child_chain_id = execution.get("child_chain_id") or bindings.get(
                "child_chain_id"
            )
            fork_id = execution.get("fork_id") or bindings.get("fork_id")
            if isinstance(child_chain_id, str) and child_chain_id:
                try:
                    self.chain_store.fail(child_chain_id, error=error)
                except KeyError:
                    pass
            if isinstance(fork_id, str) and fork_id:
                try:
                    self.fork_store.fail(fork_id, error=error)
                except KeyError:
                    pass
            return OperationEffect(
                outputs=effect.outputs,
                diff_ref=effect.diff_ref,
                verification=effect.verification,
                bindings=effect.bindings,
                execution=execution,
                status=effect.status,
                error=effect.error,
            )

        child_chain_id = execution.get("child_chain_id") or bindings.get(
            "child_chain_id"
        )
        fork_id = execution.get("fork_id") or bindings.get("fork_id")
        if not isinstance(child_chain_id, str) or not child_chain_id:
            if record.operation_id in _DATA_CHILD_NODE_OPERATIONS:
                return OperationEffect(
                    outputs=effect.outputs,
                    diff_ref=effect.diff_ref,
                    verification=effect.verification,
                    bindings=effect.bindings,
                    execution=execution,
                    status=effect.status,
                    error=effect.error,
                )
            raise ValueError("completed operation has no child chain")
        if not isinstance(fork_id, str) or not fork_id:
            raise ValueError("completed operation has no fork")
        if record.operation_id == "model.rerun":
            target_run_id = effect.outputs.get("target_run_id") or bindings.get(
                "child_run_id"
            )
        else:
            target_run_id = execution.get("source_run_id") or record.target.get(
                "run_id"
            )
        if not isinstance(target_run_id, str) or not target_run_id:
            raise ValueError("completed operation has no active-head run")
        self.chain_store.activate(child_chain_id, active_head_run_id=target_run_id)
        self.fork_store.activate(fork_id)
        return OperationEffect(
            outputs=effect.outputs,
            diff_ref=effect.diff_ref,
            verification=effect.verification,
            bindings=effect.bindings,
            execution=execution,
            status=effect.status,
            error=effect.error,
        )

    def _ensure_child_context(
        self,
        *,
        record: OperationRecord,
        source_session_entry_id: str,
        source_session_id: str,
        source_run_id: str,
        source_node_ref: str,
        run_family_id: str,
        fork_id: str,
        child_chain_id: str,
        child_session_id: str,
        context_fingerprint: str,
        append_fork_context: bool,
    ) -> None:
        try:
            self.fork_store.get(fork_id)
        except KeyError:
            self.fork_store.create(
                fork_id=fork_id,
                source_chain_id=record.chain_id,
                source_node_ref=source_node_ref,
                source_session_id=source_session_id,
                source_session_entry_id=source_session_entry_id,
                inherited_context_fingerprint=context_fingerprint,
                child_chain_id=child_chain_id,
                child_session_id=child_session_id,
            )
        try:
            self.chain_store.get(child_chain_id)
        except KeyError:
            self.chain_store.create_child(
                child_chain_id=child_chain_id,
                source_chain_id=record.chain_id,
                run_family_id=run_family_id,
                source_run_id=source_run_id,
                source_node_ref=source_node_ref,
                fork_id=fork_id,
                child_session_id=child_session_id,
            )
        try:
            self.repository.get_metadata(child_session_id)
        except KeyError:
            self.repository.create_session(
                child_session_id,
                chain_id=child_chain_id,
                role="chain",
                inherited_parent_ref=EntryRef(
                    source_session_id,
                    source_session_entry_id,
                ),
            )
        if append_fork_context and not self._has_fork_context(child_session_id, fork_id):
            self.repository.append(
                child_session_id,
                "custom_message",
                {
                    "message_type": "fork_context",
                    "audience": "model",
                    "name": "workbench_fork_context",
                    "content": "A graph fork was created from verified Workbench context.",
                    "metadata": {
                        "fork_id": fork_id,
                        "source_run_id": source_run_id,
                        "source_node_ref": source_node_ref,
                        "source_session_id": source_session_id,
                        "source_session_entry_id": source_session_entry_id,
                        "context_fingerprint": context_fingerprint,
                    },
                },
            )

    async def execute_confirmed_operation(
        self,
        record_id: str,
        *,
        project_root: Path | str,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
        allow_recovery: bool = False,
        rerun_executor: RerunExecutor | None = None,
    ) -> OperationRecord:
        """Execute one confirmed record through the shared lifecycle entry point."""

        record = self.operation_store.get(record_id)
        if record.status in {"completed", "failed", "stale", "cancelled"}:
            return record
        if (
            not allow_recovery
            and record.status in {"submitted", "running", "recovering"}
            and record.execution.get("execution_key")
        ):
            return record
        definition = self.operation_registry.require(
            record.operation_id,
            record.operation_version,
        )
        handler = _OrchestratorOperationHandler(
            self,
            executor_key=definition.executor_key,
            project_root=project_root,
            current_context_fingerprint=current_context_fingerprint,
            current_active_head_run_id=current_active_head_run_id,
            rerun_executor=rerun_executor,
        )
        if allow_recovery and record.status != "recovering":
            # Validate before changing the durable state.  A stale context
            # must remain fail-closed and must not become a recoverable
            # mutation merely because the request used the recovery entrypoint.
            validation = handler.validate(record)
            if inspect.isawaitable(validation):
                await validation
            record = self.operation_store.append_status(
                record.record_id,
                "recovering",
                execution=record.execution,
                outputs=record.outputs,
                diff_ref=record.diff_ref,
                verification=record.verification,
                error=record.error,
            )
        lifecycle = WorkbenchOperationLifecycle(
            operation_store=self.operation_store,
            operation_registry=self.operation_registry,
            handlers={definition.executor_key: handler},
            lease_owner=self._lease_owner,
            failpoint=self.failpoint,
        )
        return await lifecycle.execute(record_id)

    async def recover_operations(
        self,
        *,
        project_root: Path | str,
    ) -> list[OperationRecord]:
        """Recover interrupted records using the same deterministic lifecycle.

        A child run already present in ``runs/`` is first rebound from its
        immutable ``workbench_context`` witness. Records without a bound
        effect are retried with the same execution key; the domain executor
        must therefore either discover that witness or create the deterministic
        effect once. Recovery never invents a new proposal or execution key.
        """

        recovered: list[OperationRecord] = []
        active_statuses = {"pending", "submitted", "running", "recovering"}
        for record in self.operation_store.list_records():
            if record.status not in active_statuses:
                continue
            if record.status != "recovering":
                record = self.operation_store.append_status(
                    record.record_id,
                    "recovering",
                    execution=record.execution,
                    outputs=record.outputs,
                    verification=record.verification,
                )
            try:
                bindings = record.execution.get("bindings") or {}
                target_run_id = bindings.get("child_run_id") or record.outputs.get(
                    "target_run_id"
                )
                if record.operation_id == "model.rerun" and isinstance(
                    target_run_id, str
                ) and target_run_id:
                    if record.outputs.get("target_run_id") != target_run_id:
                        record = self.operation_store.append_status(
                            record.record_id,
                            record.status,
                            execution=record.execution,
                            outputs={
                                **record.outputs,
                                "target_run_id": target_run_id,
                            },
                        )
                    recovered.append(
                        await self.reconcile_confirmed_proposal(
                            record.record_id,
                            project_root=project_root,
                        )
                    )
                    continue
                if not record.execution.get("execution_key"):
                    recovered.append(
                        self._fail_recovered_operation(
                            record,
                            error={"type": "ChildRunMissing", "phase": "submit"},
                        )
                    )
                    continue
                recovered.append(
                    await self.execute_confirmed_operation(
                        record.record_id,
                        project_root=project_root,
                        current_context_fingerprint=record.preconditions.get(
                            "context_fingerprint"
                        ),
                        current_active_head_run_id=record.preconditions.get(
                            "active_head_run_id"
                        ),
                        allow_recovery=True,
                    )
                )
            except Exception as exc:
                recovered.append(
                    self._fail_recovered_operation(
                        record,
                        error={"type": type(exc).__name__},
                    )
                )
        return recovered

    def _fail_recovered_operation(
        self,
        record: OperationRecord,
        *,
        error: dict[str, Any],
    ) -> OperationRecord:
        """Persist a restart-recovery failure and preserve its evidence."""

        execution = record.execution
        child_chain_id = execution.get("child_chain_id")
        if isinstance(child_chain_id, str) and child_chain_id:
            try:
                self.chain_store.fail(child_chain_id, error=error)
            except KeyError:
                pass
        fork_id = execution.get("fork_id")
        if isinstance(fork_id, str) and fork_id:
            try:
                self.fork_store.fail(fork_id, error=error)
            except KeyError:
                pass
        record = self.operation_store.append_status(
            record.record_id,
            "failed",
            execution=execution,
            outputs=record.outputs,
            verification=record.verification,
            error=error,
        )
        child_session_id = execution.get("child_session_id")
        if not isinstance(child_session_id, str) or not (
            self.repository.root / "agent-sessions" / f"{child_session_id}.meta.json"
        ).exists():
            child_session_id = record.agent_session_id
        self._append_operation_result(
            child_session_id,
            record,
            outputs=record.outputs,
            status="failed",
            error=error,
        )
        self.events.emit(
            record.agent_session_id,
            "operation_failed",
            {"record_id": record.record_id, "error": error, **execution},
            command_id=record.command_id,
        )
        return record

    async def reconcile_confirmed_proposal(
        self,
        record_id: str,
        *,
        project_root: Path | str,
    ) -> OperationRecord:
        """Compatibility wrapper around the shared lifecycle reconciler."""

        record = self.operation_store.get(record_id)
        if record.status in {"completed", "failed", "stale", "cancelled"}:
            return record
        return await self.execute_confirmed_operation(
            record_id,
            project_root=project_root,
            current_context_fingerprint=record.preconditions.get(
                "context_fingerprint"
            ),
            current_active_head_run_id=record.preconditions.get(
                "active_head_run_id"
            ),
            allow_recovery=True,
        )


    async def execute_confirmed_proposal(
        self,
        record_id: str,
        *,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
        executor: RerunExecutor,
    ) -> OperationRecord:
        """Compatibility wrapper around the shared rerun lifecycle."""

        return await self.execute_confirmed_operation(
            record_id,
            project_root=self.repository.root.parent,
            current_context_fingerprint=current_context_fingerprint,
            current_active_head_run_id=current_active_head_run_id,
            allow_recovery=True,
            rerun_executor=executor,
        )


    async def execute_confirmed_fork(
        self,
        record_id: str,
        *,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
    ) -> OperationRecord:
        """Compatibility wrapper around the shared graph.fork lifecycle."""

        return await self.execute_confirmed_operation(
            record_id,
            project_root=self.repository.root.parent,
            current_context_fingerprint=current_context_fingerprint,
            current_active_head_run_id=current_active_head_run_id,
            allow_recovery=True,
        )


    def _append_operation_result(
        self,
        session_id: str,
        record: OperationRecord,
        *,
        outputs: dict[str, Any],
        status: str,
        error: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "record_id": record.record_id,
            "operation_id": record.operation_id,
            "status": status,
            "outputs": outputs,
            "error": error,
        }
        self.repository.append(
            session_id,
            "custom_message",
            {
                "message_type": "operation_result",
                "audience": "model",
                "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                "operation_result": payload,
            },
        )

    def register_chain(
        self,
        chain_id: str,
        session_id: str,
        agent: AgentCore,
    ) -> None:
        if chain_id in self._chains:
            raise ValueError(f"chain already registered: {chain_id}")
        if agent.session_id != session_id:
            raise ValueError("chain session and AgentCore session must match")
        metadata = self.repository.get_metadata(session_id)
        if metadata.get("role") != "chain" or metadata.get("chain_id") != chain_id:
            raise ValueError("registered session must be a matching chain session")
        self._chains[chain_id] = (session_id, agent)
        try:
            registry = self.tool_registry(chain_id)
            agent.attach_tools(registry.descriptors(), registry)
        except Exception:
            self._chains.pop(chain_id, None)
            self._tool_registries.pop(chain_id, None)
            raise
        self._tool_registries[chain_id] = registry

    def _chain(self, chain_id: str) -> tuple[str, AgentCore]:
        try:
            return self._chains[chain_id]
        except KeyError as exc:
            raise KeyError(f"unknown chain: {chain_id}") from exc

    @property
    def data_operation_project_root(self) -> Path | None:
        """The project the context provider is bound to, if there is one.

        Derived rather than injected: the provider already owns the project
        identity, and a second source for it could disagree with the one the
        read-only tools answer from.
        """

        root = getattr(self.context_provider, "project_root", None)
        return Path(root) if root is not None else None

    def _canonicalize_data_columns_cast_arguments(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Bind the backend facts a model must never supply for a data cast.

        The model contributes the intent — which run, which node, which columns
        become which dtype. Everything else is a fact only the backend can
        state truthfully:

          * `artifact_id` — the durable identity of the data behind the node.
            A model naming it could aim a confirmed operation at data the user
            never selected.
          * `context_fingerprint` — this is the *preview* fingerprint, and the
            preview is computed here, from the real data. The live smoke showed
            a model inventing a fingerprint; execution rejected it, which is
            correct but useless. Binding it means a confirmable proposal is an
            executable one.

        `preview_project_root` must be resolvable; without it (pure contract
        tests) the arguments pass through unchanged and execution still
        revalidates.
        """

        project_root = self.data_operation_project_root
        if project_root is None:
            return arguments
        from ..data_operations import (
            DataCastItem,
            DataColumnCastValidationError,
            DataColumnsCastSpecV1,
            preview_data_columns_cast,
            resolve_data_column_cast_context,
        )

        target = dict(arguments.get("target") or {})
        preconditions = dict(arguments.get("preconditions") or {})
        run_id = str(target.get("run_id") or "")
        node_ref = str(target.get("node_ref") or "")
        casts = target.get("casts")
        if not run_id or not node_ref or not isinstance(casts, list) or not casts:
            # Leave a structurally malformed proposal to the operation validator,
            # which owns the error vocabulary the Agent already knows to react to.
            return arguments
        try:
            context = resolve_data_column_cast_context(
                project_root,
                source_run_id=run_id,
                source_node_id=node_ref,
            )
            spec = DataColumnsCastSpecV1(
                source_run_id=run_id,
                source_node_id=node_ref,
                source_artifact_id=str(context["source_artifact_id"]),
                casts=tuple(
                    DataCastItem(str(item["column"]), str(item["target_dtype"]))
                    for item in casts
                    if isinstance(item, dict)
                ),
                output_format=str(target.get("output_format", "csv")),
            )
            preview = preview_data_columns_cast(project_root, spec)
        except (DataColumnCastValidationError, KeyError, TypeError, ValueError):
            # The proposal cannot be resolved against the real data (bad column,
            # unknown node, wrong dtype). Pass it through unbound so the operation
            # validator produces its actionable error. NB: OSError is deliberately
            # NOT caught — a filesystem fault is a real problem the user must see,
            # not something to disguise as "your proposal was malformed".
            return arguments

        target["artifact_id"] = spec.source_artifact_id
        target["casts"] = [item.to_dict() for item in spec.casts]
        target["output_format"] = spec.output_format
        preconditions["context_version"] = "data-columns-cast.v1"
        preconditions["context_fingerprint"] = preview.fingerprint
        preconditions["active_head_run_id"] = run_id
        preconditions["owner_resolution"] = "typed_data_node"
        changes = {
            "casts": target["casts"],
            "output_format": spec.output_format,
        }
        return {
            **arguments,
            "target": target,
            "preconditions": preconditions,
            "changes": changes,
        }

    def _canonicalize_proposal_arguments(
        self,
        operation_id: str,
        arguments: dict[str, Any],
        *,
        session_id: str,
    ) -> dict[str, Any]:
        """Re-derive canonical target/precondition facts from the backend.

        Design §5.3: the model supplies references (run id + node ref +
        active head); the backend is the source of truth for node_hash,
        forest_node_key, fingerprint, and owner_resolution. The live DeepSeek
        smoke showed the model copying the UI forest-projection key
        (`<hash>::<node_id>`) into the proposal, which the rerun validator
        then correctly rejected at execution — canonicalize at creation so a
        confirmable proposal is executable. Without a context provider (pure
        contract tests) the arguments pass through unchanged.
        """
        if operation_id == "data.columns.cast":
            return self._canonicalize_data_columns_cast_arguments(arguments)
        if self.context_provider is None or operation_id not in {"model.rerun", "graph.fork"}:
            return arguments
        inspect = getattr(self.context_provider, "inspect_node_context", None)
        if inspect is None:
            return arguments
        from .context_tools import InspectNodeContextRequest

        target = dict(arguments.get("target") or {})
        preconditions = dict(arguments.get("preconditions") or {})
        snapshot = inspect(
            InspectNodeContextRequest(
                request_id=f"propose:{target.get('run_id')}",
                owner_run_id=str(target.get("run_id")),
                op_node_id=str(target.get("node_ref")),
                active_head_run_id=str(preconditions.get("active_head_run_id")),
            )
        )
        target["node_hash"] = snapshot["node_hash"]
        target["forest_node_key"] = snapshot["forest_node_key"]
        preconditions["context_version"] = snapshot["context_version"]
        preconditions["context_fingerprint"] = snapshot["context_fingerprint"]
        preconditions["owner_resolution"] = snapshot["owner_resolution"]
        preconditions["active_head_run_id"] = snapshot["active_head_run_id"]
        if operation_id == "graph.fork":
            metadata = self.repository.get_metadata(session_id)
            current_leaf = metadata.get("leaf_entry_id")
            if not isinstance(current_leaf, str) or not current_leaf:
                raise ValueError("graph_fork_source_entry_missing")
            supplied_entry = target.get("source_session_entry_id")
            if supplied_entry is not None and str(supplied_entry) != current_leaf:
                raise ValueError("graph_fork_source_entry_not_current_leaf")
            target["source_session_entry_id"] = current_leaf
        return {**arguments, "target": target, "preconditions": preconditions}

    def tool_registry(self, chain_id: str) -> ToolRegistry:
        """Return the allowlisted Workbench tools scoped to one chain."""

        existing = self._tool_registries.get(chain_id)
        if existing is not None:
            return existing
        session_id, _agent = self._chain(chain_id)
        registry = ToolRegistry()

        if self.context_provider is not None:
            for definition in self.context_provider.tool_definitions(
                chain_id=chain_id,
                session_id=session_id,
                operation_registry=self.operation_registry,
            ):
                registry.register(definition)

        def propose_operation(arguments: dict[str, Any], context) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            operation_id = str(arguments["operation_id"])
            arguments = self._canonicalize_proposal_arguments(
                operation_id,
                arguments,
                session_id=session_id,
            )
            metadata = context.metadata
            if "allowed_operations" in metadata:
                allowed_operations = {
                    str(item) for item in (metadata.get("allowed_operations") or [])
                }
                if operation_id not in allowed_operations:
                    raise PermissionError("operation_not_allowed")
            command_context_fingerprint = metadata.get("context_fingerprint")
            if (
                command_context_fingerprint is not None
                and arguments["preconditions"].get("context_fingerprint")
                != command_context_fingerprint
            ):
                raise ValueError("context_fingerprint_mismatch")
            command_id = metadata.get("command_id")
            if command_id is not None and not isinstance(command_id, str):
                raise ValueError("invalid_command_id")
            proposal = self.create_proposal(
                chain_id=chain_id,
                operation_id=operation_id,
                operation_version=arguments.get("operation_version", "v1"),
                target=arguments["target"],
                preconditions=arguments["preconditions"],
                changes=arguments["changes"],
                evidence_refs=arguments["evidence_refs"],
                expected_effect=arguments["expected_effect"],
                risks=arguments["risks"],
                command_id=command_id,
            )
            return {"requires_confirmation": True, "proposal": proposal.to_dict()}

        registry.register(
            ToolDefinition(
                tool_id="propose_operation",
                version="v1",
                input_schema=self.operation_registry.proposal_tool_schema(),
                side_effect="proposal",
                scope_requirements=("chain",),
                handler=propose_operation,
            )
        )
        return registry

    def dispatch_to_chain(
        self,
        chain_id: str,
        *,
        objective: str,
        allowed_operations: Iterable[str],
        budget: dict[str, Any],
        context_fingerprint: str | None = None,
        command_type: str = "inspect",
        command_id: str | None = None,
    ) -> AgentCommand:
        """Append and publish one Main→Chain command, idempotently."""

        existing = self._load_command(command_id) if command_id else None
        if existing is not None:
            return existing
        try:
            session_id, _agent = self._chains[chain_id]
        except KeyError as exc:
            raise KeyError(f"unknown chain: {chain_id}") from exc

        command = AgentCommand(
            command_id=command_id or uuid4().hex,
            dispatch_seq=self._next_dispatch_seq(chain_id),
            child_agent_id=session_id,
            chain_id=chain_id,
            objective=objective,
            allowed_operations=tuple(allowed_operations),
            budget=dict(budget),
            context_fingerprint=context_fingerprint,
            command_type=command_type,
        )
        self.repository.append(
            session_id,
            "custom_message",
            {
                "message_type": "main_to_chain_command",
                "audience": "model",
                "content": objective,
                "command": command.to_dict(),
            },
        )
        self.events.emit(
            self.main_session_id,
            "command_dispatched",
            command.to_dict(),
            command_id=command.command_id,
        )
        self._commands[command.command_id] = command
        return command

    async def execute(self, command_id: str) -> str:
        """Run a dispatched chain command through its AgentCore exactly once at a time."""

        command = self._load_command(command_id)
        if command is None:
            raise KeyError(f"unknown agent command: {command_id}")
        completed = self._completed_result(command_id)
        if completed is not None:
            return completed
        lock = self._execution_locks.setdefault(command_id, asyncio.Lock())
        async with lock:
            completed = self._completed_result(command_id)
            if completed is not None:
                return completed
            _session_id, agent = self._chains[command.chain_id]
            result = await agent.prompt(
                command.objective,
                tool_context={
                    "command_id": command.command_id,
                    "allowed_operations": list(command.allowed_operations),
                    "context_fingerprint": command.context_fingerprint,
                },
                budget=command.budget,
            )
            self.events.emit(
                self.main_session_id,
                "command_completed",
                {"command_id": command.command_id, "chain_id": command.chain_id, "result": result},
                command_id=command.command_id,
            )
            return result

    def _load_command(self, command_id: str | None) -> AgentCommand | None:
        if command_id is None:
            return None
        if command_id in self._commands:
            return self._commands[command_id]
        for event in self.events.replay(self.main_session_id):
            if event.event_type == "command_dispatched" and event.payload.get("command_id") == command_id:
                command = AgentCommand.from_dict(event.payload)
                self._commands[command_id] = command
                return command
        return None

    def _next_dispatch_seq(self, chain_id: str) -> int:
        sequence = [
            int(event.payload.get("dispatch_seq", 0))
            for event in self.events.replay(self.main_session_id)
            if event.event_type == "command_dispatched"
            and event.payload.get("chain_id") == chain_id
        ]
        return max(sequence, default=0) + 1

    def _completed_result(self, command_id: str) -> str | None:
        for event in self.events.replay(self.main_session_id):
            if event.event_type == "command_completed" and event.payload.get("command_id") == command_id:
                return str(event.payload.get("result", ""))
        return None
