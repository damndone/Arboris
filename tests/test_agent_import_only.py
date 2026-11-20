"""Raw data must be reachable without an arbitrary prerequisite regression."""
import json

import pandas as pd
import pytest

from workbench.lineage.node_write_validation import build_rerun_operation_context
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


@pytest.mark.parametrize('rows', [2, 16])
def test_import_only_persists_source_profile_and_lineage_without_fitting(tmp_path, rows, monkeypatch):
    from workbench.engine.stages.estimation import EstimationStage

    def no_fit(*args):
        pytest.fail('an import must not fit a model')
    monkeypatch.setattr(EstimationStage, 'run', no_fit)
    project = create_project(tmp_path, 'project')
    source = tmp_path / 'categories.csv'
    pd.DataFrame({'group': ['red', 'blue'] * (rows // 2)}).to_csv(source, index=False)
    run = run_workflow(project.root, [source], mode='import', y='', x=[])
    root = project.root / 'runs' / run['run_id']
    assert run['status'] == 'completed'
    assert len(pd.read_parquet(root / 'processed/cleaned_dataset.parquet')) == rows
    assert json.loads((root / 'staged/data_profile.json').read_text())['row_count'] == rows
    assert not list((root / 'model_results').iterdir())
    manifest = json.loads((root / 'run_manifest.json').read_text())
    assert manifest['status'] == 'completed' and manifest['mode'] == 'import'
    assert (root / 'graph.json').exists()
    # Every imported node stays addressable: the Agent's node tools read through this.
    for node in ('stage:raw', 'stage:cleaned'):
        target = build_rerun_operation_context(project.root / 'runs', request_id='r', owner_run_id=run['run_id'],
                                               op_node_id=node, active_head_run_id=run['run_id'])
        assert target.node_hash
    assert not [key for key in json.loads((root / 'node_index.json').read_text()) if key.startswith('var:')]


def test_import_failure_remains_failed_and_retains_source(tmp_path):
    project = create_project(tmp_path, 'project')
    source = tmp_path / 'empty.csv'
    source.write_text('')
    with pytest.raises(Exception):
        run_workflow(project.root, [source], mode='import', y='', x=[])
    [root] = (project.root / 'runs').iterdir()
    assert json.loads((root / 'run_manifest.json').read_text())['status'] == 'failed'
    assert (root / 'errors.json').exists()


def test_evaluation_import_uses_real_dispatch_and_supports_a_data_focused_session(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    from fastapi.testclient import TestClient
    from workbench.app import app

    repo = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(repo / 'scripts'))
    spec = importlib.util.spec_from_file_location('agent_eval_import_test', repo / 'scripts/agent_eval_run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = create_project(tmp_path, 'project')
    source = tmp_path / 'tiny.csv'
    source.write_text('category\nred\nblue\n')
    run_id = module._seed(project.root, source, {'mode': 'import', 'model_type': 'auto', 'y': '', 'x': ''})
    root = project.root / 'runs' / run_id
    assert json.loads((root / 'run_manifest.json').read_text())['status'] == 'completed'
    with TestClient(app, base_url='http://127.0.0.1') as client:
        response = client.post('/agent/sessions', params={'project_root': str(project.root)}, json={
            'role': 'chain', 'chain_id': f'run:{run_id}', 'run_id': run_id, 'context_packet': {},
            'focus': {'kind': 'node', 'id': 'stage:cleaned', 'run_id': run_id, 'label': 'Imported data'}})
        assert response.status_code == 200, response.text
    assert not list((root / 'model_results').iterdir())
