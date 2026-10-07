"""E7: durable failures agree across actual HTTP, run-id CLI and Agent compiler."""
import json
import time
from fastapi.testclient import TestClient
from typer.testing import CliRunner
from workbench.api import app
from workbench.cli import app as cli_app
from workbench.projects import create_project
from workbench.agent.workflow import compile_workflow
from support import REPO,save


def failure_record(project,run_id):
    root=project/'runs'/run_id
    manifest=json.loads((root/'run_manifest.json').read_text())
    errors=json.loads((root/'errors.json').read_text())
    assert manifest['status']=='failed',manifest
    assert not (root/'model_results/glm_1.json').exists()
    assert any(issue['code']=='GLM_NB_ALPHA_REQUIRED' for issue in errors['issues']),errors
    return {'run_id':run_id,'manifest':manifest,'errors':errors}


def test_missing_glm_nb_alpha_rejects_all_public_entries(tmp_path,monkeypatch):
    source=REPO/'tests/fixtures/count_models/reference-v3/nb2.csv';project=create_project(tmp_path,'missing').root
    with TestClient(app) as client:
        reply=client.post('/runs',data={'project_root':str(project),'mode':'auto','model_type':'glm:negative_binomial','y':'y','x':'x1,x2'},files={'file':(source.name,source.read_bytes(),'text/csv')})
        assert reply.status_code==200,reply.text
        run_id=reply.json()['run_id'];deadline=time.monotonic()+60
        while True:
            terminal=client.get('/runs/'+run_id,params={'project_root':str(project)})
            assert terminal.status_code==200,terminal.text
            if terminal.json()['status']!='running':break
            assert time.monotonic()<deadline
            time.sleep(.05)
        assert terminal.json()['status']=='failed',terminal.text
    http=failure_record(project,run_id)
    monkeypatch.setenv('WORKBENCH_UI_ORIGIN','http://127.0.0.1:8000')
    cli=CliRunner().invoke(cli_app,['run',str(project),str(source),'y','--x','x1','--x','x2','--model-type','glm:negative_binomial'])
    # The documented CLI stdout contract returns a durable run_id even for a failed run.
    assert cli.exit_code==0,cli.output
    cli_id=cli.stdout.strip();cli_record=failure_record(project,cli_id)
    agent_error=None
    try:
        compile_workflow(workflow_id='e07-missing-alpha',target={'run_id':'e07-source','node_ref':'stage:cleaned','artifact_id':'cleaned_dataset'},preconditions={'context_version':'node-operation-context/v1','context_fingerprint':'sha256:e07','active_head_run_id':'e07-source','owner_resolution':'single_candidate'},available_columns=['y','x1','x2'],steps=[{'step_id':'fit','operation_id':'model.genesis','spec':{'model_family':'glm:negative_binomial','branches':[{'branch_id':'a','outcome':'y','predictors':['x1','x2']}]}}])
    except Exception as error:agent_error=str(error)
    save('e07-rejection',{'http_initial':reply.json(),'http_terminal':terminal.json(),'http_record':http,'cli_exit':cli.exit_code,'cli_record':cli_record,'agent_error':agent_error})
    assert agent_error is not None and 'alpha' in agent_error.lower()
    assert not list(project.glob('runs/*/model_results/glm_1.json'))
