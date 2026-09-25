"""Byte-preserving canonical string fast path: no authority checks are cached."""

import json
import unicodedata

import pytest

from workbench import canonical


@pytest.mark.parametrize("value", [
    "", "plain ASCII", 'quote" slash\\ controls\n\r\t\b\f',
    "".join(chr(i) for i in range(256)),
    "中文🧪\u2028\u2029\U0010ffff", "e\u0301A\u030a", "\ufffe\uffff",
])
def test_canonical_string_bytes_match_existing_json_oracle(value):
    expected = json.dumps(unicodedata.normalize("NFC", value), ensure_ascii=False, separators=(",", ":"))
    assert canonical.canonical_json_v1(value).encode("utf-8") == expected.encode("utf-8")


@pytest.mark.parametrize("value", ["\ud800", "\udfff", "\ud83e\uddea", {"\ud800": 1}])
def test_canonical_still_rejects_surrogate_code_points(value):
    with pytest.raises(canonical.CanonicalJSONError, match="surrogate"):
        canonical.canonical_json_v1(value)


def test_canonical_keeps_normalized_duplicate_key_rejection():
    with pytest.raises(canonical.CanonicalJSONError, match="duplicate"):
        canonical.canonical_json_v1({"é": 1, "e\u0301": 2})


def test_canonical_string_heavy_tree_avoids_per_leaf_json_encoder(monkeypatch):
    # A measured Report hot path serialized over 500k leaves. Verify the
    # allocation removal deterministically instead of a flaky wall-time cap.
    value = {"é": ["中🧪", "e\u0301", "\n", "", "\\"], "a": {"\ue000": 1, "🧪": 2}}
    expected = '{"a":{"":1,"🧪":2},"é":["中🧪","é","\\n","","\\\\"]}'
    original = json.dumps

    def no_string_encoder(item, *args, **kwargs):
        assert not isinstance(item, str), "canonical string/key allocated a JSONEncoder"
        return original(item, *args, **kwargs)

    monkeypatch.setattr(canonical.json, "dumps", no_string_encoder)
    assert canonical.canonical_json_v1(value) == expected


def test_canonical_fast_path_does_not_change_numeric_or_boolean_encoding():
    assert canonical.canonical_json_v1([True, False, None, -0.0, 1.0, 1e-7, 1e20]) == "[true,false,null,0,1,1e-7,100000000000000000000]"
