"""Sample candidate bytes, dispatch and errors; no performance acceptance."""
from __future__ import annotations

import gc
import hashlib
import json
import os
from pathlib import Path
import random
import sys
from types import SimpleNamespace

import pytest

from workbench import native_canonical as bridge
from workbench.analysis_loop import fingerprints

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / 'local/native-sample-fingerprint-20261029'


@pytest.mark.parametrize('module,name', [(bridge, 'encode_analysis_sample_v1'),
                                      (fingerprints, 'analysis_sample_fingerprint_native')])
def test_sample_candidate_exposes_the_existing_explicit_entrypoints(module, name):
    assert callable(getattr(module, name, None)), 'explicit sample candidate entrypoint missing'


@pytest.fixture(scope='module')
def kernel():
    binary = AREA / 'candidate-runtime/msd-v2' / ('_canonical_numbers' + bridge.EXT_SUFFIX)
    if not binary.is_file() and os.environ.get('NATIVE_SAMPLE_REQUIRED') != '1':
        pytest.skip('build the isolated sample candidate first')
    assert binary.is_file(), 'build native/canonical_numbers/build.py --output-dir local/native-sample-fingerprint-20261029/candidate-runtime/msd-v2'
    module = bridge._load_extension(binary)
    assert callable(getattr(module, 'encode_analysis_sample_v1', None)), 'native sample byte encoder missing'
    return module


