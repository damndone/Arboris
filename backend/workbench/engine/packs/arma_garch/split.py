"""Deterministic train/validation freeze before any candidate selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import math
from typing import Literal

import pandas as pd

from workbench.canonical import sha256_canonical
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.errors import (
    ArmaGarchDiagnostic,
    ArmaGarchInputError,
    diagnostic,
)
from workbench.engine.packs.arma_garch.input import (
    PARSED_TIME_COLUMN,
    ROW_ID_COLUMN,
    dataframe_canonical_hash,
)


@dataclass(frozen=True)
class FrozenTrainValidationSplit:
    split_index: int
    split_timestamp: str
    training_row_ids: tuple[str, ...]
    validation_row_ids: tuple[str, ...]
    validation_n: int
    n_train: int
    analysis_view_hash: str
    contract_hash: str
    method: Literal["expanding_window_one_step"]
    refit_every: int
    selection_repeated_during_validation: Literal[False]
    forecast_validation_status: Literal["pending", "inconclusive"]
    diagnostics: tuple[ArmaGarchDiagnostic, ...]
    _training_view: pd.DataFrame = field(repr=False)
    _validation_view: pd.DataFrame = field(repr=False)
    split_hash: str

    @property
    def training_view(self) -> pd.DataFrame:
        return self._training_view.copy(deep=True)

    @property
    def validation_view(self) -> pd.DataFrame:
        return self._validation_view.copy(deep=True)

    def hash_payload(self) -> dict[str, object]:
        return {
            "analysis_view_hash": self.analysis_view_hash,
            "contract_hash": self.contract_hash,
            "split_index": self.split_index,
            "split_timestamp": self.split_timestamp,
            "training_row_ids": list(self.training_row_ids),
            "validation_row_ids": list(self.validation_row_ids),
            "validation_n": self.validation_n,
            "n_train": self.n_train,
            "method": self.method,
            "refit_every": self.refit_every,
            "selection_repeated_during_validation": self.selection_repeated_during_validation,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.hash_payload(),
            "split_hash": self.split_hash,
            "forecast_validation_status": self.forecast_validation_status,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def freeze_train_validation_split(
    transformed_view: pd.DataFrame,
    contract: ArmaGarchAnalysisContract,
) -> FrozenTrainValidationSplit:
    """Freeze row membership and data copies before model selection is allowed."""

    required = {ROW_ID_COLUMN, PARSED_TIME_COLUMN}
    missing = sorted(required - set(transformed_view.columns))
    if missing:
        raise ArmaGarchInputError(
            diagnostic(
                "INSUFFICIENT_OBSERVATIONS",
                "transformed analysis view is missing required lineage columns",
                evidence={"missing_columns": missing},
                impact="A reproducible train/validation boundary cannot be frozen.",
            )
        )
    row_ids = tuple(transformed_view[ROW_ID_COLUMN].astype(str))
    if len(set(row_ids)) != len(row_ids):
        raise ArmaGarchInputError(
            diagnostic(
                "DUPLICATE_TIMESTAMP",
                "analysis row identifiers must be unique before split freeze",
                evidence={"row_count": len(row_ids), "unique_row_count": len(set(row_ids))},
                impact="Training and validation membership would be ambiguous.",
            )
        )
    if not transformed_view[PARSED_TIME_COLUMN].is_monotonic_increasing:
        raise ArmaGarchInputError(
            diagnostic(
                "IRREGULAR_INDEX_UNCONFIRMED",
                "analysis view must be sorted before split freeze",
                evidence={"is_monotonic_increasing": False},
                impact="A tail validation interval cannot be identified safely.",
            )
        )

    n_effective = len(transformed_view)
    validation_n = contract.validation.validation_n
    if validation_n is None:
        validation_n = min(max(20, math.ceil(0.20 * n_effective)), 250)
    if n_effective < 2 or validation_n >= n_effective:
        raise ArmaGarchInputError(
            diagnostic(
                "BACKTEST_WINDOW_TOO_SHORT",
                "validation interval leaves no non-empty training interval",
                evidence={
                    "n_effective": n_effective,
                    "validation_n": validation_n,
                },
                impact="One-step expanding validation cannot be initialized.",
            )
        )

    split_index = n_effective - validation_n
    training = transformed_view.iloc[:split_index].copy(deep=True).reset_index(drop=True)
    validation = transformed_view.iloc[split_index:].copy(deep=True).reset_index(drop=True)
    training_ids = tuple(training[ROW_ID_COLUMN].astype(str))
    validation_ids = tuple(validation[ROW_ID_COLUMN].astype(str))
    split_timestamp = _split_boundary_text(
        training.iloc[-1][PARSED_TIME_COLUMN], contract.time_index_semantics
    )
    analysis_view_hash = dataframe_canonical_hash(transformed_view)
    minimum_training_n = _minimum_training_observations(contract)
    diagnostics: tuple[ArmaGarchDiagnostic, ...] = ()
    forecast_status: Literal["pending", "inconclusive"] = "pending"
    if len(training) < minimum_training_n or validation_n < 20:
        diagnostics = (
            diagnostic(
                "INSUFFICIENT_OBSERVATIONS",
                "the frozen training or validation interval is too short for stable acceptance",
                evidence={
                    "n_train": len(training),
                    "validation_n": validation_n,
                    "minimum_training_n": minimum_training_n,
                },
                impact="Estimation may proceed only where later model gates allow, but forecast validation is inconclusive.",
                severity="warning",
            ),
        )
        forecast_status = "inconclusive"

    hash_payload = {
        "analysis_view_hash": analysis_view_hash,
        "contract_hash": contract.contract_hash,
        "split_index": split_index,
        "split_timestamp": split_timestamp,
        "training_row_ids": list(training_ids),
        "validation_row_ids": list(validation_ids),
        "validation_n": validation_n,
        "n_train": len(training),
        "method": contract.validation.method,
        "refit_every": contract.validation.refit_every,
        "selection_repeated_during_validation": False,
    }
    return FrozenTrainValidationSplit(
        split_index=split_index,
        split_timestamp=split_timestamp,
        training_row_ids=training_ids,
        validation_row_ids=validation_ids,
        validation_n=validation_n,
        n_train=len(training),
        analysis_view_hash=analysis_view_hash,
        contract_hash=contract.contract_hash,
        method="expanding_window_one_step",
        refit_every=contract.validation.refit_every,
        selection_repeated_during_validation=False,
        forecast_validation_status=forecast_status,
        diagnostics=diagnostics,
        _training_view=training,
        _validation_view=validation,
        split_hash=sha256_canonical(hash_payload),
    )


def _minimum_training_observations(contract: ArmaGarchAnalysisContract) -> int:
    if contract.selection_mode == "manual":
        mean_parameters = (contract.arma.p or 0) + (contract.arma.q or 0) + 1
        variance_parameters = max(
            contract.variance.arch_p or 0,
            (contract.variance.garch_p or 0) + (contract.variance.garch_q or 0) + 1,
        )
        maximum_parameters = max(mean_parameters, variance_parameters)
    else:
        maximum_parameters = max(
            contract.arma.auto_max_total_order + 1,
            contract.variance.auto_arch_max_p + 1,
        )
    return max(50, 10 * maximum_parameters)


def _timestamp_text(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _split_boundary_text(value: object, semantics: str) -> str:
    if semantics == "observation_order":
        # Observation-order semantics deliberately make no claim about a
        # calendar frequency.  A CSV date label is still retained as truthful
        # boundary metadata, though: `prepare_arma_garch_input` may parse it
        # into a Timestamp after establishing order.  Do not coerce that
        # Timestamp to a numeric epoch merely because the fit uses observation
        # order; doing so either fails or falsely presents nanoseconds as an
        # observation index.
        if isinstance(value, (pd.Timestamp, datetime, date)):
            return _timestamp_text(value)
        return f"{float(value):g}"
    return _timestamp_text(value)


__all__ = ["FrozenTrainValidationSplit", "freeze_train_validation_split"]
