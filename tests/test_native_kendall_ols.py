"""Opt-in exact differential on the registered, shared 1M OLS input; no copying.

NATIVE_KENDALL_OLS_REQUIRED=1 NATIVE_KENDALL_REQUIRED=1 \
PYTHONPATH=local/native-kendall .venv/bin/python -m pytest \
    tests/test_native_kendall_ols.py -q
"""
import hashlib
from itertools import combinations
import json
import os
from pathlib import Path
import struct

import pandas as pd
import pytest
from scipy import stats


COLUMNS = ['wage', 'education', 'experience', 'female', 'hours']


@pytest.fixture(scope='module')
def actual_ols():
    if os.environ.get('NATIVE_KENDALL_OLS_REQUIRED') != '1':
        pytest.skip('requires the explicitly selected registered 1M OLS input')
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / 'local/perf-inputs/ols/source.json'
    assert manifest_path.is_file(), 'registered OLS input is required; do not generate it here'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['sha256'] == 'd7b25e65fa1875e205a31354feba22f5a9988a2647fb20fd232825ce2e9e595d'
    source = Path(manifest['source'])
    with source.open('rb') as handle:
        assert hashlib.file_digest(handle, 'sha256').hexdigest() == manifest['sha256']
    identity = source.stat()
    frame = pd.read_csv(source, usecols=COLUMNS, float_precision='round_trip')
    after = source.stat()
    assert (identity.st_ino, identity.st_size, identity.st_mtime_ns) == (
        after.st_ino, after.st_size, after.st_mtime_ns)
    assert len(frame) == manifest['rows'] == 1_000_000
    assert all(frame[name].dtype.itemsize == 8 for name in COLUMNS)
    assert frame['education'].dtype.kind == frame['experience'].dtype.kind == frame['female'].dtype.kind == 'i'
    return frame


@pytest.mark.parametrize('left,right', list(combinations(COLUMNS, 2)))
def test_real_ols_float_integer_pairs_use_native_with_identical_tau_p(actual_ols, left, right):
    from workbench import native_kendall
    x, y = actual_ols[left].to_numpy(copy=False), actual_ols[right].to_numpy(copy=False)
    result = native_kendall.evaluate(x, y)
    expected = stats.kendalltau(x, y)
    assert result.engine == 'native-counts'
    for name in ('statistic', 'pvalue'):
        assert struct.pack('!d', getattr(result, name)) == struct.pack('!d', getattr(expected, name))
