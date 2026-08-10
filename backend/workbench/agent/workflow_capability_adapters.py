"""Typed adapters for capabilities exposed through the generic workflow seam.

The registry owns identity and composition metadata.  This module owns the
execution semantics of each capability family.  Keeping those concerns apart
means a new adapter can reuse the same Agent/workflow/lineage plumbing without
turning the runtime into an operation-id switch statement.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
import math
from typing import Any

import numpy as np
import pandas as pd


MAX_WORKFLOW_ROWS = 100_000
MAX_WORKFLOW_COLUMNS = 100


class WorkflowCapabilityAdapterError(ValueError):
    """A request or result violated one adapter's typed boundary."""


@dataclass(frozen=True)
class WorkflowCapabilityExecution:
    """The bounded result plus an optional dataset for the generic runtime."""

    payload: dict[str, Any]
    output_frame: pd.DataFrame | None = None
    dataset_kind: str | None = None
    artifact_type: str = "workflow_capability_result"


@dataclass(frozen=True)
class WorkflowCapabilityAdapter:
    """One adapter's request and result validators and its frame executor."""

    adapter_key: str
    validate_request: Callable[[str, Mapping[str, Any]], dict[str, Any]]
    execute: Callable[[pd.DataFrame, Mapping[str, Any]], WorkflowCapabilityExecution]
    validate_result: Callable[[str, Mapping[str, Any]], None]


def _json_safe(value: Any, *, path: str = "result") -> Any:
    """Convert numerical scalars while rejecting non-finite or opaque values."""

    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item, path=f"{path}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, np.generic):
        return _json_safe(value.item(), path=path)
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return value.isoformat()
    if isinstance(value, (str, bool)) or value is None:
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise WorkflowCapabilityAdapterError(f"{path} contains a non-finite number")
        return value
    raise WorkflowCapabilityAdapterError(
        f"{path} contains an unsupported value type: {type(value).__name__}"
    )


def _validate_json_value(value: Any, *, path: str, depth: int = 0) -> None:
    if depth > 8:
        raise WorkflowCapabilityAdapterError(f"{path} is nested too deeply")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str or not key:
                raise WorkflowCapabilityAdapterError(f"{path} keys must be non-empty strings")
            _validate_json_value(item, path=f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]", depth=depth + 1)
        return
    if isinstance(value, np.generic):
        _validate_json_value(value.item(), path=path, depth=depth)
        return
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise WorkflowCapabilityAdapterError(f"{path} must contain finite numbers")
        return
    raise WorkflowCapabilityAdapterError(
        f"{path} cannot contain {type(value).__name__}; code, formula, path, and callback values are not accepted"
    )


def _validate_common_request(
    operation_id: str, request: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise WorkflowCapabilityAdapterError(f"{operation_id} request must be an object")
    expected = {"operation_id", "input_mode", "column_bindings", "options"}
    unknown = sorted(set(request) - expected)
    if unknown:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} request contains unsupported field(s): {', '.join(unknown)}"
        )
    if request.get("operation_id") != operation_id:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} request operation_id must be {operation_id!r}"
        )
    if request.get("input_mode") != "frame":
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} input_mode must be 'frame'"
        )
    bindings = request.get("column_bindings")
    options = request.get("options")
    if not isinstance(bindings, Mapping):
        raise WorkflowCapabilityAdapterError(f"{operation_id} column_bindings must be an object")
    if not isinstance(options, Mapping):
        raise WorkflowCapabilityAdapterError(f"{operation_id} options must be an object")
    _validate_json_value(bindings, path=f"{operation_id}.column_bindings")
    _validate_json_value(options, path=f"{operation_id}.options")
    return {
        "operation_id": operation_id,
        "input_mode": "frame",
        "column_bindings": dict(bindings),
        "options": dict(options),
    }


def _frame_for_columns(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    operation_id: str,
    numeric: bool = False,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise WorkflowCapabilityAdapterError(f"{operation_id} input must be a dataframe")
    if len(frame) > MAX_WORKFLOW_ROWS:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} refuses more than {MAX_WORKFLOW_ROWS} rows; sample or declare a bounded source"
        )
    if len(frame.columns) > MAX_WORKFLOW_COLUMNS:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} refuses more than {MAX_WORKFLOW_COLUMNS} columns in one workflow step"
        )
    if not columns or any(type(column) is not str or not column for column in columns):
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} requires non-empty source column names"
        )
    if len(set(columns)) != len(columns):
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} source columns must be distinct"
        )
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} source column(s) are absent: {', '.join(missing)}"
        )
    selected = frame.loc[:, columns].copy()
    if numeric:
        non_numeric = [
            column for column in columns
            if not pd.api.types.is_numeric_dtype(selected[column])
        ]
        if non_numeric:
            raise WorkflowCapabilityAdapterError(
                f"{operation_id} requires numeric source column(s): {', '.join(non_numeric)}"
            )
    return selected


