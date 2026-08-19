"""Fold-local preprocessing primitives for the predictive research kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
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


@dataclass(frozen=True)
class ClassificationPreprocessingStepV1:
    step_id: str
    kind: str
    columns: tuple[str, ...]
    supports_weight: bool
    seed: int = 0
    recipe_version: str = "1.0"


@dataclass(frozen=True)
class ClassificationFittedPreprocessorV1:
    steps: tuple[ClassificationPreprocessingStepV1, ...]
    fit_row_refs: tuple[str, ...]
    state: dict[str, dict[str, Any]]
    receipt: dict[str, Any]

    def transform(self, frame: Any, *, row_refs: tuple[str, ...] | list[str]) -> pd.DataFrame:
        result = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
        if len(result) != len(row_refs):
            raise ContractError("CLASSIFICATION_PREPROCESSING_ALIGNMENT", "row_refs must align with transform rows")
        for step in self.steps:
            if step.kind not in {"mean_impute", "standard_scale"}:
                raise ContractError("CLASSIFICATION_PREPROCESSING_KIND_UNSUPPORTED", step.kind)
            for column in step.columns:
                key = f"{step.step_id}:{column}"
                if key not in self.state or column not in result.columns:
                    raise ContractError("CLASSIFICATION_PREPROCESSING_STATE_MISSING", key)
                values = pd.to_numeric(result[column], errors="coerce")
                if step.kind == "mean_impute":
                    result[column] = values.fillna(self.state[key]["mean"])
                else:
                    result[column] = (values - self.state[key]["mean"]) / (self.state[key]["scale"] or 1.0)
        return result


class ClassificationFoldPreprocessingV1:
    """A small fold-local transformer with an auditable fit-row receipt."""

    def __init__(self, *, steps: tuple[ClassificationPreprocessingStepV1, ...], seed: int = 0):
        self.steps = tuple(steps)
        self.seed = seed

    def fit(
        self,
        frame: Any,
        *,
        fit_row_refs: tuple[str, ...] | list[str],
        fit_rows: dict[str, dict[str, Any]],
        weight_name: str | None = None,
    ) -> ClassificationFittedPreprocessorV1:
        refs = tuple(fit_row_refs)
        if not refs or len(set(refs)) != len(refs) or set(refs) != set(fit_rows):
            raise ContractError("CLASSIFICATION_PREPROCESSING_FIT_ROWS_INVALID", "fit_row_refs must exactly identify fit_rows")
        for step in self.steps:
            if not step.step_id.strip() or not step.columns:
                raise ContractError("CLASSIFICATION_PREPROCESSING_CONTRACT_INVALID", "step id and columns are required")
            if weight_name is not None and not step.supports_weight:
                raise ContractError("CLASSIFICATION_WEIGHT_UNSUPPORTED", f"step {step.step_id!r} ignores weights")
        fit_frame = pd.DataFrame([fit_rows[ref] for ref in refs])
        state: dict[str, dict[str, Any]] = {}
        output_schema: list[str] = []
        for step in self.steps:
            if step.kind not in {"mean_impute", "standard_scale"}:
                raise ContractError("CLASSIFICATION_PREPROCESSING_KIND_UNSUPPORTED", step.kind)
            for column in step.columns:
                if column not in fit_frame.columns:
                    raise ContractError("CLASSIFICATION_PREPROCESSING_COLUMN_MISSING", column)
                values = pd.to_numeric(fit_frame[column], errors="coerce")
                if values.isna().all():
                    raise ContractError("CLASSIFICATION_PREPROCESSING_ALL_MISSING", column)
                mean = float(values.mean())
                scale = float(values.std(ddof=0)) if step.kind == "standard_scale" else 0.0
                state[f"{step.step_id}:{column}"] = {"mean": mean, "scale": scale}
                output_schema.append(column)
        receipt = {
            "fit_scope": "training_fold_only",
            "fit_row_refs": list(refs),
            "recipe_hash": hashlib.sha256(json.dumps([step.__dict__ for step in self.steps], sort_keys=True).encode()).hexdigest(),
            "seed": self.seed,
            "output_schema": output_schema,
            "weight_name": weight_name,
        }
        return ClassificationFittedPreprocessorV1(
            steps=self.steps,
            fit_row_refs=refs,
            state=state,
            receipt=receipt,
        )
