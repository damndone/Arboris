"""Score saved regression or binary forests with the validated C++ kernels.

This module accepts an already resolved model, not a path or a public request.
The project service owns artifact and lineage authentication.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .checks.ar_cancellation import current_check
from .native_cart import _INT_FIELDS as _CLASS_INT_FIELDS, _NODE_FIELDS as _CLASS_NODE_FIELDS
from .native_cart_regression import _INT_FIELDS, _NODE_FIELDS
from .native_random_forest import _HEADER_WIDTH, _MAX_NODES, validate_random_forest_size
from .native_random_forest_classification import _HEADER_WIDTH as _CLASS_HEADER_WIDTH, _TAG as _CLASS_TAG
from .native_ridge import _column_name, _loaded, _native_vector, _numeric


OPERATION_ID = "prediction.native_forest_apply"
TRAINING_OPERATION = "prediction.native_random_forest_regression"
CLASSIFICATION_OPERATION = "prediction.native_random_forest_classification"
TRAINING_OPERATIONS = frozenset((TRAINING_OPERATION, CLASSIFICATION_OPERATION))
_BATCH_ROWS = 4096


def validate_apply_size(rows: int, columns: int = 1) -> None:
    if not 1 <= rows <= 100_000 or not 1 <= columns <= 64 or rows * columns > 1_000_000:
        raise ValueError("FOREST_APPLY_WORK_LIMIT: use 1 to 100000 rows, at most 64 predictors and 1000000 predictor values")


def forest_buffer(result: dict, basis: dict) -> tuple[list[str], bytes]:
    """Restore the bounded, version-one forest receipt without refitting."""
    error = "FOREST_APPLY_MODEL_INVALID: saved forest is inconsistent"
    if not isinstance(result, dict) or not isinstance(basis, dict):
        raise ValueError(error)
    names = result.get("predictors")
    classification = result.get("model_type") == "native_random_forest_classification"
    family = "random_forest_classification" if classification else "random_forest_regression"
    if (result.get("schema_version") != 1 or result.get("model_type") != "native_" + family
            or result.get("engine") != "cpp17_" + family
            or not isinstance(names, list) or not 1 <= len(names) <= 64
            or not all(_column_name(name) for name in names) or len(set(names)) != len(names)
            or basis.get("kind") != family or basis.get("predictor_order") != names):
        raise ValueError(error)
    try:
        options, train_rows = result["options"], result["split"]["train_rows"]
        trees = basis["trees"]
        n_trees, depth, minimum, features, seed = (options[key] for key in (
            "n_trees", "max_depth", "min_samples_leaf", "max_features", "seed"))
        if type(train_rows) is not int or not 2 <= train_rows < 100_000 or features == 0:
            raise ValueError(error)
        validate_random_forest_size(
            train_rows + 1, len(names), training_rows=train_rows, n_trees=n_trees,
            max_depth=depth, min_samples_leaf=minimum, max_features=features, seed=seed,
        )
        if not isinstance(trees, list) or len(trees) != n_trees:
            raise ValueError(error)
        sizes = [len(tree["nodes"]) for tree in trees]
        count = sum(sizes)
        if (not all(1 <= size <= (1 << (depth + 1)) - 1 for size in sizes)
                or count > _MAX_NODES or result["model_structure"]["node_count"] != count
                or result["model_structure"]["tree_count"] != n_trees):
            raise ValueError(error)
        node_fields, integer_fields = (_CLASS_NODE_FIELDS, _CLASS_INT_FIELDS) if classification else (_NODE_FIELDS, _INT_FIELDS)
        if classification:
            counts = result["class_counts"]["train"]
            positive, negative = counts["1"], counts["0"]
            distinct = [tree["bootstrap_unique_rows"] for tree in trees]
            if (type(positive) is not int or type(negative) is not int or not 0 < positive < train_rows
                    or positive + negative != train_rows or result.get("classification_threshold") != .5
                    or result["prevalence_baseline"]["probability"] != positive / train_rows
                    or any(type(value) is not int or not 1 <= value <= train_rows for value in distinct)
                    or any(options.get(key) != value for key, value in {
                        "criterion": "gini", "leaf_probability": "laplace_smoothed",
                        "aggregation": "equal_weight_leaf_probability",
                    }.items())):
                raise ValueError(error)
            offset = _CLASS_HEADER_WIDTH + 2 * n_trees
            packed = np.empty(offset + count * len(node_fields), dtype=np.float64)
            packed[:_CLASS_HEADER_WIDTH] = (_CLASS_TAG, n_trees, train_rows, depth, minimum, features, seed, len(names), positive)
            packed[_CLASS_HEADER_WIDTH:offset] = np.column_stack((sizes, distinct)).ravel()
        else:
            baseline = result["mean_baseline"]["prediction"]
            if isinstance(baseline, bool) or not isinstance(baseline, (int, float)) or not math.isfinite(baseline):
                raise ValueError(error)
            offset = _HEADER_WIDTH + n_trees
            packed = np.empty(offset + count * len(node_fields), dtype=np.float64)
            packed[:_HEADER_WIDTH] = (n_trees, train_rows, depth, minimum, features, seed, len(names), baseline)
            packed[_HEADER_WIDTH:offset] = sizes
        checkpoint = current_check()
        for tree_id, tree in enumerate(trees):
            if checkpoint is not None:
                checkpoint()
            if type(tree["tree_id"]) is not int or tree["tree_id"] != tree_id:
                raise ValueError(error)
            for node_id, node in enumerate(tree["nodes"]):
                if type(node["node_id"]) is not int or node["node_id"] != node_id:
                    raise ValueError(error)
                for field in node_fields:
                    value = node[field]
                    if (isinstance(value, bool) or not isinstance(value, (int, float))
                            or not math.isfinite(value) or (field in integer_fields and type(value) is not int)):
                        raise ValueError(error)
                    packed[offset] = value
                    offset += 1
        return list(names), packed.tobytes()
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError(error) from exc


def apply_output_columns(options, *, classification: bool = False) -> tuple[str, ...]:
    """Resolve the two model families' output names without loading their model."""
    if not classification and "probability_column" in options:
        raise ValueError("FOREST_APPLY_PROBABILITY_CLASSIFICATION_ONLY: probability_column requires a saved classifier")
    columns = (options.get("prediction_column", "prediction"),)
    if classification:
        columns += (options.get("probability_column", "probability"),)
    if any(not _column_name(name) for name in columns) or len(set(columns)) != len(columns):
        raise ValueError("FOREST_APPLY_INVALID_OUTPUT: choose distinct, valid new output column names")
    return columns


