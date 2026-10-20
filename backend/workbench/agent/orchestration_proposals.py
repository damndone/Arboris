"""orchestration proposals: methods over the existing shared state."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Iterable
from ..lineage.run_inputs import read_run_inputs
from .chains import ChainStore
from . import operation_requests
from .operation_requests import OperationRequest, OperationReceipt
from .operations import OperationRecord
from .proposals import ProposalDecision, ProposalInvocation, ProposalRevision, ProposalStaleError
from .proposal_text import bounded_audit_content
from .tools import ToolVisibleError
from .operation_handlers.proposal_arguments import _overrides_from_proposal_changes, _require_editable_rerun_target

class OrchestrationProposals:
    def _operation_chain(self, session_id: str, target: dict[str, Any]) -> str:
        """Bind Main operations to a project-owned source without changing its role."""
        import hashlib
        from .chains import ensure_chain_root

        metadata = self.repository.get_metadata(session_id)
        if metadata["role"] == "chain":
            return str(metadata["chain_id"])
        source_run_id = str(target["run_id"])
        identity = hashlib.sha256(f"{session_id}:{source_run_id}".encode()).hexdigest()[:24]
        chain_id = f"main_source_{identity}"
        ensure_chain_root(self.repository.root, runs_root=self.data_operation_project_root / "runs",
            chain_id=chain_id, active_head_run_id=source_run_id, agent_session_id=session_id)
        return chain_id

    def _resolve_chain_head(
        self,
        chain_id: str,
        requested_active_head_run_id: str | None,
    ) -> str | None:
        """Read a managed Chain head without breaking legacy/unit-only callers."""

        try:
            return ChainStore(self.repository.root, create=False).resolve_active_head(
                chain_id,
                requested_active_head_run_id=requested_active_head_run_id,
            )
        except KeyError:
            return requested_active_head_run_id


    def _preflight_model_rerun_declarations(
        self, arguments: dict[str, Any], *, metadata_edit: bool = False
    ) -> None:
        """Refuse, before the user is asked, a rerun that cannot do what it says.

        Execution applies the same shared check; running it here too means the
        Agent hears the reason while it can still propose the right operation,
        instead of the user confirming a proposal that is then refused.
        """

        from ..lineage.upload_store import verify_upload
        from ..repository.run_repository import _resolve_run_root
        from ..services.run_service import (
            RerunDeclarationError,
            reject_invalid_rerun_declarations,
        )

        project_root = getattr(self.context_provider, "project_root", None)
        run_id = (arguments.get("target") or {}).get("run_id")
        if project_root is None or not isinstance(run_id, str) or not run_id:
            return
        try:
            run_root = _resolve_run_root(str(project_root), run_id)
        except Exception:
            return
        _require_editable_rerun_target(run_root, run_id, arguments)
        try:
            inputs = read_run_inputs(run_root)
            upload_bytes = verify_upload(
                Path(project_root), str((inputs.get("upload") or {}).get("sha256") or "")
            ).read_bytes()
        except Exception:
            # Unreadable inputs are execution's to report, with its own codes.
            return
        try:
            reject_invalid_rerun_declarations(
                inputs["form"],
                _overrides_from_proposal_changes(dict(arguments.get("changes") or {})),
                upload_bytes,
                str((inputs.get("upload") or {}).get("filename") or ""),
                metadata_edit=metadata_edit,
            )
        except RerunDeclarationError as exc:
            from .tools import ToolVisibleError

            # A plain ValueError reaches the model as its type name only; this
            # message is what lets the Agent re-plan.
            raise ToolVisibleError(f"{exc.code}: {exc}") from exc


    def admit_operation_request(
        self,
        request: OperationRequest,
        *,
        chain_id: str,
        session_id: str | None = None,
        command_id: str | None = None,
        proposal_id: str | None = None,
        invocation: ProposalInvocation | None = None,
    ) -> OperationReceipt:
        """Admit a typed request under a server-selected Chain session."""

        if session_id is None:
            session_id, _agent = self._chain(chain_id)
        return operation_requests.admit(
            request,
            chain_id=chain_id,
            session_id=session_id,
            command_id=command_id,
            proposal_id=proposal_id,
            repository=self.repository,
            operation_registry=self.operation_registry,
            proposal_store=self.proposal_store,
            events=self.events,
            invocation=invocation,
        )


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
                "content": bounded_audit_content(revised.to_dict()),
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
                "content": bounded_audit_content(decision.to_dict()),
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
        from .analysis_history import require_active_session
        require_active_session(self.repository, latest.session_id)
        from . import permissions
        from .permission_config import project_permission_rules
        from ..operation_approvals import OperationApprovalStore

        rules = project_permission_rules(self.repository.root.parent)
        request = self._permission_request(latest, within_budget=True)
        decision = permissions.decide(permissions.Mode(self.execution_mode), request, rules,
                                      self.session_grants or permissions.Grants())
        if decision.outcome == permissions.Outcome.DENY:
            raise PermissionError(decision.reason)
        if actor_type not in {"user", "human_ui", "human_cli"} and decision.outcome == permissions.Outcome.ASK:
            raise PermissionError(decision.reason)
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
        approval = OperationApprovalStore(self.repository.root).issue(confirmation)
        record = self.operation_store.append_status(record.record_id, record.status,
            execution={**record.execution, "approval_id":approval["approval_id"]})
        self.repository.append(
            confirmation.session_id,
            "custom_message",
            {
                "message_type": "operation_confirmation",
                "audience": "model",
                "content": bounded_audit_content(confirmation.to_dict()),
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

