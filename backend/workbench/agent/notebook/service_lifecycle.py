"""service lifecycle: methods over the existing shared state."""
from __future__ import annotations
from typing import Any
from ...services.server_run_artifacts import ServerOwnedArtifactManifestError, read_server_owned_run_artifacts
from ..trace import TraceWriter
from .errors import OptionExecutionReceiptRequired, OptionLifecycleTransitionInvalid, OptionMaterializationRequired
from .store import RECORD_LIFECYCLE, OptionView, StoredRevision
from .service_contracts import (_LEGACY_LIFECYCLE_TRANSITIONS, _LIFECYCLE_TRANSITIONS)

class ServiceLifecycle:
    def _append_revision(self, notebook_id: str, stored: StoredRevision) -> None:
        self.store.append_option_record(
            notebook_id, stored.revision.option_id, stored.to_dict()
        )


    def _append_lifecycle(
        self,
        notebook_id: str,
        option_id: str,
        *,
        from_status: str | None,
        to_status: str,
        revision: int,
        actor: str,
        reason: str,
    ) -> None:
        self.store.append_option_record(
            notebook_id,
            option_id,
            {
                "record_type": RECORD_LIFECYCLE,
                "option_id": option_id,
                "option_revision": revision,
                "from_status": from_status,
                "to_status": to_status,
                "actor": actor,
                "reason": reason,
            },
        )


    def _transition(
        self,
        notebook_id: str,
        view: OptionView,
        *,
        to_status: str,
        actor: str,
        reason: str,
        trace: TraceWriter | None = None,
        server_workflow_prepared: bool = False,
    ) -> None:
        current = view.lifecycle_status
        if server_workflow_prepared:
            proposal = view.current_stored_revision.proposal
            if proposal.operation_id != "operation.multi_step":
                raise OptionLifecycleTransitionInvalid(
                    "only a server-owned composed workflow may bypass Pipeline Draft materialization",
                    option_id=view.option_id,
                    from_status=current,
                    to_status=to_status,
                )
        if (
            view.current_revision.materializable
            and to_status == "materialized"
            and not server_workflow_prepared
        ):
            materialization = self.store.read_materialization(
                notebook_id,
                view.option_id,
                view.current_revision.option_revision,
            )
            if materialization is None:
                raise OptionMaterializationRequired(
                    f"option {view.option_id} revision "
                    f"{view.current_revision.option_revision} requires a persisted "
                    "OptionMaterialization record before entering materialized",
                    option_id=view.option_id,
                    option_revision=view.current_revision.option_revision,
                    contract_version=view.current_revision.contract_version,
                )
        transitions = (
            _LIFECYCLE_TRANSITIONS
            if view.current_revision.materializable
            else _LEGACY_LIFECYCLE_TRANSITIONS
        )
        if to_status not in transitions[current]:
            raise OptionLifecycleTransitionInvalid(
                f"option {view.option_id} cannot move from {current} to {to_status}",
                option_id=view.option_id,
                from_status=current,
                to_status=to_status,
            )
        self._append_lifecycle(
            notebook_id,
            view.option_id,
            from_status=current,
            to_status=to_status,
            revision=view.current_revision.option_revision,
            actor=actor,
            reason=reason,
        )
        if trace is not None:
            lifecycle_trace_payload = {
                "option_id": view.option_id,
                "option_revision": view.current_revision.option_revision,
                "from_status": current,
                "to_status": to_status,
                "axis": "lifecycle",
                "reason": reason,
            }
            binding_ref = getattr(
                view.current_revision, "capability_resolution_binding_ref", None
            )
            if binding_ref is not None:
                lifecycle_trace_payload["capability_resolution_binding_ref"] = binding_ref
            trace.emit(
                "option.lifecycle.changed",
                payload=lifecycle_trace_payload,
            )


    def _read_run_artifacts(
        self, run_id: str | None, *, required: bool = False
    ) -> list[dict[str, Any]]:
        try:
            return read_server_owned_run_artifacts(
                self.project_root,
                run_id,
                required=required,
            )
        except ServerOwnedArtifactManifestError as exc:
            raise OptionExecutionReceiptRequired(str(exc), **exc.details) from exc