def _binding_columns(
    bindings: Mapping[str, Any], key: str, *, operation_id: str, minimum: int = 1
) -> list[str]:
    value = bindings.get(key)
    if not isinstance(value, list) or len(value) < minimum:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} column_bindings.{key} must be a list of at least {minimum} column(s)"
        )
    if any(type(column) is not str or not column for column in value):
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} column_bindings.{key} must contain non-empty column names"
        )
    return list(value)


def _binding_column(bindings: Mapping[str, Any], key: str, *, operation_id: str) -> str:
    value = bindings.get(key)
    if type(value) is not str or not value:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} column_bindings.{key} must be a non-empty column name"
        )
    return value


def _validate_statistical_option_shapes(
    operation_id: str,
    columns: list[str],
    options: Mapping[str, Any],
) -> None:
    reference_means = options.get("reference_means")
    if reference_means is not None:
        if not isinstance(reference_means, Mapping):
            raise WorkflowCapabilityAdapterError(
                f"{operation_id} reference_means must be an object mapping columns to finite numbers"
            )
        for column, value in reference_means.items():
            if type(column) is not str or not column or column not in columns:
                raise WorkflowCapabilityAdapterError(
                    f"{operation_id} reference_means columns must be present in the declared columns"
                )
            if type(value) not in (int, float):
                raise WorkflowCapabilityAdapterError(
                    f"{operation_id} reference_means values must be finite numbers"
                )
            try:
                finite = math.isfinite(float(value))
            except (OverflowError, TypeError):
                finite = False
            if not finite:
                raise WorkflowCapabilityAdapterError(
                    f"{operation_id} reference_means values must be finite numbers"
                )

    paired_columns = options.get("paired_columns")
    if paired_columns is not None:
        if not isinstance(paired_columns, (list, tuple)):
            raise WorkflowCapabilityAdapterError(
                f"{operation_id} paired_columns must be a list of two-column pairs"
            )
        for pair in paired_columns:
            if (
                not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or any(type(column) is not str or not column for column in pair)
            ):
                raise WorkflowCapabilityAdapterError(
                    f"{operation_id} paired_columns entries must contain exactly two column names"
                )
            left, right = pair
            if left == right or left not in columns or right not in columns:
                raise WorkflowCapabilityAdapterError(
                    f"{operation_id} paired_columns entries must name two distinct declared columns"
                )


def _validate_statistical_request(operation_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_common_request(operation_id, request)
    bindings = normalized["column_bindings"]
    columns = _binding_columns(bindings, "columns", operation_id=operation_id, minimum=2)
    unknown = sorted(set(bindings) - _declared_request_properties(operation_id, "column_bindings"))
    if unknown:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} column_bindings contains unsupported field(s): {', '.join(unknown)}"
        )
    options = normalized["options"]
    unknown_options = sorted(set(options) - _declared_request_properties(operation_id, "options"))
    if unknown_options:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} options contains unsupported field(s): {', '.join(unknown_options)}"
        )
    _validate_statistical_option_shapes(operation_id, columns, options)
    return {**normalized, "column_bindings": {"columns": columns}}


def _execute_statistical(frame: pd.DataFrame, request: Mapping[str, Any]) -> WorkflowCapabilityExecution:
    operation_id = str(request["operation_id"])
    columns = list(request["column_bindings"]["columns"])
    selected_frame = _frame_for_columns(frame, columns, operation_id=operation_id)
    options = request["options"]
    _validate_statistical_option_shapes(operation_id, columns, options)
    numeric_targets = {
        column
        for column in columns
        if pd.api.types.is_numeric_dtype(selected_frame[column])
    }
    reference_means = options.get("reference_means") or {}
    non_numeric_reference_means = sorted(set(reference_means) - numeric_targets)
    if non_numeric_reference_means:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} reference_means requires numeric source column(s): "
            + ", ".join(non_numeric_reference_means)
        )
    paired_columns = options.get("paired_columns") or ()
    non_numeric_pairs = sorted(
        {
            column
            for pair in paired_columns
            for column in pair
            if column not in numeric_targets
        }
    )
    if non_numeric_pairs:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} paired_columns requires numeric source column(s): "
            + ", ".join(non_numeric_pairs)
        )
    from ..statistical_tests import run_statistical_tests

    results = run_statistical_tests(
        selected_frame,
        analysis_columns=columns,
        reference_means=options.get("reference_means"),
        paired_columns=options.get("paired_columns"),
    )
    family = operation_id.removeprefix("test.")
    payload = results.get(family)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("results"), list):
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} did not return its declared result shape"
        )
    if not payload["results"]:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} has no estimable comparison for the declared columns"
        )
    assumptions = sorted(
        {
            str(item)
            for row in payload["results"]
            if isinstance(row, Mapping)
            for item in row.get("assumptions", [])
            if isinstance(item, str) and item
        }
    )
    if not assumptions:
        assumptions = ["The declared source columns and the selected test-family input rules were used."]
    result = {
        "operation_id": operation_id,
        "family": family,
        "source_columns": columns,
        "result": _json_safe(payload),
        "assumptions": assumptions,
        "correction_scope": payload.get("correction_scope", family),
    }
    return WorkflowCapabilityExecution(payload=_json_safe(result))


