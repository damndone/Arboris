from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from workbench.canonical import sha256_canonical
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
from workbench.engine.packs.arma_garch.input import prepare_arma_garch_input
from workbench.engine.packs.arma_garch.transforms import TRANSFORMED_VALUE_COLUMN


def _contract(*, validation_n: int | None = None) -> ArmaGarchAnalysisContract:
    payload: dict[str, object] = {
        "dataset_ref": "dataset:split:1",
        "time_column": "when",
        "value_column": "value",
        "time_index_semantics": "business_or_trading_observations",
        "transform": "level",
        "transform_confirmed": True,
        "validation": {},
    }
    if validation_n is not None:
        payload["validation"] = {"validation_n": validation_n}
    return ArmaGarchAnalysisContract.from_dict(payload)


def _transformed_view(n: int = 100, *, sentinel_tail: int = 0) -> pd.DataFrame:
    values = np.linspace(10.0, 20.0, n)
    if sentinel_tail:
        values[-sentinel_tail:] = 999_999.0
    source = pd.DataFrame(
        {
            "when": pd.bdate_range("2024-01-02", periods=n),
            "value": values,
        }
    )
    return prepare_arma_garch_input(source, _contract()).transformed_view


def _split_api():
    from workbench.engine.packs.arma_garch.split import freeze_train_validation_split

    return freeze_train_validation_split


@pytest.mark.parametrize(
    ("n_effective", "expected_validation_n"),
    [(100, 20), (1_000, 200), (2_000, 250)],
)
def test_default_validation_size_uses_the_locked_formula(
    n_effective: int, expected_validation_n: int
) -> None:
    freeze_split = _split_api()

    split = freeze_split(_transformed_view(n_effective), _contract())

    assert split.validation_n == expected_validation_n
    assert split.n_train == n_effective - expected_validation_n
    assert split.split_index == split.n_train


def test_explicit_validation_size_and_boundary_are_persisted() -> None:
    freeze_split = _split_api()
    view = _transformed_view(100)
    contract = _contract(validation_n=12)

    split = freeze_split(view, contract)

    assert split.validation_n == 12
    assert len(split.training_row_ids) == 88
    assert len(split.validation_row_ids) == 12
    assert split.split_timestamp == "2024-05-02T00:00:00Z"
    assert set(split.training_row_ids).isdisjoint(split.validation_row_ids)
    assert split.selection_repeated_during_validation is False


def test_split_is_deterministic_canonical_and_immutable() -> None:
    freeze_split = _split_api()
    view = _transformed_view(100)
    contract = _contract()

    first = freeze_split(view, contract)
    second = freeze_split(view.copy(deep=True), contract)

    assert first.split_hash == second.split_hash
    assert first.split_hash == sha256_canonical(first.hash_payload())
    assert isinstance(first.training_row_ids, tuple)
    with pytest.raises(FrozenInstanceError):
        first.split_index = 0

    exposed_training = first.training_view
    original_value = float(first.training_view.loc[0, TRANSFORMED_VALUE_COLUMN])
    exposed_training.loc[0, TRANSFORMED_VALUE_COLUMN] = -999_999.0
    assert float(first.training_view.loc[0, TRANSFORMED_VALUE_COLUMN]) == original_value
    assert first.split_hash == sha256_canonical(first.hash_payload())


def test_tail_sentinel_never_enters_the_frozen_training_view() -> None:
    freeze_split = _split_api()
    view = _transformed_view(100, sentinel_tail=20)

    split = freeze_split(view, _contract())

    assert float(split.training_view[TRANSFORMED_VALUE_COLUMN].max()) < 999_999.0
    assert set(split.validation_view[TRANSFORMED_VALUE_COLUMN]) == {999_999.0}
    assert tuple(split.training_view.iloc[:, 0].index) != tuple(
        split.validation_view.iloc[:, 0].index
    )


def test_split_hash_binds_the_analysis_view_not_only_row_ids() -> None:
    freeze_split = _split_api()
    contract = _contract()
    original = _transformed_view(100)
    changed = original.copy(deep=True)
    changed.loc[changed.index[-1], TRANSFORMED_VALUE_COLUMN] += 1.0

    original_split = freeze_split(original, contract)
    changed_split = freeze_split(changed, contract)

    assert original_split.validation_row_ids == changed_split.validation_row_ids
    assert original_split.analysis_view_hash != changed_split.analysis_view_hash
    assert original_split.split_hash != changed_split.split_hash


def test_too_short_backtest_window_fails_with_structured_error() -> None:
    freeze_split = _split_api()
    view = _transformed_view(30)
    contract = _contract(validation_n=30)

    with pytest.raises(ArmaGarchInputError) as exc_info:
        freeze_split(view, contract)

    assert exc_info.value.code == "BACKTEST_WINDOW_TOO_SHORT"
    assert exc_info.value.evidence == {"n_effective": 30, "validation_n": 30}


def test_small_training_sample_is_frozen_but_marked_inconclusive() -> None:
    freeze_split = _split_api()
    view = _transformed_view(60)

    split = freeze_split(view, _contract())

    diagnostic_by_code = {item.code: item for item in split.diagnostics}
    assert diagnostic_by_code["INSUFFICIENT_OBSERVATIONS"].severity == "warning"
    assert diagnostic_by_code["INSUFFICIENT_OBSERVATIONS"].evidence["n_train"] == 40
    assert split.forecast_validation_status == "inconclusive"


def test_observation_order_split_boundary_does_not_invent_a_calendar_timestamp() -> None:
    freeze_split = _split_api()
    contract = ArmaGarchAnalysisContract.from_dict(
        {
            "dataset_ref": "dataset:ordered:1",
            "time_column": "when",
            "value_column": "value",
            "time_index_semantics": "observation_order",
            "transform": "level",
            "transform_confirmed": True,
            "validation": {},
        }
    )
    source = pd.DataFrame(
        {"when": range(1, 101), "value": np.linspace(10.0, 20.0, 100)}
    )
    view = prepare_arma_garch_input(source, contract).transformed_view

    split = freeze_split(view, contract)

    assert split.split_timestamp == "80"
