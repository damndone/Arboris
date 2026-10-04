"""Both Agent projections withhold single-dataset fit statistics."""
from pathlib import Path

from workbench.agent.context_tools import _bounded_persisted_model_facts, _public_requested_model_coefficients
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_pooled_projections_have_no_r_squared_or_residual_values(tmp_path):
    project = create_project(tmp_path, "projection")
    source = Path(__file__).parents[1] / "fixtures/multiple_imputation/data.csv"
    result = run_workflow(project.root, [source], mode="auto", model_type="ols", y="y", x=["x1", "x2", "x3"],
                          imputation={"method": "mice", "m": 2})
    root = project.root / "runs" / result["run_id"]
    assert result["status"] == "completed"
    packet = read_json(root / "model_results/ols_1.json")
    views = [_bounded_persisted_model_facts([packet], run_root=root)[0],
             _public_requested_model_coefficients(run_id=result["run_id"], result=packet, requested_terms=("x1",))]
    def inspect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert key not in {"r_squared", "r_squared_adj", "residuals", "fitted_values"}, (key, child)
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
    for view in views:
        assert view["multiple_imputation"]["m"] == 2
        inspect(view)