def _validate_prediction_request(operation_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_common_request(operation_id, request)
    bindings = normalized["column_bindings"]
    outcome = _binding_column(bindings, "outcome", operation_id=operation_id)
    features = _binding_columns(bindings, "features", operation_id=operation_id, minimum=1)
    unknown = sorted(set(bindings) - _declared_request_properties(operation_id, "column_bindings"))
    if unknown:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} column_bindings contains unsupported field(s): {', '.join(unknown)}"
        )
    if outcome in features:
        raise WorkflowCapabilityAdapterError(f"{operation_id} outcome must not be a feature")
    options = normalized["options"]
    unknown_options = sorted(set(options) - _declared_request_properties(operation_id, "options"))
    if unknown_options:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} options contains unsupported field(s): {', '.join(unknown_options)}"
        )
    structure_kind = options.get("data_structure", "iid")
    group_column = options.get("group_column")
    if structure_kind == "grouped" and (type(group_column) is not str or not group_column):
        raise WorkflowCapabilityAdapterError(f"{operation_id} grouped data requires group_column")
    if structure_kind != "grouped" and group_column is not None:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} group_column is only valid for grouped data"
        )
    return {
        **normalized,
        "column_bindings": {"outcome": outcome, "features": features},
    }


def _execute_prediction(frame: pd.DataFrame, request: Mapping[str, Any]) -> WorkflowCapabilityExecution:
    operation_id = str(request["operation_id"])
    outcome = str(request["column_bindings"]["outcome"])
    features = list(request["column_bindings"]["features"])
    selected = _frame_for_columns(frame, [outcome, *features], operation_id=operation_id, numeric=True)
    options = request["options"]
    model_type = operation_id.removeprefix("prediction.")
    seed = options.get("random_seed", 20260429)
    if type(seed) is not int or seed < 0:
        raise WorkflowCapabilityAdapterError(f"{operation_id} random_seed must be a non-negative integer")
    folds = options.get("cv_folds", 5)
    if type(folds) is not int or not 2 <= folds <= 10:
        raise WorkflowCapabilityAdapterError(f"{operation_id} cv_folds must be an integer between 2 and 10")
    holdout = options.get("final_holdout_fraction", 0.25)
    if type(holdout) not in (int, float) or not 0.05 <= float(holdout) <= 0.5:
        raise WorkflowCapabilityAdapterError(f"{operation_id} final_holdout_fraction must be between 0.05 and 0.5")
    shuffle = options.get("shuffle", True)
    if type(shuffle) is not bool:
        raise WorkflowCapabilityAdapterError(f"{operation_id} shuffle must be a boolean")
    structure_kind = options.get("data_structure", "iid")
    if structure_kind not in {"iid", "grouped"}:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} data_structure must be iid or grouped; temporal/panel profiles are not executable here"
        )
    group_column = options.get("group_column")
    if structure_kind == "grouped" and (type(group_column) is not str or not group_column):
        raise WorkflowCapabilityAdapterError(f"{operation_id} grouped data requires group_column")
    if structure_kind == "grouped":
        _frame_for_columns(frame, [group_column], operation_id=operation_id)
        if frame[group_column].isna().any():
            raise WorkflowCapabilityAdapterError(
                f"{operation_id} group column contains missing values; grouped prediction "
                "requires an explicit group identity for every row"
            )
    protocol_frame = selected.copy()
    if protocol_frame.index.has_duplicates:
        raise WorkflowCapabilityAdapterError(f"{operation_id} requires unique input row identity")
    protocol_frame.index = [str(value) for value in protocol_frame.index]
    groups = frame.loc[:, group_column].astype(str).tolist() if structure_kind == "grouped" else None
    from ..prediction import _make_v186_estimator_factory
    from ..predictive_research.contracts import (
        AvailabilitySpecV1,
        SampleSpecV1,
        SamplingSpecV1,
        SplitPlanV1,
        StructureSpecV1,
    )
    from ..predictive_research.prediction_protocol import dataset_snapshot_hash, run_oos_prediction
    from ..predictive_research.split_kernel import build_split_plan

    strategy = "grouped" if structure_kind == "grouped" else "iid"
    split = build_split_plan(
        row_refs=tuple(protocol_frame.index),
        strategy=strategy,
        groups=groups,
        final_holdout_fraction=float(holdout),
        cv_folds=folds,
        shuffle=shuffle,
        random_seed=seed,
    )
    structure = StructureSpecV1(
        kind=structure_kind,
        group_column=group_column if structure_kind == "grouped" else None,
        provenance="user_confirmed",
    )
    sample_spec = SampleSpecV1(
        dataset_sha256=dataset_snapshot_hash(protocol_frame),
        sampling=SamplingSpecV1(),
        split_plan=SplitPlanV1(
            strategy=strategy,
            profile_id=("grouped_holdout_groupkfold" if strategy == "grouped" else "iid_holdout_kfold"),
            profile_version=1,
            effective_parameters={**split.effective_parameters, "model_id": operation_id},
        ),
        structure=structure,
        availability=AvailabilitySpecV1(
            kind="declared",
            feature_available_at="workflow_input",
            label_available_at="workflow_input",
            validation_status="declared",
        ),
        split_plan_ref=split.content_hash,
    )
    model_result = run_oos_prediction(
        frame=protocol_frame,
        target=outcome,
        features=tuple(features),
        sample_spec=sample_spec,
        split_receipt=split,
        estimator_factory=_make_v186_estimator_factory(model_type, seed),
        model_id=operation_id,
        control_seed=seed,
        imputation_method=options.get("imputation_method"),
        imputation_max_iter=options.get("imputation_max_iter", 10),
        imputation_max_missing_rate=options.get("imputation_max_missing_rate", 0.4),
    )
    evaluation = model_result.evaluation_packet
    payload = {
        "protocol": "predictive_research_v1",
        "operation_id": operation_id,
        "model_type": model_type,
        "prediction_is_causal": False,
        "evaluation": {
            "oos_n": int(evaluation["oos"]["n"]),
            "metrics": evaluation["oos"]["metrics"],
            "cv": evaluation["cv"],
        },
        "prediction_packet": model_result.prediction_packet,
        "control_packet": model_result.control_packet,
        "split_plan": split.to_dict(),
        "sample_spec": sample_spec.to_dict(),
        "assumptions": [
            "Prediction is an out-of-sample association protocol, not a causal effect.",
            "The final holdout is excluded from development fitting and cross-validation.",
        ],
    }
    return WorkflowCapabilityExecution(payload=_json_safe(payload))


