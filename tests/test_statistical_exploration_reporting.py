from pathlib import Path

from tests.test_v189_evidence_report_boundary import _server_owned_evidence
from workbench.report_view_model import build_report_view_model


def _summary() -> dict:
    return {
        "model_identity": {"model_label": "OLS", "y_variable": "y"},
        "diagnostics": {"blockers": [], "warnings": [], "cautions": [], "info": []},
        "coefficients_summary": {"rows": []},
        "narrative_contract": {"constraints": {}},
    }


def _admitted_view(collection: dict, tmp_path: Path) -> dict[str, object]:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-1"
    run_root.mkdir(parents=True)
    with _server_owned_evidence(
        tmp_path / "owner-store",
        canonical_project_root=project_root,
    ) as (_record, _binding, owner):
        projection = owner.issue_report_projection(owner._canonical_report_wire())  # type: ignore[attr-defined]
        return build_report_view_model(
            _summary(),
            run_root,
            exploration=collection,
            include_legacy_presentation=True,
            evidence_projection=projection,
            owner=owner,
            artifact_admission=owner._canonical_report_artifact(),  # type: ignore[attr-defined]
        )


def test_report_view_model_keeps_the_complete_workflow_collection(tmp_path: Path) -> None:
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

    view_model = _admitted_view(collection, tmp_path)

    assert view_model["exploration"] == collection
    assert view_model["exploration"]["artifact_ids"][-1] == "report-html"


def test_incomplete_workflow_is_visible_as_a_blocking_report_issue(tmp_path: Path) -> None:
    collection = {
        "workflow_id": "wf-2",
        "status": "failed",
        "steps": [
            {"workflow_step_id": "step-1", "status": "completed"},
            {"workflow_step_id": "step-2", "status": "blocked"},
        ],
    }

    view_model = _admitted_view(collection, tmp_path)

    assert view_model["exploration"]["status"] == "failed"
    assert any(issue["code"] == "WORKFLOW_INCOMPLETE" for issue in view_model["critical_errors"])
