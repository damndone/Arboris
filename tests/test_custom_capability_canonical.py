import json

import pytest

from workbench.custom_capability.canonical import (
    canonical_json_bytes,
    domain_digest,
    parse_canonical_json,
)


def test_canonical_json_is_stable_across_mapping_order() -> None:
    left = canonical_json_bytes({"b": [2, 1], "a": {"z": True, "y": None}})
    right = canonical_json_bytes({"a": {"y": None, "z": True}, "b": [2, 1]})

    assert left == right
    assert left == b'{"a":{"y":null,"z":true},"b":[2,1]}'


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_nonfinite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_json_bytes({"value": value})


def test_parse_canonical_json_rejects_duplicate_keys_and_noncanonical_bytes() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        parse_canonical_json(b'{"a":1,"a":2}')
    with pytest.raises(ValueError, match="canonical"):
        parse_canonical_json(b'{ "a": 1 }')


def test_domain_digest_separates_protocol_namespaces() -> None:
    value = {"binding": {"attempt_id": "attempt-a"}}

    assert domain_digest("execution-result", value) != domain_digest("evidence", value)
    assert len(domain_digest("execution-result", value)) == 64


def test_canonical_json_rejects_non_string_object_keys() -> None:
    with pytest.raises(ValueError, match="string"):
        canonical_json_bytes({1: "not a protocol key"})
