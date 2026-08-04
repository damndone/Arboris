"""Model-agnostic OOS prediction protocol built on one SplitPlan receipt."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import json
import math
from typing import Any, Callable, Protocol

import pandas as pd

from .contracts import ContractError, SampleSpecV1
from .controls import add_seeded_noise_feature, permute_target
from .split_kernel import SplitAssignment, SplitPlanReceipt
from ..econometrics.optional_deps import require_optional_dependency


class Estimator(Protocol):
    def fit(self, features: pd.DataFrame, target: pd.Series) -> Any: ...

    def predict(self, features: pd.DataFrame) -> Any: ...


@dataclass(frozen=True)
class OOSPredictionResult:
    prediction_packet: dict[str, Any]
    evaluation_packet: dict[str, Any]
    control_packet: dict[str, Any]


@dataclass
class _FoldLocalMiceState:
    columns: tuple[str, ...]
    transformer: Any

    def transform(self, frame: pd.DataFrame, rows: list[str]) -> pd.DataFrame:
        scoped = frame.loc[rows].copy()
        values = self.transformer.transform(
            scoped.loc[:, list(self.columns)].to_numpy(dtype=float, copy=True)
        )
        scoped.loc[:, list(self.columns)] = values
        return scoped


def _fit_fold_local_mice(
    frame: pd.DataFrame,
    rows: list[str],
    *,
    features: tuple[str, ...],
    max_iter: int,
    max_missing_rate: float,
    random_seed: int,
) -> _FoldLocalMiceState:
    numeric_columns = tuple(
        column for column in features if pd.api.types.is_numeric_dtype(frame[column])
    )
    missing_columns = [column for column in features if frame.loc[rows, column].isna().any()]
    unsupported_missing = [column for column in missing_columns if column not in numeric_columns]
    if unsupported_missing:
        raise ContractError(
            "PREDICTION_MICE_NON_NUMERIC_MISSING",
            f"fold-local MICE only supports missing numeric features: {unsupported_missing}",
        )
    if not numeric_columns:
        raise ContractError(
            "PREDICTION_MICE_NO_NUMERIC_FEATURES",
            "fold-local MICE requires at least one numeric prediction feature",
        )
    missing_rates = frame.loc[rows, list(numeric_columns)].isna().mean()
    excessive = [
        column for column, rate in missing_rates.items()
        if float(rate) > max_missing_rate
    ]
    if excessive:
        raise ContractError(
            "PREDICTION_MICE_MISSING_RATE_UNSUPPORTED",
            f"fold-local MICE missing rate exceeds the configured limit for: {excessive}",
        )
    if len(rows) < 2:
        raise ContractError(
            "PREDICTION_MICE_FOLD_TOO_SMALL",
            "each fold-local MICE training scope requires at least two rows",
        )

    require_optional_dependency(
        "sklearn.experimental",
        extra="ml",
        engine="scikit-learn",
        model_type="prediction_mice",
        step="prediction",
    )
    # Importing this module enables the experimental IterativeImputer feature
    # before importing the public imputer class.  IterativeImputer implements
    # chained equations while keeping fit/transform state explicit per scope.
    from sklearn.experimental import enable_iterative_imputer  # noqa: F401

    sklearn_impute = require_optional_dependency(
        "sklearn.impute",
        extra="ml",
        engine="scikit-learn",
        model_type="prediction_mice",
        step="prediction",
    )
    transformer = sklearn_impute.IterativeImputer(
        max_iter=max(1, int(max_iter)),
        random_state=random_seed,
        sample_posterior=False,
        keep_empty_features=True,
    )
    try:
        transformer.fit(
            frame.loc[rows, list(numeric_columns)].to_numpy(dtype=float, copy=True)
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(
            "PREDICTION_MICE_FOLD_FIT_FAILED",
            f"fold-local MICE could not fit on the training scope: {exc}",
        ) from exc
    return _FoldLocalMiceState(columns=numeric_columns, transformer=transformer)


def _scope_record(
    *,
    fit_rows: list[str],
    apply_rows: list[str],
    fit_partition: str,
    apply_partition: str,
    fold: int | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "fit_row_refs": list(fit_rows),
        "apply_row_refs": list(apply_rows),
        "fit_partition": fit_partition,
        "apply_partition": apply_partition,
    }
    if fold is not None:
        record["fold"] = fold
    return record


def _frequency_weights(
    frame: pd.DataFrame,
    sample_spec: SampleSpecV1,
) -> tuple[str | None, pd.Series | None]:
    sampling = sample_spec.sampling
    if sampling.sampling_weight is not None:
        raise ContractError(
            "PREDICTION_WEIGHT_UNSUPPORTED",
            "sampling_weight is fail-closed until a declared strata/PSU design is "
            "supported; declare strata/PSU through the existing entity/cluster channel",
        )
    if sampling.analysis_weight is not None:
        raise ContractError(
            "PREDICTION_WEIGHT_UNSUPPORTED",
            "analysis_weight is not supported by the v1.8.6 generic estimator adapter; "
            "use an OLS run for analysis-weight execution",
        )
    column = sampling.frequency_weight
    if column is None:
        return None, None
    if column not in frame.columns:
        raise ContractError(
            "PREDICTION_WEIGHT_COLUMN_MISSING",
            f"frequency weight column {column!r} is not present in the dataset",
        )
    weights = pd.to_numeric(frame[column], errors="coerce").astype(float)
    if weights.isna().any() or not weights.map(math.isfinite).all() or (weights <= 0).any():
        raise ContractError(
            "PREDICTION_FREQUENCY_WEIGHT_INVALID",
            "frequency weights must be finite and strictly positive",
        )
    return column, weights


def _fit_estimator(
    estimator: Estimator,
    features: pd.DataFrame,
    target: pd.Series,
    sample_weight: pd.Series | None,
) -> Any:
    if sample_weight is None:
        return estimator.fit(features, target)

    fit = getattr(estimator, "fit", None)
    if fit is None:
        raise ContractError(
            "PREDICTION_FREQUENCY_WEIGHT_UNSUPPORTED",
            "estimator does not expose a fit method for frequency weights",
        )
    try:
        parameters = inspect.signature(fit).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "sample_weight" in parameters:
        return fit(features, target, sample_weight=sample_weight)

    named_steps = getattr(estimator, "named_steps", None)
    if named_steps:
        final_name, final_estimator = next(reversed(named_steps.items()))
        try:
            final_parameters = inspect.signature(final_estimator.fit).parameters
        except (TypeError, ValueError, AttributeError):
            final_parameters = {}
        if "sample_weight" in final_parameters:
            return fit(features, target, **{f"{final_name}__sample_weight": sample_weight})

    raise ContractError(
        "PREDICTION_FREQUENCY_WEIGHT_UNSUPPORTED",
        "the selected estimator does not declare sklearn-compatible sample_weight support",
    )


def dataset_snapshot_hash(frame: pd.DataFrame) -> str:
    metadata = json.dumps(
        {"columns": list(map(str, frame.columns)), "dtypes": [str(dtype) for dtype in frame.dtypes]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    values = pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
    return hashlib.sha256(metadata + values).hexdigest()


_CONTROL_POLICY_VERSION = 1
_MAX_PERMUTATIONS = 1
_MAX_NOISE_FEATURES = 1


def _control_budget_record(
    *,
    requested: tuple[str, ...],
    executed: tuple[str, ...],
) -> dict[str, Any]:
    """Describe the bounded control budget this run actually consumed.

    A packet that does not say how much of its budget it spent cannot be told
    apart from one that stopped early, which would make "the controls passed"
    unverifiable.
    """

    fully_executed = set(executed) == set(requested)
    return {
        "policy_version": _CONTROL_POLICY_VERSION,
        "max_permutations": _MAX_PERMUTATIONS,
        "max_noise_features": _MAX_NOISE_FEATURES,
        "requested_controls": len(requested),
        "executed_controls": len(executed),
        "fully_executed": fully_executed,
        "stop_reason": (
            "BUDGET_NOT_EXHAUSTED" if fully_executed else "CONTROL_NOT_EXECUTED"
        ),
    }


def _metric_weights(actual: pd.Series, sample_weight: pd.Series | None) -> list[float]:
    if sample_weight is None:
        return [1.0] * len(actual)
    aligned = sample_weight.reindex(actual.index)
    return [float(value) for value in aligned]


def _rmse(actual: pd.Series, predicted: list[float], weights: list[float]) -> float:
    errors = [
        weight * (float(left) - float(right)) ** 2
        for left, right, weight in zip(actual, predicted, weights, strict=True)
    ]
    total_weight = sum(weights)
    return math.sqrt(sum(errors) / total_weight) if total_weight > 0 else float("nan")


def _r2(actual: pd.Series, predicted: list[float], weights: list[float]) -> float | None:
    values = [float(value) for value in actual]
    if len(values) < 2:
        return None
    total_weight = sum(weights)
    if total_weight <= 0:
        return None
    mean = sum(weight * value for value, weight in zip(values, weights, strict=True)) / total_weight
    total = sum(
        weight * (value - mean) ** 2 for value, weight in zip(values, weights, strict=True)
    )
    if total == 0:
        return None
    residual = sum(
        weight * (value - estimate) ** 2
        for value, estimate, weight in zip(values, predicted, weights, strict=True)
    )
    return 1.0 - residual / total


def _metrics(
    actual: pd.Series,
    predicted: list[float],
    *,
    sample_weight: pd.Series | None = None,
) -> dict[str, float | None]:
    """Evaluation metrics.

    A declared frequency weight is an observation count, so it has to enter the
    metric as well as the fit; an unweighted metric would describe a sample that
    was never observed.
    """

    weights = _metric_weights(actual, sample_weight)
    return {"r2": _r2(actual, predicted, weights), "rmse": _rmse(actual, predicted, weights)}


def _average_metric(rows: list[dict[str, Any]], metric: str) -> float | None:
    values = [
        float(row["metrics"][metric])
        for row in rows
        if isinstance(row.get("metrics"), dict)
        and isinstance(row["metrics"].get(metric), (int, float))
        and math.isfinite(float(row["metrics"][metric]))
    ]
    return sum(values) / len(values) if values else None


def _rows_for(assignments: dict[str, SplitAssignment], *, partition: str, fold: int | None = None) -> list[str]:
    return [
        row_ref
        for row_ref, assignment in assignments.items()
        if assignment.partition == partition and (fold is None or assignment.cv_fold == fold)
    ]


def run_oos_prediction(
    *,
    frame: pd.DataFrame,
    target: str,
    features: tuple[str, ...],
    sample_spec: SampleSpecV1,
    split_receipt: SplitPlanReceipt,
    estimator_factory: Callable[[], Estimator],
    model_id: str,
    control_seed: int | None = None,
    imputation_method: str | None = None,
    imputation_max_iter: int = 10,
    imputation_max_missing_rate: float = 0.4,
) -> OOSPredictionResult:
    """Fit CV and final models without allowing final rows into development evidence."""

    unsupported_strategy = sample_spec.split_plan.strategy
    if unsupported_strategy in {"temporal", "panel"}:
        sample_spec.sampling.validate()
        sample_spec.structure.validate()
        sample_spec.availability.validate()
        required_columns = (
            [sample_spec.structure.time_column]
            if unsupported_strategy == "temporal"
            else [sample_spec.structure.entity_column, sample_spec.structure.time_column]
        )
        missing_columns = [column for column in required_columns if not column or column not in frame.columns]
        if missing_columns:
            code = (
                "PREDICTION_TIME_COLUMN_MISSING"
                if unsupported_strategy == "temporal"
                else "PREDICTION_PANEL_COLUMN_MISSING"
            )
            raise ContractError(
                code,
                f"{unsupported_strategy} prediction requires declared columns present in the dataset: {missing_columns}",
            )
        raise ContractError(
            "PREDICTION_SPLIT_PROFILE_NOT_SUPPORTED",
            f"{unsupported_strategy} prediction requires a registered safety profile in a future release",
        )
    sample_spec.validate(executable_profiles=frozenset({
        "iid_holdout_kfold",
        "grouped_holdout_groupkfold",
    }))
    normalized_imputation = (imputation_method or "").strip().lower()
    if normalized_imputation not in {"", "mice"}:
        raise ContractError(
            "PREDICTION_IMPUTATION_UNSUPPORTED",
            f"unsupported prediction preprocessing method: {imputation_method!r}",
        )
    frequency_weight_column, frequency_weights = _frequency_weights(frame, sample_spec)
    if sample_spec.split_plan_ref is not None and sample_spec.split_plan_ref != split_receipt.content_hash:
        raise ContractError(
            "PREDICTION_SPLIT_BINDING_MISMATCH",
            "SampleSpec split_plan_ref does not match the persisted SplitPlan receipt",
        )
    if not isinstance(frame.index, pd.Index) or len(set(map(str, frame.index))) != len(frame.index):
        raise ValueError("row identity must be unique")
    row_refs = tuple(map(str, frame.index))
    assignments = {assignment.row_ref: assignment for assignment in split_receipt.assignments}
    if set(assignments) != set(row_refs) or len(assignments) != len(row_refs):
        raise ValueError("split binding does not match frame row identity")
    if target not in frame.columns or any(feature not in frame.columns for feature in features):
        raise ContractError("PREDICTION_INPUT_COLUMN_MISSING", "target and features must be present in the dataset")
    if frame[target].isna().any():
        raise ContractError(
            "PREDICTION_TARGET_MISSING_UNRESOLVED",
            "prediction evaluation requires an observed target in every split partition",
        )

    final_rows = _rows_for(assignments, partition="final_holdout")
    development_rows = _rows_for(assignments, partition="development")
    if not final_rows or not development_rows:
        raise ContractError("PREDICTION_SPLIT_EMPTY_PARTITION", "development and final holdout must both contain rows")
    folds = sorted({assignment.cv_fold for assignment in assignments.values() if assignment.cv_fold is not None})
    if len(folds) < 2:
        raise ContractError("PREDICTION_SPLIT_CV_INVALID", "at least two development CV folds are required")

    preprocessing: dict[str, Any] | None = None
    if normalized_imputation == "mice":
        preprocessing = {
            "method": "mice",
            "fit_scope": "fold_local",
            "optional_dependency_status": "available",
            "folds": [],
            "final_holdout": None,
            "max_iter": max(1, int(imputation_max_iter)),
            "max_missing_rate": float(imputation_max_missing_rate),
        }

    cv_metrics: list[dict[str, Any]] = []
    permutation_cv_metrics: list[dict[str, Any]] = []
    noise_fold_importance: list[dict[str, Any]] = []
    permutation_control = None
    noise_control = None
    noise_features = tuple(features) + ("__control_noise_v1",)
    if control_seed is not None:
        permutation_control = permute_target(frame[target], seed=control_seed)
        noise_control = add_seeded_noise_feature(
            frame[list(features)],
            seed=control_seed,
            column_name="__control_noise_v1",
        )
    row_position = {row_ref: position for position, row_ref in enumerate(row_refs)}
    for fold in folds:
        validation_rows = _rows_for(assignments, partition="development", fold=fold)
        if sample_spec.split_plan.strategy == "temporal":
            first_validation_position = min(row_position[row_ref] for row_ref in validation_rows)
            training_rows = [
                row_ref
                for row_ref in development_rows
                if row_position[row_ref] < first_validation_position
            ]
        else:
            training_rows = [row_ref for row_ref in development_rows if row_ref not in validation_rows]
        if not training_rows:
            continue
        if preprocessing is not None:
            fold_mice = _fit_fold_local_mice(
                frame,
                training_rows,
                features=features,
                max_iter=imputation_max_iter,
                max_missing_rate=imputation_max_missing_rate,
                random_seed=(control_seed or 0) + fold + 1,
            )
            training_scope = fold_mice.transform(frame, training_rows)
            validation_scope = fold_mice.transform(frame, validation_rows)
            preprocessing["folds"].append(
                _scope_record(
                    fit_rows=training_rows,
                    apply_rows=validation_rows,
                    fit_partition="development_only",
                    apply_partition="development_cv_validation",
                    fold=fold,
                )
            )
        else:
            training_scope = frame.loc[training_rows].copy()
            validation_scope = frame.loc[validation_rows].copy()
        estimator = estimator_factory()
        _fit_estimator(
            estimator,
            training_scope.loc[:, list(features)],
            frame.loc[training_rows, target],
            frequency_weights.loc[training_rows] if frequency_weights is not None else None,
        )
        validation_target = frame.loc[validation_rows, target]
        cv_predictions = [float(value) for value in estimator.predict(validation_scope.loc[:, list(features)])]
        observed_fold = {
            "fold": fold,
            "n_train": len(training_rows),
            "n_validation": len(validation_rows),
            "metrics": _metrics(validation_target, cv_predictions, sample_weight=frequency_weights),
        }
        cv_metrics.append(observed_fold)

        if permutation_control is not None and noise_control is not None:
            permutation_estimator = estimator_factory()
            _fit_estimator(
                permutation_estimator,
                training_scope.loc[:, list(features)],
                permutation_control.values.loc[training_rows],
                frequency_weights.loc[training_rows] if frequency_weights is not None else None,
            )
            permutation_predictions = [
                float(value)
                for value in permutation_estimator.predict(validation_scope.loc[:, list(features)])
            ]
            permutation_cv_metrics.append(
                {
                    "fold": fold,
                    "n_train": len(training_rows),
                    "n_validation": len(validation_rows),
                    "metrics": _metrics(validation_target, permutation_predictions, sample_weight=frequency_weights),
                }
            )

            noise_estimator = estimator_factory()
            noise_training = noise_control.frame.loc[training_rows, list(noise_features)].copy()
            noise_validation = noise_control.frame.loc[validation_rows, list(noise_features)].copy()
            noise_training.loc[:, list(features)] = training_scope.loc[:, list(features)].to_numpy()
            noise_validation.loc[:, list(features)] = validation_scope.loc[:, list(features)].to_numpy()
            _fit_estimator(
                noise_estimator,
                noise_training,
                frame.loc[training_rows, target],
                frequency_weights.loc[training_rows] if frequency_weights is not None else None,
            )
            noise_base_predictions = [
                float(value) for value in noise_estimator.predict(noise_validation)
            ]
            feature_importance: dict[str, float] = {}
            for feature_index, feature_name in enumerate(noise_features):
                shuffled_validation = noise_validation.copy()
                shuffled_validation[feature_name] = permute_target(
                    shuffled_validation[feature_name],
                    seed=control_seed + fold * 1000 + feature_index,
                ).values
                shuffled_predictions = [
                    float(value) for value in noise_estimator.predict(shuffled_validation)
                ]
                importance_weights = _metric_weights(validation_target, frequency_weights)
                feature_importance[feature_name] = (
                    _rmse(validation_target, shuffled_predictions, importance_weights)
                    - _rmse(validation_target, noise_base_predictions, importance_weights)
                )
            ordered_features = sorted(
                feature_importance,
                key=lambda name: (-feature_importance[name], name),
            )
            noise_rank = ordered_features.index("__control_noise_v1") + 1
            noise_fold_importance.append(
                {
                    "fold": fold,
                    "feature_importance": feature_importance,
                    "noise_importance": feature_importance["__control_noise_v1"],
                    "noise_rank": noise_rank,
                    "n_validation": len(validation_rows),
                }
            )
    if len(cv_metrics) < 2:
        raise ContractError("PREDICTION_SPLIT_CV_INVALID", "at least two non-empty development CV fits are required")

    if preprocessing is not None:
        final_mice = _fit_fold_local_mice(
            frame,
            development_rows,
            features=features,
            max_iter=imputation_max_iter,
            max_missing_rate=imputation_max_missing_rate,
            random_seed=(control_seed or 0) + 100_000,
        )
        development_scope = final_mice.transform(frame, development_rows)
        final_scope = final_mice.transform(frame, final_rows)
        preprocessing["final_holdout"] = _scope_record(
            fit_rows=development_rows,
            apply_rows=final_rows,
            fit_partition="development_only",
            apply_partition="final_holdout",
        )
    else:
        development_scope = frame.loc[development_rows].copy()
        final_scope = frame.loc[final_rows].copy()
    final_estimator = estimator_factory()
    _fit_estimator(
        final_estimator,
        development_scope.loc[:, list(features)],
        frame.loc[development_rows, target],
        frequency_weights.loc[development_rows] if frequency_weights is not None else None,
    )
    final_predictions = [
        float(value) for value in final_estimator.predict(final_scope.loc[:, list(features)])
    ]
    baseline_value = float(frame.loc[development_rows, target].mean())
    baseline_predictions = [baseline_value] * len(final_rows)
    prediction_map = dict(zip(final_rows, final_predictions, strict=True))
    controls: list[dict[str, Any]] = []
    if control_seed is not None and permutation_control is not None and noise_control is not None:
        permutation_estimator = estimator_factory()
        noise_development = noise_control.frame.loc[development_rows, list(noise_features)].copy()
        noise_final = noise_control.frame.loc[final_rows, list(noise_features)].copy()
        noise_development.loc[:, list(features)] = development_scope.loc[:, list(features)].to_numpy()
        noise_final.loc[:, list(features)] = final_scope.loc[:, list(features)].to_numpy()
        _fit_estimator(
            permutation_estimator,
            development_scope.loc[:, list(features)],
            permutation_control.values.loc[development_rows],
            frequency_weights.loc[development_rows] if frequency_weights is not None else None,
        )
        permutation_predictions = [
            float(value)
            for value in permutation_estimator.predict(final_scope.loc[:, list(features)])
        ]
        observed_cv_r2 = _average_metric(cv_metrics, "r2")
        permuted_cv_r2 = _average_metric(permutation_cv_metrics, "r2")
        observed_cv_rmse = _average_metric(cv_metrics, "rmse")
        permuted_cv_rmse = _average_metric(permutation_cv_metrics, "rmse")
        metric_gap = {
            "r2": observed_cv_r2 - permuted_cv_r2
            if observed_cv_r2 is not None and permuted_cv_r2 is not None
            else None,
            "rmse": permuted_cv_rmse - observed_cv_rmse
            if observed_cv_rmse is not None and permuted_cv_rmse is not None
            else None,
        }
        permutation_status = (
            "CONTROL_INCONCLUSIVE"
            if metric_gap["r2"] is None or metric_gap["rmse"] is None
            else (
                "CONTROL_BEHAVED_AS_EXPECTED"
                if metric_gap["r2"] > 0 and metric_gap["rmse"] > 0
                else "LEAKAGE_OR_PROTOCOL_FAILURE_SUSPECTED"
            )
        )
        permutation_receipt = dict(permutation_control.receipt)
        permutation_receipt.update(
            {
                "metrics": _metrics(frame.loc[final_rows, target], permutation_predictions, sample_weight=frequency_weights),
                "n_train": len(development_rows),
                "n_evaluation": len(final_rows),
                "fit_scope": "development_only",
                "status": permutation_status,
                "observed_development_cv": cv_metrics,
                "permuted_target_cv": permutation_cv_metrics,
                "metric_gap": metric_gap,
                "policy_version": 1,
            }
        )

        noise_estimator = estimator_factory()
        _fit_estimator(
            noise_estimator,
            noise_development,
            frame.loc[development_rows, target],
            frequency_weights.loc[development_rows] if frequency_weights is not None else None,
        )
        noise_predictions = [
            float(value) for value in noise_estimator.predict(noise_final)
        ]
        noise_top_count = sum(
            1 for fold in noise_fold_importance if fold.get("noise_rank") == 1
        )
        noise_status = (
            "CONTROL_INCONCLUSIVE"
            if not noise_fold_importance
            else (
                "NOISE_NOT_STABLE"
                if noise_top_count == 0
                else (
                    "NOISE_DOMINATES"
                    if noise_top_count == len(noise_fold_importance)
                    else "NOISE_COMPETES_WITH_SIGNAL"
                )
            )
        )
        noise_receipt = dict(noise_control.receipt)
        noise_receipt.update(
            {
                "metrics": _metrics(frame.loc[final_rows, target], noise_predictions, sample_weight=frequency_weights),
                "n_train": len(development_rows),
                "n_evaluation": len(final_rows),
                "fit_scope": "development_only",
                "status": noise_status,
                "fold_importance": noise_fold_importance,
                "noise_top_count": noise_top_count,
                "fold_count": len(noise_fold_importance),
                "policy_version": 1,
            }
        )
        controls = [permutation_receipt, noise_receipt]
    control_packet = {
        "payload_schema": "workbench.prediction.negative-control-packet",
        "schema_version": 1,
        "model_id": model_id,
        "split_plan_hash": split_receipt.content_hash,
        "seed": control_seed,
        "controls": controls,
        "status": "prepared" if controls else "not_requested",
        "budget": _control_budget_record(
            requested=("permuted_target", "seeded_noise_features") if control_seed is not None else (),
            executed=tuple(
                str(entry.get("control"))
                for entry in controls
                if isinstance(entry, dict) and entry.get("control")
            ),
        ),
        "limits": ["control metrics require the same bounded model budget"] if controls else [],
    }
    evaluation = {
        "payload_schema": "workbench.prediction.evaluation-packet",
        "schema_version": 1,
        "split_plan_hash": split_receipt.content_hash,
        "sample_spec_hash": sample_spec.content_hash,
        "model_id": model_id,
        "baseline": {"model_id": "mean_regressor", "metrics": _metrics(frame.loc[final_rows, target], baseline_predictions, sample_weight=frequency_weights)},
        "oos": {"n": len(final_rows), "metrics": _metrics(frame.loc[final_rows, target], final_predictions, sample_weight=frequency_weights)},
        "cv": cv_metrics,
        "controls": controls,
        "preprocessing": preprocessing,
        "assumptions": {
            "final_holdout_isolated": True,
            "fit_scope": "development_only",
            "preprocessing_fit_scope": (
                "development_only" if preprocessing is not None else "not_requested"
            ),
            "temporal_cv_is_prior_only": sample_spec.split_plan.strategy == "temporal",
            "frequency_weight_column": frequency_weight_column,
            "frequency_weight_executed": frequency_weight_column is not None,
        },
        "limits": ["final holdout is not sealed across reruns"],
    }
    packet = {
        "payload_schema": "workbench.prediction.prediction-packet",
        "schema_version": 1,
        "model_id": model_id,
        "sample_spec_hash": sample_spec.content_hash,
        "split_plan_hash": split_receipt.content_hash,
        "fit_folds": ["development_cv", "development_final"],
        "n_by_partition": {"development": len(development_rows), "final_holdout": len(final_rows)},
        "row_predictions": prediction_map,
        "oos_metrics": evaluation["oos"]["metrics"],
        "baseline": evaluation["baseline"],
        "controls": controls,
        "preprocessing": preprocessing,
        "assumptions": evaluation["assumptions"],
        "limits": evaluation["limits"],
    }
    return OOSPredictionResult(
        prediction_packet=packet,
        evaluation_packet=evaluation,
        control_packet=control_packet,
    )