def _validate_resample_request(operation_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_common_request(operation_id, request)
    bindings = normalized["column_bindings"]
    outcome = _binding_column(bindings, "outcome", operation_id=operation_id)
    features = _binding_columns(bindings, "features", operation_id=operation_id, minimum=1)
    unknown = sorted(set(bindings) - _declared_request_properties(operation_id, "column_bindings"))
    if unknown:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} column_bindings contains unsupported field(s): {', '.join(unknown)}"
        )
    options = normalized["options"]
    unknown_options = sorted(set(options) - _declared_request_properties(operation_id, "options"))
    if unknown_options:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} options contains unsupported field(s): {', '.join(unknown_options)}"
        )
    if outcome in features:
        raise WorkflowCapabilityAdapterError(f"{operation_id} outcome must not be a feature")
    return {**normalized, "column_bindings": {"outcome": outcome, "features": features}}


def _execute_resample(frame: pd.DataFrame, request: Mapping[str, Any]) -> WorkflowCapabilityExecution:
    operation_id = str(request["operation_id"])
    outcome = str(request["column_bindings"]["outcome"])
    features = list(request["column_bindings"]["features"])
    selected = _frame_for_columns(frame, [outcome, *features], operation_id=operation_id, numeric=True)
    from ..prediction import _validate_sampling_target, build_sampler

    method = operation_id.removeprefix("resample.")
    _validate_sampling_target(selected[outcome], method)
    seed = request["options"].get("random_seed", 20260429)
    if type(seed) is not int or seed < 0:
        raise WorkflowCapabilityAdapterError(f"{operation_id} random_seed must be a non-negative integer")
    sampler = build_sampler(method, model_type="prediction_ridge", random_seed=seed)
    if sampler is None:
        raise WorkflowCapabilityAdapterError(f"{operation_id} did not resolve a sampler")
    features_out, target_out = sampler.fit_resample(selected[features], selected[outcome])
    output = pd.DataFrame(features_out, columns=features)
    output.insert(0, outcome, pd.Series(target_out).reset_index(drop=True))
    payload = {
        "operation_id": operation_id,
        "status": "completed",
        "method": method,
        "input_rows": int(len(selected)),
        "output_rows": int(len(output)),
        "columns": [outcome, *features],
        "dataset_kind": "prediction_training_data",
        "assumptions": [
            "Resampling is limited to a prediction-training dataset and is not an inference adjustment.",
            "The declared target is discrete; no continuous target was coerced or silently dropped.",
        ],
    }
    return WorkflowCapabilityExecution(
        payload=payload,
        output_frame=output,
        dataset_kind="prediction_training_data",
        artifact_type="workflow_prediction_training_data",
    )


def _validate_imputation_request(operation_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_common_request(operation_id, request)
    bindings = normalized["column_bindings"]
    columns = _binding_columns(bindings, "columns", operation_id=operation_id, minimum=2)
    unknown = sorted(set(bindings) - _declared_request_properties(operation_id, "column_bindings"))
    if unknown:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} column_bindings contains unsupported field(s): {', '.join(unknown)}"
        )
    options = normalized["options"]
    unknown_options = sorted(set(options) - _declared_request_properties(operation_id, "options"))
    if unknown_options:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} options contains unsupported field(s): {', '.join(unknown_options)}"
        )
    return {**normalized, "column_bindings": {"columns": columns}}


