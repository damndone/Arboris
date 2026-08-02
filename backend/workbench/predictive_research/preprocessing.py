"""Fold-local preprocessing primitives for the predictive research kernel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .contracts import ContractError


@dataclass(frozen=True)
class PreprocessingStepV1:
    transform_id: str
    transform_version: int
    fit_semantics: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class FittedPreprocessorV1:
    steps: tuple[PreprocessingStepV1, ...]
    fit_scope: str
    state: dict[str, dict[str, float]]

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        for step in self.steps:
            for column in step.columns:
                key = f"{step.transform_id}:{column}"
                if key not in self.state:
                    raise ContractError("PREDICTION_PREPROCESSING_STATE_MISSING", f"missing fit state for {key}")
                if step.transform_id == "mean_impute":
                    result[column] = result[column].fillna(self.state[key]["mean"])
                elif step.transform_id == "standard_scale":
                    scale = self.state[key]["scale"] or 1.0
                    result[column] = (result[column] - self.state[key]["mean"]) / scale
                else:
                    raise ContractError("PREDICTION_PREPROCESSING_UNKNOWN_TRANSFORM", step.transform_id)
        return result


class FoldPreprocessingKernel:
    def __init__(self, *, steps: tuple[PreprocessingStepV1, ...]):
        self.steps = tuple(steps)

    def fit(self, frame: pd.DataFrame, *, fit_scope: str) -> FittedPreprocessorV1:
        if fit_scope == "final_holdout" or not fit_scope.startswith(("development_fold_", "development")):
            raise ContractError(
                "PREDICTION_PREPROCESSING_FIT_SCOPE_INVALID",
                "fit-state may only be learned from a development training fold",
            )
        state: dict[str, dict[str, float]] = {}
        for step in self.steps:
            if step.fit_semantics not in {"stateless", "date_local", "period_fitted"}:
                raise ContractError("PREDICTION_PREPROCESSING_SEMANTICS_INVALID", "unknown fit semantics")
            if step.fit_semantics == "period_fitted" and step.transform_id not in {"mean_impute", "standard_scale"}:
                raise ContractError("PREDICTION_PREPROCESSING_UNKNOWN_TRANSFORM", step.transform_id)
            for column in step.columns:
                if column not in frame.columns:
                    raise ContractError("PREDICTION_PREPROCESSING_COLUMN_MISSING", column)
                if step.fit_semantics == "period_fitted":
                    values = pd.to_numeric(frame[column], errors="coerce")
                    mean = float(values.mean())
                    if pd.isna(mean):
                        raise ContractError("PREDICTION_PREPROCESSING_NO_FIT_DATA", column)
                    scale = float(values.std(ddof=0)) if step.transform_id == "standard_scale" else 0.0
                    state[f"{step.transform_id}:{column}"] = {"mean": mean, "scale": scale}
        return FittedPreprocessorV1(steps=self.steps, fit_scope=fit_scope, state=state)
