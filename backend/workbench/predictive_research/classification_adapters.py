"""Model-agnostic, bounded classification adapter seam for v1.8.9.

The adapter is deliberately a small boundary around a third-party estimator.
It owns explicit parameter validation, deterministic class/probability
ordering, weight admission, and resource metadata.  It does not select a
split, fit preprocessing, choose a threshold, or decide whether a model is
safe to deploy.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping, Sequence
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from .contracts import ContractError


def _error(code: str, message: str) -> ContractError:
    return ContractError(code, message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)


def _validate_seed(seed: Any) -> int:
    if not isinstance(seed, (int, np.integer)) or isinstance(seed, bool) or int(seed) < 0:
        raise _error("CLASSIFICATION_SEED_INVALID", "seed must be a non-negative integer")
    return int(seed)


def _validate_class_order(class_order: Sequence[Any] | None) -> tuple[Any, ...] | None:
    if class_order is None:
        return None
    if isinstance(class_order, (str, bytes)):
        raise _error("CLASSIFICATION_CLASS_ORDER_INVALID", "class_order must be a sequence of labels, not text")
    try:
        values = tuple(class_order)
    except TypeError as exc:
        raise _error("CLASSIFICATION_CLASS_ORDER_INVALID", "class_order must be a finite sequence") from exc
    if len(values) < 2 or len({repr(value) for value in values}) != len(values):
        raise _error("CLASSIFICATION_CLASS_ORDER_INVALID", "class_order must contain at least two unique labels")
    for value in values:
        try:
            hash(value)
        except TypeError as exc:
            raise _error("CLASSIFICATION_CLASS_ORDER_INVALID", "class labels must be hashable") from exc
        try:
            if bool(pd.isna(value)):
                raise _error("CLASSIFICATION_CLASS_ORDER_INVALID", "class labels cannot be missing")
        except (TypeError, ValueError):
            raise _error("CLASSIFICATION_CLASS_ORDER_INVALID", "class labels must be scalar values")
    return values


def _deterministic_class_order(values: Sequence[Any]) -> tuple[Any, ...]:
    try:
        return tuple(sorted(set(values)))
    except TypeError:
        return tuple(sorted(set(values), key=lambda value: (type(value).__name__, repr(value))))


def _numeric_matrix(frame: pd.DataFrame, *, max_rows: int | None = None) -> np.ndarray:
    if not isinstance(frame, pd.DataFrame) or frame.empty or frame.shape[1] == 0:
        raise _error("CLASSIFICATION_FEATURES_REQUIRED", "adapter features must be a non-empty DataFrame")
    if max_rows is not None and len(frame) > max_rows:
        raise _error("CLASSIFICATION_RESOURCE_LIMIT", "feature rows exceed the declared adapter resource bound")
    if any(not isinstance(column, str) or not column.strip() for column in frame.columns):
        raise _error("CLASSIFICATION_FEATURE_SCHEMA_INVALID", "feature columns must have non-empty names")
    if not frame.columns.is_unique:
        raise _error("CLASSIFICATION_FEATURE_SCHEMA_INVALID", "feature columns must be unique")
    for column in frame.columns:
        if not pd.api.types.is_numeric_dtype(frame[column]):
            raise _error(
                "CLASSIFICATION_FEATURE_TYPE_BLOCKED",
                "non-numeric adapter input requires an explicit fold-local recipe",
            )
    converted = frame.to_numpy(dtype=float, copy=True)
    if converted.ndim != 2 or not np.isfinite(converted).all():
        raise _error("CLASSIFICATION_FEATURE_TYPE_BLOCKED", "adapter features must be finite numeric values")
    return converted


def _validate_parameters(
    declaration: "AdapterDeclarationV1",
    parameters: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if parameters is not None and not isinstance(parameters, Mapping):
        raise _error("CLASSIFICATION_PARAMETERS_INVALID", "parameters must be an object")
    supplied = dict(parameters or {})
    unknown = sorted(set(supplied) - set(declaration.parameter_schema))
    if unknown:
        raise _error("CLASSIFICATION_PARAMETER_UNKNOWN", f"unknown adapter parameter: {unknown[0]}")
    values = dict(declaration.defaults)
    values.update(supplied)
    for name, value in values.items():
        spec = declaration.parameter_schema[name]
        kind = spec["type"]
        if kind == "integer":
            if not isinstance(value, (int, np.integer)) or isinstance(value, bool):
                raise _error("CLASSIFICATION_PARAMETER_INVALID", f"{name} must be an integer")
            value = int(value)
            values[name] = value
        elif kind == "number":
            if not _is_number(value) or not math.isfinite(float(value)):
                raise _error("CLASSIFICATION_PARAMETER_INVALID", f"{name} must be finite numeric")
            value = float(value)
            values[name] = value
        elif kind == "enum":
            if value not in spec["values"]:
                raise _error("CLASSIFICATION_PARAMETER_INVALID", f"{name} has an unsupported value")
        elif kind == "nullable_integer":
            if value is not None and (
                not isinstance(value, (int, np.integer)) or isinstance(value, bool)
            ):
                raise _error("CLASSIFICATION_PARAMETER_INVALID", f"{name} must be an integer or null")
            if value is not None:
                values[name] = int(value)
        lower = spec.get("minimum")
        upper = spec.get("maximum")
        if value is not None and lower is not None and value < lower:
            raise _error("CLASSIFICATION_PARAMETER_OUT_OF_BOUNDS", f"{name} is below its minimum")
        if value is not None and upper is not None and value > upper:
            raise _error("CLASSIFICATION_PARAMETER_OUT_OF_BOUNDS", f"{name} exceeds its maximum")
    return values


@dataclass(frozen=True)
class AdapterDeclarationV1:
    """Public catalog entry for one estimator family."""

    model_id: str
    version: str
    parameter_schema: dict[str, Any]
    defaults: dict[str, Any]
    explanation_kinds: tuple[str, ...]
    resource_class: str
    resource_bounds: dict[str, Any]
    resource_parameters: tuple[str, ...]
    supports_weight: bool
    build_estimator: Callable[[int, Mapping[str, Any]], Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "parameter_schema": dict(self.parameter_schema),
            "defaults": dict(self.defaults),
            "explanation_kinds": list(self.explanation_kinds),
            "resource_class": self.resource_class,
            "resource_bounds": dict(self.resource_bounds),
            "resource_parameters": list(self.resource_parameters),
            "supports_weight": self.supports_weight,
        }


class ClassificationAdapterV1:
    """Typed adapter interface shared by all admitted classification models."""

    declaration: AdapterDeclarationV1

    def __init__(
        self,
        *,
        seed: int = 0,
        parameters: Mapping[str, Any] | None = None,
        class_order: Sequence[Any] | None = None,
        resource_budget: Mapping[str, Any] | None = None,
    ) -> None:
        self.seed = _validate_seed(seed)
        if parameters is not None and resource_budget is not None:
            raise _error("CLASSIFICATION_PARAMETERS_INVALID", "use parameters or resource_budget, not both")
        raw_parameters = parameters if parameters is not None else resource_budget
        self.parameters = _validate_parameters(self.declaration, raw_parameters)
        self._requested_class_order = _validate_class_order(class_order)
        self.estimator: Any | None = None
        self._feature_names: tuple[str, ...] = ()
        self._class_order: tuple[Any, ...] = ()
        # Compatibility read surface for the package-local protocol.  It is
        # populated only after fit and always follows the canonical returned
        # probability order.
        self._classes: tuple[Any, ...] = ()
        self._estimator_class_order: tuple[Any, ...] = ()
        self._warnings: tuple[str, ...] = ()

    @property
    def supports_weight(self) -> bool:
        return self.declaration.supports_weight

    @property
    def feature_names(self) -> tuple[str, ...]:
        if not self._feature_names:
            raise _error("CLASSIFICATION_ADAPTER_NOT_FIT", "feature names are unavailable before fit")
        return self._feature_names

    @property
    def class_order(self) -> tuple[Any, ...]:
        if not self._class_order:
            raise _error("CLASSIFICATION_ADAPTER_NOT_FIT", "class order is unavailable before fit")
        return self._class_order

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "model_id": self.declaration.model_id,
            "version": self.declaration.version,
            "random_seed": self.seed,
            "actual_parameters": dict(self.parameters),
            "class_order": list(self._class_order),
            "supports_weight": self.supports_weight,
            "resource_class": self.declaration.resource_class,
            "resource_bounds": dict(self.declaration.resource_bounds),
            "warnings": list(self._warnings),
        }

    @property
    def resource_estimate(self) -> dict[str, Any]:
        estimate = {
            "resource_class": self.declaration.resource_class,
            "max_cpu_seconds": self.parameters["max_cpu_seconds"],
            "max_rows": self.parameters["max_rows"],
        }
        for parameter in self.declaration.resource_parameters:
            estimate[parameter] = self.parameters[parameter]
        return estimate

    @property
    def explanation_capabilities(self) -> tuple[str, ...]:
        return self.declaration.explanation_kinds

    def fit(
        self,
        features: pd.DataFrame,
        target: Sequence[Any],
        *,
        sample_weight: Sequence[float] | None = None,
        class_order: Sequence[Any] | None = None,
    ) -> "ClassificationAdapterV1":
        matrix = _numeric_matrix(features, max_rows=self.parameters["max_rows"])
        labels = np.asarray(target)
        if labels.ndim != 1 or len(labels) != len(matrix):
            raise _error("CLASSIFICATION_TARGET_ALIGNMENT", "target must align with feature rows")
        if len(labels) == 0 or pd.isna(labels).any():
            raise _error("CLASSIFICATION_TARGET_INVALID", "target must be non-empty and non-missing")
        try:
            observed = tuple(dict.fromkeys(labels.tolist()))
            observed_set = set(observed)
        except (TypeError, ValueError) as exc:
            raise _error("CLASSIFICATION_TARGET_INVALID", "target labels must be hashable") from exc
        if len(observed) < 2:
            raise _error("CLASSIFICATION_SINGLE_CLASS", "classification fit requires at least two classes")
        fit_order = _validate_class_order(class_order)
        if fit_order is not None and self._requested_class_order is not None and fit_order != self._requested_class_order:
            raise _error("CLASSIFICATION_CLASS_ORDER_MISMATCH", "fit class order conflicts with adapter class order")
        requested = fit_order if fit_order is not None else self._requested_class_order
        if requested is None:
            requested = _deterministic_class_order(observed)
        if set(requested) != observed_set or len(requested) != len(observed):
            raise _error("CLASSIFICATION_CLASS_ORDER_MISMATCH", "class_order must match all observed target classes")
        weights: np.ndarray | None = None
        if sample_weight is not None:
            if not self.supports_weight:
                raise _error("CLASSIFICATION_WEIGHT_UNSUPPORTED", "adapter does not support sample weights")
            weights = np.asarray(sample_weight, dtype=float)
            if (
                weights.ndim != 1
                or len(weights) != len(labels)
                or not np.isfinite(weights).all()
                or (weights < 0).any()
                or float(weights.sum()) <= 0
            ):
                raise _error("CLASSIFICATION_WEIGHT_INVALID", "sample_weight must be finite, non-negative and positive")
        try:
            estimator = self.declaration.build_estimator(self.seed, self.parameters)
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                if weights is None:
                    estimator.fit(matrix, labels)
                else:
                    estimator.fit(matrix, labels, sample_weight=weights)
            convergence = [item for item in captured if issubclass(item.category, ConvergenceWarning)]
            if convergence:
                raise _error("CLASSIFICATION_NONCONVERGENCE", "estimator reported non-convergence")
            estimator_order = tuple(estimator.classes_.tolist())
        except ContractError:
            raise
        except (TypeError, ValueError, RuntimeError) as exc:
            raise _error("CLASSIFICATION_ADAPTER_FIT_FAILED", "typed estimator fit failed") from exc
        if set(estimator_order) != observed_set or len(estimator_order) != len(observed):
            raise _error("CLASSIFICATION_CLASS_ORDER_MISMATCH", "estimator class order does not match target classes")
        self.estimator = estimator
        self._feature_names = tuple(str(column) for column in features.columns)
        self._class_order = tuple(requested)
        self._classes = self._class_order
        self._estimator_class_order = estimator_order
        self._warnings = tuple(str(item.message) for item in captured)
        return self

    def _require_fit(self) -> Any:
        if self.estimator is None:
            raise _error("CLASSIFICATION_ADAPTER_NOT_FIT", "adapter must be fit before prediction")
        return self.estimator

    def _reorder_probabilities(self, probabilities: np.ndarray) -> np.ndarray:
        estimator = self._require_fit()
        if (
            probabilities.ndim != 2
            or probabilities.shape[1] != len(self._class_order)
            or not np.isfinite(probabilities).all()
            or (probabilities < -1e-12).any()
            or (probabilities > 1 + 1e-12).any()
            or not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-8)
        ):
            raise _error("CLASSIFICATION_PROBABILITY_INVALID", "adapter did not return valid class probabilities")
        try:
            indexes = [self._estimator_class_order.index(label) for label in self._class_order]
        except ValueError as exc:
            raise _error("CLASSIFICATION_CLASS_ORDER_MISMATCH", "prediction class order changed after fit") from exc
        reordered = probabilities[:, indexes]
        if tuple(estimator.classes_.tolist()) != self._estimator_class_order:
            raise _error("CLASSIFICATION_CLASS_ORDER_MISMATCH", "estimator class order changed after fit")
        return reordered

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        estimator = self._require_fit()
        matrix = _numeric_matrix(features, max_rows=self.parameters["max_rows"])
        try:
            probabilities = np.asarray(estimator.predict_proba(matrix), dtype=float)
        except (TypeError, ValueError, RuntimeError) as exc:
            raise _error("CLASSIFICATION_ADAPTER_PREDICT_FAILED", "typed estimator probability prediction failed") from exc
        return self._reorder_probabilities(probabilities)

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        estimator = self._require_fit()
        matrix = _numeric_matrix(features, max_rows=self.parameters["max_rows"])
        try:
            predictions = np.asarray(estimator.predict(matrix))
        except (TypeError, ValueError, RuntimeError) as exc:
            raise _error("CLASSIFICATION_ADAPTER_PREDICT_FAILED", "typed estimator prediction failed") from exc
        if predictions.ndim != 1 or not set(predictions.tolist()).issubset(set(self._class_order)):
            raise _error("CLASSIFICATION_PREDICTION_INVALID", "estimator returned unknown class labels")
        return predictions

    def predict_at_threshold(
        self,
        features: pd.DataFrame,
        *,
        threshold: float,
        positive_class: Any | None = None,
    ) -> np.ndarray:
        if not _is_number(threshold) or not math.isfinite(float(threshold)) or not 0 <= float(threshold) <= 1:
            raise _error("CLASSIFICATION_THRESHOLD_INVALID", "threshold must be between zero and one")
        if len(self.class_order) != 2:
            raise _error("CLASSIFICATION_THRESHOLD_BINARY_ONLY", "threshold prediction requires a binary adapter")
        positive = self.class_order[-1] if positive_class is None else positive_class
        if positive not in self.class_order:
            raise _error("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is not in adapter class order")
        positive_index = self.class_order.index(positive)
        negative = self.class_order[1 - positive_index]
        probability = self.predict_proba(features)[:, positive_index]
        return np.where(probability >= float(threshold), positive, negative)


def _build_logistic(seed: int, parameters: Mapping[str, Any]) -> LogisticRegression:
    return LogisticRegression(
        C=float(parameters["C"]),
        solver="lbfgs",
        penalty="l2",
        max_iter=int(parameters["max_iter"]),
        tol=float(parameters["tol"]),
        random_state=seed,
    )


def _build_random_forest(seed: int, parameters: Mapping[str, Any]) -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=int(parameters["n_estimators"]),
        max_depth=parameters["max_depth"],
        min_samples_leaf=int(parameters["min_samples_leaf"]),
        max_features=parameters["max_features"],
        n_jobs=1,
        random_state=seed,
    )


_LOGISTIC_DECLARATION = AdapterDeclarationV1(
    model_id="logistic_regression",
    version="1.0",
    parameter_schema={
        "C": {"type": "number", "minimum": 0.0001, "maximum": 1000.0},
        "max_iter": {"type": "integer", "minimum": 50, "maximum": 2000},
        "tol": {"type": "number", "minimum": 1e-8, "maximum": 1.0},
        "max_cpu_seconds": {"type": "number", "minimum": 0.1, "maximum": 3600.0},
        "max_rows": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
    },
    defaults={"C": 1.0, "max_iter": 200, "tol": 1e-4, "max_cpu_seconds": 30.0, "max_rows": 1_000_000},
    explanation_kinds=("permutation_importance", "coefficient_direction"),
    resource_class="small",
    resource_bounds={"max_cpu_seconds": 3600.0, "max_rows": 1_000_000},
    resource_parameters=(),
    supports_weight=True,
    build_estimator=_build_logistic,
)

_RANDOM_FOREST_DECLARATION = AdapterDeclarationV1(
    model_id="random_forest",
    version="1.0",
    parameter_schema={
        "n_estimators": {"type": "integer", "minimum": 10, "maximum": 500},
        "max_depth": {"type": "nullable_integer", "minimum": 1, "maximum": 32},
        "min_samples_leaf": {"type": "integer", "minimum": 1, "maximum": 1000},
        "max_features": {"type": "enum", "values": ("sqrt", "log2", None)},
        "max_cpu_seconds": {"type": "number", "minimum": 0.1, "maximum": 3600.0},
        "max_rows": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
    },
    defaults={
        "n_estimators": 100,
        "max_depth": 8,
        "min_samples_leaf": 1,
        "max_features": "sqrt",
        "max_cpu_seconds": 60.0,
        "max_rows": 1_000_000,
    },
    explanation_kinds=("permutation_importance", "native_feature_importance"),
    resource_class="bounded",
    resource_bounds={"max_cpu_seconds": 3600.0, "max_rows": 1_000_000, "max_estimators": 500, "max_depth": 32},
    resource_parameters=("n_estimators", "max_depth"),
    supports_weight=True,
    build_estimator=_build_random_forest,
)

class LogisticRegressionAdapterV1(ClassificationAdapterV1):
    declaration = _LOGISTIC_DECLARATION


class RandomForestAdapterV1(ClassificationAdapterV1):
    declaration = _RANDOM_FOREST_DECLARATION


_ADAPTERS: dict[str, type[ClassificationAdapterV1]] = {
    "logistic_regression": LogisticRegressionAdapterV1,
    "random_forest": RandomForestAdapterV1,
}


def adapter_registry() -> dict[str, AdapterDeclarationV1]:
    """Return the server-owned model catalog projection, never a fallback."""

    return dict((model_id, adapter.declaration) for model_id, adapter in _ADAPTERS.items())


def get_classification_adapter(
    model_id: str,
    *,
    seed: int = 0,
    parameters: Mapping[str, Any] | None = None,
    class_order: Sequence[Any] | None = None,
    resource_budget: Mapping[str, Any] | None = None,
) -> ClassificationAdapterV1:
    if not isinstance(model_id, str) or not model_id.strip():
        raise _error("CLASSIFICATION_ADAPTER_UNKNOWN", "model_id must identify an admitted adapter")
    adapter_type = _ADAPTERS.get(model_id)
    if adapter_type is None:
        raise _error("CLASSIFICATION_ADAPTER_UNKNOWN", f"unknown classification adapter {model_id!r}")
    return adapter_type(
        seed=seed,
        parameters=parameters,
        class_order=class_order,
        resource_budget=resource_budget,
    )


__all__ = [
    "AdapterDeclarationV1",
    "ClassificationAdapterV1",
    "LogisticRegressionAdapterV1",
    "RandomForestAdapterV1",
    "adapter_registry",
    "get_classification_adapter",
]
