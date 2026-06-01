from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .artifacts import register_artifact, write_json
from .econometrics.optional_deps import require_optional_dependency

_SUPPORTED_PREDICTION_MODEL_TYPES = {
    "prediction_lasso",
    "prediction_ridge",
    "prediction_random_forest",
}


def run_prediction_model(
    frame: pd.DataFrame,
    run_root: Path,
    *,
    y: str,
    x: list[str],
    model_type: str,
    model_id: str,
    cv_folds: int = 5,
    random_seed: int = 20260429,
    inputs: list[str] | None = None,
) -> dict[str, Any]:
    if model_type not in _SUPPORTED_PREDICTION_MODEL_TYPES:
        raise ValueError(f"Unsupported prediction model_type: {model_type}")

    sklearn_model_selection = require_optional_dependency(
        "sklearn.model_selection",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_pipeline = require_optional_dependency(
        "sklearn.pipeline",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_preprocessing = require_optional_dependency(
        "sklearn.preprocessing",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_metrics = require_optional_dependency(
        "sklearn.metrics",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_linear = require_optional_dependency(
        "sklearn.linear_model",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_ensemble = require_optional_dependency(
        "sklearn.ensemble",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )

    data = frame[[y, *x]].dropna()
    if len(data) < 4:
        raise ValueError("Prediction models require at least four complete rows.")
    folds = min(max(int(cv_folds), 2), 5, len(data), max(len(data) // 2, 2))
    if len(data) <= 2:
        test_size = 1
    else:
        test_size = 0.25
    X = data[x]
    target = data[y]

    if model_type == "prediction_lasso":
        estimator = sklearn_linear.Lasso(
            alpha=1.0,
            random_state=random_seed,
            max_iter=5000,
        )
    elif model_type == "prediction_ridge":
        estimator = sklearn_linear.Ridge(alpha=1.0)
    else:
        estimator = sklearn_ensemble.RandomForestRegressor(
            n_estimators=100,
            random_state=random_seed,
            n_jobs=1,
        )

    pipeline = sklearn_pipeline.make_pipeline(
        sklearn_preprocessing.StandardScaler(),
        estimator,
    )
    X_train, X_test, y_train, y_test = sklearn_model_selection.train_test_split(
        X,
        target,
        test_size=test_size,
        random_state=random_seed,
    )
    pipeline.fit(X_train, y_train)
    predictions = pipeline.predict(X_test)
    cv_scores = sklearn_model_selection.cross_val_score(
        pipeline,
        X,
        target,
        cv=folds,
        scoring="r2",
    )
    result = {
        "schema_version": 1,
        "model_id": model_id,
        "model_type": model_type,
        "engine": "scikit-learn",
        "status": "completed",
        "nobs": int(len(data)),
        "input_columns": {"y": y, "x": x},
        "cv_folds": int(folds),
        "metrics": {
            "test_r2": _safe_metric(sklearn_metrics.r2_score(y_test, predictions)),
            "test_rmse": _rmse(sklearn_metrics, y_test, predictions),
            "cv_r2_mean": _safe_metric(cv_scores.mean()),
        },
        "warnings": [
            "Prediction results are not causal effects and are not regression inference."
        ],
    }
    output_dir = run_root / "prediction_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{model_id}.json"
    write_json(path, result)
    register_artifact(
        run_root,
        model_id,
        path,
        "prediction_result",
        "prediction",
        inputs or ["cleaned_dataset"],
    )
    return result


def _rmse(sklearn_metrics: Any, y_true: Any, predictions: Any) -> float | None:
    try:
        value = sklearn_metrics.mean_squared_error(
            y_true,
            predictions,
            squared=False,
        )
    except TypeError:
        value = sklearn_metrics.mean_squared_error(y_true, predictions) ** 0.5
    return _safe_metric(value)


def _safe_metric(value: Any) -> float | None:
    try:
        import math

        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None
