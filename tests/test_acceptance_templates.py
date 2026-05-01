from pathlib import Path

from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_cross_section_template_runs(tmp_path: Path):
    project = create_project(tmp_path, "cross_section_demo")
    result = run_workflow(
        project.root,
        [Path("examples/datasets/cross_section.csv")],
        mode="auto",
        y="wage",
        x=["education"],
    )
    assert result["status"] == "completed"


def test_panel_template_runs(tmp_path: Path):
    project = create_project(tmp_path, "panel_demo")
    result = run_workflow(
        project.root,
        [Path("examples/datasets/panel.csv")],
        mode="auto",
        y="sales",
        x=["assets"],
    )
    assert result["status"] == "completed"
