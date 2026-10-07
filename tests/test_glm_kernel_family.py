"""v1.8.11 step 1: a GLM kernel names its family, so post-estimation can tell
a binomial GLM from a Poisson or negative binomial one."""

from __future__ import annotations

from pathlib import Path

import pytest

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.contracts.model.result_envelope_registry import declaration_for
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

DATA = Path(__file__).parent / "fixtures" / "postestimation" / "data.csv"


@pytest.mark.parametrize(("family", "y", "link"), [("binomial", "yb", "logit"), ("poisson", "yc", "log")])
def test_glm_kernel_names_its_family_and_prediction(tmp_path, family, y, link) -> None:
    project = create_project(tmp_path, family)
    outcome = run_workflow(project.root, [DATA], mode="auto", model_type=f"glm:{family}", y=y, x=["x1", "x2"])
    assert outcome["status"] == "completed", outcome
    kernel = read_json(project.root / "runs" / outcome["run_id"] / kernel_relative_path("glm_1"))
    assert kernel["model_type"] == f"glm:{family}"
    assert declaration_for(kernel["model_type"]).inverse_link == link
