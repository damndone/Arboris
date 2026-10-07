"""Independent adversarial input and frozen no-FPC design checks."""
from pathlib import Path
from types import ModuleType
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from workbench.survey import SurveyDesign,SurveyEngineError

ROOT=Path(__file__).resolve().parents[1]/"fixtures/survey_fpc_v1811"

def data(source="design"):
    return pd.read_csv(ROOT/f"{source}.csv")

def make(frame,**kwargs):
    return SurveyDesign(frame=frame,weight="weight",strata="stratum",psu="psu",**kwargs)

@pytest.mark.parametrize("value",[np.bool_(True),np.bool_(False),-1.,float("nan"),float("inf"),complex(0.,1.),"0.25",None,2.5])
def test_invalid_numeric_types_and_values_are_fail_closed(value):
    frame=data();frame["bad"]=pd.Series([value]*len(frame),dtype=object)
    with pytest.raises(SurveyEngineError):make(frame,fpc="bad")

def test_duplicate_fpc_column_label_is_rejected():
    frame=data();frame=pd.concat([frame,frame[["fraction_fpc"]]],axis=1)
    with pytest.raises(SurveyEngineError):make(frame,fpc="fraction_fpc")

@pytest.mark.parametrize("mutation",["missing","mixed_units","inconsistent","additional_psu"])
def test_mutated_full_design_is_revalidated_before_covariance(mutation):
    frame=data();frame["review_fpc"]=2.
    design=make(frame,fpc="review_fpc")
    if mutation=="missing":frame.loc[0,"review_fpc"]=np.nan
    elif mutation=="mixed_units":frame.loc[frame.stratum==frame.stratum.iloc[0],"review_fpc"]=.5
    elif mutation=="inconsistent":frame.loc[0,"review_fpc"]=3
    else:frame.loc[0,"psu"]="new_psu"
    with pytest.raises(SurveyEngineError):design._design_variance(frame[["x1","x2"]].to_numpy())

@pytest.mark.parametrize("kind",["brr","jackknife","bootstrap","provided"])
def test_replicate_declaration_cannot_be_mutated_into_an_fpc_design(kind):
    frame=data();design=make(frame,fpc="population_fpc")
    design.replicate_type=kind
    with pytest.raises(SurveyEngineError,match="SURVEY_FPC_REPLICATE_UNSUPPORTED"):
        design._design_variance(frame[["x1"]].to_numpy())

@pytest.mark.parametrize("source",["design","lonely","subpop"])
def test_without_fpc_is_byte_identical_to_independent_frozen_baseline(source):
    module=ModuleType("workbench.survey._fpc_review_baseline")
    module.__package__="workbench.survey";sys.modules[module.__name__]=module
    code=subprocess.check_output(["git","show","3c8679c273c20ed31c2f58e493d420c2d98952c7:backend/workbench/survey/design.py"],text=True)
    exec(compile(code,"baseline_design.py","exec"),module.__dict__)
    frame=data(source)
    for policy in ("fail","remove","certainty","adjust","average"):
        for domain in (False,True):
            mask=(frame.subpop.to_numpy()==1) if domain and "subpop" in frame else np.ones(len(frame),dtype=bool)
            contribution=frame.loc[mask,["x1","x2"]].to_numpy()*frame.loc[mask,"weight"].to_numpy()[:,None]
            actual=make(frame,lonely_psu=policy)
            baseline=module.SurveyDesign(frame=frame,weight="weight",strata="stratum",psu="psu",lonely_psu=policy)
            def evaluate(design):
                try:return design._design_variance(contribution,mask=mask).tobytes()
                except SurveyEngineError as error:return (error.code,str(error))
            assert evaluate(actual)==evaluate(baseline),(source,policy,domain)
