"""Owned AR buffers: exact regression of the public snapshot and bound service."""
import asyncio
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from workbench.checks import ar_confidence as ar, ar_verified as verified
from workbench.checks.ar_cancellation import cancellation_scope, current_check


CRITICAL = 5.991464547107979
# Recorded from c8bec46c, including every rational bound and input-digest byte.
POLYNOMIAL_SHA = {
    43: 'aad9cc84a85d45d572ddb80f2f18e89a6c3e8ce4d36f0389405525cea4f715f3',
    16389: 'ccd1fecb45366865518747fc5e2c6ff863ee9b528560b5691de0ac5a49bd7738',
}
PUBLIC_SHA = 'e8d461ef36ad9f06d8773213edba39aa730306553f684a66c88620954f71e989'
PUBLIC_DIAGNOSTIC_SHA = {
    False: 'd2a9832f4b411f2b5d74127123e76edc56ae9a1fd02189c6953c4bc97014e9b0',
    True: '04998824f23d10e90509ab193270ac01ec42395fde27609a5aab8259fbc84614',
}


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _case(rows=43):
    data = np.random.default_rng(918).integers(-16, 17, (rows, 6)).astype(float) / 8
    z = data[:, 4:]
    w = np.column_stack([np.ones(rows), data[:, 2]])
    x = (z[:, 0] + z[:, 1]/2 + data[:, 1])[:, None]
    y = 1.5*x[:, 0] + data[:, 0]
    return y, x, z, w


def _polynomial_record(result):
    p, d, evidence = result
    return {'numerator': [v.record() for v in p],
            'denominator': [v.record() for v in d], 'evidence': evidence}


def _owned(module, name):
    function = getattr(module, name, None)
    assert callable(function), f'explicit internal {name} entry is missing'
    return function


