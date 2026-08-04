"""Fold-local preprocessing primitives for the predictive research kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    transformers: dict[str, Any] = field(default_factory=dict)

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        for step in self.steps:
            if step.transform_id == "mice":
                transformer_key = f"mice:{','.join(step.columns)}"
                transformer = self.transformers.get(transformer_key)
                if transformer is None:
                    raise ContractError(
                        "PREDICTION_PREPROCESSING_STATE_MISSING",
                        f"missing fit state for {transformer_key}",
                    )
                values = transformer.transform(
                    result.loc[:, list(step.columns)].to_numpy(dtype=float, copy=True)
                )
                result.loc[:, list(step.columns)] = values
                continue
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
        transformers: dict[str, Any] = {}
        for step in self.steps:
            if step.fit_semantics not in {"stateless", "date_local", "period_fitted"}:
                raise ContractError("PREDICTION_PREPROCESSING_SEMANTICS_INVALID", "unknown fit semantics")
            if step.fit_semantics == "period_fitted" and step.transform_id not in {"mean_impute", "standard_scale", "mice"}:
                raise ContractError("PREDICTION_PREPROCESSING_UNKNOWN_TRANSFORM", step.transform_id)
            if step.transform_id == "mice":
                if any(not pd.api.types.is_numeric_dtype(frame[column]) for column in step.columns if column in frame.columns):
                    raise ContractError(
                        "PREDICTION_MICE_NON_NUMERIC_MISSING",
                        "fold-local MICE only supports numeric preprocessing columns",
                    )
                missing_columns = [
                    column for column in step.columns
                    if column not in frame.columns or frame[column].isna().any()
                ]
                if any(column not in frame.columns for column in missing_columns):
                    raise ContractError(
                        "PREDICTION_PREPROCESSING_COLUMN_MISSING",
                        ", ".join(column for column in missing_columns if column not in frame.columns),
                    )
                from sklearn.experimental import enable_iterative_imputer  # noqa: F401
                from sklearn.impute import IterativeImputer

                transformer = IterativeImputer(
                    max_iter=10,
                    random_state=0,
                    sample_posterior=False,
                    keep_empty_features=True,
                )
                transformer.fit(frame.loc[:, list(step.columns)].to_numpy(dtype=float, copy=True))
                transformers[f"mice:{','.join(step.columns)}"] = transformer
                continue
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
        return FittedPreprocessorV1(
            steps=self.steps,
            fit_scope=fit_scope,
            state=state,
            transformers=transformers,
        )
