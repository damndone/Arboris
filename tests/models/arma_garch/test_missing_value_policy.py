"""Confirmed exclusion of missing observations (the Do-file's `drop if missing`).

Excluding non-trading observations is NOT interpolation, calendar filling, or
aggregation - all of which stay forbidden. It must be explicitly confirmed by the
user; the default remains a blocking diagnostic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
from workbench.engine.packs.arma_garch.input import (
    audit_time_value_input,
    prepare_arma_garch_input,
)


def _frame(n: int = 60, holidays: tuple[int, ...] = (10, 20, 30)) -> pd.DataFrame:
    values: list[float | None] = list(np.linspace(10.0, 20.0, n))
    for index in holidays:
        values[index] = None
    return pd.DataFrame(
        {"observation_date": pd.bdate_range("2020-01-01", periods=n), "vix": values}
    )


def _contract(policy: str | None = None) -> ArmaGarchAnalysisContract:
    payload: dict[str, object] = {
        "dataset_ref": "dataset:vix:1",
        "time_column": "observation_date",
        "value_column": "vix",
        "time_index_semantics": "business_or_trading_observations",
        "transform": "level",
        "transform_confirmed": True,
        "selection_mode": "manual",
        "arma": {"p": 1, "q": 0, "constant_mode": "exclude"},
        "variance": {"model": "constant_variance"},
        "validation": {"validation_n": 5},
    }
    if policy is not None:
        payload["missing_value_policy"] = policy
    return ArmaGarchAnalysisContract.from_dict(payload)


def test_default_policy_blocks_and_offers_a_recommended_action() -> None:
    with pytest.raises(ArmaGarchInputError) as exc_info:
        prepare_arma_garch_input(_frame(), _contract())
    error = exc_info.value
    assert error.code == "VALUE_PARSE_FAILED"
    assert error.evidence["missing_value_count"] == 3
    # Spec section 19: every structured failure must offer a way forward.
    assert error.recommended_actions
    patches = [dict(action.get("patch", {})) for action in error.recommended_actions]
    assert any(
        patch.get("missing_value_policy") == "drop_missing_confirmed" for patch in patches
    )


def test_confirmed_policy_excludes_missing_rows_and_prepares() -> None:
    frame = _frame()
    before = frame.copy(deep=True)
    prepared = prepare_arma_garch_input(frame, _contract("drop_missing_confirmed"))

    view = prepared.audited.analysis_view
    assert len(view) == len(frame) - 3
    assert not view["vix"].isna().any()
    # Source is never mutated by the exclusion.
    pd.testing.assert_frame_equal(frame, before)
    assert prepared.audited.source_unchanged is True


def test_confirmed_policy_reports_the_exclusion_as_information() -> None:
    audited = audit_time_value_input(_frame(), _contract("drop_missing_confirmed"))
    excluded = next(
        item for item in audited.diagnostics if item.code == "MISSING_OBSERVATIONS_EXCLUDED"
    )
    assert excluded.severity == "information"
    assert excluded.evidence["excluded_missing_count"] == 3
    assert not any(item.severity == "blocking" for item in audited.diagnostics)


def test_policy_rejects_an_unknown_value() -> None:
    with pytest.raises(Exception):
        _contract("drop_everything")
