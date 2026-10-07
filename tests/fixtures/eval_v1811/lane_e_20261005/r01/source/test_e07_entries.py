"""E7: actual HTTP, Typer CLI and deterministic Agent all reject missing NB alpha."""
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from typer.testing import CliRunner
from workbench.api import app
from workbench.cli import app as cli_app
from workbench.projects import create_project
from workbench.agent.workflow import compile_workflow
from support import OUT,REPO,save


def test_missing_glm_nb_alpha_rejects_all_public_entries(tmp_path,monkeypatch):
    source=REPO/'tests/fixtures/count_models/reference-v3/nb2.csv';project=create_project(tmp_path,'missing').root
    with TestClient(app) as client:
        reply=client.post('/runs',data={'project_root':str(project),'mode':'auto','model_type':'glm:negative_binomial','y':'y','x':'x1,x2'},files={'file':(source.name,source.read_bytes(),'text/csv')})
    monkeypatch.setenv('WORKBENCH_UI_ORIGIN','http://127.0.0.1:8000')
    cli=CliRunner().invoke(cli_app,['run',str(project),str(source),'y','--x','x1','--x','x2','--model-type','glm:negative_binomial'])
    agent_error=None
    try:
        compile_workflow(workflow_id='e07-missing-alpha',target={'run_id':'e07-source','node_ref':'stage:cleaned','artifact_id':'cleaned_dataset'},preconditions={'context_version':'node-operation-context/v1','context_fingerprint':'sha256:e07','active_head_run_id':'e07-source','owner_resolution':'single_candidate'},available_columns=['y','x1','x2'],steps=[{'step_id':'fit','operation_id':'model.genesis','spec':{'model_family':'glm:negative_binomial','branches':[{'branch_id':'a','outcome':'y','predictors':['x1','x2']}]}}])
    except Exception as error:agent_error=str(error)
    evidence={'http_status':reply.status_code,'http':reply.json(),'cli_exit':cli.exit_code,'cli_exception':str(cli.exception),'agent_error':agent_error}
    save('e07-rejection',evidence)
    assert reply.status_code>=400,reply.text
    assert cli.exit_code!=0,evidence
    assert agent_error is not None,evidence
    for text in [reply.text,str(cli.exception),agent_error]:assert 'alpha' in text.lower(),evidence
    assert not list(project.glob('runs/*/model_results/glm_1.json'))
