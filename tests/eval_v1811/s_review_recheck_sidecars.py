"""Independent runtime attacks; author setup reads real persisted WB artifacts."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import types

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest
from workbench.contracts.common.envelope import thaw_json
from workbench.script_export.plan import LANGUAGES, ScriptExportRefusal
from workbench.script_export.render import export_script
from test_script_export_result_sidecars import assets
from test_script_export_postestimation_oracles import expected_from
from workbench.econometrics.runner import run_ols
from workbench.contracts.model.inference_kernel import build_inference_kernel
from workbench.postestimation.registry import run_operation
from workbench.script_export.plan import ScriptStep
from workbench.script_export.plan import ScriptPlan
import pandas as pd

EVIDENCE = Path(__file__).with_name('s_review_recheck_evidence') / 'sidecars'
BACKEND = Path(__file__).parents[2] / 'backend'
STATA = '/Applications/Stata/StataMP.app/Contents/MacOS/stata-mp'


def setup(case, language, monkeypatch):
    directory = EVIDENCE / (case + '-' + language + '-' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    monkeypatch.setenv('PYTHONPATH', str(BACKEND))
    plan, refs = assets(directory)
    return directory, plan, refs


def execute(directory, plan, language, refs, text=None):
    exported = export_script(plan, language, result_snapshots=refs, require_native=refs is None)
    script = directory / exported.filename
    script.write_text(exported.text if text is None else text)
    (directory / 'plan.json').write_text(json.dumps(plan.to_dict(), indent=2))
    (directory / 'references.json').write_text(json.dumps({k: vars(v) for k,v in (refs or {}).items()}, indent=2))
    command = {'python': [sys.executable, script.name], 'r': ['Rscript', script.name],
               'stata': [STATA, '-b', 'do', script.name]}[language]
    run = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=90)
    output = run.stdout + run.stderr
    code = run.returncode
    if language == 'stata':
        output = script.with_suffix('.log').read_text(errors='replace')
        output = output[output.index('. do ' + script.name):]
        if re.search(r'(?m)^r\(\d+\);', output):
            code = 9
    (directory / 'public_output.txt').write_text(output)
    (directory / 'execution.json').write_text(json.dumps({'command':command, 'os_exit':run.returncode,
        'normalized_exit':code, 'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest()}, indent=2))
    return code, output


def rewrite(directory, refs, key, payload):
    path = directory / refs[key].filename
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    refs[key] = replace(refs[key], sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('attack', ('actual', 'parameters', 'models', 'source_bytes', 'snapshot_bytes', 'null_actual', 'distribution'))
def test_authenticated_asset_cannot_bypass_assertions(language, attack, monkeypatch):
    directory, plan, refs = setup(attack, language, monkeypatch)
    key = 'post' if attack in {'models','null_actual','distribution'} else 'completed'
    payload = json.loads((directory / refs[key].filename).read_bytes())
    if attack == 'actual':
        # Expected remains true; alter only the authenticated actual and rehash.
        payload['values']['coefficients']['x1'] += 1
    elif attack == 'parameters':
        payload['binding']['parameters_sha256'] = '0'*64
    elif attack == 'models':
        payload['binding']['models'] = ['independent']
    elif attack == 'source_bytes':
        path = directory / 'data.csv'
        path.write_bytes(path.read_bytes() + b'\n')
    elif attack == 'snapshot_bytes':
        path = directory / 'completed.csv'
        path.write_bytes(path.read_bytes() + b'\n')
    elif attack == 'null_actual':
        payload['values']['statistics']['test']['value'] = None
    else:
        payload['values']['statistics']['test']['distribution'] = 'Wrong reference distribution'
    if attack not in {'source_bytes','snapshot_bytes'}:
        rewrite(directory, refs, key, payload)
    code, output = execute(directory, plan, language, refs)
    assert code != 0, output


@pytest.mark.parametrize('language', LANGUAGES)
def test_snapshot_then_native_model_and_post_really_execute(language, monkeypatch):
    directory, plan, refs = setup('native-closure', language, monkeypatch)
    frame = pd.read_csv(directory/'data.csv')
    actual, fit = run_ols(frame, 'y', ['x1','x2'], False, 'independent')
    kernel = build_inference_kernel(model_id='independent', model_type='ols', param_names=list(actual['coefficients']),
        params=fit.params, vcov=fit.cov_params(), reference_distribution='t', df_resid=fit.df_resid,
        nobs=int(fit.nobs), covariance_estimator='nonrobust', loglik=fit.llf)
    spec = {'terms':{'x1':1,'x2':2}, 'constant':-.5}
    result = run_operation('lincom',[kernel],spec)
    (directory/'native_post_artifact.json').write_text(json.dumps(result, indent=2))
    step = ScriptStep('native_post', 'postestimation','postestimation.lincom',
        {**spec,'models':['independent']},('independent',),expected=expected_from(result))
    plan = replace(plan,steps=(*plan.steps,step))
    exported = export_script(plan,language,result_snapshots=refs)
    assert [x.status for x in exported.coverage] == ['snapshot','snapshot','native','native','native']
    code, output = execute(directory,plan,language,refs)
    assert code == 0, output
    # An independently wrong native post number must fail the actual estimator.
    expected = thaw_json(step.expected)
    expected['statistics']['test']['value'] += 1
    bad = replace(plan,steps=(*plan.steps[:-1],replace(step,expected=expected)))
    bad_dir = directory/'wrong_native_post'
    bad_dir.mkdir()
    for path in directory.iterdir():
        if path.is_file() and path.suffix in {'.csv','.json'}:
            (bad_dir/path.name).write_bytes(path.read_bytes())
    code, output = execute(bad_dir,bad,language,refs)
    assert code != 0, output


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('control_character', (False, True))
def test_raw_distribution_is_literal_and_nullable_actual_is_retained(language, control_character, monkeypatch):
    directory, plan, refs = setup('literal-null',language,monkeypatch)
    payload = json.loads((directory/refs['post'].filename).read_bytes())
    label = 'Recorded "custom" $HOME `unsafe`\\path reference'
    if control_character:
        label += '\ninvalid identity'
    payload['values']['statistics']['probe'] = {'value':None,'df':None,'df_denominator':None,'p_value':None,'distribution':label}
    rewrite(directory,refs,'post',payload)
    expected = thaw_json(plan.steps[1].expected)
    expected['statistics']['probe'] = dict(payload['values']['statistics']['probe'])
    plan = replace(plan,steps=(plan.steps[0],replace(plan.steps[1],expected=expected),*plan.steps[2:]))
    code, output = execute(directory,plan,language,refs)
    assert (code != 0) if control_character else (code == 0), output


@pytest.mark.parametrize('language', LANGUAGES)
def test_bridge_dependency_failure_stops_completed_closure(language, monkeypatch):
    directory, plan, refs = setup('dependency',language,monkeypatch)
    exported = export_script(plan,language,result_snapshots=refs)
    assert 'workbench' in exported.required_packages
    text = exported.text.replace('from workbench.script_export.result_snapshot import','from missing_independent_sidecar_package import') if language=='python' else exported.text.replace('python3','independent_missing_python_bridge')
    code, output = execute(directory,plan,language,refs,text)
    assert code != 0, output


@pytest.mark.parametrize('language', LANGUAGES)
def test_require_native_closure_refuses_before_asset_io(language, monkeypatch):
    directory,plan,refs = setup('require-native',language,monkeypatch)
    with pytest.raises(ScriptExportRefusal) as caught:
        export_script(plan,language,result_snapshots={},require_native=True)
    assert caught.value.code == 'NOT_FULLY_NATIVE'
    assert caught.value.steps == ('completed','post')


@pytest.mark.parametrize('language', LANGUAGES)
def test_none_path_matches_old_renderer_from_exact_git_tip(language):
    # Compare the actual old implementation, not an author-generated constant.
    root = Path(__file__).parents[2]
    source = subprocess.check_output(['git','show','92c90b599206588a999d8ff991d5cd59785f5532:backend/workbench/script_export/render.py'],cwd=root,text=True)
    module = types.ModuleType('workbench.script_export.independent_old_render')
    module.__package__ = 'workbench.script_export'
    exec(compile(source,'git:92c90b59/render.py','exec'),module.__dict__)
    plan = ScriptPlan.from_dict(json.loads((root/'tests/fixtures/script_export/validated_basic/plan.json').read_text()))
    assert export_script(plan,language,result_snapshots=None) == module.export_script(plan,language)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('convention', ('design','design_minus_p'))
def test_no_fpc_survey_wald_uses_actual_stage_kernel(language, convention, monkeypatch):
    from test_script_export_survey_oracles import survey_plan, executed_oracle, FIXTURES
    directory = EVIDENCE / ('survey-'+convention+'-'+language+'-'+uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    monkeypatch.setenv('PYTHONPATH',str(BACKEND))
    frame = pd.read_csv(FIXTURES/'design.csv')
    design = {'sampling_weight':'weight','survey_strata_col':'stratum','survey_psu_col':'psu','survey_df':convention}
    plan = survey_plan(directory,frame,design)
    _,kernel,_ = executed_oracle(frame,design)
    spec = {'constraints':[{'terms':{'x1':1},'value':.2},{'terms':{'x2':1},'value':0}]}
    result = run_operation('wald',[kernel],spec)
    (directory/'post_artifact.json').write_text(json.dumps(result,indent=2))
    post = ScriptStep('post','postestimation','postestimation.wald',{**spec,'models':['model']},('model',),expected=expected_from(result))
    plan = replace(plan,steps=(*plan.steps,post))
    code,output = execute(directory,plan,language,None)
    assert code == 0, output


@pytest.mark.parametrize('language', LANGUAGES)
def test_reader_latin1_pipe_actual_cells(language,monkeypatch):
    from workbench.script_export.plan import ScriptSource
    directory = EVIDENCE / ('reader-'+language+'-'+uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    path = directory/'reader.csv'
    path.write_bytes('city|value\ncafé|1.25\nété|2.5\n'.encode('latin1'))
    expected = pd.read_csv(path,sep='|',encoding='latin1',header=0)
    expected.to_csv(directory/'expected.csv',index=False)
    source = ScriptSource('source','csv',path.name,hashlib.sha256(path.read_bytes()).hexdigest(),{'encoding':'latin1','delimiter':'|','header':0})
    step = ScriptStep('result','data_operation','data.subset',{'columns':['city','value']},('source',),expected={'nrows':2,'columns':['city','value']})
    plan = ScriptPlan('review','reader',(source,),(step,),'1.8.11','a'*64)
    exported = export_script(plan,language,require_native=True)
    tail = {'python':"data['result'].to_csv('actual.csv',index=False)",'r':'write.csv(data[["result"]],"actual.csv",row.names=FALSE,na="")','stata':'frame wb1: export delimited using "actual.csv", replace'}[language]
    code,output = execute(directory,plan,language,None,exported.text+'\n'+tail+'\n')
    assert code == 0, output
    actual = pd.read_csv(directory/'actual.csv')
    pd.testing.assert_frame_equal(actual,expected,check_dtype=False,atol=1e-8,rtol=1e-8)
