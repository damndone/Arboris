"""Request-independent preparation and submission for model reruns."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from ..events import get_event_manager
from ..graph_store import GraphStore
from ..lineage.op_contract import (
    OpOverrideError,
    resolve_operation_contract,
    resolve_overrides_target,
    validate_overrides,
)
from ..lineage.hashing import override_hash
from ..lineage.node_write_validation import (
    NodeWriteOperationRequestV1,
    validate_rerun_operation_target,
)
from ..lineage.run_inputs import read_run_inputs
from ..lineage.upload_store import verify_upload
from ..repository.run_repository import _read_manifest, _resolve_run_root
from .run_service import _submit_run, encode_form_override


TERMINAL_RUN_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "interrupted", "partial", "blocked"}
)


class RerunServiceError(RuntimeError):
    """A request-independent rerun rejection with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RerunBusyError(RerunServiceError):
    def __init__(self) -> None:
        super().__init__("slot_busy", "A run is already in progress.")


@dataclass(frozen=True)
class RerunSubmissionRequest:
    source_run_id: str
    from_node: str
    op_overrides: dict[str, Any]
    rerun_reason: str = "manual_override"
    rerun_from: dict[str, Any] | None = None
    workbench_context: dict[str, Any] | None = None
    before_dispatch: Callable[[str], None] | None = None


@dataclass(frozen=True)
class RerunSubmissionResult:
    run_id: str
    status: str


@dataclass(frozen=True)
class RerunReconciliationRequest:
    source_run_id: str
    target_run_id: str
    from_node: str
    op_overrides: dict[str, Any]
    workbench_context: dict[str, Any]


@dataclass(frozen=True)
class RerunReconciliationResult:
    status: str
    target_run_id: str
    outputs: dict[str, Any]
    diff_ref: dict[str, Any] | None = None
    verification: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None


_CANONICAL_CONTEXT_FIELDS = (
    "context_version",
    "context_fingerprint",
    "owner_run_id",
    "op_node_id",
    "node_hash",
    "forest_node_key",
    "owner_resolution",
    "active_head_run_id",
)


def _validate_workbench_context(
    runs_root: Path,
    request: RerunSubmissionRequest,
) -> None:
    """Reuse the node-operation validator for Agent-originated reruns."""

    context = request.workbench_context
    if context is None:
        return
    if not isinstance(context, dict):
        raise RerunServiceError(
            "invalid_workbench_context",
            "workbench_context must be an object.",
        )

    missing = [field for field in _CANONICAL_CONTEXT_FIELDS if not context.get(field)]
    if missing:
        raise RerunServiceError(
            "invalid_workbench_context",
            "workbench_context missing canonical fields: " + ", ".join(missing),
        )
    if context["owner_run_id"] != request.source_run_id:
        raise RerunServiceError(
            "context_mismatch",
            "workbench_context owner_run_id does not match source_run_id.",
        )
    if context["op_node_id"] != request.from_node:
        raise RerunServiceError(
            "context_mismatch",
            "workbench_context op_node_id does not match from_node.",
        )

    try:
        target = NodeWriteOperationRequestV1(
            request_id=str(
                context.get("operation_record_id")
                or context.get("proposal_id")
                or f"rerun:{request.source_run_id}:{request.from_node}"
            ),
            operation="rerun",
            context_version=context["context_version"],
            context_fingerprint=context["context_fingerprint"],
            owner_run_id=context["owner_run_id"],
            op_node_id=context["op_node_id"],
            node_hash=context["node_hash"],
            forest_node_key=context["forest_node_key"],
            owner_resolution=context["owner_resolution"],
            active_head_run_id=context["active_head_run_id"],
        )
    except ValidationError as exc:
        raise RerunServiceError(
            "invalid_workbench_context",
            "workbench_context failed node-operation schema validation.",
        ) from exc

    try:
        validate_rerun_operation_target(runs_root, target)
    except ValueError as exc:
        message = str(exc)
        code = message.split(":", 1)[0]
        raise RerunServiceError(code, message) from exc


