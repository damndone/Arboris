"""Finite group buffers preserve the existing float and evidence contracts."""

import struct
import warnings

import numpy as np
import pandas as pd
import pytest

from workbench import statistical_test_evidence as evidence
from workbench import statistical_test_kernels as kernels


def bits(value):
    if isinstance(value, float):
        return struct.pack('>d', value)
    if isinstance(value, dict):
        return {key: bits(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [bits(item) for item in value]
    return value


def test_group_preparation_retains_arrays_with_unchanged_selection_and_order():
    frame = pd.DataFrame({
        'x': [1., 2., 3., 4., np.nan, 5., np.inf, 7., 8., 9., 10.],
        'g': ['b', 'b', 'a', 'a', 'a', 'c', 'c', 'd', 'd', None, 'single'],
    })
    before = frame.copy(deep=True)
    labels, groups = evidence._finite_groups(frame, 'x', 'g')
    assert labels == ['a', 'b', 'd']
    assert all(isinstance(group, np.ndarray) and group.dtype == np.float64 for group in groups)
    assert [group.tolist() for group in groups] == [[3., 4.], [1., 2.], [7., 8.]]
    pd.testing.assert_frame_equal(frame, before, check_exact=True)
    assert evidence._finite_groups(frame.iloc[:2], 'x', 'g') is None


def test_array_summary_keeps_builtin_python_float_compensated_sum():
    values = np.array([1e16, 1., -1e16])
    actual = kernels._GroupSummary(values)
    expected = kernels._GroupSummary(values.tolist())
    assert actual.values is values
    assert type(actual.total) is float
    assert bits(actual.total) == bits(expected.total) == bits(1.)
    assert bits(actual.variance) == bits(expected.variance)


@pytest.mark.parametrize('values', [
    [1., 2., 3.], [-0., 0., -0., 0.],
    [-np.nextafter(0., 1.), 0., np.nextafter(0., 1.)],
    [1e16, 1., -1e16, 2.], [1e150, 1., -1e150, 3.],
])
def test_summary_list_and_strided_buffer_have_identical_total_and_variance_bits(values):
    # Keep the same order in the two routes, including reversed storage.
    array = np.asarray(values)[::-1]
    expected = kernels._GroupSummary(array.tolist())
    actual = kernels._GroupSummary(array)
    assert actual.values is array
    assert bits(actual.total) == bits(expected.total)
    assert bits(actual.variance) == bits(expected.variance)
    assert bits(actual.variance) == bits(expected.variance)


def test_effect_size_consumers_avoid_boxing_finite_group_arrays(monkeypatch):
    groups = {'a': np.array([1., 2., 5., 3.]), 'b': np.array([9., 2., 1., 4.]),
              'c': np.array([3., 4., 3., 6.])}
    expected = [kernels.eta_squared({key: group.tolist() for key, group in groups.items()}),
                kernels.omega_squared({key: group.tolist() for key, group in groups.items()})]

    def boxed(*args, **kwargs):
        pytest.fail('finite group buffers were converted into an observation list')

    monkeypatch.setattr(kernels, '_finite_values', boxed)
    assert bits([kernels.eta_squared(groups), kernels.omega_squared(groups)]) == bits(expected)


@pytest.mark.parametrize('layout', ['contiguous', 'strided', 'fortran', 'big_endian'])
def test_group_sums_preserve_original_contiguous_reduction_order(layout):
    matrix = np.array([[1e16, 1., -1e16, 2.], [2., -1e16, 1., 1e16],
                       [3., 5., 7., 11.]])
    if layout == 'strided':
        matrix = matrix[:, ::-1]
    elif layout == 'fortran':
        matrix = np.asfortranarray(matrix)
    elif layout == 'big_endian':
        matrix = matrix.astype('>f8')
    groups = {str(i): row for i, row in enumerate(matrix)}
    original_values = {key: np.asarray(group, dtype=float).tolist() for key, group in groups.items()}
    assert bits(kernels._group_sums_of_squares(groups, 'test')) == bits(
        kernels._group_sums_of_squares(original_values, 'test'))


@pytest.mark.parametrize('variant', ['ordinary', 'constant', 'ties', 'nan', 'uint64'])
def test_full_evidence_matches_original_list_route_including_warnings(variant, monkeypatch):
    i = np.arange(60)
    frame = pd.DataFrame({'x': np.sin(i / 3) + i / 97, 'y': np.cos(i / 5) + i / 101,
                          'binary': np.where(i % 2, 'a', 'b'),
                          'group': np.array(['a', 'b', 'c'], dtype=object)[i % 3]})
    if variant == 'constant':
        frame['x'] = 3.
    elif variant == 'ties':
        frame['x'] = i % 7
    elif variant == 'nan':
        frame.loc[[1, 7], 'x'] = np.nan
    elif variant == 'uint64':
        frame['x'] = i.astype(np.uint64) + np.uint64(2**53)
    options = dict(numeric=['x', 'y'], categorical=['binary', 'group'],
                   reference_means={'y': 0.}, paired_columns=[('x', 'y')])
    with warnings.catch_warnings(record=True) as actual_warnings:
        warnings.simplefilter('always')
        actual = evidence._build_advanced_evidence_results(frame, **options)
    prepare = evidence._finite_groups

    def original_list_groups(*args, **kwargs):
        selected = prepare(*args, **kwargs)
        if selected is None:
            return None
        labels, groups = selected
        return labels, [list(map(float, group)) for group in groups]

    monkeypatch.setattr(evidence, '_finite_groups', original_list_groups)
    with warnings.catch_warnings(record=True) as expected_warnings:
        warnings.simplefilter('always')
        expected = evidence._build_advanced_evidence_results(frame, **options)
    assert bits(actual) == bits(expected)
    assert [(warning.category, str(warning.message)) for warning in actual_warnings] == [
        (warning.category, str(warning.message)) for warning in expected_warnings]


def test_group_owner_cancellation_remains_the_original_error():
    error = ValueError('cancelled by owner')

    def check():
        raise error

    frame = pd.DataFrame({'x': [1., 2., 3., 4.], 'g': ['a', 'a', 'b', 'b']})
    with pytest.raises(ValueError) as caught:
        evidence._finite_groups(frame, 'x', 'g', check_cancel=check)
    assert caught.value is error