def _execute_imputation(frame: pd.DataFrame, request: Mapping[str, Any]) -> WorkflowCapabilityExecution:
    operation_id = str(request["operation_id"])
    columns = list(request["column_bindings"]["columns"])
    selected = _frame_for_columns(frame, columns, operation_id=operation_id, numeric=True)
    missing_columns = [column for column in columns if selected[column].isna().any()]
    if not missing_columns:
        output = frame.copy(deep=True)
        status = "completed_no_missing_values"
    else:
        if len(columns) < 2:
            raise WorkflowCapabilityAdapterError(
                f"{operation_id} MICE requires at least two selected numeric columns"
            )
        max_rate = request["options"].get("max_missing_rate", 0.4)
        if type(max_rate) not in (int, float) or not 0 < float(max_rate) <= 1:
            raise WorkflowCapabilityAdapterError(f"{operation_id} max_missing_rate must be between 0 and 1")
        excessive = [
            column for column in missing_columns
            if float(selected[column].isna().mean()) > float(max_rate)
        ]
        if excessive:
            raise WorkflowCapabilityAdapterError(
                f"{operation_id} missing rate exceeds the declared limit for: {', '.join(excessive)}"
            )
        from statsmodels.imputation.mice import MICEData

        seed = request["options"].get("random_seed", 20260429)
        if type(seed) is not int or seed < 0:
            raise WorkflowCapabilityAdapterError(f"{operation_id} random_seed must be a non-negative integer")
        max_iter = request["options"].get("max_iter", 10)
        if type(max_iter) is not int or not 1 <= max_iter <= 100:
            raise WorkflowCapabilityAdapterError(f"{operation_id} max_iter must be between 1 and 100")
        state = np.random.get_state()
        try:
            np.random.seed(seed)
            mice = MICEData(selected.copy())
            for _ in range(max_iter):
                mice.update_all()
            output = frame.copy(deep=True)
            output.loc[:, columns] = mice.data.loc[:, columns]
        finally:
            np.random.set_state(state)
        if output.loc[:, missing_columns].isna().any().any():
            raise WorkflowCapabilityAdapterError(
                f"{operation_id} did not resolve every selected missing value; no dataset was published"
            )
        status = "completed"
    payload = {
        "operation_id": operation_id,
        "status": status,
        "method": "mice",
        "selected_columns": columns,
        "imputed_columns": missing_columns,
        "row_count": int(len(output)),
        "dataset_kind": "prepared_data",
        "pooled_estimates": False,
        "assumptions": [
            "Only selected numeric columns were imputed.",
            "The source frame was preserved and no rows were silently discarded.",
        ],
    }
    return WorkflowCapabilityExecution(
        payload=payload,
        output_frame=output,
        dataset_kind="prepared_data",
        artifact_type="workflow_prepared_data",
    )


def _validate_model_request(operation_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_common_request(operation_id, request)
    bindings = normalized["column_bindings"]
    outcome = _binding_column(bindings, "outcome", operation_id=operation_id)
    features = _binding_columns(bindings, "features", operation_id=operation_id, minimum=1)
    unknown = sorted(set(bindings) - _declared_request_properties(operation_id, "column_bindings"))
    if unknown:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} column_bindings contains unsupported field(s): {', '.join(unknown)}"
        )
    if outcome in features:
        raise WorkflowCapabilityAdapterError(f"{operation_id} outcome must not be a feature")
    if operation_id == "model.auto":
        unknown_options = sorted(
            set(normalized["options"]) - _declared_request_properties(operation_id, "options")
        )
        if unknown_options:
            raise WorkflowCapabilityAdapterError(
                f"{operation_id} options contains unsupported field(s): {', '.join(unknown_options)}"
            )
    return {**normalized, "column_bindings": {"outcome": outcome, "features": features}}


