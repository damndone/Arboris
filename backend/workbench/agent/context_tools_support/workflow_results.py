"""Workflow results: bounded read-only context projection."""

from __future__ import annotations
import json
from typing import Any
from ..context_compiler import resolve_registered_artifact
from ..operations import OperationRecord, OperationRecordStore
from ...jsonl_store import read_jsonl
from ..tools import ToolVisibleError
from .requests import (
    InspectCompletedOperationsRequest,
    InspectNotebookWorkflowResultsRequest,
    InspectOperationArtifactRequest,
    InspectProjectNotebookWorkflowResultsRequest,
    _PROJECT_RUN_ID_RE,
)
from .summaries import (
    _bounded_completed_operation,
    _bounded_node,
    _operation_artifact_ids,
    _public_operation_artifact_result,
)

def _notebook_source_runs_by_revision(
    records: list[dict[str, Any]],
) -> dict[str, str]:
    """Recover server-recorded source runs without trusting a caller value."""

    source_runs: dict[str, str] = {}
    for record in records:
        if record.get("record_type") != "revision":
            continue
        revision = _notebook_option_revision_key(record.get("option_revision"))
        proposal = record.get("typed_proposal")
        target = proposal.get("target") if isinstance(proposal, dict) else None
        source_run_id = target.get("run_id") if isinstance(target, dict) else None
        if revision is None or not isinstance(source_run_id, str):
            continue
        if _PROJECT_RUN_ID_RE.fullmatch(source_run_id):
            source_runs[revision] = source_run_id
    return source_runs


def _committed_notebook_workflow_receipt(
    record: dict[str, Any],
) -> dict[str, Any] | None:
    """Validate the minimal receipt shape needed for bounded read-only evidence."""

    if (
        record.get("record_type") != "execution_result"
        or record.get("execution_status") != "succeeded"
        or record.get("committed") is not True
    ):
        return None
    option_revision = _notebook_option_revision_key(record.get("option_revision"))
    execution = record.get("workflow_execution")
    if option_revision is None or not isinstance(execution, dict):
        return None
    workflow_id = execution.get("workflow_id")
    plan_fingerprint = execution.get("plan_fingerprint")
    if (
        not isinstance(workflow_id, str)
        or not workflow_id
        or len(workflow_id) > 300
        or not isinstance(plan_fingerprint, str)
        or not plan_fingerprint
        or len(plan_fingerprint) > 300
        or execution.get("status") != "completed"
    ):
        return None
    raw_branches = execution.get("branch_runs")
    if not isinstance(raw_branches, list) or not raw_branches:
        return None
    branch_runs: list[dict[str, str]] = []
    for branch in raw_branches:
        if not isinstance(branch, dict):
            return None
        branch_id = branch.get("branch_id")
        run_id = branch.get("run_id")
        if (
            not isinstance(branch_id, str)
            or not branch_id
            or len(branch_id) > 300
            or not isinstance(run_id, str)
            or _PROJECT_RUN_ID_RE.fullmatch(run_id) is None
        ):
            return None
        branch_runs.append({"branch_id": branch_id, "run_id": run_id})
    raw_artifact_ids = execution.get("post_estimation_artifact_ids")
    if not isinstance(raw_artifact_ids, list):
        return None
    artifact_ids = [
        artifact_id
        for artifact_id in raw_artifact_ids
        if isinstance(artifact_id, str) and artifact_id and len(artifact_id) <= 500
    ]
    if len(artifact_ids) != len(raw_artifact_ids):
        return None
    return {
        "option_revision": option_revision,
        "workflow_id": workflow_id,
        "plan_fingerprint": plan_fingerprint,
        "branch_runs": branch_runs,
        "post_estimation_artifact_ids": list(dict.fromkeys(artifact_ids)),
    }


