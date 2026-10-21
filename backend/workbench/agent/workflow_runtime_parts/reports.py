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
    *,
    source_rows: int,
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
        "source_rows": source_rows,
        "steps": steps,
        "exploration_log": events,
    }
    selected = None
    regression_table = None
    if step is not None and step.spec.get('result_refs'):
        from ..report_sources import collect_report_sources
        from ...report_view_model import build_regression_table, regression_table_export_rows
        selected = collect_report_sources(root, draft.target, step.spec['result_refs'])
        collection['result_sources'] = selected['references']
        regression_table = build_regression_table(selected['models'])
    curve = None
    review, review_table = None, None
    if step is not None and step.spec.get("specification_curve"):
        from ..specification_curves import publish_curve
        curve = publish_curve(root, draft, step.spec["specification_curve"])
        collection["specification_curve"] = curve
    if step is not None and step.spec.get("research_review"):
        from ..report_reviews import collect_review, review_rows
        review = collect_review(root, draft.target, step.spec["research_review"])
        review_table = review_rows(review)
        collection["research_review"] = review
    from ... import analysis_disclosure, analysis_ledger
    from ..operations import OperationRecordStore
    record = next((item for item in OperationRecordStore(root / "workbench", create=False).list_records()
                   if item.execution.get("workflow_id") == draft.workflow_id), None)
    proof = record.execution.get("research_specification", {}) if record else {}
    current = []
    for member in draft.steps:
        if member.step_id not in previous or analysis_ledger.step_category(member.operation_id) not in {"model", "inferential", "descriptive", "data_change"}:
            continue
        current.append({"record_id": record.record_id if record else None, "run_id": draft.target["run_id"],
            "step_id": member.step_id, "operation_id": member.operation_id, "status": "completed",
            "question_id": proof.get("question_id"), "specification_status": proof.get("specification_status", "exploratory"),
            "verification": proof.get("verification", "unverified"), "reason": proof.get("reason", "no_pre_execution_evidence"),
            "at": None, "specification_event_id": proof.get("specification_event_id")})
    prior = analysis_disclosure.disclosure(root, draft.target["run_id"])["research_specifications"]
    sections = {key: [row for row in prior[key] if not record or row["record_id"] != record.record_id]
                + [row for row in current if row["specification_status"] == key]
                for key in ("pre_specified", "exploratory")}
    collection["research_specifications"] = sections
    collection_path = run_root / "artifacts" / "statistical_exploration" / f"{draft.workflow_id}.json"
    collection_path.parent.mkdir(parents=True, exist_ok=True)
    if collection_path.exists() and read_json(collection_path) != collection:
        raise WorkflowExecutionError("workflow report collection path is occupied")
    if not collection_path.exists():
        write_json(collection_path, collection)
    inputs = ([curve["artifact_id"]] if curve else []) + (review["local_artifact_inputs"] if review else [])
    if selected:
        inputs.extend([draft.target['artifact_id'], *(ref['artifact_id'] for ref in selected['references']
                       if ref['run_id'] == draft.target['run_id'])])
    register_artifact(run_root, collection_id, collection_path, "report_collection", "report.compose", inputs)
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
            f"Source rows: {source_rows}",
        ],
        "claims": [],
        "warnings": [],
        "descriptive_stats": [],
        "exploration": collection,
        "research_specifications": sections,
        **({"specification_curve": curve_view} if curve_view else {}),
        **({"research_review": review, "research_review_rows": review_table} if review else {}),
    }
    if selected:
        view_model['regression_table'] = regression_table
        view_model['facts'].extend([
            'Selected existing results are source-verified; identification, inference validity and report completeness are not certified by provenance.',
            'Coefficients retain the native model scale; Cox coefficients are log hazard coefficients, not hazard ratios.',
            'AR global certification concerns the confidence-set inversion; instrument validity and sampling coverage remain assumptions.',
            f"Omitted diagnostic scalar fields: {selected['omitted_diagnostic_fields']}. Refer to the pinned artifacts for complete details.",
            *(f"{row['run_id']}:{row['artifact_id']} / {row['field']}: {row['value']}" for row in selected['diagnostic_rows'])])
    render_html_report(view_model, run_root, filename=f"{draft.workflow_id}.html", artifact_id=html_id, inputs=[collection_id])
    export_pdf(view_model, run_root, filename=f"{draft.workflow_id}.pdf", artifact_id=pdf_id, inputs=[collection_id])
    export_xlsx(
        {
            **sections,
            **({'regression_table': regression_table_export_rows(regression_table),
                'diagnostics': selected['diagnostic_rows'], 'result_sources': selected['references']} if selected else {}),
            **({"specification_curve": curve_view["rows"]} if curve_view else {}),
            **({"research_review": review_table} if review else {}),
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
