"""Execute native data scripts against the real Workbench declarations."""
import hashlib
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import pandas as pd
import pytest

from workbench.data_operation_registry import data_operation_declarations
from workbench.script_export.plan import LANGUAGES, ScriptPlan, ScriptSource, ScriptStep
from test_script_export_render import renderer
import native_runner

NATIVE = ('subset', 'recode', 'rename', 'fill_missing', 'dedupe', 'merge', 'append', 'aggregate', 'reshape', 'lag', 'tsset')
ROOT = Path(__file__).parent / 'fixtures/script_export/local_runs'
STATA = Path('/Applications/Stata/StataMP.app/Contents/MacOS/stata-mp')


def fresh_directory():
    ROOT.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='oracle-', dir=ROOT))
    print(f'Local script output: {directory}')
    return directory


def execute(export, directory, plan=None):
    if plan is not None:
        (directory/'plan.json').write_text(json.dumps(plan.to_dict(),indent=2))
    evidence=[]
    for line in export.text.splitlines():
        if export.language=='stata':
            match=re.fullmatch(r'assert !missing\((wb_number_\d+)\) & abs\(\1-\(([^)]+)\)\) <= ([^+]+)\+([^*]+)\*abs\([^)]*\)',line)
            if match:evidence.append({'scalar':match[1],'expected':float(match[2]),'abs':float(match[3]),'rel':float(match[4])})
        else:
            pattern=r'wb_check\(checks\[(\d+)\], ([^,]+), ([^,]+), ([^,]+), (.*)\)' if export.language=='python' else r'wb_check\(checks\[\[(\d+)\]\], ([^,]+), ([^,]+), ([^,]+), (.*)\)'
            match=re.fullmatch(pattern,line)
            if match:evidence.append({'expected':float(match[2]),'abs':float(match[3]),'rel':float(match[4]),'label':ast.literal_eval(match[5])})
    if evidence:
        if export.language=='python':
            trace='with open("numeric_actual.tsv","w") as wb_fh:\n    wb_fh.write("\\n".join(format(x,".17g") for x in checks))\n'
        elif export.language=='r':
            trace='writeLines(format(unlist(checks),digits=17,trim=TRUE),"numeric_actual.tsv")\n'
        else:
            trace='file open wb_numbers using "numeric_actual.tsv", write text replace\n'+''.join('file write wb_numbers %21.17g ('+e['scalar']+') _n\n' for e in evidence)+'file close wb_numbers\n'
        marker=('*' if export.language=='stata' else '#')+' Closing self-checks'
        from dataclasses import replace
        export=replace(export,text=export.text.replace(marker,trace+marker))
    path = directory / export.filename
    path.write_text(export.text)
    if export.language == 'stata':
        assert STATA.is_file(), 'Required Stata binary is missing'
    # One warm interpreter per language (tests/native_runner.py); WORKBENCH_NATIVE_COLD=1
    # runs a fresh process per script as before.
    code, stdout, stderr = native_runner.run(export.language, directory, path.name, timeout=90)
    os_exit = code
    output=stdout+stderr
    if export.language == 'stata':
        log = path.with_suffix('.log').read_text(errors='replace')
        marker = '. do ' + path.name
        log = log[log.index(marker):] if marker in log else log
        if re.search(r'(?m)^r\(\d+\);', log):
            code=9
        output=log
    numbers=directory/'numeric_actual.tsv'
    if numbers.is_file():
        values=[float(x) for x in numbers.read_text().splitlines()]
        assert len(values)==len(evidence)
        for item,actual in zip(evidence,values):
            item['actual']=actual;item['difference']=abs(actual-item['expected'])
            item['allowed']=item['abs']+item['rel']*abs(item['expected'])
    (directory/'numeric_pairs.json').write_text(json.dumps(evidence,indent=2))
    (directory/'execution.json').write_text(json.dumps({'run':os.environ.get('WB_EXPORT_EVIDENCE_RUN'),'language':export.language,'command':native_runner.describe(export.language, path.name),'os_exit':os_exit,'normalized_exit':code},indent=2))
    (directory/'command_output.txt').write_text(output)
    return code,output


def source(directory, frame, name, source_id):
    path = directory / name
    frame.to_csv(path, index=False)
    return ScriptSource(source_id, 'csv', name, hashlib.sha256(path.read_bytes()).hexdigest())


def data_evidence(directory,actual,expected):
    expected=expected.reset_index(drop=True)
    differences={c:float((actual[c]-expected[c]).abs().max()) if len(actual) else 0 for c in expected.select_dtypes(include='number')}
    (directory/'data_pairs.json').write_text(json.dumps({'actual':json.loads(actual.to_json(orient='split')),'expected':json.loads(expected.to_json(orient='split')),'max_differences':differences,'rtol':1e-8,'atol':1e-8},indent=2))


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('operation', NATIVE)
def test_data_operation_native_oracle(operation, language):
    declaration = next(d for d in data_operation_declarations() if d.operation == operation)
    directory = fresh_directory()
    frame = declaration.example_frame()
    parameters = declaration.parameters_of(declaration.example)
    secondary = declaration.example_secondary_frame() if declaration.secondary_input else None
    expected = declaration.run(frame, declaration.example, secondary)
    sources = [source(directory, frame, 'data.csv', 'source')]
    if secondary is not None:
        sources.append(source(directory, secondary, 'secondary.csv', 'secondary'))
    step = ScriptStep('step', 'data_operation', 'data.' + operation, parameters,
                      tuple(s.source_id for s in sources), expected={'nrows': len(expected), 'columns': list(expected.columns)})
    plan = ScriptPlan('data-oracle', operation, tuple(sources), (step,), '1.8.11', '0'*64)
    export = renderer()(plan, language, require_native=True)
    assert export.fully_native
    tails = {'python': "data['step'].to_csv('result.csv', index=False)",
             'r': 'write.csv(data[["step"]], "result.csv", row.names=FALSE, na="")',
             'stata': 'frame wb1: export delimited using "result.csv", replace'}
    from dataclasses import replace
    export = replace(export, text=export.text + '\n' + tails[language] + '\n')
    code, output = execute(export, directory,plan)
    assert code == 0, output
    actual = pd.read_csv(directory / 'result.csv')
    pd.testing.assert_frame_equal(actual, expected.reset_index(drop=True), check_dtype=False, check_names=False, rtol=1e-8)
    data_evidence(directory,actual,expected)

