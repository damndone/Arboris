"""Fast canonical paths (number lists, plain ASCII strings) give byte-identical text."""

import random
import struct

import pytest

from workbench import canonical
from workbench.canonical import CanonicalJSONError, canonical_json_v1


def _slow(value):
    """The per-item encoder, with the fast paths disabled."""
    saved = canonical._numeric_list, canonical._plain_string_list
    canonical._numeric_list = canonical._plain_string_list = lambda value: False
    try:
        return canonical_json_v1(value)
    finally:
        canonical._numeric_list, canonical._plain_string_list = saved


def _numbers(n, seed):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        k = rng.random()
        if k < 0.25:
            out.append(rng.randint(-10**9, 10**9))
        elif k < 0.5:
            out.append(round(rng.uniform(-1e4, 1e4), rng.randint(0, 6)))
        elif k < 0.75:
            value = struct.unpack("d", struct.pack("Q", rng.getrandbits(64)))[0]
            out.append(value if value == value and abs(value) != float("inf") else 0.5)
        else:
            out.append(rng.choice([0.0, -0.0, 1.0, 1e-7, 1e-6, 9.99e-7, 1e21, 1e20, 5e-324,
                                   1.7976931348623157e308, 0.1, 2.5, 40.0, 1, 0]))
    return out


def test_number_lists_are_byte_identical_on_100k_values():
    values = _numbers(100_000, 20261021)
    assert canonical_json_v1(values) == _slow(values)
    assert canonical_json_v1({"y": values[:5000], "X": {"a": values[5000:9000]}}) == _slow(
        {"y": values[:5000], "X": {"a": values[5000:9000]}})


@pytest.mark.parametrize("values", [
    [str(i) for i in range(50_000)],
    ["a b", "~!@#$%^&*()_+-=[]{}|;:',./<>?", "", "0001"],
    ['quo"te', "back\\slash", "tab\t", "nl\n", "del\x7f", "é", "中", "é"],
    ["1", 2, "3"], [True, 1, 1.0], [], [None, "x", 0.0, -0.0],
])
def test_string_and_mixed_lists_are_byte_identical(values):
    assert canonical_json_v1(values) == _slow(values)


def test_non_finite_numbers_still_raise():
    for bad in ([1.0, float("nan")], [float("inf")], [1, float("-inf")]):
        with pytest.raises(CanonicalJSONError):
            canonical_json_v1(bad)
