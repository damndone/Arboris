"""Model-agnostic OOS prediction protocol built on one SplitPlan receipt."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
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

    executable_profiles = frozenset({
        "iid_holdout_kfold",
        "grouped_holdout_groupkfold",
        "temporal_holdout_rolling",
    })
    sample_spec.validate(executable_profiles=executable_profiles)
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
        estimator.fit(frame.loc[training_rows, list(features)], frame.loc[training_rows, target])
        cv_predictions = [float(value) for value in estimator.predict(frame.loc[validation_rows, list(features)])]
        cv_metrics.append(
            {
                "fold": fold,
                "n_train": len(training_rows),
                "n_validation": len(validation_rows),
                "metrics": _metrics(frame.loc[validation_rows, target], cv_predictions),
            }
        )
    if len(cv_metrics) < 2:
        raise ContractError("PREDICTION_SPLIT_CV_INVALID", "at least two non-empty development CV fits are required")

    final_estimator = estimator_factory()
    final_estimator.fit(frame.loc[development_rows, list(features)], frame.loc[development_rows, target])
    final_predictions = [
        float(value) for value in final_estimator.predict(frame.loc[final_rows, list(features)])
    ]
    baseline_value = float(frame.loc[development_rows, target].mean())
    baseline_predictions = [baseline_value] * len(final_rows)
    prediction_map = dict(zip(final_rows, final_predictions, strict=True))
    controls: list[dict[str, Any]] = []
    if control_seed is not None:
        permutation = permute_target(frame[target], seed=control_seed)
        noise = add_seeded_noise_feature(
            frame[list(features)],
            seed=control_seed,
            column_name="__control_noise_v1",
        )
        controls = [permutation.receipt, noise.receipt]
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