EDGE_CASES = (
 ('subset',pd.DataFrame({'id':[1,2,3,4],'x':[None,2.,8.,9.]}),{'columns':['id','x'],'filters':[{'column':'x','op':'gt','value':5}]},None),
 ('subset',pd.DataFrame({'id':[1,2,3,4],'x':[1.,2.,8.,9.]}),{'columns':['x','id'],'row_indices':[3,1]},None),
 ('dedupe',pd.DataFrame({'id':[2,1,2,1],'x':[1.,2.,3.,4.]}),{'columns':['id'],'keep':'last'},None),
 ('recode',pd.DataFrame({'x':[1.,2.,3.,None]}),{'column':'x','output':'code','rules':[{'from':{'low':1,'high':2},'to':10},{'from':2,'to':20},{'from':'missing','to':-1},{'from':'else','to':'copy'}]},None),
 ('rename',pd.DataFrame({'a':[1.,2.],'b':[3.,4.]}),{'mapping':{'a':'b','b':'a'}},None),
 ('fill_missing',pd.DataFrame({'x':[None,2.,4.],'z':[1.,None,3.]}),{'strategies':[{'column':'x','strategy':'mean'},{'column':'z','strategy':'constant','value':8}]},None),
 ('fill_missing',pd.DataFrame({'x':[4.,2.,4.,None,2.]}),{'strategies':[{'column':'x','strategy':'mode'}]},None),
 ('aggregate',pd.DataFrame({'g':['z','a','z',None],'x':[1.,4.,3.,6.]}),{'group_by':['g'],'aggregations':[{'column':'x','func':'std','output':'sd'},{'column':'x','func':'count','output':'n'},{'column':'x','func':'sum','output':'total'}]},None),
 ('lag',pd.DataFrame({'x':[1.,3.,6.,10.,15.]}),{'columns':['x'],'lags':[1,3],'difference':2},None),
 ('reshape',pd.DataFrame({'id':[2,1,2,1],'kind':['a','a','b','b'],'value':[3.,4.,5.,6.]}),{'direction':'long_to_wide','index':['id'],'columns':'kind','values':'value'},None),
 ('tsset',pd.DataFrame({'id':[2,1,2,1],'date':['2020-01-02','2020-01-02','2020-01-01','2020-01-01'],'x':[1.,2.,3.,4.]}),{'time_column':'date','panel_id_column':'id','frequency':'D'},None),
 ('merge',pd.DataFrame({'id':[2,1,3],'x':[2.,1.,3.]}),{'keys':['id'],'how':'outer'},pd.DataFrame({'id':[1,2,4],'x':[10.,20.,40.]})),
 ('append',pd.DataFrame({'id':[1,2],'x':[1.,2.]}),{'schema_policy':'union'},pd.DataFrame({'id':[3,4],'z':[3.,4.]})),
 ('merge',pd.DataFrame({'id':[2,1,3],'x':[2.,1.,3.]}),{'keys':['id'],'how':'outer','indicator':True},pd.DataFrame({'id':[1,2,4],'x':[10.,20.,40.]})),
)


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('case',EDGE_CASES,ids=[f'{i}-{case[0]}' for i,case in enumerate(EDGE_CASES)])
def test_data_edge_semantics(case,language):
    from workbench.data_operation_registry import get_data_operation
    from dataclasses import replace
    operation,d,parameters,right=case
    directory=fresh_directory();expected=get_data_operation(operation).run(d,parameters,right)
    sources=[source(directory,d,'data.csv','source')]
    if right is not None:sources.append(source(directory,right,'secondary.csv','secondary'))
    step=ScriptStep('step','data_operation','data.'+operation,parameters,tuple(s.source_id for s in sources),expected={'nrows':len(expected),'columns':list(expected.columns)})
    plan=ScriptPlan('edges',operation,tuple(sources),(step,),'1.8.11','5'*64)
    export=renderer()(plan,language)
    tail={'python':"data['step'].to_csv('result.csv',index=False)",'r':'write.csv(data[["step"]],"result.csv",row.names=FALSE,na="")','stata':'frame wb1: export delimited using "result.csv", replace'}[language]
    code,output=execute(replace(export,text=export.text+'\n'+tail+'\n'),directory,plan)
    assert code==0,output
    actual=pd.read_csv(directory/'result.csv')
    pd.testing.assert_frame_equal(actual,expected.reset_index(drop=True),check_dtype=False,check_categorical=False,check_names=False,rtol=1e-8)
    data_evidence(directory,actual,expected)
