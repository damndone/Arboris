"""WorkbenchOrchestrator: state ownership and public entry point."""
from __future__ import annotations
import asyncio
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Iterable
from uuid import uuid4
from ..lineage.rerun_provenance import run_rerun_from_from_context
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
    ChainHeadConflict,
    ChainStore,
    ForkStore,
    RerunExecutionRequest,
    RerunExecutionResult,
    RerunExecutor,
)
from .context_tools import InspectNodeContextRequest, WorkbenchContextProvider
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
from . import operation_requests
from .operation_requests import OperationRequest, OperationReceipt
from .operation_outcome import result_view
from .operations import (
    RERUN_OPERATIONS,
    OperationRecord,
    OperationRecordStore,
    OperationRegistry,
    is_rerun_operation,
)
from .proposals import (
    ProposalConfirmation,
    ProposalConfirmationError,
    ProposalDecision,
    ProposalInvocation,
    ProposalRevision,
    ProposalStaleError,
    ProposalStore,
)
from .risk import (
    RiskAuthorizationReplay,
    RiskAuthorizationRequired,
    RiskAuthorizationStore,
)
from .session import EntryRef, JsonlSessionRepository
from .tools import ToolRegistry, ToolVisibleError
from .toolsets import _UPDATE_PLAN_SCHEMA, build_chain_tool_registry
from .operation_handlers.proposal_arguments import (
    _overrides_from_proposal_changes,
    _require_editable_rerun_target,
    _canonicalize_data_columns_cast_arguments,
    _canonicalize_workflow_arguments,
    _clustered_analysis_loop_intent,
    _precheck_model_options,
)
from .workflow import (
    WorkflowDraft,
    WorkflowExecutionState,
    execute_workflow,
)

