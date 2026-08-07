"""Fail-closed linear and quadratic discriminant analysis kernels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

import numpy as np
import pandas as pd

from workbench.contracts.model.multivariate import make_result_envelope

from .common import MultivariatePackError, json_native


DISCRIMINANT_METHODS = frozenset({"lda", "qda"})
DISCRIMINANT_PRIOR_POLICIES = frozenset({"empirical", "declared"})
DISCRIMINANT_EVALUATIONS = frozenset({"none", "holdout"})


def _normalize_features(features: Sequence[str]) -> list[str]:
    if isinstance(features, (str, bytes)):
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "features must be an array of column names"
        )
    try:
        normalized = list(features)
    except TypeError as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "features must be an array of column names"
        ) from exc
    if len(normalized) < 1 or any(type(feature) is not str or not feature for feature in normalized):
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "features must contain non-empty column names"
        )
    if len(set(normalized)) != len(normalized):
        raise MultivariatePackError(
            "MULTIVARIATE_DUPLICATE_COLUMN", "features must not contain duplicates"
        )
    return normalized


def _normalize_label(value: object) -> str | int:
    if isinstance(value, np.integer):
        return int(value)
    if type(value) in (str, int):
        return value
    raise MultivariatePackError(
        "MULTIVARIATE_BAD_INPUT",
        "target labels must be strings or integers without coercion",
    )


def _prepare_supervised(
    frame: pd.DataFrame,
    features: Sequence[str],
    target: str,
) -> tuple[np.ndarray, list[str | int], tuple[str, ...], tuple[int, ...]]:
    if not isinstance(frame, pd.DataFrame):
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "frame must be a pandas DataFrame"
        )
    normalized_features = _normalize_features(features)
    if type(target) is not str or not target:
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "target must be a non-empty column name"
        )
    if target in normalized_features:
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "target must not also be a feature"
        )
    missing = [column for column in [*normalized_features, target] if column not in frame.columns]
    if missing:
        raise MultivariatePackError(
            "MULTIVARIATE_MISSING_COLUMN", "unknown columns: " + ", ".join(missing)
        )
    selected = frame.loc[:, [*normalized_features, target]].copy()
    for feature in normalized_features:
        dtype = selected[feature].dtype
        if (
            not pd.api.types.is_numeric_dtype(dtype)
            or pd.api.types.is_bool_dtype(dtype)
            or pd.api.types.is_complex_dtype(dtype)
        ):
            raise MultivariatePackError(
                "MULTIVARIATE_NON_NUMERIC_COLUMN",
                f"feature {feature!r} is not a real numeric column",
            )
    mask = selected.notna().all(axis=1)
    retained_positions = tuple(np.flatnonzero(mask.to_numpy()).tolist())
    complete = selected.loc[mask]
    if len(complete) < 4:
        raise MultivariatePackError(
            "MULTIVARIATE_TOO_FEW_OBSERVATIONS",
            "at least four complete observations are required",
        )
    try:
        values = complete.loc[:, normalized_features].to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError) as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_NON_NUMERIC_COLUMN", "features cannot be represented as real numbers"
        ) from exc
    if not np.isfinite(values).all():
        raise MultivariatePackError(
            "MULTIVARIATE_NON_FINITE_VALUE", "features contain non-finite values"
        )
    labels = [_normalize_label(value) for value in complete[target].tolist()]
    class_order = sorted(set(labels), key=lambda value: (type(value).__name__, value))
    if len(class_order) < 2:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "at least two target classes are required"
        )
    counts = {label: labels.count(label) for label in class_order}
    if any(count < 2 for count in counts.values()):
        raise MultivariatePackError(
            "MULTIVARIATE_TOO_FEW_OBSERVATIONS",
            "each target class requires at least two complete observations",
        )
    return values, labels, tuple(normalized_features), retained_positions


def _validate_priors(
    labels: list[str | int],
    class_order: tuple[str | int, ...],
    prior_policy: str,
    priors: Mapping[str | int, float] | None,
) -> np.ndarray:
    if prior_policy == "empirical":
        if priors is not None:
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION", "empirical priors do not accept priors"
            )
        return np.asarray([labels.count(label) / len(labels) for label in class_order], dtype=float)
    if priors is None or not isinstance(priors, Mapping) or set(priors) != set(class_order):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION",
            "declared priors must contain exactly every target class",
        )
    values = np.asarray([priors[label] for label in class_order], dtype=float)
    if (
        not np.isfinite(values).all()
        or np.any(values <= 0.0)
        or not np.isclose(values.sum(), 1.0, atol=1e-12, rtol=0.0)
    ):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION",
            "declared priors must be positive finite values summing to one",
        )
    return values


def _regularized_covariance(covariance: np.ndarray, regularization: float) -> np.ndarray:
    covariance = np.atleast_2d(np.asarray(covariance, dtype=float))
    if regularization > 0.0:
        covariance = covariance + regularization * np.eye(covariance.shape[0])
    sign, _ = np.linalg.slogdet(covariance)
    if sign <= 0.0 or not np.isfinite(covariance).all():
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "covariance is singular or not positive definite; declare positive regularization",
        )
    try:
        np.linalg.inv(covariance)
    except np.linalg.LinAlgError as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "covariance inversion failed; declare positive regularization",
        ) from exc
    return covariance


def _fit_parameters(
    values: np.ndarray,
    labels: list[str | int],
    class_order: tuple[str | int, ...],
    method: str,
    priors: np.ndarray,
    regularization: float,
) -> dict[str, object]:
    means: list[np.ndarray] = []
    covariances: list[np.ndarray] = []
    counts: list[int] = []
    for label in class_order:
        class_values = values[np.asarray([item == label for item in labels])]
        counts.append(len(class_values))
        means.append(class_values.mean(axis=0))
        raw_covariance = np.atleast_2d(np.cov(class_values, rowvar=False, ddof=1))
        if not np.isfinite(raw_covariance).all():
            raise MultivariatePackError(
                "MULTIVARIATE_NUMERIC_DEGENERACY", "class covariance contains non-finite values"
            )
        covariances.append(raw_covariance)
    if method == "lda":
        pooled = sum(
            (count - 1) * covariance
            for count, covariance in zip(counts, covariances)
        ) / (len(values) - len(class_order))
        shared_covariance = _regularized_covariance(pooled, regularization)
        return {
            "means": means,
            "covariances": [shared_covariance],
            "shared_covariance": shared_covariance,
            "counts": counts,
        }
    return {
        "means": means,
        "covariances": [
            _regularized_covariance(covariance, regularization)
            for covariance in covariances
        ],
        "counts": counts,
    }


def _predict(
    values: np.ndarray,
    parameters: dict[str, object],
    class_order: tuple[str | int, ...],
    priors: np.ndarray,
    method: str,
) -> np.ndarray:
    means = parameters["means"]
    covariances = parameters["covariances"]
    scores = np.empty((len(values), len(class_order)), dtype=float)
    for class_index, mean in enumerate(means):
        covariance = parameters["shared_covariance"] if method == "lda" else covariances[class_index]
        inverse = np.linalg.inv(covariance)
        centered = values - mean
        if method == "lda":
            scores[:, class_index] = (
                values @ inverse @ mean
                - 0.5 * mean @ inverse @ mean
                + np.log(priors[class_index])
            )
        else:
            sign, log_determinant = np.linalg.slogdet(covariance)
            if sign <= 0.0:
                raise MultivariatePackError(
                    "MULTIVARIATE_NUMERIC_DEGENERACY", "QDA covariance is not positive definite"
                )
            scores[:, class_index] = (
                -0.5 * log_determinant
                - 0.5 * np.einsum("ij,jk,ik->i", centered, inverse, centered)
                + np.log(priors[class_index])
            )
    return np.argmax(scores, axis=1)


def _evaluation_metrics(actual: np.ndarray, predicted: np.ndarray, n_classes: int) -> dict[str, object]:
    confusion = np.zeros((n_classes, n_classes), dtype=int)
    for observed, estimate in zip(actual, predicted):
        confusion[int(observed), int(estimate)] += 1
    f1_values: list[float] = []
    for class_index in range(n_classes):
        true_positive = confusion[class_index, class_index]
        precision_denominator = confusion[:, class_index].sum()
        recall_denominator = confusion[class_index, :].sum()
        precision = true_positive / precision_denominator if precision_denominator else 0.0
        recall = true_positive / recall_denominator if recall_denominator else 0.0
        f1_values.append(
            2.0 * precision * recall / (precision + recall)
            if precision + recall > 0.0
            else 0.0
        )
    return {
        "accuracy": float(np.mean(actual == predicted)),
        "macro_f1": float(np.mean(f1_values)),
        "confusion_matrix": confusion,
        "support": confusion.sum(axis=1),
    }


def _split_holdout(labels: list[str | int], test_size: float, random_state: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(random_state)
    train: list[int] = []
    test: list[int] = []
    for label in sorted(set(labels), key=lambda value: (type(value).__name__, value)):
        indices = np.asarray([index for index, item in enumerate(labels) if item == label])
        shuffled = rng.permutation(indices)
        n_test = min(max(1, int(round(len(indices) * test_size))), len(indices) - 1)
        test.extend(shuffled[:n_test].tolist())
        train.extend(shuffled[n_test:].tolist())
    return np.asarray(sorted(train), dtype=int), np.asarray(sorted(test), dtype=int)


def fit_discriminant(
    frame: pd.DataFrame,
    *,
    features: Sequence[str],
    target: str,
    method: Literal["lda", "qda"],
    prior_policy: Literal["empirical", "declared"],
    priors: Mapping[str | int, float] | None = None,
    regularization: float,
    evaluation: Literal["none", "holdout"],
    test_size: float | None = None,
    random_state: int | None = None,
    include_predictions: bool = False,
    max_prediction_rows: int = 500,
    missing_policy: str = "complete_case_v1",
) -> dict[str, object]:
    """Fit LDA/QDA with explicit priors, covariance policy, and evaluation split."""

    if method not in DISCRIMINANT_METHODS or prior_policy not in DISCRIMINANT_PRIOR_POLICIES:
        raise MultivariatePackError(
            "MULTIVARIATE_UNSUPPORTED_OPTION", "method or prior_policy is not declared"
        )
    if evaluation not in DISCRIMINANT_EVALUATIONS:
        raise MultivariatePackError(
            "MULTIVARIATE_UNSUPPORTED_OPTION", "evaluation is not declared"
        )
    if type(regularization) not in (int, float) or not np.isfinite(regularization) or regularization < 0.0:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "regularization must be finite and non-negative"
        )
    if type(include_predictions) is not bool or type(max_prediction_rows) is not int or max_prediction_rows < 1:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "prediction output options are invalid"
        )
    if evaluation == "none":
        if test_size is not None or random_state is not None or include_predictions:
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                "evaluation none cannot accept holdout or prediction options",
            )
    else:
        if (
            type(test_size) is not float
            or not np.isfinite(test_size)
            or not 0.0 < test_size < 1.0
            or type(random_state) is not int
            or random_state < 0
        ):
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                "holdout requires finite float test_size in (0,1) and non-negative random_state",
            )
    values, labels, feature_order, retained_positions = _prepare_supervised(frame, features, target)
    class_order = tuple(sorted(set(labels), key=lambda value: (type(value).__name__, value)))
    if missing_policy != "complete_case_v1":
        raise MultivariatePackError(
            "MULTIVARIATE_UNSUPPORTED_MISSING_POLICY",
            "only complete_case_v1 is currently declared",
        )
    evaluation_indices: tuple[np.ndarray, np.ndarray] | None = None
    if evaluation == "holdout":
        evaluation_indices = _split_holdout(labels, float(test_size), int(random_state))
        train_indices, test_indices = evaluation_indices
        if len(train_indices) < len(class_order) * 2 or len(test_indices) < len(class_order):
            raise MultivariatePackError(
                "MULTIVARIATE_TOO_FEW_OBSERVATIONS", "holdout leaves too few observations per class"
            )
        fit_values = values[train_indices]
        fit_labels = [labels[index] for index in train_indices]
    else:
        fit_values, fit_labels = values, labels
    fit_class_order = tuple(sorted(set(fit_labels), key=lambda value: (type(value).__name__, value)))
    prior_values = _validate_priors(fit_labels, fit_class_order, prior_policy, priors)
    parameters = _fit_parameters(
        fit_values,
        fit_labels,
        fit_class_order,
        method,
        prior_values,
        float(regularization),
    )
    parameter_rows = [
        {
            "class": label,
            "prior": prior_values[index],
            "mean": parameters["means"][index],
            "covariance": (
                parameters["shared_covariance"]
                if method == "lda"
                else parameters["covariances"][index]
            ),
            "n_training": parameters["counts"][index],
        }
        for index, label in enumerate(fit_class_order)
    ]
    result: dict[str, object] = {
        "method": method,
        "features": list(feature_order),
        "target": target,
        "class_order": list(fit_class_order),
        "prior_policy": prior_policy,
        "priors": [
            {"class": label, "probability": prior_values[index]}
            for index, label in enumerate(fit_class_order)
        ],
        "covariance_regularization": {
            "method": "diagonal_ridge",
            "value": float(regularization),
        },
        "class_parameters": parameter_rows,
        "predictions_available": False,
        "missing_policy": missing_policy,
        "retained_positions": list(retained_positions),
    }
    if evaluation_indices is None:
        result["evaluation"] = {"status": "not_requested"}
    else:
        train_indices, test_indices = evaluation_indices
        actual = np.asarray([fit_class_order.index(labels[index]) for index in test_indices], dtype=int)
        predicted = _predict(values[test_indices], parameters, fit_class_order, prior_values, method)
        metrics = _evaluation_metrics(actual, predicted, len(fit_class_order))
        result["evaluation"] = {
            "status": "holdout",
            "test_size": float(test_size),
            "random_state": random_state,
            "n_train": len(train_indices),
            "n_test": len(test_indices),
            **metrics,
        }
        if include_predictions:
            bounded_count = min(max_prediction_rows, len(predicted))
            result["predictions_available"] = True
            result["predictions"] = [fit_class_order[int(index)] for index in predicted[:bounded_count]]
            result["predictions_row_count"] = bounded_count
            result["predictions_truncated"] = bounded_count < len(predicted)
    return make_result_envelope(
        operation_id="multivariate.discriminant",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=len(values),
        columns=feature_order,
        result=json_native(result),
    )


__all__ = [
    "DISCRIMINANT_EVALUATIONS",
    "DISCRIMINANT_METHODS",
    "DISCRIMINANT_PRIOR_POLICIES",
    "fit_discriminant",
]
