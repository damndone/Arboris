from pathlib import Path

from workbench.report_view_model import build_report_view_model


def _summary() -> dict:
    return {
        "model_identity": {"model_label": "OLS", "y_variable": "y"},
        "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
        "coefficients_summary": {"rows": []},
        "narrative_contract": {"constraints": {}},
    }


def test_report_view_model_keeps_the_complete_workflow_collection() -> None:
    collection = {
        "workflow_id": "wf-1",
        "status": "completed",
        "steps": [
            {
                "workflow_step_id": "step-1",
                "operation_id": "statistical.explore@v1",
                "status": "completed",
                "artifact_ids": ["table-1"],
            },
            {
                "workflow_step_id": "step-8",
                "operation_id": "model.genesis@v1",
                "status": "completed",
                "artifact_ids": ["ols-1", "diagnostics-ols-1"],
            },
        ],
        "artifact_ids": ["table-1", "ols-1", "diagnostics-ols-1", "report-html"],
    }

    view_model = build_report_view_model(
        _summary(), Path("/tmp/fake"), exploration=collection
    )

    assert view_model["exploration"] == collection
    assert view_model["exploration"]["artifact_ids"][-1] == "report-html"


def test_incomplete_workflow_is_visible_as_a_blocking_report_issue() -> None:
    collection = {
        "workflow_id": "wf-2",
        "status": "failed",
        "steps": [
            {"workflow_step_id": "step-1", "status": "completed"},
            {"workflow_step_id": "step-2", "status": "blocked"},
        ],
    }

    view_model = build_report_view_model(
        _summary(), Path("/tmp/fake"), exploration=collection
    )

    assert view_model["exploration"]["status"] == "failed"
    assert any(issue["code"] == "CLASS3_WORKFLOW_INCOMPLETE" for issue in view_model["critical_errors"])
