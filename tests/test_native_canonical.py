"""Opt-in byte/error differential tests for the unconnected native pilot.

Build with ``.venv/bin/python native/canonical_numbers/build.py``; then run
``NATIVE_CANONICAL_REQUIRED=1 PYTHONPATH=backend:local/native-canonical
.venv/bin/python -m pytest tests/test_native_canonical.py -q``.
No timing or resource measurements are performed here.
"""

from __future__ import annotations

import importlib
import importlib.util
import math
import os
import random
import struct
import sys

import pytest

from workbench.canonical import CanonicalJSONError, canonical_json_v1


def test_required_pilot_is_available():
    if os.environ.get("NATIVE_CANONICAL_REQUIRED") == "1":
        assert importlib.util.find_spec("_canonical_numbers") is not None, "native pilot is missing"


@pytest.fixture(scope="module")
def native():
    spec = importlib.util.find_spec("_canonical_numbers")
    if spec is None and os.environ.get("NATIVE_CANONICAL_REQUIRED") != "1":
        pytest.skip("independent native pilot not built/on PYTHONPATH")
    assert spec is not None, "build the independent _canonical_numbers extension first"
    return importlib.import_module("_canonical_numbers")


@pytest.mark.parametrize("values", [
    [], (), [0, -0.0, 0.0], (1.0, -2, 2.5),
    [1e-6, math.nextafter(1e-6, 0.0), math.nextafter(1e-6, math.inf)],
    [1e21, math.nextafter(1e21, 0.0), math.nextafter(1e21, math.inf)],
    [5e-324, -5e-324, sys.float_info.min, sys.float_info.max, -sys.float_info.max],
    [10**300, -(10**300), 2**53 - 1, 2**53, 2**53 + 1],
    [10**21, 1e21], [1e21, 10**21],
    [10**21, 1e21, 0, -0.0, 2**100, float(2**100)],
    [float(2**100), 2**100],
])
def test_numeric_sequences_match_current_canonical_bytes(native, values):
    assert native.encode_numbers(values).encode("utf-8") == canonical_json_v1(values).encode("utf-8")


def test_mixed_numeric_cache_keeps_first_equal_key_format(native):
    assert native.encode_numbers([10**21, 1e21]) == "[1000000000000000000000,1000000000000000000000]"
    assert native.encode_numbers([1e21, 10**21]) == "[1e+21,1e+21]"
    assert native.encode_numbers([1e21]) == "[1e+21]"  # Cache is per call.


def test_100k_fixed_binary64_patterns_match_bytes(native):
    rng = random.Random(20261027)
    values = []
    while len(values) < 100_000:
        value = struct.unpack(">d", struct.pack(">Q", rng.getrandbits(64)))[0]
        if math.isfinite(value):
            values.append(value)
    for offset in range(0, len(values), 1000):
        batch = values[offset:offset + 1000]
        assert native.encode_numbers(batch) == canonical_json_v1(batch)


def test_decimal_exponents_and_adjacent_values_match_bytes(native):
    values = []
    for exponent in range(-323, 309):
        value = float(f"1e{exponent}")
        for neighbor in (math.nextafter(value, 0.0), value, math.nextafter(value, math.inf)):
            if math.isfinite(neighbor):
                values.extend((neighbor, -neighbor))
    assert native.encode_numbers(values) == canonical_json_v1(values)


@pytest.mark.parametrize("values", [
    [math.nan], [math.inf], [-math.inf], [1, math.nan],
    [10**400], [-(10**400)], [1.0, 10**400],
    [math.inf, 10**400], [10**400, math.inf],
])
def test_nonfinite_and_oversized_int_errors_match_reference(native, values):
    with pytest.raises((CanonicalJSONError, OverflowError)) as expected:
        canonical_json_v1(values)
    with pytest.raises(type(expected.value)) as actual:
        native.encode_numbers(values)
    assert type(actual.value) is type(expected.value)
    assert str(actual.value) == str(expected.value)


class IntSubclass(int):
    pass


class FloatSubclass(float):
    pass


@pytest.mark.parametrize("values", [
    [True], [False, 1], [None], ["1"], [[1]], [IntSubclass(1)], [FloatSubclass(1)],
    iter([1]), {"x": 1}, "123", 1,
])
def test_pilot_rejects_values_outside_exact_numeric_sequence_boundary(native, values):
    with pytest.raises(TypeError):
        native.encode_numbers(values)