def wire(row_set, row_order):
    return json.dumps({'fingerprint_type': 'analysis_sample_v1',
        'value': {'row_set': sorted(row_set), 'row_order': row_order}},
        ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def test_native_sample_declares_iterative_msd_radix(kernel):
    # Version/selection audit only; byte differentials below prove semantics.
    assert getattr(kernel, 'ANALYSIS_SAMPLE_SORT_ALGORITHM', None) == 'iterative-msd-radix'


@pytest.mark.parametrize('shape', ['common-prefix', 'prefix-chain', 'identical', 'extreme-length'])
def test_radix_preserves_terminators_duplicates_and_long_decimal_prefixes(kernel, shape):
    if shape == 'common-prefix':
        prefix = '0' * 8192
        rows = [prefix + suffix for suffix in ('9', '00', '', '1', '0', '10', '', '000', '90')]
    elif shape == 'prefix-chain':
        rows = ['0' * length for length in range(2049, 0, -1)]
    elif shape == 'identical':
        rows = ['7' * 65537] * 17
    else:
        prefix = '9' * 100001
        rows = [prefix + '0', '0', prefix, prefix[:-1], '00', prefix + '0']
    order = tuple(reversed(rows))
    before = tuple(rows)
    actual = kernel.encode_analysis_sample_v1(rows, order)
    assert actual == wire(rows, order)
    assert json.loads(actual)['value'] == {'row_set': sorted(rows), 'row_order': list(order)}
    assert tuple(rows) == before


@pytest.mark.parametrize('seed', [912, 11342])
def test_radix_matches_lexical_sort_for_random_digit_lengths_and_duplicates(kernel, seed):
    rng = random.Random(seed)
    rows = ['0' * rng.randrange(20) + ''.join(rng.choices('0123456789', k=rng.randrange(1, 257)))
            for _ in range(2049)]
    rows.extend(rows[::7])
    rng.shuffle(rows)
    order = rows[::3] + rows[1::3]
    assert kernel.encode_analysis_sample_v1(tuple(rows), order) == wire(rows, order)


@pytest.mark.parametrize('row_set,row_order', [
    ([], []), ((), ()), (['0'], ('0',)),
    (['2', '10', '001', '0', '2'], ['10', '2', '10', '0']),
    (('000', '00', '0', '000'), ('0', '000', '00')),
    (['1'], ['2', '3']),
    (['0' * 2048 + '1', '9' * 5000, '01'], ['9' * 5000, '01']),
])
def test_native_sample_bytes_preserve_sort_order_duplicates_and_leading_zeroes(kernel, row_set, row_order):
    original_set, original_order = tuple(row_set), tuple(row_order)
    actual = kernel.encode_analysis_sample_v1(row_set, row_order)
    assert type(actual) is bytes and actual == wire(row_set, row_order)
    assert tuple(row_set) == original_set and tuple(row_order) == original_order
    assert json.loads(actual)['value']['row_order'] == list(row_order)
    assert not gc.is_tracked(actual)


def test_alias_and_many_prefixes_keep_original_inputs_and_references(kernel):
    rng = random.Random(20261029)
    rows = [str(rng.randrange(300)).zfill(rng.randrange(1, 8)) for _ in range(513)]
    before = tuple(rows)
    counts = [sys.getrefcount(item) for item in rows]
    expected = wire(rows, rows)
    for _ in range(20):
        assert kernel.encode_analysis_sample_v1(rows, rows) == expected
    assert tuple(rows) == before
    assert [sys.getrefcount(item) for item in rows] == counts


class StringSubclass(str):
    pass


class ListSubclass(list):
    pass


@pytest.mark.parametrize('row_set,row_order', [
    ({'1'}, ['1']), (ListSubclass(['1']), ['1']), (['1'], ListSubclass(['1'])),
    ([StringSubclass('1')], ['1']), ([''], ['1']), (['1'], ['']),
    (['١'], ['1']), (['1'], ['²']), (['a'], ['1']), (['1'], ['"']),
    ([1, '2'], ['1']), (['1'], [None]),
])
def test_other_shapes_return_none_then_keep_existing_python_semantics(kernel, monkeypatch, row_set, row_order):
    assert kernel.encode_analysis_sample_v1(row_set, row_order) is None
    monkeypatch.setattr(bridge, '_load', lambda: (kernel, 'native', 'extension_loaded'))
    assert fingerprints.analysis_sample_fingerprint_native(row_set, row_order) == fingerprints.analysis_sample_fingerprint(row_set, row_order)


def test_unsupported_iterator_is_not_consumed_by_the_native_probe(kernel, monkeypatch):
    rows = iter(['2', '1'])
    assert kernel.encode_analysis_sample_v1(rows, ['1', '2']) is None
    assert next(rows) == '2'
    monkeypatch.setattr(bridge, '_load', lambda: (kernel, 'native', 'extension_loaded'))
    assert fingerprints.analysis_sample_fingerprint_native(iter(['2', '1']), ['1', '2']) == fingerprints.analysis_sample_fingerprint(iter(['2', '1']), ['1', '2'])


def test_unsupported_inputs_preserve_the_original_exception(kernel, monkeypatch):
    original = RuntimeError('owner iterator failed')
    class Broken:
        def __iter__(self):
            raise original
    monkeypatch.setattr(bridge, '_load', lambda: (kernel, 'native', 'extension_loaded'))
    with pytest.raises(RuntimeError) as caught:
        fingerprints.analysis_sample_fingerprint_native(Broken(), ['1'])
    assert caught.value is original
    for function in (fingerprints.analysis_sample_fingerprint, fingerprints.analysis_sample_fingerprint_native):
        with pytest.raises(ValueError, match='NaN or Infinity'):
            function(['1'], [float('nan')])


def test_explicit_small_sample_uses_native_without_borrowing_the_numeric_cutover(kernel, monkeypatch):
    calls = []
    def encode(row_set, row_order):
        calls.append((row_set, row_order))
        return kernel.encode_analysis_sample_v1(row_set, row_order)
    fields = {name: getattr(kernel, name) for name in ('ANALYSIS_SAMPLE_ABI_VERSION', 'ANALYSIS_SAMPLE_SOURCE_SHA256')}
    monkeypatch.setattr(bridge, '_load', lambda: (SimpleNamespace(**fields, encode_analysis_sample_v1=encode), 'native', 'extension_loaded'))
    rows = ['2', '10', '001']
    assert fingerprints.analysis_sample_fingerprint_native(rows, rows) == hashlib.sha256(wire(rows, rows)).hexdigest()
    assert len(calls) == 1 and calls[0][0] is rows and calls[0][1] is rows


def test_small_default_sample_does_not_probe_the_candidate(monkeypatch):
    def forbidden(*args):
        pytest.fail('small samples must not load the sample candidate')
    monkeypatch.setattr(bridge, '_load', forbidden)
    rows = ['2', '10', '001']
    assert fingerprints.analysis_sample_fingerprint(rows, rows) == hashlib.sha256(wire(rows, rows)).hexdigest()


def test_large_default_sample_dispatches_to_the_existing_native_entrypoint(monkeypatch):
    rows = ['1'] * 1_000_000
    called = []
    def native(row_set, row_order):
        called.append((row_set, row_order))
        return 'native-dispatch-proof'
    monkeypatch.setattr(fingerprints, 'analysis_sample_fingerprint_native', native)
    assert fingerprints.analysis_sample_fingerprint(rows, rows) == 'native-dispatch-proof'
    assert len(called) == 1 and called[0][0] is rows and called[0][1] is rows


@pytest.mark.parametrize('size,selected', [(999_999, 'reference'), (1_000_000, 'native'), (1_000_001, 'native')])
def test_sample_cutoff_counts_members_without_restricting_order_length(monkeypatch, size, selected):
    assert callable(getattr(fingerprints, '_analysis_sample_fingerprint_reference', None))
    rows, order = ['1'] * size, ()
    calls = []
    def answer(name):
        def compute(row_set, row_order):
            calls.append((name, row_set, row_order))
            return name
        return compute
    monkeypatch.setattr(fingerprints, '_analysis_sample_fingerprint_reference', answer('reference'))
    monkeypatch.setattr(fingerprints, 'analysis_sample_fingerprint_native', answer('native'))
    assert fingerprints.analysis_sample_fingerprint(rows, order) == selected
    assert len(calls) == 1 and calls[0][1] is rows and calls[0][2] is order


@pytest.mark.parametrize('row_set,row_order', [
    (ListSubclass(['2', '1']), ['1', '2']), (['2', '1'], ListSubclass(['1', '2'])),
    ({'1', '2'}, ['1', '2']),
])
def test_other_outer_shapes_keep_reference_without_loading_a_kernel(monkeypatch, row_set, row_order):
    monkeypatch.setattr(fingerprints, '_SAMPLE_NATIVE_MIN_ROWS', 1)
    expected = fingerprints._analysis_sample_fingerprint_reference(row_set, row_order)
    def forbidden():
        pytest.fail('unsupported outer shapes must not load the native candidate')
    monkeypatch.setattr(bridge, '_load', forbidden)
    assert fingerprints.analysis_sample_fingerprint(row_set, row_order) == expected


@pytest.mark.parametrize('missing', [True, False], ids=['missing-so', 'unsupported-inner-shape'])
def test_large_default_reference_fallback_occurs_once_without_redispatch(kernel, monkeypatch, missing):
    rows = ['r1'] * 1_000_000
    loads, references = [], []
    monkeypatch.setattr(bridge, '_load', lambda: loads.append(True) or (None if missing else kernel, 'reference' if missing else 'native', 'unit-fixture'))
    def reference(row_set, row_order):
        references.append((row_set, row_order))
        return 'single-reference-result'
    monkeypatch.setattr(fingerprints, '_analysis_sample_fingerprint_reference', reference)
    assert fingerprints.analysis_sample_fingerprint(rows, rows) == 'single-reference-result'
    assert loads == [True] and len(references) == 1
    assert references[0][0] is rows and references[0][1] is rows


@pytest.mark.parametrize('failure', ['load', 'abi', 'source', 'calculation'])
def test_large_default_keeps_present_kernel_errors_visible(kernel, monkeypatch, failure):
    rows = ['1'] * 1_000_000
    fields = {name: getattr(kernel, name) for name in ('ANALYSIS_SAMPLE_ABI_VERSION', 'ANALYSIS_SAMPLE_SOURCE_SHA256', 'encode_analysis_sample_v1')}
    original = ImportError('present sample load failed') if failure == 'load' else ArithmeticError('sample calculation failed')
    def broken(*args):
        raise original
    if failure == 'load':
        monkeypatch.setattr(bridge, '_load', broken)
        error, message = ImportError, 'present sample load failed'
    else:
        if failure == 'abi':
            fields['ANALYSIS_SAMPLE_ABI_VERSION'] = True
            error, message = RuntimeError, 'ABI mismatch'
        elif failure == 'source':
            fields['ANALYSIS_SAMPLE_SOURCE_SHA256'] = 'stale'
            error, message = RuntimeError, 'source digest mismatch'
        else:
            fields['encode_analysis_sample_v1'] = broken
            error, message = ArithmeticError, 'sample calculation failed'
        monkeypatch.setattr(bridge, '_load', lambda: (SimpleNamespace(**fields), 'native', 'extension_loaded'))
    def forbidden(*args):
        pytest.fail('a present invalid kernel must not enter reference fallback')
    monkeypatch.setattr(fingerprints, '_analysis_sample_fingerprint_reference', forbidden)
    with pytest.raises(error, match=message) as caught:
        fingerprints.analysis_sample_fingerprint(rows, rows)
    if failure in {'load', 'calculation'}:
        assert caught.value is original


def test_missing_optional_binary_keeps_the_explicit_python_reference(monkeypatch):
    monkeypatch.setattr(bridge, '_load', lambda: (None, 'reference', 'extension_not_built'))
    rows = ['2', '10']
    assert fingerprints.analysis_sample_fingerprint_native(rows, rows) == fingerprints.analysis_sample_fingerprint(rows, rows)


@pytest.mark.parametrize('field,value', [('ANALYSIS_SAMPLE_ABI_VERSION', True),
    ('ANALYSIS_SAMPLE_ABI_VERSION', 2), ('ANALYSIS_SAMPLE_SOURCE_SHA256', 'stale'),
    ('encode_analysis_sample_v1', None)])
def test_sample_abi_source_and_entrypoint_errors_do_not_fall_back(kernel, monkeypatch, field, value):
    fields = {name: getattr(kernel, name) for name in ('ANALYSIS_SAMPLE_ABI_VERSION', 'ANALYSIS_SAMPLE_SOURCE_SHA256', 'encode_analysis_sample_v1')}
    fields[field] = value
    monkeypatch.setattr(bridge, '_load', lambda: (SimpleNamespace(**fields), 'native', 'extension_loaded'))
    with pytest.raises(RuntimeError, match='native canonical sample'):
        fingerprints.analysis_sample_fingerprint_native(['1'], ['1'])


def test_old_present_kernel_or_runtime_errors_are_not_missing_builds(kernel, monkeypatch):
    monkeypatch.setattr(bridge, '_load', lambda: (SimpleNamespace(ABI_VERSION=1), 'native', 'extension_loaded'))
    with pytest.raises(RuntimeError, match='native canonical sample'):
        fingerprints.analysis_sample_fingerprint_native(['1'], ['1'])
    original = ArithmeticError('native sample computation failed')
    def broken(*args):
        raise original
    fields = {name: getattr(kernel, name) for name in ('ANALYSIS_SAMPLE_ABI_VERSION', 'ANALYSIS_SAMPLE_SOURCE_SHA256')}
    monkeypatch.setattr(bridge, '_load', lambda: (SimpleNamespace(**fields, encode_analysis_sample_v1=broken), 'native', 'extension_loaded'))
    with pytest.raises(ArithmeticError) as caught:
        fingerprints.analysis_sample_fingerprint_native(['1'], ['1'])
    assert caught.value is original


@pytest.mark.parametrize('invalid_result', ['bytes required', bytearray(b'not immutable bytes')])
def test_invalid_sample_output_is_not_hashed_or_replaced(kernel, monkeypatch, invalid_result):
    fields = {name: getattr(kernel, name) for name in ('ANALYSIS_SAMPLE_ABI_VERSION', 'ANALYSIS_SAMPLE_SOURCE_SHA256')}
    monkeypatch.setattr(bridge, '_load', lambda: (SimpleNamespace(**fields,
        encode_analysis_sample_v1=lambda *args: invalid_result), 'native', 'extension_loaded'))
    with pytest.raises(RuntimeError, match='invalid byte result'):
        fingerprints.analysis_sample_fingerprint_native(['1'], ['1'])


def test_original_1m_public_run_ols_arguments_match_native_bytes(monkeypatch, tmp_path, record_property):
    if os.environ.get('NATIVE_SAMPLE_ORIGINAL_1M') != '1':
        pytest.skip('explicit original-input functional check; no clocks or performance claim')
    from workbench.cleaning import clean_frame
    from workbench.config import WorkbenchConfig
    from workbench.econometrics.runner import run_ols
    from workbench.ingestion import read_frame_bounded
    from workbench.metadata import infer_schema
    from workbench.orchestrator._column_checks import _detect_categorical_x_vars

    module, _, reason = bridge._load()
    if module is None:
        if os.environ.get('NATIVE_SAMPLE_REQUIRED') != '1':
            pytest.skip(f'ordinary optional native build unavailable: {reason}')
        pytest.fail('ordinary native build required for default-path functional proof')
    original_encoder = module.encode_analysis_sample_v1
    native_calls = []
    def encode(row_set, row_order):
        encoded = original_encoder(row_set, row_order)
        native_calls.append((row_set, row_order, encoded))
        return encoded
    monkeypatch.setattr(module, 'encode_analysis_sample_v1', encode)

    manifest = json.loads((ROOT / 'local/perf-inputs/ols/source.json').read_text())
    source = Path(manifest['source'])
    before = source.stat()
    with source.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == manifest['sha256'] == 'd7b25e65fa1875e205a31354feba22f5a9988a2647fb20fd232825ce2e9e595d'
    raw, truncated = read_frame_bounded(source, max_rows=WorkbenchConfig().max_rows)
    assert not truncated and len(raw) == 1_000_000
    schema = infer_schema('dataset_1', {source.name: raw}, tmp_path)
    frame, _ = clean_frame(raw, list(schema.time_candidates))
    y, x = manifest['kwargs']['y'], manifest['kwargs']['x']
    captured = {}
    def observe(actual_frame, event, value):
        if actual_frame.f_code is fingerprints.analysis_sample_fingerprint.__code__:
            if event == 'call':
                assert not captured
                captured['row_set'] = actual_frame.f_locals['row_set']
                captured['row_order'] = actual_frame.f_locals['row_order']
            elif event == 'return':
                captured['fingerprint'] = value
    assert sys.getprofile() is None
    sys.setprofile(observe)
    try:
        _, fitted = run_ols(frame, y=y, x=x, robust=True, model_id='ols_1',
            categorical_x=_detect_categorical_x_vars(frame, x), covariance='robust', covariance_explicit=False,
            dataset_snapshot={'upload_sha256': manifest['sha256'], 'model_input_artifact': 'cleaned_dataset'},
            row_ids=[str(value) for value in frame.index])
    finally:
        sys.setprofile(None)
    del fitted
    rows, order = captured['row_set'], captured['row_order']
    assert rows is order and len(rows) == 1_000_000
    assert len(native_calls) == 1
    native_set, native_order, encoded = native_calls[0]
    assert native_set is rows and native_order is order
    assert encoded == wire(rows, order)
    assert hashlib.sha256(encoded).hexdigest() == captured['fingerprint'] == '349201f22eecd0ad8c56340812cb76aaf3928ff096161df163bf8dfe0af19e1f'
    after = source.stat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    record_property('original_csv_sha256', manifest['sha256'])
    record_property('sample_wire_sha256', captured['fingerprint'])
    record_property('default_native_call_count', len(native_calls))
    record_property('sample_source_sha256', module.ANALYSIS_SAMPLE_SOURCE_SHA256)
    record_property('sample_candidate_binary_sha256', hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())