def _execute_auto_model(frame: pd.DataFrame, request: Mapping[str, Any]) -> WorkflowCapabilityExecution:
    operation_id = str(request["operation_id"])
    outcome = str(request["column_bindings"]["outcome"])
    features = list(request["column_bindings"]["features"])
    selected = _frame_for_columns(
        frame, [outcome, *features], operation_id=operation_id, numeric=True
    )
    missing_columns = [column for column in selected.columns if selected[column].isna().any()]
    if missing_columns:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} refuses implicit complete-case row removal; missing values in: "
            + ", ".join(missing_columns)
        )
    if len(selected) < 4:
        raise WorkflowCapabilityAdapterError(f"{operation_id} requires at least four complete rows")
    target = selected[outcome]
    unique = int(target.nunique())
    if unique == 2:
        model_type = "logit"
    elif pd.api.types.is_integer_dtype(target) and (target >= 0).all():
        model_type = "poisson"
    else:
        model_type = "ols"
    import statsmodels.api as sm

    design = sm.add_constant(selected[features].astype(float), has_constant="add")
    if model_type == "logit":
        fitted = sm.Logit(target.astype(float), design).fit(disp=False, maxiter=200)
    elif model_type == "poisson":
        fitted = sm.GLM(target.astype(float), design, family=sm.families.Poisson()).fit()
    else:
        fitted = sm.OLS(target.astype(float), design).fit()
    params = {str(name): float(value) for name, value in fitted.params.items()}
    bse = {str(name): float(value) for name, value in fitted.bse.items()}
    pvalues = {str(name): float(value) for name, value in fitted.pvalues.items()}
    payload = {
        "operation_id": operation_id,
        "status": "completed",
        "selected_model_type": model_type,
        "selection": {
            "policy": "server_y_type_policy_v1",
            "target_unique_count": unique,
            "target_dtype": str(target.dtype),
            "agent_override_allowed": False,
        },
        "result": {
            "model_type": model_type,
            "nobs": int(fitted.nobs),
            "params": params,
            "bse": bse,
            "pvalues": pvalues,
        },
        "assumptions": [
            "Model family was selected by the server-owned target-type policy.",
            "Auto selection does not authorize a causal interpretation.",
        ],
    }
    return WorkflowCapabilityExecution(payload=_json_safe(payload))


def _validate_time_series_request(operation_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_common_request(operation_id, request)
    bindings = normalized["column_bindings"]
    time_column = _binding_column(bindings, "time", operation_id=operation_id)
    value_column = _binding_column(bindings, "value", operation_id=operation_id)
    if time_column == value_column:
        raise WorkflowCapabilityAdapterError(f"{operation_id} time and value columns must differ")
    unknown = sorted(set(bindings) - _declared_request_properties(operation_id, "column_bindings"))
    if unknown:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} column_bindings contains unsupported field(s): {', '.join(unknown)}"
        )
    options = normalized["options"]
    protected = {
        "pack_id",
        "contract_version",
        "dataset_ref",
        "time_column",
        "value_column",
    }
    overrides = sorted(set(options) & protected)
    if overrides:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} options cannot override server-owned binding field(s): "
            + ", ".join(overrides)
        )
    unknown_options = sorted(
        set(options) - _declared_request_properties(operation_id, "options")
    )
    if unknown_options:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} options contains unsupported option(s): "
            + ", ".join(unknown_options)
        )
    if "time_index_semantics" not in options:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} requires an explicit time_index_semantics; the adapter will not infer calendar meaning"
        )
    return {**normalized, "column_bindings": {"time": time_column, "value": value_column}}


def _execute_ets(frame: pd.DataFrame, request: Mapping[str, Any]) -> WorkflowCapabilityExecution:
    operation_id = str(request["operation_id"])
    time_column = str(request["column_bindings"]["time"])
    value_column = str(request["column_bindings"]["value"])
    _frame_for_columns(frame, [time_column, value_column], operation_id=operation_id)
    options = {
        "time_column": time_column,
        "value_column": value_column,
        "error": "add",
        "trend": "add",
        "seasonal": None,
        "damped_trend": False,
        **dict(request["options"]),
    }
    from ..engine.packs.ets.runner import fit_ets

    outcome = fit_ets(frame, options)
    payload = {
        "operation_id": operation_id,
        "status": "completed",
        "model_type": "time_series.ets",
        "result": outcome.to_dict(),
        "assumptions": [
            "ETS estimates the conditional mean; it is not a volatility model.",
            "Time-index semantics were explicitly declared by the request.",
        ],
    }
    return WorkflowCapabilityExecution(payload=_json_safe(payload))