def _validate_apply_columns(frame: pd.DataFrame, names: list[str], prediction_column: str | None) -> None:
    if (not isinstance(frame, pd.DataFrame) or isinstance(frame.columns, pd.MultiIndex)
            or not frame.columns.is_unique or any(name not in frame.columns for name in names)):
        raise ValueError("FOREST_APPLY_INVALID_COLUMNS: new data must contain the saved predictor names exactly once")
    validate_apply_size(len(frame), len(names))
    if prediction_column is not None and (not _column_name(prediction_column) or prediction_column in frame.columns):
        raise ValueError("FOREST_APPLY_INVALID_OUTPUT: choose a new prediction column name")


def _numeric_batches(frame: pd.DataFrame, names: list[str]):
    checkpoint = current_check()
    for start in range(0, len(frame), _BATCH_ROWS):
        if checkpoint is not None:
            checkpoint()
        stop = min(start + _BATCH_ROWS, len(frame))
        values = np.empty((stop - start, len(names)), dtype=np.float64)
        for column, name in enumerate(names):
            try:
                values[:, column] = _numeric(frame[name].iloc[start:stop])
            except ValueError as exc:
                raise ValueError(f"FOREST_APPLY_INVALID_DATA: {exc}") from exc
        yield start, values


def validate_apply_frame(frame: pd.DataFrame, names: list[str], prediction_column: str | None = None) -> None:
    """Preview validates all inputs without retaining the converted batches."""
    _validate_apply_columns(frame, names, prediction_column)
    for _ in _numeric_batches(frame, names):
        pass


def score_saved_forest(frame: pd.DataFrame, *, forest: tuple[list[str], bytes],
                       prediction_column: str | None = None, classification: bool = False) -> tuple[np.ndarray, dict]:
    """Consume the parsed model and validate/convert each input batch once."""
    names, packed = forest
    _validate_apply_columns(frame, names, prediction_column)
    native, receipt = _loaded()
    score = getattr(native, "predict_random_forest_classification" if classification else "predict_random_forest_regression", None)
    if not callable(score):
        raise RuntimeError("FOREST_APPLY_BUILD_INVALID: rebuild native/ridge/build.py and restart Workbench")
    checkpoint = current_check()
    output = np.empty(len(frame), dtype=np.float64)
    for start, values in _numeric_batches(frame, names):
        predicted = _native_vector(
            score(values.tobytes(), len(values), len(names), packed, checkpoint), len(values), prefix="FOREST_APPLY",
        )
        if classification and not ((0 < predicted) & (predicted < 1)).all():
            raise RuntimeError("FOREST_APPLY_BUILD_INVALID: classifier probabilities must be strictly between 0 and 1")
        output[start:start + len(values)] = predicted
    if checkpoint is not None:
        checkpoint()
    return output, dict(receipt)
