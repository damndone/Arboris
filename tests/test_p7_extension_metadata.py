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
        {key: value for key, value in _scope().items() if key != "estimand"},
        {**_scope(), "estimand": ""},
        {**_scope(), "estimand": 1},
        {**_scope(), "assumptions": []},
        {**_scope(), "limitations": ["x" * 1001]},
        {**_scope(), "not_claimed": ["ok"] * 65},
        {**_scope(), "unsupported_extensions": [{"raw_rows": [1]}]},
        {**_scope(), "raw_rows": [{"x": 1}]},
        {**_scope(), "formula": "y ~ x"},
        {**_scope(), "input_semantics": "y ~ x"},
        {**_scope(), "input_semantics": "/tmp/raw.csv"},
        {**_scope(), "input_semantics": "see /etc/hosts for example"},
        {**_scope(), "input_semantics": r"C:\\raw.csv"},
        {**_scope(), "input_semantics": "~/raw.csv"},
        {**_scope(), "input_semantics": "./raw.csv"},
        {**_scope(), "input_semantics": "../raw.csv"},
        {**_scope(), "input_semantics": "data/raw.csv"},
        {**_scope(), "input_semantics": "folder/file"},
        {**_scope(), "input_semantics": r"folder\file"},
        {**_scope(), "input_semantics": r"folder\\file"},
        {**_scope(), "input_semantics": "see data/raw for preprocessing"},
        {**_scope(), "input_semantics": "stored in folder/subfolder"},
        {**_scope(), "input_semantics": r"folder\\file.csv"},
        {**_scope(), "input_semantics": "file:raw.csv"},
        {**_scope(), "input_semantics": "import os"},
        {**_scope(), "input_semantics": "exec(unsafe)"},
        {**_scope(), "input_semantics": "eval(unsafe)"},
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


def test_scope_accepts_safe_punctuation_and_explanatory_prose() -> None:
    scope = P7ScopeMetadata.from_dict(
        _scope(
            input_semantics=(
                "supports A/B comparisons; x ~ y notation is explanatory; "
                "we discuss the /api/v1 endpoint and file: semantics; "
                "import is discussed conceptually; group/time interaction and x/y notation"
            ),
            limitations=[r"a backslash may appear in prose but is not a path"],
        )
    )

    assert scope.input_semantics.startswith("supports A/B")
    assert scope.limitations == (r"a backslash may appear in prose but is not a path",)