def _execute_arma_garch(frame: pd.DataFrame, request: Mapping[str, Any]) -> WorkflowCapabilityExecution:
    operation_id = str(request["operation_id"])
    time_column = str(request["column_bindings"]["time"])
    value_column = str(request["column_bindings"]["value"])
    _frame_for_columns(frame, [time_column, value_column], operation_id=operation_id)
    options = {
        "pack_id": operation_id.removeprefix("model."),
        "dataset_ref": "workflow_input",
        "time_column": time_column,
        "value_column": value_column,
        "time_index_semantics": request["options"]["time_index_semantics"],
        "transform": "level",
        "transform_confirmed": True,
        **dict(request["options"]),
    }
    from ..contracts.model.arma_garch import ArmaGarchAnalysisContract
    from ..artifacts import initialize_artifact_index
    from ..engine.context import DataHandle, ModelingContext, RunEnv
    from ..engine.packs.arma_garch.runner import fit_from_context
    from ..graph_recorder import GraphRecorder
    from ..graph_store import GraphStore
    from ..graph_model import Stage
    from tempfile import TemporaryDirectory
    from pathlib import Path

    contract = ArmaGarchAnalysisContract.from_dict(options)
    with TemporaryDirectory(prefix="workbench-workflow-arma-") as temporary:
        run_root = Path(temporary) / "run"
        run_root.mkdir(parents=True, exist_ok=True)
        # The pack owns its artifact index, but the generic adapter owns the
        # temporary run boundary. Initialize that boundary before the pack
        # starts registering its durable outputs.
        initialize_artifact_index(run_root)
        ctx = ModelingContext(
            data=DataHandle.of(frame.copy(), artifact_id="workflow_input", provenance=("workflow_input",)),
            y_col=value_column,
            x_cols=[],
            requested_model_type=operation_id,
            artifacts={
                "_model_options": contract.to_dict(),
                "_frames": {"workflow_input": frame.copy()},
                "_raw_inputs": ["workflow_input"],
                "_upload_hash": "workflow_input",
            },
        )
        env = RunEnv(
            run_root=run_root,
            run_id="workflow",
            recorder=GraphRecorder(run_id="workflow", store=GraphStore(run_root.parent)),
        )
        env.recorder.record_stage(
            node_id="stage:raw",
            display_label="Workflow input",
            summary=f"Workflow input: {len(frame)} rows x {len(frame.columns)} columns",
            stage=Stage.SOURCE,
        )
        _, result, _ = fit_from_context(ctx, env)
    payload = {
        "operation_id": operation_id,
        "status": "completed",
        "model_type": operation_id,
        "result": result,
        "assumptions": [
            "ARMA-GARCH ran its pack-owned audit, frozen split, candidate selection, validation, and artifact manifest.",
            "Time-index semantics and transform were explicit server-validated options.",
        ],
    }
    return WorkflowCapabilityExecution(payload=_json_safe(payload))


