"""Public FPC contracts preserve corrected inference and reject bypasses."""
import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.survey.adapters import build_design_from_artifacts
from workbench.survey.design import SurveyDesign
from workbench.survey.engine import estimate_with_design
from workbench.survey.errors import SurveyEngineError
from workbench.survey.estimator import EstimatorSpec

FIXTURES=Path(__file__).parent/"fixtures/survey_fpc_v1811"


@pytest.mark.parametrize("column",[True,False,0,1,[],["population_fpc"],{}])
def test_public_adapter_refuses_fpc_column_coercion(column):
    frame=pd.read_csv(FIXTURES/"design.csv")
    with pytest.raises(SurveyEngineError,match="FPC"):
        build_design_from_artifacts(frame,{"_sampling_weight":"weight",
            "_survey_psu_col":"psu","_survey_strata_col":"stratum","_survey_fpc_col":column})


def test_method_level_replicate_fpc_refuses_before_any_refit():
    design=SurveyDesign(pd.read_csv(FIXTURES/"design.csv"),weight="weight",
        strata="stratum",psu="psu",fpc="population_fpc")
    def forbidden(*args):
        pytest.fail("Replicate plus FPC reached an estimator refit")
    estimator=EstimatorSpec(name="refittable",refit=forbidden)
    with pytest.raises(SurveyEngineError,match="FPC"):
        estimate_with_design(design,estimator,method="replicate",replicate_type="jackknife")


@pytest.mark.parametrize("column,units",[("population_fpc","population_psu_count"),
                                         ("fraction_fpc","sampling_fraction")])
def test_real_public_run_persists_and_projects_fpc_definition(tmp_path,column,units):
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    from workbench.agent.context_tools import _bounded_survey_design, _public_requested_model_coefficients
    from workbench.report_view_model import _survey_design_facts,_design_summary
    project=create_project(tmp_path,"fpc-public")
    outcome=run_workflow(project.root,[FIXTURES/"design.csv"],mode="auto",model_type="ols",
        y="y",x=["x1","x2"],sampling_weight="weight",survey_strata_col="stratum",
        survey_psu_col="psu",survey_fpc_col=column)
    root=project.root/"runs"/outcome["run_id"]
    assert outcome["status"] == "completed",read_json(root/"errors.json")
    packet=read_json(root/"model_results/ols_1.json")
    assert packet["covariance_estimator"] == "survey_design_linearization"
    assert packet["covariance_evidence"]["effective_df"] == packet["survey_design"]["inference_degf"]
    assert packet["covariance_evidence"]["df_method"] == packet["survey_design"]["df_convention"]
    projected = _public_requested_model_coefficients(run_id=outcome["run_id"], result=packet, requested_terms=("x1",))
    assert projected["inference"]["effective_df"] == packet["survey_design"]["inference_degf"]
    assert projected["df_resid"] == packet.get("df_resid")
    fpc=packet["survey_design"]["fpc"]
    assert fpc["column"] == column and fpc["units"] == units
    assert len(fpc["strata"]) == 8
    assert all(row["sampled_psus"] == 2 for row in fpc["strata"])
    assert all(row["variance_factor"] == pytest.approx(1-row["sampling_fraction"])
               for row in fpc["strata"])
    assert _bounded_survey_design([packet])["fpc"] == fpc
    assert any("Finite population correction" in fact for fact in _survey_design_facts(root))
    assert "FPC=" in _design_summary(packet["survey_design"])
    json.dumps(packet,allow_nan=False)


def test_census_zero_variance_has_unavailable_p_values_and_finite_public_json(tmp_path):
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    frame=pd.read_csv(FIXTURES/"design.csv")
    frame["census_fraction"]=1.
    source=tmp_path/"census.csv"; frame.to_csv(source,index=False)
    project=create_project(tmp_path,"census")
    outcome=run_workflow(project.root,[source],mode="auto",model_type="ols",y="y",x=["x1","x2"],
        sampling_weight="weight",survey_strata_col="stratum",survey_psu_col="psu",survey_fpc_col="census_fraction")
    root=project.root/"runs"/outcome["run_id"]
    assert outcome["status"] == "completed",read_json(root/"errors.json")
    packet=read_json(root/"model_results/ols_1.json")
    assert all(row["std_error"] == 0 and row["p_value"] is None for row in packet["coefficients"].values())
    assert any(row["code"] == "SURVEY_ZERO_VARIANCE_INFERENCE_UNAVAILABLE" for row in packet["warnings"])
    json.dumps(packet,allow_nan=False)
