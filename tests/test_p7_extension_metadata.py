"""Red tests for the bounded scope metadata shared by the final P7 packs."""

from __future__ import annotations

import dataclasses
import json

import pytest

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.p7_extension import P7ScopeMetadata
from workbench.engine.packs.p7_common import make_p7_scope


def _scope(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "estimand": "rank location difference",
        "input_semantics": "two independent finite numeric samples",
        "assumptions": ["observations are independent within the declared design"],
        "limitations": ["ties require the declared asymptotic correction"],
        "not_claimed": ["does not establish a causal effect"],
        "unsupported_extensions": ["complex survey rank variance is not included"],
    }
    value.update(overrides)
    return value


def test_scope_round_trips_as_bounded_json_metadata() -> None:
    scope = P7ScopeMetadata.from_dict(_scope())

    assert scope.to_dict() == _scope()
    assert json.loads(json.dumps(scope.to_dict())) == _scope()
    assert make_p7_scope(**_scope()) == _scope()


def test_scope_is_immutable() -> None:
    scope = P7ScopeMetadata.from_dict(_scope())

    assert dataclasses.is_dataclass(scope)
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        scope.estimand = "changed"  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        scope.limitations.append("changed")  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "bad",
    [
        {**_scope(), "unknown": "rejected"},
        {**_scope(), "estimand": ""},
        {**_scope(), "estimand": 1},
        {**_scope(), "assumptions": []},
        {**_scope(), "limitations": ["x" * 1001]},
        {**_scope(), "not_claimed": ["ok"] * 65},
        {**_scope(), "unsupported_extensions": [{"raw_rows": [1]}]},
        {**_scope(), "raw_rows": [{"x": 1}]},
        {**_scope(), "formula": "y ~ x"},
        {**_scope(), "input_semantics": "/tmp/raw.csv"},
    ],
)
def test_scope_rejects_unsafe_or_incomplete_metadata(bad: dict[str, object]) -> None:
    with pytest.raises(ContractError):
        P7ScopeMetadata.from_dict(bad)


def test_scope_rejects_non_string_sequence_members() -> None:
    bad = _scope(assumptions=["ok", 1])

    with pytest.raises(ContractError):
        P7ScopeMetadata.from_dict(bad)


def test_scope_rejects_nested_raw_payloads() -> None:
    bad = _scope(limitations=["ok"], not_claimed=["raw_data is excluded"])
    bad["unsupported_extensions"] = [{"raw_values": [1, 2]}]

    with pytest.raises(ContractError):
        P7ScopeMetadata.from_dict(bad)
