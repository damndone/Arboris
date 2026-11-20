"""RangeIndex preview alignment keeps the original string-key contract."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from workbench import visualization as plots


ROOT = Path(__file__).resolve().parents[1]


def _reference_align(frame, model_result, n):
    sample = model_result.get('analysis_sample')
    row_order = sample.get('row_order') if isinstance(sample, dict) else None
    if isinstance(row_order, list) and len(row_order) >= n:
        positions = {str(value): position for position, value in enumerate(frame.index)}
        selected = [positions.get(str(value)) for value in row_order[:n]]
        if all(position is not None for position in selected):
            return frame.iloc[[int(position) for position in selected]]
    return frame.iloc[:n]


def test_real_range_index_alignment_does_not_enumerate_the_whole_index(monkeypatch):
    frame = pd.DataFrame({'x': range(100)}, index=pd.RangeIndex(-1000, -800, 2))
    result = {'analysis_sample': {'row_order': ['-990', '-1000', '-980']}}
    expected = _reference_align(frame, result, 3)
    def forbidden(index):
        raise AssertionError('preview alignment enumerated the complete RangeIndex')
    monkeypatch.setattr(pd.RangeIndex, '__iter__', forbidden)
    pd.testing.assert_frame_equal(plots._align_model_preview_frame(frame, result, 3), expected, check_exact=True)


@pytest.mark.parametrize('index,order,n', [
    (pd.RangeIndex(8), ['4', 1, '0', '4'], 4),
    (pd.RangeIndex(-8, 8, 2), ['-4', '6', '-8'], 3),
    (pd.RangeIndex(10, -10, -3), ['4', '10', '-8'], 3),
    (pd.RangeIndex(8), ['3', '01'], 2),
    (pd.RangeIndex(8), ['3', '+1'], 2),
    (pd.RangeIndex(8), ['3', '1.0'], 2),
    (pd.RangeIndex(8), ['3', 1.0], 2),
    (pd.RangeIndex(8), ['3', '-0'], 2),
    (pd.RangeIndex(8), ['3', '100'], 2),
    (pd.RangeIndex(8), ['3'], 2),
    (pd.RangeIndex(8), ('3', '1'), 2),
    (pd.RangeIndex(8), ['3', '1'], 0),
    (pd.Index([1, '1', 2, 2, 'x']), [1, '2', 1], 3),
])
def test_alignment_matches_reference_for_requested_order_and_whole_batch_fallback(index, order, n):
    frame = pd.DataFrame({'x': range(len(index))}, index=index)
    result = {'analysis_sample': {'row_order': order}}
    pd.testing.assert_frame_equal(plots._align_model_preview_frame(frame, result, n),
        _reference_align(frame, result, n), check_exact=True)


def test_a_later_string_error_is_not_hidden_by_an_earlier_missing_id():
    original = RuntimeError('row identity could not be rendered')
    class BrokenIdentity:
        def __str__(self):
            raise original
    frame = pd.DataFrame({'x': range(4)})
    result = {'analysis_sample': {'row_order': ['missing', BrokenIdentity()]}}
    for align in (_reference_align, plots._align_model_preview_frame):
        with pytest.raises(RuntimeError) as caught:
            align(frame, result, 2)
        assert caught.value is original


def test_range_index_subclass_keeps_the_general_string_key_path():
    class ReversedLabels(pd.RangeIndex):
        def __iter__(self):
            return iter(reversed(range(self.start, self.stop, self.step)))
    index = ReversedLabels(0, 5)
    frame = pd.DataFrame({'x': range(5)}, index=index)
    assert type(frame.index) is ReversedLabels
    result = {'analysis_sample': {'row_order': ['0', '3']}}
    pd.testing.assert_frame_equal(plots._align_model_preview_frame(frame, result, 2),
        _reference_align(frame, result, 2), check_exact=True)


def test_original_1m_run_ols_preview_data_and_png_match_reference(tmp_path, monkeypatch, record_property):
    if os.environ.get('PLOT_ALIGNMENT_ORIGINAL_1M') != '1':
        pytest.skip('explicit original-input functional comparison; no timing or performance claim')
    from workbench.cleaning import clean_frame
    from workbench.config import WorkbenchConfig
    from workbench.econometrics.runner import run_ols
    from workbench.ingestion import read_frame_bounded
    from workbench.metadata import infer_schema
    from workbench.orchestrator._column_checks import _detect_categorical_x_vars
    from workbench.projects import create_project, create_run

    manifest = json.loads((ROOT/'local/perf-inputs/ols/source.json').read_text())
    source = Path(manifest['source'])
    before = source.stat()
    assert manifest['sha256'] == 'd7b25e65fa1875e205a31354feba22f5a9988a2647fb20fd232825ce2e9e595d'
    registered = manifest['source_stat']
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (
        registered['inode'], registered['size'], registered['mtime_ns'])
    raw, truncated = read_frame_bounded(source, max_rows=WorkbenchConfig().max_rows)
    assert not truncated and len(raw) == 1_000_000
    schema = infer_schema('dataset_1', {source.name: raw}, tmp_path)
    frame, _ = clean_frame(raw, list(schema.time_candidates))
    assert type(frame.index) is pd.RangeIndex
    y, x = manifest['kwargs']['y'], manifest['kwargs']['x']
    result, fitted = run_ols(frame, y=y, x=x, robust=True, model_id='ols_1',
        categorical_x=_detect_categorical_x_vars(frame, x), covariance='robust', covariance_explicit=False,
        dataset_snapshot={'upload_sha256': manifest['sha256'], 'model_input_artifact': 'cleaned_dataset'},
        row_ids=[str(value) for value in frame.index])
    del fitted
    residuals, total = plots._model_diagnostic_sample(result, 'residuals')
    fitted_values, _ = plots._model_diagnostic_sample(result, 'fitted_values')
    n = min(len(residuals), len(fitted_values), len(frame))
    assert n == 500 and total == 1_000_000
    assert len(result['analysis_sample']['row_order']) == 1_000_000
    producer_bytes = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    producer_sha = hashlib.sha256(producer_bytes).hexdigest()
    del producer_bytes
    actual_align = plots._align_model_preview_frame
    reference = _reference_align(frame, result, n)
    pd.testing.assert_frame_equal(actual_align(frame, result, n), reference, check_exact=True)
    observed = []
    save = plots._save_predictor_diagnostic
    def observe(plot_frame, predictor, y_column, *args, **kwargs):
        observed.append((predictor, y_column, plot_frame.copy(deep=True), kwargs['analysis_rows']))
        return save(plot_frame, predictor, y_column, *args, **kwargs)
    monkeypatch.setattr(plots, '_save_predictor_diagnostic', observe)
    project = create_project(tmp_path, 'plot-alignment')
    outputs = []
    for align in (_reference_align, actual_align):
        run = create_run(project.root, mode='auto')
        figures_dir = run.root/'figures'
        figures = {}
        with monkeypatch.context() as selection:
            selection.setattr(plots, '_align_model_preview_frame', align)
            plots._plot_predictor_diagnostics(frame, x, [('ols_1', result)], figures_dir, run.root, figures)
        outputs.append({key: (run.root/path).read_bytes() for key, path in figures.items()})
    assert len(outputs[0]) == len(outputs[1]) == 2*len(x) == 8
    assert outputs[0] == outputs[1]
    assert len(observed) == 16
    for left, right in zip(observed[:8], observed[8:], strict=True):
        assert left[:2] == right[:2] and left[3] == right[3] == total
        assert len(left[2]) == len(right[2]) == n
        pd.testing.assert_frame_equal(left[2], right[2], check_exact=True)
    assert hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest() == producer_sha
    after = source.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    record_property('registered_original_csv_sha256', manifest['sha256'])
    record_property('producer_result_sha256', producer_sha)
    record_property('actual_alignment_n', n)
    record_property('analysis_rows', total)
    record_property('identical_png_sha256', json.dumps({key: hashlib.sha256(value).hexdigest() for key, value in outputs[1].items()}, sort_keys=True))
