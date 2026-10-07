"""Independent C3 probes; preserve native outputs and real engine comparisons."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

import numpy as np
import pandas as pd
import pytest

from workbench.data_operation_registry import get_data_operation
from workbench.econometrics import runner
from workbench.script_export.plan import LANGUAGES, ScriptPlan, ScriptSource, ScriptStep
from workbench.script_export.render import export_script

EVIDENCE = Path(__file__).with_name('s_review_evidence')
STATA = '/Applications/Stata/StataMP.app/Contents/MacOS/stata-mp'


def directory(case, language):
    target = EVIDENCE / (case + '-' + language + '-' + uuid.uuid4().hex[:8])
    target.mkdir(parents=True)
    print(f'Independent local script output: {target}')
    return target


def source(target, frame):
    path = target / 'data.csv'
    frame.to_csv(path, index=False)
    return ScriptSource('source', 'csv', path.name, hashlib.sha256(path.read_bytes()).hexdigest())


def execute(target, plan, language, tail=''):
    exported = export_script(plan, language, require_native=True)
    (target / 'plan.json').write_text(json.dumps(plan.to_dict(), indent=2))
    script = target / exported.filename
    marker = ('*' if language == 'stata' else '#') + ' Closing self-checks'
    if language == 'python':
        trace = "Path('numeric_actual.tsv').write_text('\\n'.join(format(x,'.17g') for x in checks))\n"
    elif language == 'r':
        trace = 'writeLines(sprintf("%.17g",unlist(checks)),"numeric_actual.tsv")\n'
    else:
        scalars = re.findall(r'(?m)^scalar (wb_number_\d+) =', exported.text)
        trace = 'file open wb_review_numbers using "numeric_actual.tsv", write text replace\n'
        trace += ''.join(f'file write wb_review_numbers %21.17g ({name}) _n\n' for name in scalars)
        trace += 'file close wb_review_numbers\n'
    script.write_text(exported.text.replace(marker, trace + marker) + '\n' + tail + '\n')
    commands = {'python': [sys.executable, script.name], 'r': ['Rscript', script.name],
                'stata': [STATA, '-b', 'do', script.name]}
    completed = subprocess.run(commands[language], cwd=target, capture_output=True, text=True, timeout=90)
    output = completed.stdout + completed.stderr
    code = completed.returncode
    if language == 'stata':
        output = script.with_suffix('.log').read_text(errors='replace')
        current = output[output.index('. do ' + script.name):]
        if re.search(r'(?m)^r\(\d+\);', current):
            code = 9
    (target / 'output.txt').write_text(output)
    public = output[output.index('. do ' + script.name):] if language == 'stata' else output
    (target / 'public_output.txt').write_text(public)
    (target / 'execution.json').write_text(json.dumps({'command': commands[language], 'os_exit': completed.returncode,
        'normalized_exit': code, 'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest()}, indent=2))
    return code, output


def model_frame():
    rng = np.random.default_rng(202610042)
    n = 240
    group = np.resize([1, 2, 3], n)
    x = rng.normal(size=n)
    return pd.DataFrame({'y': 1 + .3*x + .2*group + .12*group**2 + rng.normal(size=n),
                         'x': x, 'category': group, 'wb_cat0': rng.normal(size=n),
                         'time': np.arange(n)})


def model_step(name, frame, x, categorical=(), covariance='unadjusted'):
    params = {'model_type': 'ols', 'y': 'y', 'x': x, 'categorical_x': list(categorical),
              'covariance': covariance, 'weights': None, 'model_options': {}}
    sink = []
    kwargs = {'categorical_x': set(categorical), 'covariance': covariance, 'fitted_sink': sink.append}
    if covariance == 'hac':
        params.update(hac_lags=2, model_options={'time_order': 'time'})
        kwargs.update(hac_time_order='time', hac_lags=2)
    result, _ = runner.run_ols(frame, 'y', x, False, name, **kwargs)
    fitted = sink[0]
    coefficients = result['coefficients']
    expected = {'nobs': result['nobs'], 'coefficients': {k: v['estimate'] for k, v in coefficients.items()},
                'std_errors': {k: v['std_error'] for k, v in coefficients.items()},
                'statistics': {k: {'value': float(np.asarray(fitted.tvalues)[i]), 'p_value': float(np.asarray(fitted.pvalues)[i]),
                                  'df': float(fitted.df_resid), 'distribution': 't'}
                               for i, k in enumerate(coefficients)}}
    return ScriptStep(name, 'model', 'model.ols', params, ('source',), expected=expected)


@pytest.mark.parametrize('language', LANGUAGES)
def test_categorical_branch_does_not_mutate_continuous_branch(language):
    target = directory('branch-isolation', language)
    frame = model_frame()
    steps = (model_step('categorical', frame, ['x', 'category'], ['category']),
             model_step('continuous', frame, ['x', 'category']))
    plan = ScriptPlan('review', 'branch-isolation', (source(target, frame),), steps, '1.8.11', '1'*64)
    code, output = execute(target, plan, language)
    assert code == 0, output


@pytest.mark.parametrize('language', LANGUAGES)
def test_user_predictor_does_not_collide_with_export_internal_name(language):
    target = directory('internal-column', language)
    frame = model_frame()
    step = model_step('model', frame, ['wb_cat0', 'category'], ['category'])
    plan = ScriptPlan('review', 'internal-column', (source(target, frame),), (step,), '1.8.11', '2'*64)
    code, output = execute(target, plan, language)
    assert code == 0, output


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('time_kind', ('numeric-unit', 'iso-dates'))
def test_supported_hac_time_order_is_translated(language, time_kind):
    target = directory('hac-' + time_kind, language)
    frame = model_frame()
    if time_kind == 'iso-dates':
        frame['time'] = pd.date_range('2020-01-01', periods=len(frame), freq='D').astype(str)
    step = model_step('model', frame, ['x'], covariance='hac')
    plan = ScriptPlan('review', time_kind, (source(target, frame),), (step,), '1.8.11', '3'*64)
    code, output = execute(target, plan, language)
    assert code == 0, output


@pytest.mark.parametrize('language', LANGUAGES)
def test_numeric_category_names_keep_full_precision_identity(language):
    target = directory('numeric-category', language)
    frame = model_frame()
    frame['category'] = frame['category'].astype(float)
    step = model_step('model', frame, ['x', 'category'], ['category'])
    plan = ScriptPlan('review', 'numeric-category', (source(target, frame),), (step,), '1.8.11', '5'*64)
    code, output = execute(target, plan, language)
    assert code == 0, output


DATA_CASES = (
    ('aggregate-empty-group', 'aggregate', pd.DataFrame({'group': ['a', 'a', 'b', 'b'], 'x': [1., 2., None, None]}),
     {'group_by': ['group'], 'aggregations': [{'column': 'x', 'func': 'min', 'output': 'minimum'},
                                           {'column': 'x', 'func': 'max', 'output': 'maximum'}]}),
    ('string-mode', 'fill_missing', pd.DataFrame({'id': [1, 2, 3, 4], 'x': ['west', 'east', None, 'west']}),
     {'strategies': [{'column': 'x', 'strategy': 'mode'}]}),
    ('string-only-header', 'subset', pd.DataFrame({'x': ['west', 'east', 'south']}), {'columns': ['x']}),
    ('tsset-internal-column', 'tsset', pd.DataFrame({'time': ['2020-01-02', '2020-01-01'], '__wb_time': [100., 200.]}),
     {'time_column': 'time', 'frequency': 'D'}),
)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('case', DATA_CASES, ids=[item[0] for item in DATA_CASES])
def test_valid_data_operations_preserve_native_semantics(language, case):
    case_id, operation, frame, parameters = case
    target = directory(case_id, language)
    expected = get_data_operation(operation).run(frame, parameters)
    expected.to_csv(target / 'expected.csv', index=False)
    step = ScriptStep('result', 'data_operation', 'data.' + operation, parameters, ('source',),
                      expected={'nrows': len(expected), 'columns': list(expected.columns)})
    plan = ScriptPlan('review', case_id, (source(target, frame),), (step,), '1.8.11', '4'*64)
    tail = {'python': "data['result'].to_csv('actual.csv',index=False)",
            'r': 'write.csv(data[["result"]],"actual.csv",row.names=FALSE,na="")',
            'stata': 'frame wb1: export delimited using "actual.csv", replace'}[language]
    code, output = execute(target, plan, language, tail)
    assert code == 0, output
    actual = pd.read_csv(target / 'actual.csv')
    pd.testing.assert_frame_equal(actual, expected.reset_index(drop=True), check_dtype=False, check_names=False,
                                  check_categorical=False, rtol=1e-8, atol=1e-8)