# Preserve initialization order before loading the extracted implementation owners.
from .orchestration_workflows import OrchestrationWorkflows
from .orchestration_proposals import OrchestrationProposals
from .orchestration_data_effects import OrchestrationDataEffects
from .orchestration_reruns import OrchestrationReruns
from .orchestration_forks import OrchestrationForks
from .orchestration_analysis_loop import OrchestrationAnalysisLoop
from .orchestration_receipts import OrchestrationReceipts
from .orchestration_tools import OrchestrationTools
from .orchestration_permissions import OrchestrationPermissions
from .orchestration_commands import OrchestrationCommands
from .orchestration_operation_handler import (_OrchestratorOperationHandler, _DATA_CHILD_NODE_OPERATIONS)
from .orchestration_audit import _record_operation_in_ledger
from .orchestration_command import (AgentCommand)
class WorkbenchOrchestrator(OrchestrationWorkflows, OrchestrationProposals, OrchestrationDataEffects, OrchestrationReruns, OrchestrationForks, OrchestrationAnalysisLoop, OrchestrationReceipts, OrchestrationTools, OrchestrationPermissions, OrchestrationCommands):
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
        notebook_service=None,
        failpoint: OperationFailpoint | None = None,
        risk_authorization_store: RiskAuthorizationStore | None = None,
    ) -> None:
        self.repository = repository
        self.events = events
        self.main_session_id = main_session_id
        self.proposal_store = proposal_store or ProposalStore(repository.root)
        self.operation_store = operation_store or OperationRecordStore(repository.root)
        self.operation_registry = operation_registry or OperationRegistry()
        self.context_provider = context_provider
        self.notebook_service = notebook_service
        self.failpoint = failpoint or NoopFailpoint()
        self.risk_authorization_store = risk_authorization_store or RiskAuthorizationStore(
            repository.root
        )
        self.chain_store = ChainStore(repository.root)
        self.fork_store = ForkStore(repository.root)
        self._chains: dict[str, tuple[str, AgentCore]] = {}
        self._tool_registries: dict[str, ToolRegistry] = {}
        self._commands: dict[str, AgentCommand] = {}
        self._execution_locks: dict[str, asyncio.Lock] = {}
        self._operation_locks: dict[str, asyncio.Lock] = {}
        # Set by the HTTP layer, which owns the context-fingerprint and active
        # head checks a confirmation needs. When absent, every proposal waits
        # for the user (see read_only_policy).
        self.execution_policy = "auto_read_only"
        # v1.9.1 execution mode ("ask" every step / "auto" within an approved
        # plan), project permission rules and this conversation's grants; the
        # permission engine (permissions.py) decides from these and the
        # operation's declared class, never from model text.
        self.execution_mode = "ask"
        self.permission_rules = None
        self.session_grants = None
        self.plan_scope = None
        # runner(proposal, actor) confirms and executes under the given authority.
        self.read_only_runner: Callable[..., Awaitable[OperationRecord]] | None = None
        self._lease_owner = f"agent:{uuid4().hex}"


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
        if is_rerun_operation(record.operation_id):
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
        risk_authorization_id: str | None = None,
        risk_authorization_token: str | None = None,
        notebook_service=None,
    ) -> OperationRecord:
        """Execute one confirmed record through the shared lifecycle entry point."""

        record = self.operation_store.get(record_id)
        if record.status in {"completed", "failed", "stale", "cancelled"}:
            return self._ensure_terminal_analysis_loop_observation(
                record,
                project_root=project_root,
            )
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
        try:
            current_active_head_run_id = self._resolve_chain_head(
                record.chain_id,
                current_active_head_run_id,
            )
        except ChainHeadConflict as exc:
            raise ProposalStaleError(str(exc)) from exc
        if definition.requires_risk_authorization:
            if (risk_authorization_id is None) != (risk_authorization_token is None):
                raise RiskAuthorizationRequired(
                    "risk authorization id and token must be provided together"
                )
            if risk_authorization_id is not None and risk_authorization_token is not None:
                key = self._operation_execution_key(record)
                existing_authorization_id = record.execution.get("risk_authorization_id")
                if (
                    existing_authorization_id is not None
                    and existing_authorization_id != risk_authorization_id
                ):
                    try:
                        existing_authorization = self.risk_authorization_store.read(
                            str(existing_authorization_id)
                        )
                    except (KeyError, ValueError, FileNotFoundError) as exc:
                        raise RiskAuthorizationRequired(
                            "the operation's existing risk authorization is unavailable"
                        ) from exc
                    if existing_authorization.get("status") == "consumed":
                        raise RiskAuthorizationReplay(
                            "the operation already has a consumed risk authorization"
                        )
                record = self.operation_store.bind_risk_authorization(
                    record.record_id,
                    risk_authorization_id,
                )
                self.risk_authorization_store.consume(
                    risk_authorization_id,
                    token=risk_authorization_token,
                    operation_id=record.operation_id,
                    operation_version=record.operation_version,
                    proposal_id=record.proposal_id,
                    revision=record.proposal_revision,
                    fingerprint=record.proposal_fingerprint,
                    session_id=record.agent_session_id,
                    chain_id=record.chain_id,
                    active_head_run_id=str(current_active_head_run_id or ""),
                    execution_key=key,
                )
        handler = _OrchestratorOperationHandler(
            self,
            executor_key=definition.executor_key,
            project_root=project_root,
            current_context_fingerprint=current_context_fingerprint,
            current_active_head_run_id=current_active_head_run_id,
            rerun_executor=rerun_executor,
        )
        if record.execution.get("capability_notebook_id"):
            from .notebook.capability_adapter import CapabilityOperationHandler
            if notebook_service is None:
                from .notebook.errors import OptionExecutionGatewayUnavailable
                raise OptionExecutionGatewayUnavailable("The configured capability execution service is required for recovery.")
            handler = CapabilityOperationHandler(self, service=notebook_service, executor_key=definition.executor_key,
                project_root=project_root, current_context_fingerprint=current_context_fingerprint,
                current_active_head_run_id=current_active_head_run_id)
            if allow_recovery:
                record = handler.restore_receipt_binding(record)
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
            project_root=Path(project_root),
            operation_store=self.operation_store,
            operation_registry=self.operation_registry,
            handlers={definition.executor_key: handler},
            lease_owner=self._lease_owner,
            failpoint=self.failpoint,
            risk_authorization_store=self.risk_authorization_store,
        )
        from ..data_operations import DataColumnCastValidationError

        try:
            terminal = await lifecycle.execute(record_id)
        except DataColumnCastValidationError as exc:
            # The confirmed source does not resolve: the operation failed, and
            # the Agent is told so, instead of a server error and a pending record.
            current = self.operation_store.get(record_id)
            if current.status != "pending":
                raise
            terminal = self._fail_operation(current, error={
                "type": "DataColumnCastValidationError", "phase": "validate",
                "code": "WORKFLOW_SOURCE_INVALID", "message": str(exc)})
        if terminal.status in {"completed", "failed"}:
            _record_operation_in_ledger(project_root, terminal)
        return terminal


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
                if is_rerun_operation(record.operation_id) and isinstance(
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
                        await self.execute_confirmed_operation(
                            record.record_id,
                            current_context_fingerprint=record.preconditions.get("context_fingerprint"),
                            current_active_head_run_id=record.preconditions.get("active_head_run_id"),
                            allow_recovery=True,
                            project_root=project_root,
                        )
                    )
                    continue
                if not record.execution.get("execution_key"):
                    recovered.append(
                        self._fail_operation(
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
                    self._fail_operation(
                        record,
                        error={"type": type(exc).__name__, "message": str(exc)},
                    )
                )
        return recovered


    def _fail_operation(
        self,
        record: OperationRecord,
        *,
        error: dict[str, Any],
    ) -> OperationRecord:
        """Persist a failed operation and preserve its original evidence."""

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


    def register_main(self, session_id: str, agent: AgentCore) -> None:
        metadata = self.repository.get_metadata(session_id)
        if metadata.get("role") != "main" or session_id != self.main_session_id:
            raise ValueError("registered session must be the project Main session")
        self._register_session(str(metadata["chain_id"]), session_id, agent)

    def register_chain(
        self,
        chain_id: str,
        session_id: str,
        agent: AgentCore,
    ) -> None:
        metadata = self.repository.get_metadata(session_id)
        if metadata.get("role") != "chain" or metadata.get("chain_id") != chain_id:
            raise ValueError("registered session must be a matching chain session")
        self._register_session(chain_id, session_id, agent)

    def _register_session(self, chain_id: str, session_id: str, agent: AgentCore) -> None:
        from .analysis_history import require_active_session, capture_checkpoint
        require_active_session(self.repository, session_id)
        if chain_id in self._chains:
            raise ValueError(f"chain already registered: {chain_id}")
        if agent.session_id != session_id:
            raise ValueError("chain session and AgentCore session must match")
        self._chains[chain_id] = (session_id, agent)
        try:
            registry = self.tool_registry(chain_id)
            agent.attach_tools(registry.descriptors(), registry)
        except Exception:
            self._chains.pop(chain_id, None)
            self._tool_registries.pop(chain_id, None)
            raise
        self._tool_registries[chain_id] = registry
        agent.command_check = lambda: require_active_session(self.repository, session_id)
        agent.input_checkpoint = lambda command: capture_checkpoint(self.repository, session_id, command)
        from .planning.agent_phase import restore_phase
        agent.completion_check = lambda: self._completion_check(session_id)
        from .extension_runtime import dispatch_hooks
        hook_root = getattr(self.context_provider, "project_root", None)
        if hook_root is not None:
            agent.turn_end_observer = lambda command_id, status: dispatch_hooks(
                hook_root, "turn_end", {"session_id": session_id, "status": status}, key=command_id)
        from .research_review import build_context
        agent.research_review_mode = lambda: self.execution_mode
        agent.research_review_context = lambda candidate: build_context(
            getattr(self.context_provider, "project_root", self.repository.root.parent),
            self.plan_store.current(session_id), mode=self.execution_mode, candidate=candidate,
            config=getattr(agent.adapter, "config", None))
        def restore_core_phase(checkpoint):
            if checkpoint.get("kind") == "research_review/v1":
                from .research_review import restore_phase as restore_review
                return restore_review(agent, checkpoint)
            return restore_phase(core=agent, orchestrator=self, chain_id=chain_id, checkpoint=checkpoint)
        agent.phase_restorer = restore_core_phase


    def _completion_check(self, session_id, *, suggest=False):
        from .completion import derive_evidence, evaluate

        plan = self.plan_store.current(session_id)
        project_root = getattr(self.context_provider, "project_root", self.repository.root.parent)
        evidence, bound = derive_evidence(project_root, plan.completion if plan else None,
                                          plan.completion_evidence if plan else None)
        result = evaluate(project_root, plan.completion if plan else None, evidence, suggest=suggest, options=True)
        result['bound_by_workbench'] = bound['bound_by_workbench']
        if bound['dropped']:
            # Named back to the Agent: a reference that does not resolve to the right kind
            # of verified product is not evidence, whatever it was meant to be.
            result['dropped_references'] = bound['dropped'][:12]
        if result['status'] == 'requirements_met':
            # In the paid fix2 round (iv_weak, Auto) the Agent met every requirement and still
            # would not call the analysis complete, reading not_certified as unfinished.
            result['next_step'] = ('Delivery requirements are met: report this analysis as complete and state its '
                                   'scientific limitations. A finding that the data cannot support the requested '
                                   'claim is a complete answer, not a missing step.')
        elif bound['primary_candidates']:
            result['primary_candidates'] = bound['primary_candidates']
            result['next_step'] = ('Several fits are eligible as the primary model. Choose one by the fixed '
                                   'specification and question, never by significance, and call update_plan with '
                                   'completion_evidence {"models": [its run_id and artifact_id]}; the Workbench binds '
                                   'its diagnostics, the other fits and the report.')
        elif result.get('sensitivity_options') and result['status'] == 'partial':
            # off3 leverage.goal composed its report three times before the sensitivity fit it lacked.
            from .completion_sensitivity import SENSITIVITY_NEXT_STEP
            result['next_step'] = SENSITIVITY_NEXT_STEP
        elif 'compose_report' in bound and result['status'] == 'partial':
            result['compose_report'] = bound['compose_report']
            result['next_step'] = ('No report covers the bound results yet. Propose compose_report exactly as given '
                                   '(run_operation, operation.multi_step with one report.compose step).')
        if result['status'] == 'partial' and plan and (evidence or {}).get('models'):
            def repairable(code):
                return (code.startswith('report:') or ':model:' in code or ':sensitivity:' in code
                    or code.endswith(':diagnostics:computed_and_model_bound')
                    or code == 'iv:diagnostics:ar_unavailable')
            if all(repairable(code) for code in result['missing']):
                result['recovery_action'] = 'inspect_and_repair'
                from ..canonical import sha256_canonical
                result['recovery_question_sha256'] = sha256_canonical(plan.question)
        return result


    def _chain(self, chain_id: str) -> tuple[str, AgentCore]:
        try:
            return self._chains[chain_id]
        except KeyError as exc:
            raise KeyError(f"unknown chain: {chain_id}") from exc
