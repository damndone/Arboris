"""Internal sort keys must never alias legitimate data column identities."""
from dataclasses import replace
import pandas as pd
import pytest
from workbench.data_operation_registry import get_data_operation
from workbench.script_export.plan import LANGUAGES,ScriptPlan,ScriptStep
from test_script_export_data_oracles import fresh_directory,source,execute,data_evidence
from test_script_export_render import renderer


@pytest.mark.parametrize('language',LANGUAGES)
def test_tsset_entity_named_time_preserves_group_sort_and_user_columns(language):
    frame=pd.DataFrame({'time':[2,1,2,1],'date':['2020-01-02','2020-01-02','2020-01-01','2020-01-01'],'__wb_time':[81,82,83,84]})
    parameters={'time_column':'date','panel_id_column':'time','frequency':'D'}
    expected=get_data_operation('tsset').run(frame,parameters)
    directory=fresh_directory()
    step=ScriptStep('step','data_operation','data.tsset',parameters,('source',),expected={'nrows':len(expected),'columns':list(expected.columns)})
    plan=ScriptPlan('internal','identities',(source(directory,frame,'data.csv','source'),),(step,),'1.8.11','e'*64)
    export=renderer()(plan,language,require_native=True)
    tail={'python':"data['step'].to_csv('result.csv',index=False)",'r':'write.csv(data[["step"]],"result.csv",row.names=FALSE)','stata':'frame wb1: export delimited using "result.csv", replace'}[language]
    code,output=execute(replace(export,text=export.text+'\n'+tail+'\n'),directory,plan)
    assert code==0,output
    actual=pd.read_csv(directory/'result.csv')
    pd.testing.assert_frame_equal(actual,expected.reset_index(drop=True),check_dtype=False)
    data_evidence(directory,actual,expected)
