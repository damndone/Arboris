"""Formal report/export writers must fail before any filesystem IO."""

from __future__ import annotations

from pathlib import Path
import os
from unittest.mock import patch

import pytest

from tests.workflow_fixtures import compile_fixture_workflow
from workbench.agent.workflow import WorkflowExecutionError
from workbench.exports import export_pdf, export_xlsx
from workbench.agent.workflow_runtime import (
    _admit_workflow_host_endpoint_from_supervisor,
    _WRITE_CONTEXT,
    issue_server_evidence_port,
)
from workbench.reporting import render_html_report


@pytest.mark.parametrize(
    "writer, kwargs, expected_name",
    (
        (
            render_html_report,
            {"view_model": {"title": "Report"}},
            "report.html",
        ),
        (
            export_pdf,
            {"report": {"title": "Report"}},
            "report.pdf",
        ),
        (
            export_xlsx,
            {"tables": {"results": [{"value": 1}]}},
            "tables.xlsx",
        ),
    ),
)
def test_formal_writers_require_an_admitted_receipt_before_io(
    tmp_path: Path, writer, kwargs, expected_name: str
) -> None:
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)

    with pytest.raises(
        WorkflowExecutionError,
        match="WORKFLOW_ADMISSION_RECEIPT_REQUIRED",
    ):
        writer(run_root=run_root, **kwargs)

    assert not list(run_root.rglob(expected_name))
    assert not (run_root / "reports").exists()
    assert not (run_root / "exports").exists()


def test_formal_html_writer_rejects_a_symlinked_parent_before_external_write(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (run_root / "reports").symlink_to(outside, target_is_directory=True)

    workflows = tmp_path / "workbench" / "workflows"
    workflows.mkdir(parents=True)
    endpoint_fd = os.open(workflows, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        import workbench.agent.workflow_runtime as workflow_runtime

        draft = compile_fixture_workflow(workflow_id="wf-report-path")
        with patch.object(
            workflow_runtime,
            "_deployment_host_endpoint_from_supervisor",
            return_value=_admit_workflow_host_endpoint_from_supervisor(tmp_path, endpoint_fd),
        ):
            port = issue_server_evidence_port(tmp_path)
        receipt = port.admit(draft, draft.steps[0])
        context_token = _WRITE_CONTEXT.set((port, receipt, draft, draft.steps[0]))
        try:
            with pytest.raises(
                WorkflowExecutionError,
                match="WORKFLOW_ARTIFACT_PATH",
            ):
                render_html_report(
                    {"title": "Report"},
                    run_root,
                    filename="escape.html",
                    evidence_port=port,
                    admission_receipt=receipt,
                )
        finally:
            _WRITE_CONTEXT.reset(context_token)
    finally:
        os.close(endpoint_fd)

    assert not (outside / "escape.html").exists()
