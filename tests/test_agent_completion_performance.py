"""Storage/CPU contracts: evidence never serializes or re-reads full observations."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest


def test_array_digest_is_versioned_and_binds_dtype_shape_and_order():
    from workbench.services.completion_products import array_fingerprint
    values = np.arange(24, dtype='<f8').reshape(6, 4)
    digest = array_fingerprint(values)
    assert digest == array_fingerprint(np.asfortranarray(values))
    assert digest != array_fingerprint(values.astype('<f4'))
    assert digest != array_fingerprint(values.reshape(4, 6))
    assert digest != array_fingerprint(values[::-1])
    header = {'version': 'numpy-bytes.v1', 'dtype': values.dtype.str, 'shape': list(values.shape)}
    h = hashlib.sha256(json.dumps(header, sort_keys=True, separators=(',', ':')).encode() + b'\0')
    h.update(memoryview(values).cast('B'))
    assert digest == h.hexdigest()


def test_source_binding_only_reads_registration_and_hashes_live_columns():
    from workbench.services.completion_products import source_binding
    record = {'artifact_id': 'data', 'sha256': 'a'*64, 'artifact_type': 'raw_data', 'path': 'input.csv'}
    class Pinned:
        def lmm_source_record(self, **kwargs):
            return record
        def read_lmm_analysis_source(self, **kwargs):
            pytest.fail('source must not be re-read or decoded for publication')
    frame = pd.DataFrame({'x': [1., 2.], 'label': ['a', 'b']})
    source = source_binding(Pinned(), frame, artifact_id='data')
    assert source['sha256'] == 'a'*64 and source['row_count'] == 2
    changed = frame.copy()
    changed.loc[0, 'x'] = 3
    assert source_binding(Pinned(), changed, artifact_id='data')['frame_fingerprint'] != source['frame_fingerprint']


def test_default_iv_check_does_not_invert_ar(monkeypatch):
    from tests.test_iv_diagnostics import _fitted
    from workbench.checks import build_context
    from workbench.checks.iv_checks import FIRST_STAGE_STRENGTH
    import workbench.checks.ar_confidence as ar
    monkeypatch.setattr(ar, 'robust_set', lambda *a, **k: pytest.fail('AR must be explicitly requested'))
    fitted, *_ = _fitted(2)
    context = build_context(fitted=fitted, model_id='iv', model_type='iv_2sls', kernel=None, nobs=800)
    value = FIRST_STAGE_STRENGTH.run(context, FIRST_STAGE_STRENGTH)
    assert value.evidence['anderson_rubin_95'] == {'kind': 'not_computed', 'reason': 'request_ar_confidence_explicitly'}


def test_million_row_sample_metadata_is_constant_size():
    from workbench.services.completion_products import sample_metadata
    value = sample_metadata(np.arange(1_000_000), 1_000_000)
    assert value['retained_count'] == 1_000_000 and value['missing_count'] == 0
    assert 'retained_positions' not in value
    assert len(json.dumps(value)) < 512
    assert value != sample_metadata(np.arange(1, 1_000_001), 1_000_001)


def test_panel_diagnostics_are_vectorized_and_do_not_change_fit_bits(tmp_path):
    from tests.test_agent_completion_panel import SOURCE
    from workbench.econometrics.runner import run_panel_ols
    from workbench.engine.panel_diagnostics import panel_evidence
    frame = pd.read_csv(SOURCE).sample(frac=1, random_state=9).reset_index(drop=True)
    primary, fitted = run_panel_ols(frame, y='y', x=['x1', 'x2'], entity='g', time='time', model_id='p')
    before = [np.asarray(x).tobytes() for x in (fitted.params, fitted.std_errors, fitted.tstats, fitted.pvalues)]
    result, positions, definition = panel_evidence(fitted, primary, frame, y='y', x=['x1', 'x2'], entity='g', time='time')
    assert isinstance(result['residuals'], np.ndarray)
    assert isinstance(positions, np.ndarray)
    assert result['residual_summary']['count'] == len(frame)
    assert 'groups' not in result
    assert before == [np.asarray(x).tobytes() for x in (fitted.params, fitted.std_errors, fitted.tstats, fitted.pvalues)]


def test_completion_fixtures_have_one_km_one_rmst_and_fit_storage_budget():
    from pathlib import Path
    root = Path(__file__).parent/'fixtures/agent_completion'
    files = [p for p in root.rglob('*') if p.is_file() and '__pycache__' not in str(p)]
    assert sum(p.stat().st_size for p in files) <= 1_000_000
    assert len(list(root.rglob('*kaplan_meier*.gz'))) == 1
    assert len(list(root.rglob('*rmst*.gz'))) == 1


def test_iv_diagnostics_reuses_already_computed_first_stage(monkeypatch):
    from tests.test_iv_diagnostics import _fitted
    from workbench.checks.iv_checks import first_stage_diagnostic
    import workbench.engine.iv_diagnostics as module
    fitted, _, _ = _fitted(2)
    original = first_stage_diagnostic(fitted)
    monkeypatch.setattr(module, 'first_stage_diagnostic', lambda *a: pytest.fail('first stage was already computed'))
    diag = module.build_iv_diagnostics(fitted, 1, 2, {'evidence': original})
    assert diag['weak_instruments']['per_endogenous'] == original['per_endogenous']


def test_frame_numeric_fingerprint_uses_actual_array_bytes():
    from workbench.services.completion_products import frame_fingerprint, array_fingerprint
    values = np.array([0., -0., 2.])
    frame = pd.DataFrame({'x': values})
    columns = [{'name': 'x', 'dtype': str(values.dtype), 'encoding': 'numpy-bytes.v1',
                'sha256': array_fingerprint(values)}]
    expected = hashlib.sha256(json.dumps({'version': 'dataframe-columns.v1', 'columns': columns,
        'rows': len(frame)}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert frame_fingerprint(frame) == expected


def test_legacy_direct_lmm_fit_without_index_still_has_public_result(tmp_path, monkeypatch):
    # This real legacy entry failed in 9 public-view tests in the host suite;
    # keep it in the standard group as well as in the family-specific suite.
    from tests.agent.test_lmm_public_result_view import _valid_run
    from workbench.agent.recipes.lmm_public_result_view import build_repeated_measures_recipe_from_run
    run = _valid_run(tmp_path, monkeypatch)
    result = build_repeated_measures_recipe_from_run(tmp_path, run.name)
    assert result['proposal']['operation'] == 'model.rerun'
