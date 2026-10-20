"""Reports service for workflow execution."""

from __future__ import annotations
from pathlib import Path
import base64
from typing import Any, Mapping
from ...artifacts import read_json, register_artifact, write_json
from ...exports import export_pdf, export_xlsx
from ...reporting import render_html_report
from ..workflow import WorkflowDraft, WorkflowExecutionError, WorkflowStepResult


def _execute_workflow_report(
    root: Path,
    draft: WorkflowDraft,
    previous: Mapping[str, WorkflowStepResult],
    step: Any | None = None,
) -> WorkflowStepResult:
    run_root = root / "runs" / str(draft.target["run_id"])
    log_path = root / "workbench" / "exploration" / f"{draft.workflow_id}.jsonl"
    events = []
    if log_path.is_file():
        from ...jsonl_store import read_jsonl

        events = read_jsonl(log_path)
    steps = {
        step_id: {
            "status": "completed",
            "artifact_ids": list(result.artifact_ids),
        }
        for step_id, result in previous.items()
    }
    collection_id = f"workflow_report_collection_{draft.workflow_id}"
    html_id = f"workflow_report_{draft.workflow_id}_html"
    pdf_id = f"workflow_report_{draft.workflow_id}_pdf"
    xlsx_id = f"workflow_report_{draft.workflow_id}_xlsx"
    report_step_id = getattr(step, "step_id", None)
    if not isinstance(report_step_id, str) or not report_step_id:
        report_step_id = next(
            (
                candidate.step_id
                for candidate in draft.steps
                if candidate.operation_id == "report.compose"
            ),
            "report.compose",
        )
    steps[report_step_id] = {
        "status": "completed",
        "artifact_ids": [collection_id, html_id, pdf_id, xlsx_id],
    }
    collection = {
        "schema_version": "workflow-report-collection.v1",
        "workflow_id": draft.workflow_id,
        "workflow_plan_fingerprint": draft.plan_fingerprint,
        "status": "completed",
        "steps": steps,
        "exploration_log": events,
    }
    curve = None
    if step is not None and step.spec.get("specification_curve"):
        from ..specification_curves import publish_curve
        curve = publish_curve(root, draft, step.spec["specification_curve"])
        collection["specification_curve"] = curve
    collection_path = run_root / "artifacts" / "statistical_exploration" / f"{draft.workflow_id}.json"
    collection_path.parent.mkdir(parents=True, exist_ok=True)
    if collection_path.exists() and read_json(collection_path) != collection:
        raise WorkflowExecutionError("workflow report collection path is occupied")
    if not collection_path.exists():
        write_json(collection_path, collection)
    register_artifact(run_root, collection_id, collection_path, "report_collection", "report.compose", [curve["artifact_id"]] if curve else [])
    curve_view = None
    if curve:
        folder = run_root / "artifacts/specification_curves"
        curve_view = {**read_json(folder / f"{draft.workflow_id}.json"),
            "images": ["data:image/png;base64," + base64.b64encode((folder / name).read_bytes()).decode("ascii")
                       for name in curve["panel_files"]]}
    view_model = {
        "title": "Statistical workflow report",
        "facts": [
            f"Workflow steps completed: {len(steps)}.",
            f"Workflow id: {draft.workflow_id}",
            f"Source rows: {next(iter(previous.values())).row_counts.get('source', 0) if previous else 0}",
        ],
        "claims": [],
        "warnings": [],
        "descriptive_stats": [],
        "exploration": collection,
        **({"specification_curve": curve_view} if curve_view else {}),
    }
    render_html_report(view_model, run_root, filename=f"{draft.workflow_id}.html", artifact_id=html_id, inputs=[collection_id])
    export_pdf(view_model, run_root, filename=f"{draft.workflow_id}.pdf", artifact_id=pdf_id, inputs=[collection_id])
    export_xlsx(
        {
            **({"specification_curve": curve_view["rows"]} if curve_view else {}),
            "workflow_steps": [
                {
                    "step_id": key,
                    "status": value["status"],
                    "artifact_ids": ", ".join(value["artifact_ids"]),
                }
                for key, value in steps.items()
            ]
        },
        run_root,
        filename=f"{draft.workflow_id}.xlsx",
        artifact_id=xlsx_id,
        inputs=[collection_id],
    )
    return WorkflowStepResult(
        artifact_ids=[collection_id, html_id, pdf_id, xlsx_id] + ([curve["artifact_id"], *curve["figure_artifact_ids"]] if curve else []),
        row_counts={"steps": len(steps)},
        payload={"collection_id": collection_id},
    )
