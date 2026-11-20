"""Unavailable persisted inputs must not become a confirmable rerun."""
import json
from types import SimpleNamespace

import pytest

from workbench.agent.orchestration_proposals import OrchestrationProposals
from workbench.agent.tools import ToolVisibleError
from workbench.lineage.upload_store import store_upload_bytes


def _source(tmp_path):
    root = tmp_path / 'project'
    run = root / 'runs' / 'source'
    run.mkdir(parents=True)
    digest = store_upload_bytes(root, b'y,x\n2,1\n4,2\n6,3\n', filename='data.csv')
    (run / 'run_inputs.json').write_text(json.dumps({
        'form': {'model_type': 'ols', 'y': 'y', 'x': 'x'},
        'upload': {'sha256': digest, 'filename': 'data.csv'},
    }))
    runtime = OrchestrationProposals()
    runtime.context_provider = SimpleNamespace(project_root=root)
    return runtime, root, run, digest


@pytest.mark.parametrize('failure', ['missing_run', 'missing_inputs', 'invalid_json', 'missing_upload', 'changed_upload', 'invalid_shape'])
def test_unavailable_rerun_source_is_an_explicit_recoverable_refusal(tmp_path, failure):
    runtime, root, run, digest = _source(tmp_path)
    arguments = {'target': {'run_id': 'source'}, 'changes': {'covariance': 'HC3'}}
    if failure == 'missing_run':
        arguments['target']['run_id'] = 'not-a-run'
    elif failure == 'missing_inputs':
        (run / 'run_inputs.json').rename(run / 'preserved_inputs.json')
    elif failure == 'invalid_json':
        (run / 'run_inputs.json').write_text('{')
    elif failure == 'missing_upload':
        (root / 'data' / 'uploads' / digest).rename(root / 'data' / 'uploads' / 'preserved.csv')
    elif failure == 'changed_upload':
        (root / 'data' / 'uploads' / digest).write_bytes(b'changed input')
    else:
        (run / 'run_inputs.json').write_text('[]')
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    with pytest.raises(ToolVisibleError, match='MODEL_RERUN_SOURCE_UNAVAILABLE') as caught:
        runtime._preflight_model_rerun_declarations(arguments)

    assert 'No proposal was created' in str(caught.value)
    assert 'restore' in str(caught.value)
    assert caught.value.__cause__ is not None
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_valid_rerun_source_and_declaration_rules_still_apply(tmp_path):
    runtime, _, _, _ = _source(tmp_path)
    runtime._preflight_model_rerun_declarations({'target': {'run_id': 'source'}, 'changes': {'covariance': 'HC3'}})
    with pytest.raises(ToolVisibleError, match='MEASUREMENT_LEVEL_UNKNOWN_COLUMN'):
        runtime._preflight_model_rerun_declarations({'target': {'run_id': 'source'},
            'changes': {'labels': {'measurement_level': {'not_a_column': 'scale'}}}})


def test_noneditable_target_refusal_precedes_upload_reads(tmp_path, monkeypatch):
    from workbench.agent import orchestration_proposals
    runtime, _, _, _ = _source(tmp_path)

    def refuse_target(*args):
        raise ToolVisibleError('MODEL_RERUN_TARGET_NOT_EDITABLE: inspect an editable model node')

    def forbid_read(*args):
        pytest.fail('A rejected target must not read its saved data')

    monkeypatch.setattr(orchestration_proposals, '_require_editable_rerun_target', refuse_target)
    monkeypatch.setattr(orchestration_proposals, 'read_run_inputs', forbid_read)
    with pytest.raises(ToolVisibleError, match='MODEL_RERUN_TARGET_NOT_EDITABLE'):
        runtime._preflight_model_rerun_declarations({'target': {'run_id': 'source'}})
