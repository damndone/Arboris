"""Vectorized runner helpers equal the per-value code they replace."""

import math

import numpy as np
import pandas as pd
import pytest

from workbench.econometrics.runner import _aligned_positions, _python_scalar, _python_values


def _same(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert type(x) is type(y)
        assert x == y or (isinstance(x, float) and math.isnan(x) and math.isnan(y)) or (x is None and y is None)
        if isinstance(x, float):
            assert math.copysign(1, x) == math.copysign(1, y)


@pytest.mark.parametrize("series", [
    pd.Series([1.5, -0.0, 0.0, np.nan, 1e308, 5e-324, 3.0]),
    pd.Series([1, 2, -3], dtype="int64"), pd.Series([1, 2], dtype="uint8"), pd.Series([True, False]),
    pd.Series([1, None, 3], dtype="Int64"), pd.Series(["a", None, 1]), pd.Series(pd.to_datetime(["2020-01-01", None])),
    pd.Series(pd.Categorical(["x", "y", "x"])), pd.Series([], dtype="float64"), pd.Series([np.nan, np.nan]),
])
def test_python_values_matches_per_value_conversion(series):
    _same(_python_values(series), [_python_scalar(v) for v in series])


def _per_label(reference, labels):
    positions_by_label = {}
    for position, label in enumerate(reference):
        positions_by_label.setdefault(label, []).append(position)
    out = []
    for label in labels:
        positions = positions_by_label.get(label)
        if not positions:
            raise ValueError("misaligned")
        out.append(positions.pop(0))
    return out


@pytest.mark.parametrize("reference, labels", [
    (list(range(10)), list(range(10))), (list(range(10)), [0, 2, 5, 9]), (list("abcde"), list("eca")),
    (["a", "a", "b"], ["a", "b", "a"]), (["a", "a", "b"], ["a", "a", "b"]), ([0.0, float("nan"), 2.0], [2.0, 0.0]),
    (list(range(5)), [1, 7]), (list(range(5)), [1, 1]), (["a", "b"], ["a", "a"]),
])
def test_aligned_positions_matches_the_per_label_path(reference, labels):
    try:
        expected = _per_label(reference, labels)
    except ValueError:
        with pytest.raises(ValueError):
            _aligned_positions(reference, labels)
        return
    assert _aligned_positions(reference, labels) == expected


@pytest.mark.parametrize("ids", [[str(i) for i in range(1000)], ["a", "b", "a"], ["1", 1], [1, 2, 3], []])
def test_row_ids_match_the_typed_rendering(ids):
    from workbench.econometrics import runner
    frame = pd.DataFrame({"y": range(len(ids))})
    def slow(values):
        original = [f"{type(v).__module__}.{type(v).__qualname__}" for v in values]
        normalized = [_python_scalar(v) for v in values]
        rendered = [str(v) for v in normalized]
        return rendered if len(set(rendered)) == len(rendered) else [f"{t}:{v}" for t, v in zip(original, normalized)]
    expected_values = slow(list(ids))
    try:
        got = runner._row_id_values(frame, ids)
    except ValueError:
        assert len(set(expected_values)) != len(expected_values) and frame.index.is_unique
        return
    if len(set(expected_values)) == len(expected_values):
        assert got == expected_values
