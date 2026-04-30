from pathlib import Path

import pandas as pd

from workbench.projects import create_project, create_run
from workbench.visualization import create_figures


def test_create_figures_writes_png_artifacts(tmp_path: Path):
    frame = pd.DataFrame({"x": [1, 2, 3, 4], "y": [2, 4, 6, 8]})
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    figures = create_figures(frame, run.root, numeric_columns=["x", "y"], time_column=None)
    assert "correlation_heatmap" in figures
    assert (run.root / figures["correlation_heatmap"]).exists()
