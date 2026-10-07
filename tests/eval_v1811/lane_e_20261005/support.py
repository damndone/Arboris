"""Retain independent lane evidence without modifying existing assets."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
OUT = Path(os.environ['WB_LANE_E_OUT']).resolve()
assert OUT.is_relative_to(REPO / 'tests/fixtures/eval_v1811/lane_e_20261005')
OUT.mkdir(parents=True, exist_ok=True)
BASELINE = '5f8451b929ac51ba7ae9821e4a8a7f1adea642a8'


def save(name, payload):
    path = OUT / (name + '.json')
    assert not path.exists(), path
    path.write_text(json.dumps(payload, indent=2, allow_nan=False, default=str))
    return path


def native_stata(body, name, temp):
    sys.path.insert(0, str(REPO / 'tests'))
    from stata_oracle import STATA, run
    assert STATA.is_file(), 'Real Stata is required; no skip'
    directory = temp / ('native-' + name)
    assert not directory.exists()
    values = None
    error_type = None
    try:
        values = run(directory, body, name='lane_e')
    except Exception as error:
        error_type = type(error).__name__
    log = directory / 'lane_e.log'
    raw = ''
    if log.exists():
        log.chmod(0o600)
        raw = log.read_text(errors='replace')
    marker = '. do lane_e.do'
    public = OUT / (name + '-stata-output.txt')
    assert not public.exists()
    public.write_text(raw[raw.index(marker):] if marker in raw else 'Native command marker unavailable; private log retained.')
    (OUT / (name + '.do')).write_bytes((directory / 'lane_e.do').read_bytes())
    save(name + '-stata', {'values': values, 'raw_log': str(log), 'error_type': error_type,
        'public_log': str(public), 'command': [str(STATA), '-b', 'do', 'lane_e.do']})
    assert values is not None, f'Native Stata failed ({error_type}); retained public output: {public}'
    assert marker in raw, 'Cannot safely isolate native command output'
    return values


def emit(name, expression):
    sys.path.insert(0, str(REPO / 'tests'))
    from stata_oracle import emit as native_emit
    return native_emit(name, expression).replace('%21.15g', '%24.17g')


def native_r(script, data, name, temp):
    source = temp / (name + '.R')
    source.write_text(script)
    output = temp / (name + '-oracle.json')
    cmd = ['Rscript', '--vanilla', str(source), str(data), str(output)]
    completed = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    (OUT / (name + '.R')).write_bytes(source.read_bytes())
    (OUT / (name + '-r-output.txt')).write_text(completed.stdout + completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output.read_text())
    save(name + '-r', {'oracle': result, 'command': cmd, 'exit': completed.returncode})
    return result


def fit(project, data, family, y, x, **options):
    from workbench.orchestrator import run_workflow
    from workbench.artifacts import read_json
    from workbench.contracts.model.inference_kernel import kernel_relative_path
    outcome = run_workflow(project, [data], mode='auto', model_type=family, y=y, x=x, **options)
    root = project / 'runs' / outcome['run_id']
    assert outcome['status'] == 'completed', outcome
    model = ('glm' if family.startswith('glm:') else family) + '_1'
    return root, read_json(root / f'model_results/{model}.json'), read_json(root / kernel_relative_path(model))


def finished(client, project, run_id):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        response = client.get('/runs/' + run_id, params={'project_root': str(project)})
        assert response.status_code == 200, response.text
        status = response.json()['status']
        if status in {'completed', 'failed', 'blocked', 'partial'}:
            assert status == 'completed', response.text
            return response.json()
        time.sleep(.05)
    raise AssertionError('Actual public run did not finish')


def execute_script(export, directory, plan):
    spec = importlib.util.spec_from_file_location('lane_e_existing_native_executor', REPO / 'tests/test_script_export_data_oracles.py')
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO / 'tests'))
    spec.loader.exec_module(module)
    result = module.execute(export, directory, plan)
    if export.language == 'stata':
        for log in directory.glob('*.log'):
            log.chmod(0o600)
    return result
