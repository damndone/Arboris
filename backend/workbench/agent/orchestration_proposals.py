"""orchestration proposals: methods over the existing shared state."""
from __future__ import annotations
import json
import re
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Iterable
from ..lineage.run_inputs import read_run_inputs
from ..api_errors import WorkbenchAPIError
from .chains import ChainStore
from . import operation_requests
from .operation_requests import OperationRequest, OperationReceipt
from .operations import OperationRecord
from .proposals import ProposalDecision, ProposalInvocation, ProposalRevision, ProposalStaleError
from .proposal_text import bounded_audit_content
from .tools import ToolVisibleError
from .operation_handlers.proposal_arguments import _overrides_from_proposal_changes, _require_editable_rerun_target

_EXCLUSION = re.compile(r"\b(?:exclud\w*|without|remov\w*|drop(?:s|ped|ping)?|omit\w*|except(?:ing)?)\b(.{1,80})", re.I)


def _letters(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", text.lower())


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


    def _preflight_workflow_columns(self, arguments: dict[str, Any]) -> str | None:
        """Check workflow columns and automatic group counts before admission.

        Confirmation compiles against the same columns; in QRData 40 all 12 stuck operations
        passed the proposal and only failed here, so the Agent never heard why.
        """

        steps = (arguments.get("changes") or {}).get("steps")
        target = arguments.get("target") or {}
        if not isinstance(steps, list) or not target.get("run_id") or not target.get("node_ref"):
            return
        from ..statistical_exploration import resolve_statistical_source
        from .plan_preflight import check_workflow_group_limits
        from .workflow_contracts import validate_workflow_steps

        project_root = Path(getattr(self.context_provider, "project_root", self.repository.root.parent)).expanduser().resolve()
        try:
            source, frame = resolve_statistical_source(
                project_root, source_run_id=str(target["run_id"]), source_node_id=str(target["node_ref"]),
                source_artifact_id=str(target["artifact_id"]))
        except (OSError, ValueError, KeyError):
            return None  # Confirmation resolves the source for itself and reports any failure there.
        normalized = validate_workflow_steps(steps, available_columns=list(frame.columns))
        check_workflow_group_limits(frame, normalized)
        return source["source_sha256"]

    def _proposal_source_frame(self, target: dict[str, Any]) -> Any:
        """The frame a proposal's target node holds, or None; confirmation resolves it again and reports failures."""

        from ..data_operations import resolve_data_column_cast_context
        from ..data_operations.frames import _read_frame

        project_root = Path(getattr(self.context_provider, "project_root", self.repository.root.parent)).expanduser().resolve()
        try:
            context = resolve_data_column_cast_context(
                project_root, source_run_id=str(target["run_id"]), source_node_id=str(target["node_ref"]))
            return _read_frame(project_root / "runs" / str(target["run_id"]) / context["source_artifact_path"])
        except (OSError, ValueError, KeyError):
            return None

    def _preflight_pack_steps(self, arguments: dict[str, Any]) -> None:
        """Run each pack step's source-frame checks before the person is asked.

        Execution runs the same preflight; QRData 374 (55ce11c1 round) proposed synthetic-control periods
        written as ranges and the refusal could only come after approval, and QRData 070 (08cfac50 round)
        did the same with a proportions group_order. Steps that read another step's output are checked at
        execution, where that frame exists.
        """

        steps = (arguments.get("changes") or {}).get("steps")
        target = arguments.get("target") or {}
        if not isinstance(steps, list) or not target.get("run_id") or not target.get("node_ref"):
            return
        from ..contracts.common.errors import OperationValidationError
        from .p7_pack_registry import p7_pack_registry

        from .workflow_capability_adapters import preflight_statistical

        pack = set(p7_pack_registry.operation_ids())
        checked = [step for step in steps if isinstance(step, dict)
                   and (step.get("operation_id") in pack or str(step.get("operation_id", "")).startswith("test."))
                   and isinstance(step.get("spec"), dict) and "source" not in step["spec"]]
        if not checked:
            return
        frame = self._proposal_source_frame(target)
        if frame is None:
            return
        from .workflow_contract_parts.graph import _with_single_values

        for step in checked:
            spec = _with_single_values(step["operation_id"], step["spec"])
            request = {"operation_id": step["operation_id"], "input_mode": spec.get("input_mode"),
                       "column_bindings": spec.get("column_bindings"), "options": spec.get("options")}
            try:
                if step["operation_id"] in pack:
                    p7_pack_registry.get(step["operation_id"]).preflight(frame, request)
                else:
                    preflight_statistical(frame, request)
            except ValueError as exc:
                raise OperationValidationError(f"workflow step {step.get('step_id')}: {exc}") from exc

    def _latest_user_text(self, session_id: str) -> str:
        """The person's most recent message; Workbench continuations are not user messages."""

        try:
            branch = self.repository.get_branch(session_id, payload_entry_types=frozenset({"message"}))
        except (KeyError, ValueError, OSError):
            return ""
        for entry in reversed(branch):
            if entry.entry_type == "message" and entry.payload.get("role") == "user":
                content = entry.payload.get("content")
                return content if isinstance(content, str) else ""
        return ""

    def _preflight_claimed_exclusions(self, arguments: dict[str, Any], request_text: str = "") -> None:
        """Refuse a plan whose stated effect, or the request it answers, excludes a data value no step filters.

        QRData 397 (2026-11-02): expected_effect said "excluding Palm Beach county", no step
        filtered anything, and the answer reported a fit on all 67 counties as the fit without it.
        In the 3724e8b2 round the plan no longer said it, but the request did ("we fit the model
        without Palm Beach county") and the answer again claimed the exclusion: the prompt's 68
        counties against 67 rows led the model to believe the row was already gone.
        Only a plan with no filtering step at all is refused, so an exclusion written by row
        position or by another column still passes.
        """

        texts = [str(text) for text in arguments.get("expected_effect") or () if isinstance(text, str)]
        phrases = [(match.group(1), "expected_effect says it excludes")
                   for text in texts for match in _EXCLUSION.finditer(text)]
        phrases += [(match.group(1), "the request asks to exclude") for match in _EXCLUSION.finditer(request_text or "")]
        steps = (arguments.get("changes") or {}).get("steps")
        target = arguments.get("target") or {}
        if not phrases or not isinstance(steps, list) or not target.get("run_id") or not target.get("node_ref"):
            return
        encoded = json.dumps(steps, ensure_ascii=False)
        if any(isinstance(step, dict) and str(step.get("operation_id", "")).startswith("data.") for step in steps) \
                or any(key in encoded for key in ('"filters"', '"exclude', '"subset')):
            return
        from ..contracts.common.errors import OperationValidationError

        frame = self._proposal_source_frame(target)
        if frame is None:
            return
        values: dict[str, tuple[str, str]] = {}
        for column in frame.columns:
            series = frame[column]
            if series.dtype.kind in "biufcmM":
                continue
            distinct = series.dropna().astype(str).unique()
            if len(distinct) > 5000:
                continue
            for value in distinct:
                key = _letters(value)
                if len(key) >= 3:
                    values.setdefault(key, (str(column), str(value)))
        for phrase, said in phrases:
            # Whole words only, joined as the data may spell them: "Palm Beach" names PalmBeach.
            words = re.findall(r"[0-9a-z]+", phrase.lower())
            spoken = {"".join(words[start:stop]) for start in range(len(words))
                      for stop in range(start + 1, min(start + 5, len(words) + 1))}
            for key, (column, value) in values.items():
                if key in spoken:
                    # State what the data holds: in the 55ce11c1 round the model believed the value was
                    # already gone, dropped the claim from expected_effect, and claimed it again in its answer.
                    present = int((frame[column].astype(str) == value).sum())
                    raise OperationValidationError(
                        f"{said} {value!r} (column {column}), but the source still has "
                        f"{present} of {len(frame)} rows with {column} = {value!r} and no step filters anything. "
                        f"Add a data.subset step with filters [{{\"column\": \"{column}\", \"op\": \"ne\", "
                        f"\"value\": \"{value}\"}}] and fit on its output. If the exclusion is not intended, "
                        f"say so and do not report the result as excluding {value!r}."
                    )

    def _preflight_model_rerun_declarations(
        self, arguments: dict[str, Any], *, metadata_edit: bool = False
    ) -> str | None:
        """Refuse, before the user is asked, a rerun that cannot do what it says.

        Execution applies the same shared check; running it here too means the
        Agent hears the reason while it can still propose the right operation,
        instead of the user confirming a proposal that is then refused.
        """

        from ..repository.run_repository import _resolve_run_root
        from ..services.rerun_service import read_verified_rerun_upload, rerun_input_fingerprint
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
            _require_editable_rerun_target(run_root, run_id, arguments)
            inputs = read_run_inputs(run_root)
            input_fingerprint = rerun_input_fingerprint(inputs)
            upload_bytes = read_verified_rerun_upload(Path(project_root), inputs["upload"]["sha256"])
        except ToolVisibleError:
            raise
        except (WorkbenchAPIError, OSError, ValueError) as exc:
            raise ToolVisibleError(
                f"MODEL_RERUN_SOURCE_UNAVAILABLE: Cannot verify the saved inputs for {run_id[:160]}. "
                "No proposal was created. Inspect the source run and restore its registered inputs/upload, "
                "or select another rerunnable model. Do not retry the unchanged request."
            ) from exc
        try:
            reject_invalid_rerun_declarations(
                inputs["form"],
                _overrides_from_proposal_changes(dict(arguments.get("changes") or {})),
                upload_bytes,
                str((inputs.get("upload") or {}).get("filename") or ""),
                metadata_edit=metadata_edit,
            )
        except RerunDeclarationError as exc:
            # A plain ValueError reaches the model as its type name only; this
            # message is what lets the Agent re-plan.
            raise ToolVisibleError(f"{exc.code}: {exc}") from exc
        return input_fingerprint


    def admit_operation_request(
        self,
        request: OperationRequest,
        *,
        chain_id: str,
        session_id: str | None = None,
        command_id: str | None = None,
        proposal_id: str | None = None,
        invocation: ProposalInvocation | None = None,
        plan_only: bool = False,
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
            plan_only=plan_only,
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
        expected: tuple[int, str] | None = None,
    ) -> tuple[ProposalDecision, bool]:
        decision, created, last_pending = self.proposal_store.decline_with_status(
            proposal_id,
            actor_type=actor_type,
            reason=reason,
            expected=expected,
        )
        if not created:
            return decision, False
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
        return decision, last_pending


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
        human = actor_type in {"user", "human_ui", "human_cli"}
        if not human and decision.outcome == permissions.Outcome.ASK:
            raise PermissionError(decision.reason)
        if actor_type == "approved_plan" and decision.authority != "approved_plan":
            raise PermissionError("The selected plan no longer authorizes this exact proposal.")
        scope = self.plan_scope or {}
        plan = scope.get("plan_snapshot") if not human and decision.authority == "approved_plan" else None
        store = self.plan_store
        approvals = OperationApprovalStore(self.repository.root)
        with store.locked(latest.session_id) if plan is not None else nullcontext():
            issued = None
            if plan is not None and store.current(latest.session_id) != plan:
                prior = self.proposal_store.latest_confirmation(proposal_id)
                if (prior is not None and prior.status == "confirmed" and prior.revision == revision
                        and prior.fingerprint == fingerprint and prior.actor_type == actor_type):
                    issued = approvals.existing(prior)
                if issued is None:
                    raise PermissionError("The approved plan changed before operation authorization.")
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

            record = self.operation_store.create_pending(confirmation, command_id=confirmation.command_id)
            approval = issued if issued is not None else approvals.issue(confirmation)
            if record.execution.get("approval_id") != approval["approval_id"]:
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