class RerunService:
    """Prepare and submit a rerun without depending on FastAPI request types."""

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root).resolve()

    def submit(self, request: RerunSubmissionRequest) -> RerunSubmissionResult:
        source_run_root = _resolve_run_root(str(self.project_root), request.source_run_id)
        manifest = _read_manifest(source_run_root)
        if manifest.get("status") not in TERMINAL_RUN_STATUSES:
            raise RerunServiceError(
                "parent_not_terminal",
                f"Parent run not terminal (status={manifest.get('status')}).",
            )

        graph = GraphStore(runs_root=self.project_root / "runs").read(
            request.source_run_id
        )
        node = graph.nodes.get(request.from_node)
        if node is None:
            raise RerunServiceError(
                "unknown_from_node",
                f"from_node not in run graph: {request.from_node}",
            )
        stage = node.stage.value if node.stage is not None else None
        contract = resolve_operation_contract(stage=stage, manifest=manifest)
        if contract is None:
            raise RerunServiceError(
                "node_not_editable",
                f"Node {request.from_node} is not editable.",
            )
        try:
            target = resolve_overrides_target(contract, request.op_overrides)
            validate_overrides(target, request.op_overrides)
        except OpOverrideError as exc:
            raise RerunServiceError("invalid_overrides", str(exc)) from exc

        _validate_workbench_context(self.project_root / "runs", request)

        try:
            inputs = read_run_inputs(source_run_root)
        except (FileNotFoundError, OSError) as exc:
            raise RerunServiceError(
                "missing_run_inputs",
                "Parent run has no run_inputs.json (not rerunnable).",
            ) from exc
        parent_sha = (inputs.get("upload") or {}).get("sha256")
        if not parent_sha:
            raise RerunServiceError(
                "missing_upload_sha256",
                "Parent run_inputs.json has no upload sha256.",
            )
        try:
            upload_bytes = verify_upload(self.project_root, parent_sha).read_bytes()
        except (OSError, ValueError) as exc:
            raise RerunServiceError("unusable_parent_upload", str(exc)) from exc

        merged_form = {
            **inputs["form"],
            **{
                key: encode_form_override(key, value)
                for key, value in request.op_overrides.items()
            },
        }
        events = get_event_manager()
        if not events.try_acquire_slot():
            raise RerunBusyError()
        child_id: str | None = None
        try:
            result = _submit_run(
                self.project_root,
                form=merged_form,
                upload_bytes=upload_bytes,
                upload_filename=inputs["upload"].get("filename") or "upload.csv",
                started_at=datetime.now(timezone.utc).isoformat(),
                rerun_of=request.source_run_id,
                from_node=request.from_node,
                rerun_reason=request.rerun_reason,
                op_overrides=request.op_overrides,
                rerun_from=request.rerun_from,
                workbench_context=request.workbench_context,
                before_dispatch=request.before_dispatch,
            )
            child_id = result["run_id"]
            return RerunSubmissionResult(run_id=child_id, status=result["status"])
        except Exception:
            events.release_slot(child_id)
            raise

    def reconcile_submission(
        self,
        request: RerunReconciliationRequest,
    ) -> RerunReconciliationResult:
        """Observe a child run and verify immutable rerun provenance deterministically."""

        try:
            target_root = _resolve_run_root(str(self.project_root), request.target_run_id)
        except Exception:
            return RerunReconciliationResult(
                status="failed",
                target_run_id=request.target_run_id,
                outputs={
                    "target_run_id": request.target_run_id,
                    "status": "missing",
                },
                verification={
                    "passed": False,
                    "checks": {"child_run_present": False},
                },
                error={
                    "type": "ChildRunMissing",
                    "target_run_id": request.target_run_id,
                },
            )
        target_manifest = _read_manifest(target_root)
        target_status = str(target_manifest.get("status"))
        outputs = {
            "target_run_id": request.target_run_id,
            "status": target_status,
        }
        if target_status not in TERMINAL_RUN_STATUSES:
            return RerunReconciliationResult(
                status=target_status,
                target_run_id=request.target_run_id,
                outputs=outputs,
            )

        if target_status != "completed":
            return RerunReconciliationResult(
                status="failed",
                target_run_id=request.target_run_id,
                outputs=outputs,
                verification={
                    "passed": False,
                    "checks": {"child_terminal_status": target_status},
                },
                error={
                    "type": "ChildRunFailed",
                    "status": target_status,
                },
            )

        source_root = _resolve_run_root(str(self.project_root), request.source_run_id)
        source_inputs = read_run_inputs(source_root)
        target_inputs = read_run_inputs(target_root)
        target_form = dict(target_inputs.get("form") or {})
        source_form = dict(source_inputs.get("form") or {})
        checks = {
            "child_terminal_status": target_status == "completed",
            "rerun_of": target_inputs.get("rerun_of") == request.source_run_id,
            "from_node": target_inputs.get("from_node") == request.from_node,
            "override_hash": target_inputs.get("override_hash")
            == override_hash(request.op_overrides),
            "workbench_context": target_inputs.get("workbench_context")
            == request.workbench_context,
        }
        changed_fields = sorted(
            key for key in request.op_overrides if source_form.get(key) != target_form.get(key)
        )
        verification = {
            "passed": all(checks.values()),
            "checks": checks,
            "changed_fields": changed_fields,
        }
        diff_ref = {
            "kind": "input_diff.v1",
            "source_run_id": request.source_run_id,
            "target_run_id": request.target_run_id,
            "changed_fields": changed_fields,
        }
        if not verification["passed"]:
            return RerunReconciliationResult(
                status="failed",
                target_run_id=request.target_run_id,
                outputs=outputs,
                diff_ref=diff_ref,
                verification=verification,
                error={"type": "VerificationFailed"},
            )
        return RerunReconciliationResult(
            status="completed",
            target_run_id=request.target_run_id,
            outputs=outputs,
            diff_ref=diff_ref,
            verification=verification,
        )
