"""Public progress observation reaches the existing hook without entering run identity."""
import json

import pytest


@pytest.mark.parametrize('observed', [False, True])
def test_public_workflow_forwards_optional_progress_hook_only(observed, tmp_path, monkeypatch):
    import workbench.orchestrator as orchestrator
    from workbench.projects import create_project
    source = tmp_path / 'iv.csv'
    source.write_text('y,w,d,z1,z2\n1,2,3,4,5\n')
    project = create_project(tmp_path, 'progress_hook')
    events, forwarded = [], []
    callback = (lambda *args: events.append(args)) if observed else None
    def inner(run_root, run_id, *args, **kwargs):
        forwarded.append(kwargs.get('on_step'))
        if kwargs.get('on_step'):
            kwargs['on_step']('estimation', 'start', 'Fitting IV')
        return {'run_id': run_id, 'status': 'completed'}
    monkeypatch.setattr(orchestrator, '_run_workflow', inner)
    outcome = orchestrator.run_workflow(project.root, [source], mode='auto', model_type='iv_2sls',
        y='y', x=['w'], iv_endog=['d'], iv_instruments=['z1', 'z2'], on_step=callback)
    assert forwarded == [callback]
    assert events == ([('estimation', 'start', 'Fitting IV')] if observed else [])
    inputs = json.loads((project.root / 'runs' / outcome['run_id'] / 'run_inputs.json').read_text())
    assert 'on_step' not in inputs['form']
