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


class Estimator(Protocol):
    def fit(self, features: pd.DataFrame, target: pd.Series) -> Any: ...

    def predict(self, features: pd.DataFrame) -> Any: ...


@dataclass(frozen=True)
class OOSPredictionResult:
    prediction_packet: dict[str, Any]
    evaluation_packet: dict[str, Any]
    control_packet: dict[str, Any]


def _frequency_weights(
    frame: pd.DataFrame,
    sample_spec: SampleSpecV1,
) -> tuple[str | None, pd.Series | None]:
    sampling = sample_spec.sampling
    if sampling.sampling_weight is not None or sampling.analysis_weight is not None:
        raise ContractError(
            "PREDICTION_WEIGHT_UNSUPPORTED",
            "sampling_weight and analysis_weight are not supported by the v1.8.6 generic estimator adapter",
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


def _rmse(actual: pd.Series, predicted: list[float]) -> float:
    errors = [(float(left) - float(right)) ** 2 for left, right in zip(actual, predicted, strict=True)]
    return math.sqrt(sum(errors) / len(errors)) if errors else float("nan")


def _r2(actual: pd.Series, predicted: list[float]) -> float | None:
    values = [float(value) for value in actual]
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    total = sum((value - mean) ** 2 for value in values)
    if total == 0:
        return None
    residual = sum((value - estimate) ** 2 for value, estimate in zip(values, predicted, strict=True))
    return 1.0 - residual / total


def _metrics(actual: pd.Series, predicted: list[float]) -> dict[str, float | None]:
    return {"r2": _r2(actual, predicted), "rmse": _rmse(actual, predicted)}


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
    if frame[list(features) + [target]].isna().any().any():
        raise ContractError(
            "PREDICTION_INPUT_MISSING_UNRESOLVED",
            "missing values require an explicit fold-local preprocessing plan",
        )

    final_rows = _rows_for(assignments, partition="final_holdout")
    development_rows = _rows_for(assignments, partition="development")
    if not final_rows or not development_rows:
        raise ContractError("PREDICTION_SPLIT_EMPTY_PARTITION", "development and final holdout must both contain rows")
    folds = sorted({assignment.cv_fold for assignment in assignments.values() if assignment.cv_fold is not None})
    if len(folds) < 2:
        raise ContractError("PREDICTION_SPLIT_CV_INVALID", "at least two development CV folds are required")

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
        estimator = estimator_factory()
        _fit_estimator(
            estimator,
            frame.loc[training_rows, list(features)],
            frame.loc[training_rows, target],
            frequency_weights.loc[training_rows] if frequency_weights is not None else None,
        )
        validation_target = frame.loc[validation_rows, target]
        cv_predictions = [float(value) for value in estimator.predict(frame.loc[validation_rows, list(features)])]
        observed_fold = {
            "fold": fold,
            "n_train": len(training_rows),
            "n_validation": len(validation_rows),
            "metrics": _metrics(validation_target, cv_predictions),
        }
        cv_metrics.append(observed_fold)

        if permutation_control is not None and noise_control is not None:
            permutation_estimator = estimator_factory()
            _fit_estimator(
                permutation_estimator,
                frame.loc[training_rows, list(features)],
                permutation_control.values.loc[training_rows],
                frequency_weights.loc[training_rows] if frequency_weights is not None else None,
            )
            permutation_predictions = [
                float(value)
                for value in permutation_estimator.predict(frame.loc[validation_rows, list(features)])
            ]
            permutation_cv_metrics.append(
                {
                    "fold": fold,
                    "n_train": len(training_rows),
                    "n_validation": len(validation_rows),
                    "metrics": _metrics(validation_target, permutation_predictions),
                }
            )

            noise_estimator = estimator_factory()
            _fit_estimator(
                noise_estimator,
                noise_control.frame.loc[training_rows, list(noise_features)],
                frame.loc[training_rows, target],
                frequency_weights.loc[training_rows] if frequency_weights is not None else None,
            )
            noise_validation = noise_control.frame.loc[validation_rows, list(noise_features)]
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
                feature_importance[feature_name] = (
                    _rmse(validation_target, shuffled_predictions)
                    - _rmse(validation_target, noise_base_predictions)
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

    final_estimator = estimator_factory()
    _fit_estimator(
        final_estimator,
        frame.loc[development_rows, list(features)],
        frame.loc[development_rows, target],
        frequency_weights.loc[development_rows] if frequency_weights is not None else None,
    )
    final_predictions = [
        float(value) for value in final_estimator.predict(frame.loc[final_rows, list(features)])
    ]
    baseline_value = float(frame.loc[development_rows, target].mean())
    baseline_predictions = [baseline_value] * len(final_rows)
    prediction_map = dict(zip(final_rows, final_predictions, strict=True))
    controls: list[dict[str, Any]] = []
    if control_seed is not None and permutation_control is not None and noise_control is not None:
        permutation_estimator = estimator_factory()
        _fit_estimator(
            permutation_estimator,
            frame.loc[development_rows, list(features)],
            permutation_control.values.loc[development_rows],
            frequency_weights.loc[development_rows] if frequency_weights is not None else None,
        )
        permutation_predictions = [
            float(value)
            for value in permutation_estimator.predict(frame.loc[final_rows, list(features)])
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
                "metrics": _metrics(frame.loc[final_rows, target], permutation_predictions),
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
            noise_control.frame.loc[development_rows, list(noise_features)],
            frame.loc[development_rows, target],
            frequency_weights.loc[development_rows] if frequency_weights is not None else None,
        )
        noise_predictions = [
            float(value)
            for value in noise_estimator.predict(noise_control.frame.loc[final_rows, list(noise_features)])
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
                "metrics": _metrics(frame.loc[final_rows, target], noise_predictions),
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
        "limits": ["control metrics require the same bounded model budget"] if controls else [],
    }
    evaluation = {
        "payload_schema": "workbench.prediction.evaluation-packet",
        "schema_version": 1,
        "split_plan_hash": split_receipt.content_hash,
        "sample_spec_hash": sample_spec.content_hash,
        "model_id": model_id,
        "baseline": {"model_id": "mean_regressor", "metrics": _metrics(frame.loc[final_rows, target], baseline_predictions)},
        "oos": {"n": len(final_rows), "metrics": _metrics(frame.loc[final_rows, target], final_predictions)},
        "cv": cv_metrics,
        "controls": controls,
        "assumptions": {
            "final_holdout_isolated": True,
            "fit_scope": "development_only",
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
        "assumptions": evaluation["assumptions"],
        "limits": evaluation["limits"],
    }
    return OOSPredictionResult(
        prediction_packet=packet,
        evaluation_packet=evaluation,
        control_packet=control_packet,
    )