def _completed_owner(root, frame=None, *, source=None):
    from workbench.projects import create_project
    from workbench.orchestrator import run_workflow
    root.mkdir(parents=True, exist_ok=True)
    if source is None:
        source = root / 'iv.csv'
        frame.to_csv(source, index=False)
    project = create_project(root, 'owned-ar')
    outcome = run_workflow(project.root, [source], mode='auto', model_type='iv_2sls',
        y='y', x=['w'], iv_endog=['d'], iv_instruments=['z1', 'z2'], covariance='robust')
    assert outcome['status'] == 'completed', outcome
    run = project.root / 'runs' / outcome['run_id']
    path = run / 'processed/cleaned_dataset.parquet'
    binding = {'run_id': run.name, 'artifact_id': 'cleaned_dataset',
               'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return run, binding, pd.read_parquet(path)


def test_real_service_owned_path_never_stacks_the_full_observation_matrix(tmp_path, monkeypatch):
    from workbench.services.iv_ar import compute_ar
    y, x, z, w = _case(16389)
    frame = pd.DataFrame({'y': y, 'd': x[:, 0], 'w': w[:, 1], 'z1': z[:, 0], 'z2': z[:, 1]})
    run, binding, frame = _completed_owner(tmp_path / 'owner', frame)
    before = frame.copy(deep=True)
    stack = np.column_stack
    shapes = []

    def observe(columns):
        result = stack(columns)
        if sys._getframe(1).f_code.co_filename == verified.__file__:
            shapes.append(result.shape)
        return result

    monkeypatch.setattr(verified.np, 'column_stack', observe)
    result = compute_ar(run, 'iv_2sls_1', binding, frame)
    assert result['anderson_rubin_95']['computation']['path'] == 'verified_numpy'
    assert shapes and max(rows for rows, _ in shapes) <= 16384, shapes
    assert shapes == [(16384, 7), (5, 7)]
    pd.testing.assert_frame_equal(frame, before, check_exact=True)


def test_real_service_does_not_compute_unused_first_stage_diagnostic(tmp_path, monkeypatch):
    from workbench.checks import iv_checks
    from workbench.services.iv_ar import compute_ar
    y, x, z, w = _case()
    frame = pd.DataFrame({'y': y, 'd': x[:, 0], 'w': w[:, 1], 'z1': z[:, 0], 'z2': z[:, 1]})
    run, binding, frame = _completed_owner(tmp_path / 'region-only', frame)
    diagnostic = iv_checks.first_stage_diagnostic
    calls = []

    def observe(fitted):
        calls.append(1)
        return diagnostic(fitted)

    monkeypatch.setattr(iv_checks, 'first_stage_diagnostic', observe)
    result = compute_ar(run, 'iv_2sls_1', binding, frame)
    assert calls == [], 'AR-only service recomputed unused first-stage diagnostics'
    assert _sha(result['anderson_rubin_95']) == PUBLIC_SHA


@pytest.mark.parametrize('compute_ar', [False, True])
def test_public_diagnostic_keeps_its_original_call_and_complete_result(compute_ar, monkeypatch):
    from workbench.econometrics.runner import run_iv_2sls
    from workbench.checks.context import build_context
    from workbench.checks import iv_checks
    y, x, z, w = _case()
    frame = pd.DataFrame({'y': y, 'd': x[:, 0], 'w': w[:, 1], 'z1': z[:, 0], 'z2': z[:, 1]})
    _, fitted = run_iv_2sls(frame, y='y', exog=['w'], endog=['d'], instruments=['z1', 'z2'],
                          model_id='iv_2sls_1', covariance='robust')
    context = build_context(model_id='iv_2sls_1', model_type='iv_2sls', fitted=fitted, kernel=None, nobs=len(y))
    diagnostic = iv_checks.first_stage_diagnostic
    calls = []

    def observe(actual):
        calls.append(1)
        return diagnostic(actual)

    monkeypatch.setattr(iv_checks, 'first_stage_diagnostic', observe)
    spec = iv_checks.FIRST_STAGE_STRENGTH
    outcome = iv_checks.first_stage_strength(context, spec, compute_ar=compute_ar)
    assert calls == [1]
    assert _sha(spec.result(outcome)) == PUBLIC_DIAGNOSTIC_SHA[compute_ar]


@pytest.mark.parametrize('entry', ['robust_set', 'verified_set', 'polynomial_enclosures'])
def test_public_entries_keep_a_private_complete_snapshot(entry, monkeypatch):
    values = _case()
    enclose = verified.moment_enclosure
    observed = []

    def observe(data):
        assert data.shape == (43, 7) and data.flags.c_contiguous
        assert all(not np.shares_memory(data, value) for value in values)
        # An external writer after the public snapshot cannot change its proof.
        for value in values:
            value[...] = -999.
        observed.append(data.shape)
        return enclose(data)

    monkeypatch.setattr(verified, 'moment_enclosure', observe)
    if entry == 'robust_set':
        result = ar.robust_set(*values)
        assert _sha(result) == PUBLIC_SHA
    elif entry == 'verified_set':
        result = verified.verified_set(*values, CRITICAL)
        assert result['global_certification']['reduction']['input_sha256'] == '9a5bc5a31406460a2cd54b4e3bd466b0fdfff6c97b8fa67777c712a7a08e9933'
    else:
        assert _sha(_polynomial_record(verified.polynomial_enclosures(*values, CRITICAL))) == POLYNOMIAL_SHA[43]
    assert observed == [(43, 7)]


@pytest.mark.parametrize('rows', [43, 16389])
def test_owned_full_bounds_and_digest_match_the_recorded_original(rows):
    values = _case(rows)
    before = [value.tobytes() for value in values]
    owned = _owned(verified, '_polynomial_enclosures_owned')
    actual = _polynomial_record(owned(*values, CRITICAL))
    public = _polynomial_record(verified.polynomial_enclosures(*values, CRITICAL))
    assert _encoded(actual) == _encoded(public)
    assert _sha(actual) == POLYNOMIAL_SHA[rows]
    assert [value.tobytes() for value in values] == before


def test_owned_public_result_and_original_public_signatures_are_exact():
    owned = _owned(ar, '_robust_set_owned')
    result = owned(*_case())
    assert _encoded(result) == _encoded(ar.robust_set(*_case()))
    assert _sha(result) == PUBLIC_SHA
    for function, names in [(ar.robust_set, ['y', 'x', 'z', 'w', 'alpha']),
            (verified.verified_set, ['y', 'x', 'z', 'w', 'critical']),
            (verified.polynomial_enclosures, ['y', 'x', 'z', 'w', 'critical']),
            (verified.moment_enclosure, ['data'])]:
        assert list(inspect.signature(function).parameters) == names


def test_owned_near_boundary_uses_the_original_exact_fallback():
    owned = _owned(ar, '_robust_set_owned')
    x = np.array([[1.], [0.], [2.], [0.]])
    z = np.array([[1.], [-1.], [0.], [0.]])
    values = (2*x[:, 0], x, z, np.empty((4, 0)))
    before = [value.tobytes() for value in values]
    result = owned(*values)
    assert _encoded(result) == _encoded(ar.robust_set(*values))
    assert result['computation']['path'] == 'exact_fallback'
    assert result['reason'] == 'singular_covariance_on_real_line'
    assert [value.tobytes() for value in values] == before


def test_owned_entry_preserves_the_execution_owner_exception_and_scope():
    owned = _owned(ar, '_robust_set_owned')
    original = asyncio.CancelledError('existing AR execution owner')

    def owner():
        raise original

    with cancellation_scope(owner):
        before = current_check()
        with pytest.raises(asyncio.CancelledError) as caught:
            owned(*_case())
        assert caught.value is original and current_check() is before
    assert current_check() is None


@pytest.mark.parametrize('case,reason', [
    ('multiple', 'multiple_endogenous_regressors'),
    ('weighted', 'weighted_ar_not_validated'),
    ('clustered', 'unsupported_covariance_for_ar'),
])
def test_owned_check_keeps_the_original_eligibility_refusals(case, reason):
    from linearmodels.iv import IV2SLS
    from workbench.checks.context import build_context
    from workbench.checks.iv_checks import FIRST_STAGE_STRENGTH, first_stage_strength
    from workbench.checks import iv_checks
    y, x, z, w = _case()
    if case == 'multiple':
        x = np.column_stack([x, np.random.default_rng(2).normal(size=len(y))])
    weights = np.linspace(1., 2., len(y)) if case == 'weighted' else None
    fitted = IV2SLS(y, w, x, z, weights=weights).fit(cov_type='clustered' if case == 'clustered' else 'robust')
    context = build_context(model_id='iv_2sls_1', model_type='iv_2sls', fitted=fitted, kernel=None, nobs=len(y))
    owned = _owned(iv_checks, '_ar_region_owned')(fitted)
    public = first_stage_strength(context, FIRST_STAGE_STRENGTH, compute_ar=True)
    assert _encoded(owned) == _encoded(public.evidence['anderson_rubin_95'])
    assert owned == {'kind': 'unavailable', 'reason': reason}


def test_owned_unadjusted_fit_keeps_the_homoskedastic_path():
    from workbench.econometrics.runner import run_iv_2sls
    from workbench.checks.context import build_context
    from workbench.checks.iv_checks import FIRST_STAGE_STRENGTH, first_stage_strength
    from workbench.checks import iv_checks
    y, x, z, w = _case()
    frame = pd.DataFrame({'y': y, 'd': x[:, 0], 'w': w[:, 1], 'z1': z[:, 0], 'z2': z[:, 1]})
    _, fitted = run_iv_2sls(frame, y='y', exog=['w'], endog=['d'], instruments=['z1', 'z2'],
                          model_id='iv_2sls_1', covariance='unadjusted')
    context = build_context(model_id='iv_2sls_1', model_type='iv_2sls', fitted=fitted, kernel=None, nobs=len(y))
    owned = _owned(iv_checks, '_ar_region_owned')(fitted)
    public = first_stage_strength(context, FIRST_STAGE_STRENGTH, compute_ar=True)
    assert _encoded(owned) == _encoded(public.evidence['anderson_rubin_95'])
    assert owned['method'] == 'homoskedastic'


def _frozen_public():
    root = Path(__file__).resolve().parents[1]
    local = root / 'local/ar-verified-owned-buffers-20261030'
    manifest = json.loads((local / 'baseline.json').read_text())
    assert manifest['baseline'] == 'c8bec46c1d0fa769ff4d9a1de2aad1da6f5a8346'
    package_name = 'workbench._ar_owned_frozen_reference'
    package = ModuleType(package_name)
    package.__path__ = [str(Path(verified.__file__).parent)]
    sys.modules[package_name] = package
    for name in ('ar_verified', 'ar_confidence'):
        path = local / f'baseline_{name}.py'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest['files'][f'backend/workbench/checks/{name}.py']['sha256']
        spec = importlib.util.spec_from_file_location(f'{package_name}.{name}', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(os.environ.get('AR_OWNED_ORIGINAL1M_REQUIRED') != '1', reason='explicit original-1M functional lane')
def test_original1m_completed_owner_service_matches_frozen_public(tmp_path, monkeypatch, record_property):
    """Real owner/source admission and default fit; no timing or memory claim."""
    from workbench.services import iv_ar
    from workbench.services.completion_products import array_fingerprint
    from workbench.checks import iv_checks
    from workbench.checks.iv_checks import _arrays
    root = Path(__file__).resolve().parents[1]
    source = root / 'local/perf-inputs/iv/iv.csv'
    stat = source.stat()
    source_identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    with source.open('rb') as stream:
        source_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert source_sha == '4f18e7f8f28c324e0383952e1a1d4e8b6402dcabb2dbcf8f10acfb758981c6ef'
    frozen = _frozen_public()
    run, binding, frame = _completed_owner(tmp_path / 'original-owner', source=source)
    assert len(frame) == 1_000_000
    completion = json.loads((run / 'model_results/iv_2sls_1.completion.json').read_text())
    assert completion['diagnostics']['iv']['weak_instruments']['anderson_rubin_95']['kind'] == 'not_computed'
    original_files = {path: path.read_bytes() for path in [run / 'run_manifest.json',
        run / 'model_results/iv_2sls_1.json', run / 'model_results/iv_2sls_1.completion.json', run / 'iv_diagnostics.json']}
    checked = iv_ar._ar_region_owned
    observed = []
    diagnostic_calls = []
    diagnostic = iv_checks.first_stage_diagnostic

    def compare(fitted):
        arrays = _arrays(fitted)
        values = tuple(arrays[key] for key in ('y', 'x', 'z', 'w'))
        before = [array_fingerprint(value) for value in values]
        expected = frozen.robust_set(*values)
        result = checked(fitted)
        assert _encoded(result) == _encoded(expected)
        assert [array_fingerprint(value) for value in values] == before
        observed.append(expected)
        return result

    def observe_diagnostic(fitted):
        diagnostic_calls.append(1)
        return diagnostic(fitted)

    shapes = []
    stack = np.column_stack

    def observe(columns):
        result = stack(columns)
        if sys._getframe(1).f_code.co_filename == verified.__file__:
            shapes.append(result.shape)
        return result

    monkeypatch.setattr(iv_ar, '_ar_region_owned', compare)
    monkeypatch.setattr(iv_checks, 'first_stage_diagnostic', observe_diagnostic)
    monkeypatch.setattr(verified.np, 'column_stack', observe)
    result = iv_ar.compute_ar(run, 'iv_2sls_1', binding, frame)
    assert len(observed) == 1
    assert diagnostic_calls == []
    expected, = observed
    assert _encoded(result['anderson_rubin_95']) == _encoded(expected)
    assert expected['computation']['path'] == 'verified_numpy'
    assert shapes == [(16384, 7)] * 61 + [(576, 7)]
    assert result['point_estimation_fingerprint'] == completion['point_estimation_fingerprint']
    for path, raw in original_files.items():
        assert path.read_bytes() == raw
    with source.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == source_sha
    stat = source.stat()
    assert (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) == source_identity
    record_property('original_input_sha256', source_sha)
    record_property('original_input_identity_unchanged', source_identity)
    record_property('frozen_public_and_owned_result_sha256', _sha(expected))
    record_property('moment_input_sha256', expected['global_certification']['reduction']['input_sha256'])
    record_property('owned_blocks', len(shapes))
    record_property('complete_bounds_and_certificate_exact', True)
    record_property('first_stage_diagnostic_calls_in_service', len(diagnostic_calls))
