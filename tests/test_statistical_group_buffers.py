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


def _legacy_posthoc_anova(groups, *, correction):
    """Pre-buffer post-hoc route, retaining its library calls and observation order."""
    from itertools import combinations

    arrays = {str(name): kernels._finite_values(values, label=f'group {name}') for name, values in groups.items()}
    if len(arrays) < 2:
        raise ValueError('posthoc_anova requires at least two groups')
    if correction not in {'tukey', 'bonferroni'}:
        raise ValueError('correction must be tukey or bonferroni')
    labels = [name for name, values in arrays.items() for _ in values]
    values = [value for group in arrays.values() for value in group]
    statistic, p_value = kernels.stats.f_oneway(*arrays.values())
    comparisons = []
    if correction == 'tukey':
        comparisons.extend(kernels.statsmodels_pairwise_tukey(values, labels))
    else:
        pairs = list(combinations(arrays, 2))
        for left_name, right_name in pairs:
            pair_stat, pair_p = kernels.stats.ttest_ind(arrays[left_name], arrays[right_name], equal_var=False)
            comparisons.append({'group1': left_name, 'group2': right_name,
                'statistic': kernels._safe_float(pair_stat), 'p_value': min(1., float(pair_p) * len(pairs)),
                'correction': 'bonferroni', 'effect_size': kernels.cohens_d(arrays[left_name], arrays[right_name])})
    result = kernels._evidence_result(test_id='anova_posthoc', test_type='anova_posthoc', nobs=len(values),
        statistic=statistic, p_value=p_value, effect_size=kernels.eta_squared(arrays),
        assumptions=['independent observations', 'approximately normal residuals', 'homogeneous variance'])
    result.update({'correction': correction, 'family': 'all_group_pairs', 'comparisons': comparisons})
    return result


def _posthoc_groups(variant):
    first = np.array([1., 2., 5., 3., 2., 7., 4., 6.])
    second = np.array([9., 2., 1., 4., 6., 5., 8., 3.])
    third = np.array([3., 4., 3., 6., 5., 7., 8., 9.])
    if variant == 'strided-unicode':
        return {'β': first[::-2], '长短标签' * 12: second[::2], 'a': third[::-2]}
    if variant == 'str-collision':
        # The later string key replaces the integer key's data, retaining its first position.
        return {7: first, 'tail': second, '7': third[::-2], '较长的组名': first[::2]}
    if variant == 'constant':
        return {'b': np.ones(4), 'a': np.full(4, 2.), 'c': np.full(4, 3.)}
    return {'b': first, 'a': second, 'c': third}


def _posthoc_outcome(function, groups, correction):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            result = ('returned', bits(function(groups, correction=correction)))
        except ValueError as error:
            result = ('rejected', type(error), str(error))
    return result, [(warning.category, str(warning.message)) for warning in caught]


@pytest.mark.parametrize('variant', ['ordinary', 'strided-unicode', 'str-collision'])
def test_tukey_receives_contiguous_buffers_with_the_legacy_label_dtype_and_group_order(variant, monkeypatch):
    groups = _posthoc_groups(variant)
    original = {key: values.copy() for key, values in groups.items()}
    legacy = {str(key): np.asarray(values, dtype=float).tolist() for key, values in groups.items()}
    expected_values = np.asarray([value for values in legacy.values() for value in values])
    expected_labels = np.asarray([key for key, values in legacy.items() for _ in values])
    delegate = kernels.statsmodels_pairwise_tukey
    observed = []

    def capture(values, labels):
        assert isinstance(values, np.ndarray) and isinstance(labels, np.ndarray)
        assert values.flags.c_contiguous and labels.flags.c_contiguous
        assert values.dtype == expected_values.dtype and labels.dtype == expected_labels.dtype
        assert values.tobytes() == expected_values.tobytes()
        assert labels.tobytes() == expected_labels.tobytes()
        observed.append((values.size, labels.size))
        return delegate(values, labels)

    monkeypatch.setattr(kernels, 'statsmodels_pairwise_tukey', capture)
    kernels.posthoc_anova(groups, correction='tukey')
    assert observed == [(expected_values.size, expected_labels.size)]
    for key, values in groups.items():
        assert values.dtype == original[key].dtype and values.tobytes() == original[key].tobytes()


@pytest.mark.parametrize('variant', ['ordinary', 'strided-unicode', 'str-collision', 'constant'])
@pytest.mark.parametrize('correction', ['tukey', 'bonferroni'])
def test_posthoc_buffer_results_and_warnings_are_bit_identical_to_the_list_route(variant, correction):
    groups = _posthoc_groups(variant)
    assert _posthoc_outcome(kernels.posthoc_anova, groups, correction) == _posthoc_outcome(
        _legacy_posthoc_anova, groups, correction)


def test_bonferroni_does_not_build_a_flat_observation_or_label_buffer(monkeypatch):
    class NoFlatBuffers:
        def __getattr__(self, name):
            if name in {'concatenate', 'repeat'}:
                pytest.fail('Bonferroni does not need a full observation or label buffer')
            return getattr(np, name)

    groups = _posthoc_groups('strided-unicode')
    expected = _posthoc_outcome(_legacy_posthoc_anova, groups, 'bonferroni')
    monkeypatch.setattr(kernels, 'np', NoFlatBuffers())
    assert _posthoc_outcome(kernels.posthoc_anova, groups, 'bonferroni') == expected