def _notebook_option_revision_key(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return str(int(value))
    return None


class WorkflowResultsMixin:
    def inspect_project_notebook_workflow_results(
        self,
        request: InspectProjectNotebookWorkflowResultsRequest,
    ) -> dict[str, Any]:
        """Read committed workflow receipts for named, visible project runs."""

        workflows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for run_id in sorted(set(request.run_ids)):
            self._project_run_root(run_id)
            for workflow in self._notebook_workflow_results_for_run(run_id):
                workflow_id = workflow.get("workflow_id")
                plan_fingerprint = workflow.get("plan_fingerprint")
                if not isinstance(workflow_id, str) or not isinstance(plan_fingerprint, str):
                    continue
                key = (workflow_id, plan_fingerprint)
                if key in seen:
                    continue
                seen.add(key)
                workflows.append(workflow)
        workflows.sort(
            key=lambda workflow: (
                str(workflow.get("workflow_id") or ""),
                str(workflow.get("plan_fingerprint") or ""),
            )
        )
        payload: dict[str, Any] = {
            "workflows": workflows[:4],
            "omitted_sections": ["raw_artifact_payloads", "raw_rows"],
        }
        if len(workflows) > 4:
            payload["workflows_omitted"] = len(workflows) - 4
        return payload

    def inspect_completed_operations(
        self,
        request: InspectCompletedOperationsRequest,
        *,
        chain_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Discover completed operations only within the current Agent scope."""

        canonical, node, _manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        records = self._completed_operation_records(
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            chain_id=chain_id,
            session_id=session_id,
        )
        omitted = max(len(records) - 8, 0)
        return {
            **canonical,
            "node": _bounded_node(node),
            "completed_operations": [
                _bounded_completed_operation(record) for record in records[:8]
            ],
            "omitted_counts": (
                {"completed_operations": omitted} if omitted else {}
            ),
            "omitted_sections": ["raw_artifact_payloads"],
        }

    def inspect_operation_artifact(
        self,
        request: InspectOperationArtifactRequest,
        *,
        chain_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Return one declared operation artifact through a public result view.

        The caller supplies durable ids, never a path.  The ids are accepted
        only after checking the current node/Chain scope and the operation's
        own emitted artifact list.
        """

        canonical, node, _manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        records = self._completed_operation_records(
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            chain_id=chain_id,
            session_id=session_id,
        )
        record = next(
            (
                candidate
                for candidate in records
                if candidate.record_id == request.operation_record_id
            ),
            None,
        )
        if record is None:
            raise ToolVisibleError(
                "OPERATION_RESULT_NOT_IN_SCOPE: the completed operation is not "
                "available in this Chain and node scope."
            )
        allowed_artifacts = set(_operation_artifact_ids(record))
        if request.artifact_id not in allowed_artifacts:
            raise ToolVisibleError(
                "OPERATION_ARTIFACT_NOT_DECLARED: the artifact was not emitted "
                "by this completed operation."
            )
        artifact = resolve_registered_artifact(
            self.project_root / "runs" / request.owner_run_id,
            request.artifact_id,
        )
        if artifact is None:
            raise ToolVisibleError(
                "OPERATION_ARTIFACT_UNAVAILABLE: the declared artifact is not "
                "available from the active run."
            )
        artifact_type, artifact_sha256, payload = artifact
        public_result, omitted_sections = _public_operation_artifact_result(
            artifact_type,
            payload,
        )
        return {
            **canonical,
            "node": _bounded_node(node),
            "artifact_evidence": {
                "available": public_result is not None,
                "status": (
                    "complete"
                    if public_result is not None
                    else "public_result_not_available"
                ),
                "evidence_ref": {
                    "operation_record_id": record.record_id,
                    "artifact_id": request.artifact_id,
                    "artifact_type": artifact_type,
                    "sha256": artifact_sha256,
                },
                "result": public_result,
                "reason": (
                    None
                    if public_result is not None
                    else "This artifact type has no registered public Agent result view."
                ),
            },
            "omitted_sections": omitted_sections,
        }

    def executed_workflow_results(self, record: Any, *, max_chars: int = 6000) -> list[dict[str, Any]]:
        """Public results of a just-executed workflow, step by step.

        The same public-result view inspect_operation_artifact serves, handed
        to the model with the execution receipt so a read-only workflow is
        answered in the turn that ran it.
        """

        run_id = str((record.target or {}).get("run_id") or "")
        state = ((record.outputs or {}).get("workflow_state") or {}).get("steps") or {}
        steps = {item.get("step_id"): item for item in (record.changes or {}).get("steps") or () if isinstance(item, dict)}
        results: list[dict[str, Any]] = []
        for step_id, step_state in state.items():
            entry: dict[str, Any] = {
                "step_id": step_id,
                "operation_id": (steps.get(step_id) or {}).get("operation_id"),
                "status": step_state.get("status"),
                "artifacts": [],
            }
            for artifact_id in step_state.get("artifact_ids") or ():
                artifact = resolve_registered_artifact(self.project_root / "runs" / run_id, str(artifact_id))
                if artifact is None:
                    entry["artifacts"].append({"artifact_id": artifact_id, "available": False})
                    continue
                artifact_type, _sha256, payload = artifact
                public_result, _omitted = _public_operation_artifact_result(artifact_type, payload)
                item: dict[str, Any] = {"artifact_id": artifact_id, "artifact_type": artifact_type}
                if public_result is None:
                    item["available"] = False
                elif len(json.dumps(public_result, ensure_ascii=False, default=str)) > max_chars:
                    item["available"] = False
                    item["reason"] = "too large to include; read it with inspect_operation_artifact"
                else:
                    item["result"] = public_result
                entry["artifacts"].append(item)
            results.append(entry)
        return results

    def inspect_notebook_workflow_results(
        self,
        request: InspectNotebookWorkflowResultsRequest,
    ) -> dict[str, Any]:
        """Discover committed Notebook workflows containing the selected run.

        Notebook confirmation has a separate append-only lifecycle from Agent
        operation records.  This bridge exposes only receipts that explicitly
        contain the currently selected run, then projects declared
        post-estimation artifacts through the same public-result boundary used
        elsewhere.  It never accepts a notebook id, option id, path, or source
        run id from the model.
        """

        canonical, node, _manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        workflows = self._notebook_workflow_results_for_run(request.owner_run_id)
        omitted = max(len(workflows) - 4, 0)
        return {
            **canonical,
            "node": _bounded_node(node),
            "notebook_workflows": workflows[:4],
            "omitted_counts": {"notebook_workflows": omitted} if omitted else {},
            "omitted_sections": ["raw_artifact_payloads", "raw_rows"],
        }

    def _notebook_workflow_results_for_run(
        self,
        owner_run_id: str,
    ) -> list[dict[str, Any]]:
        """Read only committed receipts that prove membership of ``owner_run_id``."""

        notebooks_root = self.project_root / "notebooks"
        if not notebooks_root.is_dir():
            return []
        try:
            resolved_notebooks_root = notebooks_root.resolve()
        except OSError:
            return []

        workflows: list[dict[str, Any]] = []
        seen_receipts: set[tuple[str, str, str]] = set()
        for option_path in sorted(notebooks_root.glob("*/options/*.jsonl")):
            try:
                option_path.resolve().relative_to(resolved_notebooks_root)
                records = read_jsonl(option_path)
            except (OSError, ValueError):
                continue
            source_runs_by_revision = _notebook_source_runs_by_revision(records)
            for record in reversed(records):
                receipt = _committed_notebook_workflow_receipt(record)
                if receipt is None:
                    continue
                workflow_id = receipt["workflow_id"]
                option_revision = receipt["option_revision"]
                receipt_key = (str(option_path), workflow_id, str(option_revision))
                if receipt_key in seen_receipts:
                    continue
                branch_runs = receipt["branch_runs"]
                if owner_run_id not in {branch["run_id"] for branch in branch_runs}:
                    continue
                seen_receipts.add(receipt_key)
                source_run_id = source_runs_by_revision.get(option_revision)
                evidence, unavailable = self._notebook_post_estimation_evidence(
                    source_run_id=source_run_id,
                    artifact_ids=receipt["post_estimation_artifact_ids"],
                )
                workflows.append(
                    {
                        "workflow_id": workflow_id,
                        "plan_fingerprint": receipt["plan_fingerprint"],
                        "status": "completed",
                        "branch_runs": branch_runs[:8],
                        "post_estimation_evidence": evidence[:16],
                        "unavailable_post_estimation_artifact_count": unavailable,
                    }
                )
        return workflows

    def _notebook_post_estimation_evidence(
        self,
        *,
        source_run_id: str | None,
        artifact_ids: list[str],
    ) -> tuple[list[dict[str, Any]], int]:
        """Resolve receipt-declared source artifacts through a public view only."""

        if source_run_id is None:
            return [], len(artifact_ids)
        try:
            source_root = self._project_run_root(source_run_id)
        except ToolVisibleError:
            return [], len(artifact_ids)
        evidence: list[dict[str, Any]] = []
        unavailable = 0
        for artifact_id in artifact_ids[:16]:
            artifact = resolve_registered_artifact(source_root, artifact_id)
            if artifact is None:
                unavailable += 1
                continue
            artifact_type, sha256, payload = artifact
            public_result, _omitted = _public_operation_artifact_result(
                artifact_type, payload
            )
            if public_result is None:
                unavailable += 1
                continue
            evidence.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "evidence_ref": {
                        "run_id": source_run_id,
                        "artifact_id": artifact_id,
                        "artifact_type": artifact_type,
                        "sha256": sha256,
                    },
                    "result": public_result,
                }
            )
        return evidence, unavailable + max(len(artifact_ids) - 16, 0)

    def _completed_operation_records(
        self,
        *,
        owner_run_id: str,
        op_node_id: str,
        chain_id: str,
        session_id: str,
    ) -> list[OperationRecord]:
        """Select only terminal, caller-owned parent operation records."""

        store = OperationRecordStore(self.project_root / "workbench", create=False)
        records = [
            record
            for record in store.list_records()
            if record.status == "completed"
            and record.chain_id == chain_id
            and record.agent_session_id == session_id
            and record.target.get("run_id") == owner_run_id
            and record.target.get("node_ref") == op_node_id
            and record.workflow_step_id is None
        ]
        return sorted(records, key=lambda record: (record.updated_at, record.record_id), reverse=True)