def _validate_result(operation_id: str, result: Mapping[str, Any]) -> None:
    if not isinstance(result, Mapping):
        raise WorkflowCapabilityAdapterError(f"{operation_id} result must be an object")
    if result.get("operation_id") != operation_id:
        raise WorkflowCapabilityAdapterError(f"{operation_id} result operation_id is not bound to the request")
    if not isinstance(result.get("assumptions"), list) or not result["assumptions"]:
        raise WorkflowCapabilityAdapterError(f"{operation_id} result must declare assumptions")
    try:
        json.dumps(_json_safe(result), allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise WorkflowCapabilityAdapterError(f"{operation_id} result is not JSON-safe: {exc}") from exc


_ADAPTERS: dict[str, WorkflowCapabilityAdapter] = {
    "statistical_test": WorkflowCapabilityAdapter(
        "statistical_test", _validate_statistical_request, _execute_statistical, _validate_result
    ),
    "prediction_model": WorkflowCapabilityAdapter(
        "prediction_model", _validate_prediction_request, _execute_prediction, _validate_result
    ),
    "resampling": WorkflowCapabilityAdapter(
        "resampling", _validate_resample_request, _execute_resample, _validate_result
    ),
    "imputation": WorkflowCapabilityAdapter(
        "imputation", _validate_imputation_request, _execute_imputation, _validate_result
    ),
    "auto_model": WorkflowCapabilityAdapter(
        "auto_model", _validate_model_request, _execute_auto_model, _validate_result
    ),
    "ets": WorkflowCapabilityAdapter(
        "ets", _validate_time_series_request, _execute_ets, _validate_result
    ),
    "arma_garch": WorkflowCapabilityAdapter(
        "arma_garch", _validate_time_series_request, _execute_arma_garch, _validate_result
    ),
}


def _string_schema() -> dict[str, Any]:
    return {"type": "string", "minLength": 1}


def _columns_schema(*, minimum: int) -> dict[str, Any]:
    return {
        "type": "array",
        "items": _string_schema(),
        "minItems": minimum,
    }


def _object_schema(
    properties: Mapping[str, Any], *, required: tuple[str, ...] = ()
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


def _request_schema(
    bindings: Mapping[str, Any],
    *,
    required_bindings: tuple[str, ...],
    options: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["operation_id", "input_mode", "column_bindings", "options"],
        "properties": {
            "operation_id": {"type": "string", "minLength": 1},
            "input_mode": {"const": "frame"},
            "column_bindings": _object_schema(bindings, required=required_bindings),
            "options": _object_schema(options),
        },
        "additionalProperties": False,
    }


_ADAPTER_REQUEST_SCHEMAS: dict[str, dict[str, Any]] = {
    "statistical_test": _request_schema(
        {"columns": _columns_schema(minimum=2)},
        required_bindings=("columns",),
        options={
            "reference_means": {"type": "object"},
            "paired_columns": {"type": "array"},
        },
    ),
    "prediction_model": _request_schema(
        {"outcome": _string_schema(), "features": _columns_schema(minimum=1)},
        required_bindings=("outcome", "features"),
        options={
            "random_seed": {"type": "integer", "minimum": 0},
            "cv_folds": {"type": "integer", "minimum": 2, "maximum": 10},
            "final_holdout_fraction": {"type": "number", "minimum": 0.05, "maximum": 0.5},
            "shuffle": {"type": "boolean"},
            "data_structure": {"type": "string", "enum": ["iid", "grouped"]},
            "group_column": _string_schema(),
            "imputation_method": _string_schema(),
            "imputation_max_iter": {"type": "integer", "minimum": 1},
            "imputation_max_missing_rate": {"type": "number", "minimum": 0, "maximum": 1},
        },
    ),
    "resampling": _request_schema(
        {"outcome": _string_schema(), "features": _columns_schema(minimum=1)},
        required_bindings=("outcome", "features"),
        options={"random_seed": {"type": "integer", "minimum": 0}},
    ),
    "imputation": _request_schema(
        {"columns": _columns_schema(minimum=2)},
        required_bindings=("columns",),
        options={
            "max_iter": {"type": "integer", "minimum": 1, "maximum": 100},
            "random_seed": {"type": "integer", "minimum": 0},
            "max_missing_rate": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        },
    ),
    "auto_model": _request_schema(
        {"outcome": _string_schema(), "features": _columns_schema(minimum=1)},
        required_bindings=("outcome", "features"),
        options={},
    ),
    "ets": _request_schema(
        {"time": _string_schema(), "value": _string_schema()},
        required_bindings=("time", "value"),
        options={
            "error": _string_schema(),
            "trend": _string_schema(),
            "seasonal": {"type": "string", "nullable": True},
            "seasonal_periods": {"type": "integer", "minimum": 2},
            "damped_trend": {"type": "boolean"},
            "time_index_semantics": {
                "type": "string",
                "enum": [
                    "regular_calendar",
                    "business_or_trading_observations",
                    "observation_order",
                ],
            },
        },
    ),
    "arma_garch": _request_schema(
        {"time": _string_schema(), "value": _string_schema()},
        required_bindings=("time", "value"),
        options={
            "time_index_semantics": {
                "type": "string",
                "enum": [
                    "regular_calendar",
                    "business_or_trading_observations",
                    "observation_order",
                ],
            },
            "transform": {"type": "string", "enum": ["level", "log_level", "diff_1", "log_return_pct"]},
            "transform_confirmed": {"type": "boolean"},
            "analysis_goal": {"type": "string", "enum": ["balanced", "forecast", "parsimony", "replication"]},
            "selection_mode": {"type": "string", "enum": ["auto", "manual"]},
            "arma": {"type": "object"},
            "variance": {"type": "object"},
            "estimation_strategy": {"type": "string", "enum": ["auto", "sequential", "joint"]},
            "innovation_distribution": {"type": "string", "enum": ["normal", "student_t"]},
            "missing_value_policy": {"type": "string", "enum": ["block", "drop_missing_confirmed"]},
            "validation": {"type": "object"},
            "forecast": {"type": "object"},
            "random_seed": {"type": "integer", "minimum": 0},
        },
    ),
}


def _adapter_key_for_operation(operation_id: str) -> str:
    if operation_id.startswith("test."):
        return "statistical_test"
    if operation_id.startswith("prediction."):
        return "prediction_model"
    if operation_id.startswith("resample."):
        return "resampling"
    if operation_id.startswith("imputation."):
        return "imputation"
    if operation_id == "model.auto":
        return "auto_model"
    if operation_id.startswith("model.time_series."):
        return operation_id.removeprefix("model.time_series.")
    raise WorkflowCapabilityAdapterError(
        f"{operation_id} has no declared request schema"
    )


def _declared_request_properties(operation_id: str, field_name: str) -> set[str]:
    adapter_key = _adapter_key_for_operation(operation_id)
    try:
        properties = _ADAPTER_REQUEST_SCHEMAS[adapter_key]["properties"][field_name]["properties"]
    except (KeyError, TypeError) as exc:
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} has no declared {field_name} schema"
        ) from exc
    if not isinstance(properties, Mapping):
        raise WorkflowCapabilityAdapterError(
            f"{operation_id} declared {field_name} schema is not an object"
        )
    return {str(name) for name in properties}


def workflow_capability_request_schema(adapter_key: str) -> dict[str, Any]:
    """Return the adapter declaration used by Agent and workflow schemas."""

    try:
        return deepcopy(_ADAPTER_REQUEST_SCHEMAS[adapter_key])
    except KeyError as exc:
        raise KeyError(f"unknown workflow capability adapter schema: {adapter_key}") from exc


def get_workflow_capability_adapter(adapter_key: str) -> WorkflowCapabilityAdapter:
    try:
        return _ADAPTERS[adapter_key]
    except KeyError as exc:
        raise KeyError(f"unknown workflow capability adapter: {adapter_key}") from exc


__all__ = [
    "WorkflowCapabilityAdapter",
    "WorkflowCapabilityAdapterError",
    "WorkflowCapabilityExecution",
    "get_workflow_capability_adapter",
    "workflow_capability_request_schema",
]
