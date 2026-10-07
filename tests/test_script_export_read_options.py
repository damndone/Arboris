"""Closed local reader translations compared with the Workbench reader engines."""
from dataclasses import replace
import hashlib
from pathlib import Path
import pandas as pd
import pytest
from workbench.config import WorkbenchConfig
from workbench.ingestion import _read_frame
from workbench.script_export.plan import LANGUAGES,ScriptPlan,ScriptSource,ScriptStep,ScriptExportRefusal
from test_script_export_data_oracles import fresh_directory,execute,data_evidence
from test_script_export_render import renderer


CASES=(('utf8_semicolon',{'delimiter':';','encoding':'utf-8','header':0},'id;city;value\n1;北京;1.25\n2;café;2.5\n'),
       ('latin1_pipe',{'delimiter':'|','encoding':'latin1','header':0},'id|city|value\n1|café|1.25\n2|été|2.5\n'),
       ('tab_no_header',{'delimiter':'\t','encoding':'utf-8','header':None,'names':['id','city','value']},'1\twest\t1.25\n2\teast\t2.5\n'))


def run_reader(directory,source,expected,language):
    step=ScriptStep('result','data_operation','data.subset',{'columns':list(expected.columns)},('source',),expected={'nrows':len(expected),'columns':list(expected.columns)})
    plan=ScriptPlan('reader','translated',(source,),(step,),'1.8.11','9'*64)
    export=renderer()(plan,language,require_native=True)
    tail={'python':"data['result'].to_csv('result.csv',index=False)",'r':'write.csv(data[["result"]],"result.csv",row.names=FALSE,na="")','stata':'frame wb1: export delimited using "result.csv", replace'}[language]
    code,output=execute(replace(export,text=export.text+'\n'+tail+'\n'),directory,plan)
    assert code==0,output
    actual=pd.read_csv(directory/'result.csv')
    pd.testing.assert_frame_equal(actual,expected,check_dtype=False,rtol=1e-8,atol=1e-8)
    data_evidence(directory,actual,expected)


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('case',CASES,ids=[c[0] for c in CASES])
def test_common_csv_reader_options_execute_native(language,case):
    name,options,content=case;directory=fresh_directory();path=directory/'data.csv'
    path.write_bytes(content.encode(options['encoding']))
    kwargs={'sep':options['delimiter'],'encoding':options['encoding'],'header':options['header']}
    if 'names' in options:kwargs['names']=options['names']
    expected=pd.read_csv(path,**kwargs)
    source=ScriptSource('source','csv','data.csv',hashlib.sha256(path.read_bytes()).hexdigest(),options)
    run_reader(directory,source,expected,language)


def test_r_csv_precision_preserves_explicit_nonfinite_and_missing_cells():
    directory=fresh_directory();path=directory/'data.csv'
    path.write_text('id,value\n1,1.25\n2,Inf\n3,-Inf\n4,NA\n')
    expected=pd.read_csv(path)
    source=ScriptSource('source','csv','data.csv',hashlib.sha256(path.read_bytes()).hexdigest())
    run_reader(directory,source,expected,'r')


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('sheet',('Chosen',None))
def test_workbench_excel_selected_sheet_executes_native(language,sheet):
    directory=fresh_directory();path=directory/'data.xlsx'
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({'x':[999.]}).to_excel(writer,sheet_name='Decoy',index=False)
        pd.DataFrame({'x':[3.,4.,5.]}).to_excel(writer,sheet_name='Chosen',index=False)
    expected=_read_frame(path,WorkbenchConfig(),sheet_name=sheet,transpose=False)
    source=ScriptSource('source','xlsx','data.xlsx',hashlib.sha256(path.read_bytes()).hexdigest(),{'sheet_name':sheet,'transpose':False})
    run_reader(directory,source,expected,language)


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('options',({'unknown':True},{'header':True},{'names':42},{'header':None},{'delimiter':';','sep':','},{'transpose':True}))
def test_unknown_or_non_equivalent_reader_options_refuse_explicitly(language,options):
    source=ScriptSource('source','csv','data.csv','0'*64,options)
    plan=ScriptPlan('reader','refusal',(source,),(),'1.8.11','9'*64)
    with pytest.raises(ScriptExportRefusal):renderer()(plan,language)
