"""The ARMA-GARCH option vocabulary must be provably true, not merely written.

A vocabulary that drifts from the frozen contract is worse than none: it teaches
an Agent to emit patches that confirmation will reject, while reading as
authoritative. So every claim here is checked against the real validator - the
enums by rejection, the limits by accepting the cap and rejecting one past it,
and the cross-field rules by executing their own violation examples.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from workbench.agent.recipes.arma_garch_vocabulary import (
    build_arma_garch_option_vocabulary,
)
from workbench.contracts.model.arma_garch import (
    ARCH_ORDER_LIMIT,
    AR_ORDER_LIMIT,
    AUTO_AR_ORDER_LIMIT,
    AUTO_MA_ORDER_LIMIT,
    AUTO_TOTAL_ORDER_LIMIT,
    GARCH_P_ORDER_LIMIT,
    GARCH_Q_ORDER_LIMIT,
    MA_ORDER_LIMIT,
    ArmaGarchAnalysisContract,
    ArmaGarchContractError,
    _TOP_LEVEL_FIELDS,
)


BASE: dict[str, Any] = {
    "dataset_ref": "dataset:t:1",
    "time_column": "observation_date",
    "value_column": "VIXCLS",
    "time_index_semantics": "business_or_trading_observations",
    "transform": "log_return_pct",
    "transform_confirmed": True,
    "validation": {"validation_n": 250},
}

MANUAL_GARCH: dict[str, Any] = {
    "selection_mode": "manual",
    "arma": {"p": 1, "q": 1},
    "variance": {"model": "garch", "garch_p": 1, "garch_q": 1},
}


def _merged(*patches: dict[str, Any]) -> dict[str, Any]:
    """One-level merge with key-wise nested sections, as the server does."""

    result = deepcopy(BASE)
    for patch in patches:
        for key, value in patch.items():
            current = result.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                result[key] = {**current, **value}
            else:
                result[key] = deepcopy(value)
    return result


def _resolve(payload: dict[str, Any], path: str) -> Any:
    node: Any = payload
    for part in path.split("."):
        assert isinstance(node, dict), f"{path} is not reachable"
        assert part in node, f"{path} is not a contract field"
        node = node[part]
    return node


def _vocabulary_fields() -> dict[str, dict[str, Any]]:
    return {item["path"]: item for item in build_arma_garch_option_vocabulary()["fields"]}


def test_base_contract_is_valid_so_the_negative_cases_prove_something() -> None:
    assert ArmaGarchAnalysisContract.from_dict(BASE).selection_mode == "auto"
    assert ArmaGarchAnalysisContract.from_dict(_merged(MANUAL_GARCH)).arma.q == 1


def test_every_declared_path_exists_in_the_frozen_contract() -> None:
    frozen = ArmaGarchAnalysisContract.from_dict(_merged(MANUAL_GARCH)).to_dict()
    for path in _vocabulary_fields():
        _resolve(frozen, path)


def test_vocabulary_covers_every_top_level_contract_field() -> None:
    declared = {path.split(".")[0] for path in _vocabulary_fields()}
    assert _TOP_LEVEL_FIELDS - declared == set()


def test_missing_value_policy_is_published_with_its_real_choices() -> None:
    # The newest contract field; an Agent cannot recover from blocked real-world
    # data without knowing the confirmed-exclusion option exists.
    spec = _vocabulary_fields()["missing_value_policy"]
    assert spec["enum"] == ["block", "drop_missing_confirmed"]


@pytest.mark.parametrize(
    "path",
    sorted(path for path, spec in _vocabulary_fields().items() if "enum" in spec),
)
def test_declared_enums_are_closed_sets_in_the_validator(path: str) -> None:
    section, _, leaf = path.rpartition(".")
    sentinel = "__not_a_declared_choice__"
    patch = {section: {leaf: sentinel}} if section else {path: sentinel}
    with pytest.raises(ArmaGarchContractError):
        ArmaGarchAnalysisContract.from_dict(_merged(MANUAL_GARCH, patch))


@pytest.mark.parametrize(
    "path",
    [
        "time_index_semantics",
        "transform",
        "analysis_goal",
        "innovation_distribution",
        "missing_value_policy",
        "arma.constant_mode",
        "validation.method",
    ],
)
def test_independently_settable_enum_values_are_all_accepted(path: str) -> None:
    section, _, leaf = path.rpartition(".")
    for value in _vocabulary_fields()[path]["enum"]:
        patch = {section: {leaf: value}} if section else {path: value}
        frozen = ArmaGarchAnalysisContract.from_dict(_merged(MANUAL_GARCH, patch))
        assert _resolve(frozen.to_dict(), path) == value


@pytest.mark.parametrize(
    ("path", "limit", "companions"),
    [
        ("arma.auto_max_p", AUTO_AR_ORDER_LIMIT, {}),
        ("arma.auto_max_q", AUTO_MA_ORDER_LIMIT, {}),
        ("arma.auto_max_total_order", AUTO_TOTAL_ORDER_LIMIT, {}),
        ("variance.auto_arch_max_p", ARCH_ORDER_LIMIT, {}),
        ("arma.p", AR_ORDER_LIMIT, MANUAL_GARCH),
        ("arma.q", MA_ORDER_LIMIT, MANUAL_GARCH),
        ("variance.garch_p", GARCH_P_ORDER_LIMIT, MANUAL_GARCH),
        ("variance.garch_q", GARCH_Q_ORDER_LIMIT, MANUAL_GARCH),
        (
            "variance.arch_p",
            ARCH_ORDER_LIMIT,
            {
                "selection_mode": "manual",
                "arma": {"p": 1, "q": 1},
                "variance": {"model": "arch", "garch_p": None, "garch_q": None},
            },
        ),
    ],
)
def test_published_limits_are_the_real_server_caps(
    path: str, limit: int, companions: dict[str, Any]
) -> None:
    section, _, leaf = path.rpartition(".")
    assert _vocabulary_fields()[path]["maximum"] == limit

    at_cap = ArmaGarchAnalysisContract.from_dict(
        _merged(companions, {section: {leaf: limit}})
    )
    assert _resolve(at_cap.to_dict(), path) == limit

    with pytest.raises(ArmaGarchContractError) as excinfo:
        ArmaGarchAnalysisContract.from_dict(
            _merged(companions, {section: {leaf: limit + 1}})
        )
    assert excinfo.value.code == "CANDIDATE_LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    "rule",
    build_arma_garch_option_vocabulary()["cross_field_rules"],
    ids=lambda rule: rule["rule_id"],
)
def test_each_cross_field_rule_reproduces_its_declared_violation(
    rule: dict[str, Any],
) -> None:
    with pytest.raises(ArmaGarchContractError) as excinfo:
        ArmaGarchAnalysisContract.from_dict(_merged(rule["violation_example"]))
    assert excinfo.value.code == rule["violation_code"]


def test_server_owned_fields_are_not_offered_as_agent_editable() -> None:
    fields = _vocabulary_fields()
    for path in (
        "pack_id",
        "contract_version",
        "dataset_ref",
        "forecast.horizon",
        "validation.selection_repeated_during_validation",
    ):
        assert fields[path]["agent_editable"] is False


def test_patch_shape_states_the_one_level_object_contract() -> None:
    vocabulary = build_arma_garch_option_vocabulary()
    assert "one-level patch" in vocabulary["patch_shape"]
    assert "old/new" in vocabulary["patch_shape"]
