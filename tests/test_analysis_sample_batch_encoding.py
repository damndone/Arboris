"""Batch sample encoding must reproduce the original canonical wire bytes."""

from __future__ import annotations

import hashlib
import random

import pytest

from workbench.analysis_loop import fingerprints
from workbench.canonical import CanonicalJSONError, canonical_json_v1


def _original_wire(row_set, row_order):
    """Independent oracle: the unchanged canonical encoder and old sort key."""
    sorted_rows = sorted(row_set, key=canonical_json_v1)
    return canonical_json_v1({
        "fingerprint_type": "analysis_sample_v1",
        "value": {"row_set": sorted_rows, "row_order": row_order},
    }).encode("utf-8")


def _capture_wire(monkeypatch):
    captured = []
    original_sha256 = hashlib.sha256
    def sha256(value):
        captured.append(value)
        return original_sha256(value)
    monkeypatch.setattr(hashlib, "sha256", sha256)
    return captured


@pytest.mark.parametrize("rows", [[], ["0"], ["2", "10", "1"],
                                 ["01", "1", "000", "0", "01"], ["9", "100", "20", "3"]])
@pytest.mark.parametrize("containers", [(list, list), (tuple, list), (list, tuple), (tuple, tuple)])
def test_decimal_containers_match_original_bytes_and_skip_per_item_encoding(monkeypatch, rows, containers):
    row_set, row_order = containers[0](rows), containers[1](reversed(rows))
    expected_wire = _original_wire(row_set, row_order)
    expected_hash = hashlib.sha256(expected_wire).hexdigest()
    captured = _capture_wire(monkeypatch)
    def legacy_call(_):
        pytest.fail("decimal row IDs should use the batch encoder")
    monkeypatch.setattr(fingerprints, "canonical_json_v1", legacy_call)
    monkeypatch.setattr(fingerprints, "sha256_canonical", legacy_call)
    assert fingerprints.analysis_sample_fingerprint(row_set, row_order) == expected_hash
    assert captured == [expected_wire]


def test_seeded_100k_random_rows_match_full_original_wire_and_hash(monkeypatch):
    rng = random.Random(20261018)
    rows = ["0" * rng.randrange(4) + str(rng.randrange(10**14)) for _ in range(100_000)]
    rows[::11] = ["0001"] * len(rows[::11])
    order = list(rows)
    rng.shuffle(order)
    expected_wire = _original_wire(rows, order)
    expected_hash = hashlib.sha256(expected_wire).hexdigest()
    captured = _capture_wire(monkeypatch)
    calls = []
    original = fingerprints.canonical_json_v1
    def canonical(value):
        calls.append(value)
        return original(value)
    monkeypatch.setattr(fingerprints, "canonical_json_v1", canonical)
    assert fingerprints.analysis_sample_fingerprint(rows, order) == expected_hash
    assert captured == [expected_wire]
    assert calls == []


def test_aliased_inputs_preserve_duplicates_and_order():
    rows = ["2", "10", "2", "01"]
    result = fingerprints.analysis_sample_fingerprint(rows, rows)
    assert result == hashlib.sha256(_original_wire(rows, rows)).hexdigest()
    assert result != fingerprints.analysis_sample_fingerprint(rows, list(reversed(rows)))
    assert result != fingerprints.analysis_sample_fingerprint(["2", "10", "01"], rows)
    assert rows == ["2", "10", "2", "01"]


class _ListSubclass(list):
    pass


class _StringSubclass(str):
    pass


@pytest.mark.parametrize("row_set,row_order", [
    (["e\u0301", "é", "世界"], ["é", "世界", "e\u0301"]),
    (["１２", "1"], ["1", "１２"]),
    (["a\n", '"', "\\", " "], [" ", "\\", '"', "a\n"]),
    (["-1", "1"], ["1", "-1"]),
    (["", "0"], ["0", ""]),
    ([1, "2", 0.0, -0.0, True, None], [None, True, -0.0, 0.0, "2", 1]),
    ([["1"], {"a": "2"}], [{"a": "2"}, ["1"]]),
    (_ListSubclass(["1", "2"]), ["1", "2"]),
    (["1", "2"], _ListSubclass(["1", "2"])),
    ([_StringSubclass("1"), "2"], ["1", "2"]),
    (["1", "2"], [_StringSubclass("1"), "2"]),
    (["1", "2"], {"order": ["1", "2"]}),
])
def test_other_inputs_use_the_original_generic_path(monkeypatch, row_set, row_order):
    expected = hashlib.sha256(_original_wire(row_set, row_order)).hexdigest()
    calls = []
    original = fingerprints.sha256_canonical
    def canonical(value):
        calls.append(value)
        return original(value)
    monkeypatch.setattr(fingerprints, "sha256_canonical", canonical)
    assert fingerprints.analysis_sample_fingerprint(row_set, row_order) == expected
    assert len(calls) == 1


def test_generator_membership_is_not_consumed_by_a_speculative_guard():
    consumed = []
    def rows():
        for value in ("2", "10", "1"):
            consumed.append(value)
            yield value
    order = ["1", "2", "10"]
    expected = hashlib.sha256(_original_wire(["2", "10", "1"], order)).hexdigest()
    assert fingerprints.analysis_sample_fingerprint(rows(), order) == expected
    assert consumed == ["2", "10", "1"]


def test_generator_order_keeps_the_old_unsupported_type_error_without_iteration():
    consumed = []
    def order():
        consumed.append("iterated")
        yield "1"
    with pytest.raises(CanonicalJSONError, match="unsupported canonical JSON value: generator"):
        fingerprints.analysis_sample_fingerprint(["1"], order())
    assert consumed == []


@pytest.mark.parametrize("row_set,row_order", [
    ([float("nan")], ["1"]), (["1"], [float("nan")]),
    ([float("inf")], ["1"]), (["1"], [float("-inf")]),
    (["\ud800"], ["1"]), (["1"], ["\udfff"]),
    ([object()], ["1"]), (["1"], [object()]),
    ([{"é": 1, "e\u0301": 2}], ["1"]), (["1"], {1: "invalid key"}),
])
def test_invalid_values_preserve_the_original_exception(row_set, row_order):
    with pytest.raises(CanonicalJSONError) as expected:
        _original_wire(row_set, row_order)
    with pytest.raises(CanonicalJSONError) as actual:
        fingerprints.analysis_sample_fingerprint(row_set, row_order)
    assert str(actual.value) == str(expected.value)


def test_lexical_golden_is_not_numeric_order():
    expected_wire = b'{"fingerprint_type":"analysis_sample_v1","value":{"row_order":["2","10","1"],"row_set":["1","10","2"]}}'
    assert _original_wire(["2", "10", "1"], ["2", "10", "1"]) == expected_wire
    assert fingerprints.analysis_sample_fingerprint(["2", "10", "1"], ["2", "10", "1"]) == hashlib.sha256(expected_wire).hexdigest()
