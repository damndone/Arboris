"""Completed family documents retain all declared values and their identities."""
from pathlib import Path
from dataclasses import dataclass
import hashlib
import json

import pytest
from workbench.artifacts import read_json
from workbench.contracts.model.result_envelope_registry import declaration_for
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.script_export.builder import build_script_plan
from workbench.services.script_export import _prepare

@dataclass(frozen=True)
class Executable:
    language: str
    filename: str
    text: str

ROOT = Path(__file__).parents[1]
CASES = {
    'quantile_regression': ('tests/fixtures/v186_families/families.csv', {'y':'y', 'x':['x1','x2','grp'], 'model_options':{'quantiles':[.25,.5,.75], 'bootstrap_reps':0}}),
    'cs_did': ('tests/fixtures/cs_did/panel.csv', {'y':'y','x':['x1'],'entity_col':'unit','time_col':'period','did_mode':'cohort','did_cohort_col':'first_treat','cs_control_group':'never','cs_est_method':'dr','cs_base_period':'varying'}),
    'sa_did': ('tests/fixtures/sa_did/panel_balanced.csv', {'y':'y','x':[],'entity_col':'id','time_col':'year','did_mode':'cohort','did_cohort_col':'cohort'}),
    'dcdh': ('tests/fixtures/dcdh/panel_nonabsorbing.csv', {'y':'y','x':[],'entity_col':'id','time_col':'year','did_treatment_path':'d'}),
    'did': ('tests/fixtures/panel_cluster/staggered.csv', {'y':'y','x':['x1'],'entity_col':'g','time_col':'time','did_mode':'cohort','did_cohort_col':'first_treat','covariance':'clustered'}),
}

@pytest.fixture(scope='module', params=[*CASES,'time_series.ets','time_series.arma_garch'])
def completed(request,tmp_path_factory):
    family=request.param
    directory=tmp_path_factory.mktemp('complete-script-'+family)
    if family in CASES:
        filename,params=CASES[family];source=ROOT/filename
    elif family=='time_series.ets':
        from tests.fixtures.models.ets.known_truth import short_stable_series
        source=directory/'series.csv';short_stable_series().frame().to_csv(source,index=False)
        params={'y':'y','x':[],'model_options':{'time_column':'date','value_column':'y','error':'add','trend':'add','seasonal':None,'damped_trend':False}}
    else:
        from tests.models.arma_garch.test_pack_runtime import _source,_options
        source=directory/'series.csv';_source().to_csv(source,index=False)
        params={'y':'value','x':[],'model_options':_options()}
    project=create_project(directory,'owner').root
    outcome=run_workflow(project,[source],mode='auto',model_type=family,**params)
    root=project/'runs'/outcome['run_id']
    assert outcome['status']=='completed',read_json(root/'errors.json')
    from workbench.graph_store import GraphStore
    graph=GraphStore(project/'runs').read(root.name)
    node=next(node for node in graph.nodes.values() if node.kind.value=='model')
    return family,project,root,node


def test_completed_documents_keep_declared_field_paths(completed):
    family,project,root,node=completed
    built=build_script_plan(project,root.name,node.id)
    terminal=built.plan.steps[-1]
    _,raw=built.result_sidecars[terminal.step_id]
    sidecar=json.loads(raw)
    assert 'documents' in sidecar, 'A primary kernel cannot certify complete family results'
    documents=sidecar['documents']
    packet=next(doc for doc in documents.values() if doc['artifact_id']==node.id.removeprefix('model:'))
    assert built.files[packet['filename']] == (root/node.payload_ref).read_bytes()
    for doc in documents.values():
        assert hashlib.sha256(built.files[doc['filename']]).hexdigest()==doc['sha256']
    declaration=declaration_for(family)
    if declaration.evidence_document:
        evidence=json.loads(built.files[documents['evidence']['filename']])
        assert evidence==read_json(root/declaration.evidence_document)
    else:
        evidence=json.loads(built.files[packet['filename']])
    for field in declaration.fields:
        if field.sidecar:continue
        actual=evidence.get(field.source_key)
        if field.nested_key and actual is not None:actual=actual.get(field.nested_key)
        if actual is None:continue
        # Keep the entire typed value, including quantile/cohort/time labels.
        retained=json.loads(built.files[documents.get('evidence',packet)['filename']])
        value=retained.get(field.source_key)
        if field.nested_key:value=value.get(field.nested_key)
        assert value==actual
    if family=='time_series.arma_garch':
        original=read_json(root/node.payload_ref)
        for role,path in original['artifact_refs'].items():
            if path.endswith('.json'):
                assert built.files[documents[role]['filename']]==(root/path).read_bytes()
    if family=='time_series.ets':
        assert terminal.expected['nobs']==read_json(root/node.payload_ref)['result']['n_obs']
        assert not terminal.expected['std_errors']


@pytest.mark.parametrize('language',['python','r','stata'])
def test_completed_owner_scripts_execute(completed,language,tmp_path,monkeypatch):
    monkeypatch.setenv('PYTHONPATH',str(ROOT/'backend'))
    family,project,root,node=completed
    files,summary,_=_prepare(project,root.name,node.id,language,False)
    for name,raw in files.items():(tmp_path/name).write_bytes(raw)
    from test_script_export_data_oracles import execute
    filename={'python':'analysis.py','r':'analysis.R','stata':'analysis.do'}[language]
    code,output=execute(Executable(language=language,filename=filename,text=files[filename].decode()),tmp_path)
    assert code==0, output[-3000:]
    if family=='did':
        assert any(row['operation']=='data.estimation_input' and row['status']=='native' for row in summary['coverage'])
        assert summary['coverage'][-1]['status']=='native'
        _prepare(project,root.name,node.id,language,True)
