"""Fold-local preprocessing primitives for the predictive research kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from typing import Any

import pandas as pd

from .contracts import ContractError
from .classification_contracts import ClassificationPreprocessingStepV1


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


def _classification_missing(value: Any) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        result = pd.isna(value)
        return bool(result) if not hasattr(result, "__len__") else False
    except (TypeError, ValueError):
        return False


def _classification_numeric(values: list[Any], *, column: str) -> pd.Series:
    non_missing = [value for value in values if not _classification_missing(value)]
    if any(isinstance(value, (Mapping, list, tuple, set)) for value in non_missing):
        raise ContractError("CLASSIFICATION_PREPROCESSING_NESTED_UNSUPPORTED", column)
    if any(isinstance(value, str) for value in non_missing):
        raise ContractError("CLASSIFICATION_PREPROCESSING_FREE_TEXT_UNSUPPORTED", column)
    if any(isinstance(value, (dt.date, dt.datetime, pd.Timestamp)) for value in non_missing):
        raise ContractError("CLASSIFICATION_PREPROCESSING_DATETIME_RECIPE_REQUIRED", column)
    converted = pd.to_numeric(pd.Series(values, dtype="object"), errors="coerce")
    if converted.notna().sum() != len(non_missing):
        raise ContractError("CLASSIFICATION_PREPROCESSING_NON_NUMERIC", column)
    return converted


def _classification_datetime_component(recipe: str | Mapping[str, Any] | None, *, column: str) -> str:
    if recipe is None:
        raise ContractError("CLASSIFICATION_PREPROCESSING_DATETIME_RECIPE_REQUIRED", column)
    component = recipe if isinstance(recipe, str) else recipe.get("component")
    if component not in {"year", "month", "day", "dayofweek"}:
        raise ContractError("CLASSIFICATION_PREPROCESSING_RECIPE_INVALID", f"datetime recipe for {column} is unsupported")
    return str(component)


def _classification_recipe_hash(steps: tuple[ClassificationPreprocessingStepV1, ...]) -> str:
    payload = [step.to_dict() for step in steps]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ClassificationFittedPreprocessorV1:
    steps: tuple[ClassificationPreprocessingStepV1, ...]
    fit_row_refs: tuple[str, ...]
    state: dict[str, dict[str, Any]]
    receipt: dict[str, Any]

    def transform(self, frame: Any, *, row_refs: tuple[str, ...] | list[str]) -> pd.DataFrame:
        result = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
        refs = tuple(row_refs)
        if len(result) != len(refs) or len(set(refs)) != len(refs):
            raise ContractError(
                "CLASSIFICATION_PREPROCESSING_ALIGNMENT",
                "row_refs must be unique and align with transform rows",
            )
        for step in self.steps:
            step.validate()
            for column in step.columns:
                if column not in result.columns:
                    raise ContractError("CLASSIFICATION_PREPROCESSING_COLUMN_MISSING", column)
                values = result[column].tolist()
                if step.kind in {"mean_impute", "standard_scale"}:
                    numeric = _classification_numeric(values, column=column)
                    # ``_classification_numeric`` is built from a plain
                    # values list, so pandas gives it a fresh RangeIndex.
                    # Rebind that series to the server-owned row identity
                    # before assigning it back; otherwise a non-default row
                    # index aligns to no labels and silently produces NaNs.
                    numeric.index = result.index
                    key = f"{step.step_id}:{column}"
                    if key not in self.state:
                        raise ContractError("CLASSIFICATION_PREPROCESSING_STATE_MISSING", key)
                    if step.kind == "mean_impute":
                        result[column] = numeric.fillna(self.state[key]["mean"])
                    else:
                        scale = self.state[key]["scale"] or 1.0
                        result[column] = (numeric - self.state[key]["mean"]) / scale
                elif step.kind in {"one_hot", "categorical_one_hot"}:
                    key = f"{step.step_id}:{column}"
                    if key not in self.state:
                        raise ContractError("CLASSIFICATION_PREPROCESSING_STATE_MISSING", key)
                    categories = tuple(self.state[key]["categories"])
                    unknown = [
                        value
                        for value in values
                        if not _classification_missing(value) and value not in categories
                    ]
                    if unknown:
                        raise ContractError("CLASSIFICATION_PREPROCESSING_UNKNOWN_CATEGORY", column)
                    for category in categories:
                        output = f"{column}=={category}"
                        result[output] = [
                            1 if value == category else 0
                            for value in values
                        ]
                elif step.kind == "datetime_extract":
                    component = _classification_datetime_component(step.recipe, column=column)
                    parsed = pd.to_datetime(result[column], errors="raise")
                    output = f"{column}__{component}"
                    if component == "year":
                        result[output] = parsed.dt.year
                    elif component == "month":
                        result[output] = parsed.dt.month
                    elif component == "day":
                        result[output] = parsed.dt.day
                    else:
                        result[output] = parsed.dt.dayofweek
                else:
                    raise ContractError("CLASSIFICATION_PREPROCESSING_KIND_UNSUPPORTED", step.kind)
        return result


class ClassificationFoldPreprocessingV1:
    """Fit only on an explicit training-row map and return an audit receipt."""

    def __init__(self, *, steps: tuple[ClassificationPreprocessingStepV1, ...], seed: int = 0):
        self.steps = tuple(steps)
        self.seed = seed

    def fit(
        self,
        frame: Any,
        *,
        fit_row_refs: tuple[str, ...] | list[str],
        fit_rows: Mapping[str, Mapping[str, Any]],
        weight_name: str | None = None,
    ) -> ClassificationFittedPreprocessorV1:
        del frame  # fit_rows is the server-bound row identity, not an ambient frame slice.
        refs = tuple(fit_row_refs)
        if not refs or len(set(refs)) != len(refs) or set(refs) != set(fit_rows):
            raise ContractError(
                "CLASSIFICATION_PREPROCESSING_FIT_ROWS_INVALID",
                "fit_row_refs must exactly identify fit_rows",
            )
        if weight_name is not None and (not isinstance(weight_name, str) or not weight_name.strip()):
            raise ContractError("CLASSIFICATION_WEIGHT_INVALID", "weight_name must be non-empty text")
        for step in self.steps:
            step.validate()
            if weight_name is not None and not step.supports_weight:
                raise ContractError(
                    "CLASSIFICATION_WEIGHT_UNSUPPORTED",
                    f"step {step.step_id!r} ignores declared weight",
                )

        fit_rows_ordered = [fit_rows[ref] for ref in refs]
        if any(not isinstance(row, Mapping) for row in fit_rows_ordered):
            raise ContractError("CLASSIFICATION_PREPROCESSING_FIT_ROWS_INVALID", "fit rows must be objects")
        state: dict[str, dict[str, Any]] = {}
        output_schema: list[str] = []
        weight_values: list[float] | None = None
        if weight_name is not None and all(weight_name in row for row in fit_rows_ordered):
            raw_weights = [row[weight_name] for row in fit_rows_ordered]
            weight_series = _classification_numeric(raw_weights, column=weight_name)
            if weight_series.isna().any() or (weight_series < 0).any() or float(weight_series.sum()) <= 0:
                raise ContractError("CLASSIFICATION_WEIGHT_INVALID", "weights must be finite, non-negative and non-zero")
            weight_values = [float(value) for value in weight_series]

        for step in self.steps:
            for column in step.columns:
                if any(column not in row for row in fit_rows_ordered):
                    raise ContractError("CLASSIFICATION_PREPROCESSING_COLUMN_MISSING", column)
                values = [row.get(column) for row in fit_rows_ordered]
                if all(_classification_missing(value) for value in values):
                    raise ContractError("CLASSIFICATION_PREPROCESSING_ALL_MISSING", column)
                if step.kind in {"mean_impute", "standard_scale"}:
                    numeric = _classification_numeric(values, column=column)
                    key = f"{step.step_id}:{column}"
                    if weight_values is not None:
                        observed = numeric.notna()
                        weights = pd.Series(weight_values)
                        denominator = float(weights[observed].sum())
                        if denominator <= 0:
                            raise ContractError("CLASSIFICATION_PREPROCESSING_ALL_MISSING", column)
                        mean = float((numeric.fillna(0.0) * weights).where(observed, 0.0).sum() / denominator)
                        variance = float(
                            ((numeric.fillna(mean) - mean) ** 2 * weights).where(observed, 0.0).sum() / denominator
                        )
                    else:
                        mean = float(numeric.mean())
                        variance = float(((numeric - mean) ** 2).mean())
                    state[key] = {
                        "mean": mean,
                        "scale": variance**0.5 if step.kind == "standard_scale" else 0.0,
                    }
                    output_schema.append(column)
                elif step.kind in {"one_hot", "categorical_one_hot"}:
                    non_missing = [value for value in values if not _classification_missing(value)]
                    if any(isinstance(value, (Mapping, list, tuple, set)) for value in non_missing):
                        raise ContractError("CLASSIFICATION_PREPROCESSING_NESTED_UNSUPPORTED", column)
                    if any(isinstance(value, (dt.date, dt.datetime, pd.Timestamp)) for value in non_missing):
                        raise ContractError("CLASSIFICATION_PREPROCESSING_DATETIME_RECIPE_REQUIRED", column)
                    categories = tuple(sorted({str(value) for value in non_missing}))
                    if not categories:
                        raise ContractError("CLASSIFICATION_PREPROCESSING_ALL_MISSING", column)
                    if len(categories) > 100:
                        raise ContractError("CLASSIFICATION_PREPROCESSING_FREE_TEXT_UNSUPPORTED", column)
                    state[f"{step.step_id}:{column}"] = {"categories": categories}
                    output_schema.extend(f"{column}=={category}" for category in categories)
                elif step.kind == "datetime_extract":
                    component = _classification_datetime_component(step.recipe, column=column)
                    try:
                        pd.to_datetime(pd.Series(values), errors="raise")
                    except (TypeError, ValueError) as error:
                        raise ContractError("CLASSIFICATION_PREPROCESSING_DATETIME_INVALID", column) from error
                    state[f"{step.step_id}:{column}"] = {"component": component}
                    output_schema.append(f"{column}__{component}")
                else:
                    raise ContractError("CLASSIFICATION_PREPROCESSING_KIND_UNSUPPORTED", step.kind)

        receipt = {
            "fit_scope": "training_fold_only",
            "fit_row_refs": list(refs),
            "recipe_hash": _classification_recipe_hash(self.steps),
            "seed": self.seed,
            "step_seeds": {step.step_id: step.seed for step in self.steps},
            "output_schema": output_schema,
            "weight_name": weight_name,
            "weight_applied": weight_values is not None,
        }
        return ClassificationFittedPreprocessorV1(
            steps=self.steps,
            fit_row_refs=refs,
            state=state,
            receipt=receipt,
        )
