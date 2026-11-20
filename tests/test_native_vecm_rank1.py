import ctypes
from pathlib import Path
import shutil

import numpy as np
import pytest

from workbench.native_build import artifact_names, default_output, manifest_path, verify_build

from tests.vecm_fixed_rank_reference import TOLERANCE, fixture, reference


MODULE = Path(__file__).resolve().parents[1] / 'native/time_series'
POINTER = ctypes.POINTER(ctypes.c_double)
SIZE = ctypes.c_size_t
POLL = ctypes.CFUNCTYPE(ctypes.c_int32)
SENTINEL = -99001.0


@pytest.fixture(scope='module')
def library():
    out = default_output(MODULE)
    path = out / artifact_names(MODULE)[0]
    if not any(item.exists() or item.is_symlink() for item in (path, manifest_path(out))):
        pytest.skip('build the isolated native time-series snapshot for the real Rust checks')
    verify_build(MODULE, out)
    return ctypes.CDLL(str(path))


def vecm_call(library, values, lag=1, horizon=13, *, training=None, capacity=None, count=None, values_len=None, poll=None):
    values = np.require(values, dtype=np.float64, requirements=['C', 'A'])
    output = np.full(11 + 4 * lag + 6 * horizon if capacity is None else capacity, SENTINEL)
    error_index = SIZE()
    kernel = library.arboris_vecm_rank1
    kernel.argtypes = [POINTER, SIZE, SIZE, SIZE, SIZE, SIZE, POINTER, SIZE, ctypes.POINTER(SIZE), POLL]
    kernel.restype = ctypes.c_int32
    status = kernel(values.ctypes.data_as(POINTER), values.size if values_len is None else values_len,
                    len(values) if count is None else count, len(values) if training is None else training,
                    lag, horizon, output.ctypes.data_as(POINTER), output.size, ctypes.byref(error_index),
                    POLL() if poll is None else poll)
    return status, error_index.value, output


def unpack(output, lag, horizon):
    gamma_end = 7 + 4 * lag
    return {'lambda': output[:2], 'beta': output[2:5], 'alpha': output[5:7],
            'gamma': output[7:gamma_end], 'innovation_covariance': output[gamma_end:gamma_end + 4],
            'forecast': output[gamma_end + 4:].reshape(horizon, 6)}


@pytest.mark.parametrize('seed,lag,scales', [(749, 1, [1, 1]), (912, 2, [.25, 7]), (842, 4, [2, .6])])
def test_rank1_restricted_constant_vecm_matches_real_urca(library, seed, lag, scales):
    if shutil.which('Rscript') is None:
        pytest.skip('Rscript and urca are required for the Johansen oracle')
    values = fixture(seed) * scales
    horizon = 13
    training = len(values) - horizon
    expected = reference(values[:training], lag, horizon)
    status, _, output = vecm_call(library, values, lag, horizon, training=training)

    assert status == 0
    actual = unpack(output, lag, horizon)
    for name, data in actual.items():
        np.testing.assert_allclose(data.ravel(), expected[name], **TOLERANCE, err_msg=name)
    assert actual['beta'][0] == 1
    assert 0 <= actual['lambda'][1] < actual['lambda'][0] < 1
    assert expected['n_fit'][0] == training - lag - 1
    assert actual['forecast'][0, 3] != 0.0
    matrices = actual['forecast'][:, 2:].reshape(horizon, 2, 2)
    np.testing.assert_array_equal(matrices, matrices.transpose(0, 2, 1))
    assert np.min(np.linalg.eigvalsh(matrices)) >= 0


def test_held_out_values_never_change_fit_or_level_forecast_bits(library):
    values = fixture(749)
    modified = values.copy()
    modified[-13:] *= -800
    first = vecm_call(library, values, 4, 13, training=len(values) - 13)
    second = vecm_call(library, modified, 4, 13, training=len(values) - 13)

    assert first[0] == second[0] == 0
    np.testing.assert_array_equal(first[2].view(np.uint64), second[2].view(np.uint64))


def test_perfectly_dependent_differences_reject_the_controls_stage(library):
    base = fixture(749)[:, 0]
    status, index, output = vecm_call(library, np.column_stack((base, 2 * base + 1)))

    assert status == 4 and index == 1
    assert np.all(output == SENTINEL)


def test_near_equal_canonical_roots_reject_rank_one_direction(library):
    phase = 2 * np.pi * (np.arange(162) % 8) / 8
    path = np.exp(1j * phase) + .6 * np.exp(2j * phase) + .3 * np.exp(3j * phase)
    values = np.column_stack((path.real, path.imag))
    status, index, output = vecm_call(library, values)

    assert (status, index) == (7, 1)
    assert np.all(output == SENTINEL)


@pytest.mark.parametrize('options', [
    {'lag': 0}, {'lag': 5}, {'horizon': 0}, {'horizon': 201}, {'training': 9},
    {'training': 300}, {'count': 20_001}, {'values_len': 4}, {'capacity': 6},
])
def test_invalid_shape_or_unusable_holdout_fails_closed(library, options):
    status, _, output = vecm_call(library, fixture(749), **options)

    assert status == 1
    assert np.all(output == SENTINEL)


def test_nonfinite_held_out_value_is_reported_in_original_row_order(library):
    values = fixture(749)
    values[-4, 1] = np.nan
    status, index, output = vecm_call(library, values, training=len(values) - 13)

    assert status == 3 and index == 2 * (len(values) - 4) + 1
    assert np.all(output == SENTINEL)


def test_cancellation_during_shared_qr_publishes_no_partial_result(library):
    polls = 0

    @POLL
    def stop():
        nonlocal polls
        polls += 1
        return int(polls == 7)

    status, _, output = vecm_call(library, fixture(749), poll=stop)

    assert status == 5 and polls == 7
    assert np.all(output == SENTINEL)
