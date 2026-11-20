"""Audited native regularized prediction with a chronological holdout."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import importlib.util
import math
from numbers import Real
from pathlib import Path
from threading import Lock

import numpy as np
import pandas as pd
from pandas.api import types as pandas_types

from .checks.ar_cancellation import current_check
from .native_build import NativeBuildError, artifact_names, default_output, manifest_path, verify_build

ABI_VERSION = 1
_MODULE = Path(__file__).resolve().parents[2] / "native/ridge"
_EXTENSION = artifact_names(_MODULE)[0]
_LOAD_LOCK = Lock()
# Validate before constructing or sorting buffers. The extension rechecks its own inputs.
_MAX_ROWS, _MAX_FEATURES, _MAX_VALUES, _MAX_WORK = 1_000_000, 512, 4_000_000, 100_000_000
_MAX_EXACT_INTEGER = 2**53
_ELASTIC_MAX_ROWS, _ELASTIC_MAX_FEATURES, _ELASTIC_MAX_VALUES = 100_000, 128, 1_000_000
_ELASTIC_MAX_WORK = 50_000_000
_ELASTIC_MAX_ITERATIONS = 12_000
_ELASTIC_TOLERANCE = 1e-11
_LOGISTIC_MAX_ROWS, _LOGISTIC_MAX_FEATURES, _LOGISTIC_MAX_VALUES = 100_000, 64, 1_000_000
_LOGISTIC_MAX_WORK = 100_000_000
_LOGISTIC_MAX_ITERATIONS = 128
_LOGISTIC_GRADIENT_TOLERANCE = 1e-10


def library_directory() -> Path:
    return default_output(_MODULE)


def _identity(path: Path) -> tuple[int, ...]:
    stat = path.lstat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _open(path: Path):
    spec = importlib.util.spec_from_file_location("_ridge", path)
    if spec is None or spec.loader is None:
        raise ImportError("could not create the Ridge extension loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _load_once():
    directory = library_directory()
    path = directory / _EXTENSION
    if not path.is_file():
        manifest = manifest_path(directory)
        broken = path.is_symlink() or manifest.exists() or manifest.is_symlink() or any(directory.glob("_ridge*"))
        code = "RIDGE_BUILD_INVALID" if broken else "RIDGE_BUILD_UNAVAILABLE"
        raise RuntimeError(f"{code}: build the native Ridge extension with native/ridge/build.py")
    try:
        identity = _identity(path)
        record = verify_build(_MODULE, directory)
        if identity != _identity(path):
            raise NativeBuildError("binary changed during verification")
    except (NativeBuildError, OSError) as error:
        raise RuntimeError(f"RIDGE_BUILD_INVALID: {error}; rebuild with native/ridge/build.py") from error

    try:
        module = _open(path)
        if identity != _identity(path):
            raise RuntimeError("binary changed while loading")
        if type(module.ABI_VERSION) is not int or module.ABI_VERSION != ABI_VERSION \
                or record["abi_version"] != ABI_VERSION or not callable(module.fit):
            raise RuntimeError("unexpected Ridge extension ABI")
    except (AttributeError, ImportError, OSError, RuntimeError, SystemError) as error:
        # dlopen may have mapped an image. Never admit a replacement as if it
        # were the image already mapped in this process.
        return error
    receipt = {key: record[key] for key in
               ("module", "abi_version", "source_sha256", "binary_sha256", "build_identity_sha256")}
    return module, receipt


def _loaded():
    with _LOAD_LOCK:
        result = _load_once()
    if isinstance(result, Exception):
        raise RuntimeError(f"RIDGE_BUILD_INVALID: {result}; rebuild and restart Workbench") from result
    return result


def _number(value, *, error: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(error)
    try:
        numeric = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(error) from exc
    if not math.isfinite(numeric):
        raise ValueError(error)
    return numeric


def _column_name(value) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 256


def _columns(frame: pd.DataFrame, outcome: str, predictors, time_col: str | None) -> list[str]:
    if (
        not isinstance(frame, pd.DataFrame) or isinstance(frame.columns, pd.MultiIndex)
        or not frame.columns.is_unique or not _column_name(outcome)
        or not isinstance(predictors, (list, tuple)) or not predictors
    ):
        raise ValueError("RIDGE_INVALID_COLUMNS: select an outcome and predictors from uniquely named flat columns")
    if len(predictors) > _MAX_FEATURES:
        raise ValueError("RIDGE_WORK_LIMIT: at most 512 predictors are supported")
    if not all(_column_name(name) for name in predictors) or len(set(predictors)) != len(predictors) \
            or outcome in predictors or (time_col is not None and (not _column_name(time_col) or time_col == outcome)):
        raise ValueError("RIDGE_INVALID_COLUMNS: use distinct predictors and a time column different from the outcome")
    required = [outcome, *predictors, *([time_col] if time_col is not None else [])]
    if any(name not in frame.columns for name in required):
        raise ValueError("RIDGE_INVALID_COLUMNS: a requested column is missing")
    return list(predictors)


def _holdout(value) -> float:
    error = "RIDGE_INVALID_HOLDOUT: holdout_fraction must be strictly between zero and one"
    fraction = _number(value, error=error)
    if not 0 < fraction < 1:
        raise ValueError(error)
    return fraction


def _time_keys(series: pd.Series):
    error = "RIDGE_INVALID_TIME: use nonmissing finite numeric times or ISO 8601 dates and times"
    if series.isna().any():
        raise ValueError(error)
    if pandas_types.is_numeric_dtype(series.dtype) and not pandas_types.is_bool_dtype(series.dtype):
        keys = series.to_numpy()
        if keys.dtype.kind not in "iuf" or not np.isfinite(keys).all():
            raise ValueError(error)
        return keys, lambda position: str(keys[position].item())
    if pandas_types.infer_dtype(series, skipna=False) not in {"date", "datetime", "datetime64", "string"}:
        raise ValueError(error)
    try:
        dates = pd.to_datetime(series, format="ISO8601", utc=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(error) from exc
    if dates.isna().any():
        raise ValueError(error)
    return dates.array.asi8, lambda position: dates.iloc[position].isoformat()


def nominal_training_rows(rows: int, fraction: float) -> int:
    train_rows = rows - math.ceil(rows * fraction)
    if train_rows < 2:
        raise ValueError("RIDGE_SPLIT_TOO_SMALL: at least two training rows and one test row are required")
    return train_rows


def _time_order(frame: pd.DataFrame, time_col: str):
    keys, label = _time_keys(frame[time_col])
    positions = np.argsort(keys, kind="stable")
    return positions, keys[positions], label


def _keep_time_ties(ordered: np.ndarray, cutoff: int) -> int:
    cutoff = int(np.searchsorted(ordered, ordered[cutoff], side="left"))
    if cutoff < 2:
        raise ValueError("RIDGE_SPLIT_TOO_SMALL: keeping equal times together leaves fewer than two training rows")
    return cutoff


def _split(frame: pd.DataFrame, time_col: str | None, fraction: float, *, time_order=None):
    rows = len(frame)
    train_rows = nominal_training_rows(rows, fraction)
    positions = train_last = test_first = None
    if time_col is not None:
        positions, ordered, label = _time_order(frame, time_col) if time_order is None else time_order
        # Move the cutoff to the start of the first test time. The requested
        # holdout count is a minimum when several rows share the boundary time.
        train_rows = _keep_time_ties(ordered, train_rows)
        train_last = label(positions[train_rows - 1])
        test_first = label(positions[train_rows])
    return positions, {
        "method": "chronological_holdout",
        "order": "input_order" if time_col is None else "time_column",
        "time_col": time_col, "train_rows": train_rows, "test_rows": rows - train_rows,
        "holdout_fraction_requested": fraction, "holdout_fraction_actual": (rows - train_rows) / rows,
        "train_last_time": train_last, "test_first_time": test_first,
    }


def _numeric(series: pd.Series) -> np.ndarray:
    error = f"RIDGE_INVALID_DATA: column {series.name!r} must contain only finite numeric values"
    if not pandas_types.is_numeric_dtype(series.dtype) or pandas_types.is_complex_dtype(series.dtype):
        raise ValueError(error)
    if pandas_types.is_integer_dtype(series.dtype) \
            and ((series > _MAX_EXACT_INTEGER).any() or (series < -_MAX_EXACT_INTEGER).any()):
        raise ValueError(f"RIDGE_INVALID_DATA: column {series.name!r} has integers outside the exact binary64 range")
    try:
        values = series.to_numpy(dtype=np.float64, na_value=np.nan)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(error) from exc
    if not np.isfinite(values).all():
        raise ValueError(error)
    return values


def _sample_values(frame, names, outcome, positions, checkpoint) -> np.ndarray:
    values = np.empty((len(frame), len(names) + 1), dtype=np.float64)
    for i, name in enumerate([*names, outcome]):
        if checkpoint is not None:
            checkpoint()
        column = _numeric(frame[name])
        values[:, i] = column if positions is None else column[positions]
    return values


def _scale(train: np.ndarray, test: np.ndarray, *, include_varying: bool = False):
    # Work in units of each training column's magnitude before squaring.
    # This also handles features whose raw-unit variances would overflow.
    magnitude = np.max(np.abs(train), axis=0)
    magnitude[magnitude == 0] = 1
    standardized = train / magnitude
    center = standardized.mean(axis=0)
    standardized -= center
    spread = np.sqrt(np.mean(standardized**2, axis=0))
    varying = spread != 0
    spread[~varying] = 1
    standardized /= spread
    test_standardized = np.zeros_like(test)
    # A constant training column has no identified predictive slope. Its
    # standardized input is zero on both sides, even if later values differ.
    np.divide(test, magnitude, out=test_standardized, where=varying)
    np.subtract(test_standardized, center, out=test_standardized, where=varying)
    np.divide(test_standardized, spread, out=test_standardized, where=varying)
    scaled = standardized, test_standardized, center, spread, magnitude
    return (*scaled, varying) if include_varying else scaled


def _r2_scale(actual: np.ndarray) -> tuple[float | None, str | None]:
    if actual.size < 2:
        return None, "insufficient_test_observations"
    if np.all(actual == actual[0]):
        return None, "constant_test_outcome"
    magnitude = np.max(np.abs(actual))
    spread = float(magnitude * np.std(actual / magnitude))
    if spread == 0:
        raise ValueError("RIDGE_NUMERICAL_RANGE: test outcome variance is below binary64 precision")
    return spread, None


def _metrics(actual: np.ndarray, prediction: np.ndarray | float, r2_scale: float | None) -> dict:
    residuals = np.abs(actual - prediction)
    magnitude = float(residuals.max())
    if magnitude == 0:
        rmse = mae = 0.0
    else:
        relative = residuals / magnitude
        rmse = magnitude * float(np.sqrt(np.mean(relative**2)))
        mae = magnitude * float(relative.mean())
    r2 = None
    if r2_scale is not None:
        ratio = rmse / r2_scale
        r2 = 1 - ratio * ratio
        if not math.isfinite(r2):
            raise ValueError("RIDGE_NUMERICAL_RANGE: R² is outside the binary64 range")
    return {"rmse": rmse, "mae": mae, "r2": r2}


@contextmanager
def _binary64_arithmetic(*, prefix: str = "RIDGE"):
    try:
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            yield
    except FloatingPointError as error:
        raise ValueError(
            f"{prefix}_NUMERICAL_RANGE: preprocessing, coefficients, or metrics exceeded binary64 range"
        ) from error


def _native_vector(packed, size, *, prefix: str = "RIDGE") -> np.ndarray:
    if type(packed) is not bytes or len(packed) != 8 * size:
        raise RuntimeError(f"{prefix}_BUILD_INVALID: native fit returned an invalid result shape")
    result = np.frombuffer(packed, dtype=np.float64)
    if not np.isfinite(result).all():
        raise RuntimeError(f"{prefix}_BUILD_INVALID: native fit returned nonfinite coefficients")
    return result


def _prediction_evidence(parameters, scaled, actual, baseline, y_magnitude):
    _, test, center, spread, magnitude, _ = scaled
    with _binary64_arithmetic():
        beta, offset = parameters[:-1], parameters[-1]
        unstandardized = beta / spread
        coefficients = (unstandardized * y_magnitude) / magnitude
        intercept = float((offset - center @ unstandardized) * y_magnitude)
        prediction = (test @ beta + offset) * y_magnitude
        r2_scale, r2_reason = _r2_scale(actual)
        metrics = _metrics(actual, prediction, r2_scale)
        baseline_metrics = _metrics(actual, baseline, r2_scale)
    return coefficients, intercept, metrics, baseline_metrics, r2_reason


def _prediction_basis(names, parameters, scaled, response_magnitude) -> dict:
    """Record the exact scaled representation used to score the holdout."""
    _, _, center, spread, magnitude, varying = scaled
    beta, intercept = parameters[:-1], float(parameters[-1])
    fields = {
        "input_magnitude": magnitude, "normalized_center": center, "normalized_scale": spread,
        "standardized_coefficients": beta,
    }
    shape = (len(names),)
    if (any(values.shape != shape or not np.isfinite(values).all() for values in fields.values())
            or varying.shape != shape or varying.dtype != np.dtype(bool)
            or (magnitude <= 0).any() or (spread <= 0).any()
            or not math.isfinite(intercept) or not math.isfinite(response_magnitude) or response_magnitude <= 0):
        raise RuntimeError("RIDGE_PREDICTION_BASIS_INVALID: scaled prediction parameters are not finite and aligned")
    return {
        "schema_version": 1, "scale_policy": "training_max_abs_then_population_sd", "predictors": list(names),
        **{name: values.tolist() for name, values in fields.items()}, "varying": varying.tolist(),
        "standardized_intercept": intercept, "response_magnitude": float(response_magnitude),
    }


def validate_prediction_size(rows: int, columns: int, *, elastic_net: bool) -> None:
    if elastic_net:
        if rows > _ELASTIC_MAX_ROWS or columns > _ELASTIC_MAX_FEATURES or rows * columns > _ELASTIC_MAX_VALUES:
            raise ValueError("ELASTIC_NET_WORK_LIMIT: input exceeds 100,000 rows, 128 predictors, or 1,000,000 values")
    elif rows > _MAX_ROWS or rows * (columns + 1) > _MAX_VALUES:
        raise ValueError("RIDGE_WORK_LIMIT: input exceeds the native Ridge size limit")


def validate_logistic_size(rows: int, columns: int) -> None:
    if rows > _LOGISTIC_MAX_ROWS or columns > _LOGISTIC_MAX_FEATURES or rows * (columns + 1) > _LOGISTIC_MAX_VALUES:
        raise ValueError("LOGISTIC_WORK_LIMIT: input exceeds 100,000 rows, 64 predictors, or 1,000,000 values")


def run_ridge(frame: pd.DataFrame, *, outcome: str, predictors: list[str], alpha: float,
              holdout_fraction: float, time_col: str | None = None) -> dict:
    """Fit one dense Ridge and return coefficients, held-out metrics, and a build receipt.

    The input order is the stated chronology when time_col is omitted. Otherwise
    times are sorted ascending and equal times remain on the same side of the
    split. Naive ISO timestamps use UTC. The standardizer uses the training
    means and population standard deviations. The baseline is the training
    response mean. Alpha multiplies the squared standardized slopes in the
    sum-of-squares objective. Coefficients are returned in raw units for
    interpretation. The prediction basis preserves the scored representation
    when large raw feature offsets would cause cancellation.
    """
    checkpoint = current_check()
    if checkpoint is not None:
        checkpoint()
    names = _columns(frame, outcome, predictors, time_col)
    penalty_error = "RIDGE_INVALID_ALPHA: alpha must be finite and positive"
    penalty = _number(alpha, error=penalty_error)
    if penalty <= 0:
        raise ValueError(penalty_error)
    fraction = _holdout(holdout_fraction)

    rows, columns = len(frame), len(names)
    validate_prediction_size(rows, columns, elastic_net=False)
    positions, split = _split(frame, time_col, fraction)
    train_rows = split["train_rows"]
    if train_rows * columns * columns > _MAX_WORK:
        raise ValueError("RIDGE_WORK_LIMIT: training shape exceeds the native Ridge work budget")

    values = _sample_values(frame, names, outcome, positions, checkpoint)
    native, receipt = _loaded()
    return _ridge_from_sample(native, receipt, values, names, outcome, split, penalty, checkpoint)


def _ridge_from_sample(native, receipt, values, names, outcome, split, penalty, checkpoint):
    rows, columns, train_rows = len(values), len(names), split["train_rows"]
    target = values[:, -1]
    with _binary64_arithmetic():
        scaled = _scale(values[:train_rows, :-1], values[train_rows:, :-1], include_varying=True)
        train_y, actual = target[:train_rows], target[train_rows:]
        y_magnitude = float(np.max(np.abs(train_y))) or 1.0
        y = train_y / y_magnitude
    # The caller's cancellation exception bypasses the numeric error translation.
    result = _native_vector(native.fit(scaled[0].tobytes(), y.tobytes(), train_rows, columns, penalty, checkpoint),
                            columns + 1)
    baseline = math.fsum(y) / train_rows * y_magnitude
    coefficients, intercept, metrics, baseline_metrics, r2_reason = _prediction_evidence(
        result, scaled, actual, baseline, y_magnitude,
    )
    prediction_basis = _prediction_basis(names, result, scaled, y_magnitude)
    if checkpoint is not None:
        checkpoint()
    return {
        "schema_version": 1, "model_type": "native_ridge", "engine": "cpp17_ridge",
        "outcome": outcome, "predictors": names, "alpha": penalty, "nobs": rows,
        "intercept": intercept, "coefficients": dict(zip(names, map(float, coefficients), strict=True)),
        "split": split, "metrics": metrics, "mean_baseline": {"prediction": baseline, **baseline_metrics},
        "r2_reason": r2_reason, "native_build": dict(receipt), "prediction_basis": prediction_basis,
    }


def run_elastic_net(frame: pd.DataFrame, *, outcome: str, predictors: list[str], alpha: float,
                    l1_ratio: float, holdout_fraction: float, time_col: str | None = None) -> dict:
    """Fit certified Elastic Net on the same chronological prediction split as Ridge.

    Alpha weights the L1 and L2 penalties against SSE / (2 * training rows).
    Features use training-only standardization and the response uses its original
    scale, which is necessary for the L1 penalty. Report slopes in raw units.
    """
    checkpoint = current_check()
    if checkpoint is not None:
        checkpoint()
    names = _columns(frame, outcome, predictors, time_col)
    penalty_error = "ELASTIC_NET_INVALID_PENALTY: alpha must be finite and positive"
    penalty = _number(alpha, error=penalty_error)
    if penalty <= 0:
        raise ValueError(penalty_error)
    mixing_error = "ELASTIC_NET_INVALID_L1_RATIO: l1_ratio must be strictly between zero and one"
    mixing = _number(l1_ratio, error=mixing_error)
    if not 0 < mixing < 1:
        raise ValueError(mixing_error)
    fraction = _holdout(holdout_fraction)

    rows, columns = len(frame), len(names)
    validate_prediction_size(rows, columns, elastic_net=True)
    positions, split = _split(frame, time_col, fraction)
    train_rows = split["train_rows"]
    sweeps = min(_ELASTIC_MAX_ITERATIONS, _ELASTIC_MAX_WORK // (train_rows * columns))
    values = _sample_values(frame, names, outcome, positions, checkpoint)
    native, receipt = _loaded()
    fit = getattr(native, "fit_elastic_net", None)
    if not callable(fit):
        raise RuntimeError("ELASTIC_NET_BUILD_INVALID: rebuild with native/ridge/build.py and restart Workbench")

    with _binary64_arithmetic():
        scaled = _scale(values[:train_rows, :-1], values[train_rows:, :-1], include_varying=True)
        train_y, actual = values[:train_rows, -1], values[train_rows:, -1]
        y_magnitude = float(np.max(np.abs(train_y))) or 1.0
        baseline = math.fsum(train_y / y_magnitude) / train_rows * y_magnitude
    packed = fit(scaled[0].tobytes(), train_y.tobytes(), train_rows, columns, penalty, mixing,
                 _ELASTIC_TOLERANCE, sweeps, checkpoint)
    result = _native_vector(packed, columns + 4)
    violation, coefficient_bound, iterations = map(float, result[-3:])
    if not (0 <= violation <= _ELASTIC_TOLERANCE and 0 <= coefficient_bound <= _ELASTIC_TOLERANCE
            and iterations.is_integer() and 1 <= iterations <= sweeps):
        raise RuntimeError("ELASTIC_NET_BUILD_INVALID: native fit returned invalid convergence evidence")
    coefficients, intercept, metrics, baseline_metrics, r2_reason = _prediction_evidence(
        result[:columns + 1], scaled, actual, baseline, 1.0,
    )
    prediction_basis = _prediction_basis(names, result[:columns + 1], scaled, 1.0)
    if checkpoint is not None:
        checkpoint()
    return {
        "schema_version": 1, "model_type": "native_elastic_net", "engine": "cpp17_elastic_net",
        "outcome": outcome, "predictors": names, "alpha": penalty, "l1_ratio": mixing, "nobs": rows,
        "intercept": intercept, "coefficients": dict(zip(names, map(float, coefficients), strict=True)),
        "split": split, "metrics": metrics, "mean_baseline": {"prediction": baseline, **baseline_metrics},
        "r2_reason": r2_reason, "native_build": dict(receipt), "prediction_basis": prediction_basis,
        "convergence": {
            "status": "converged", "method": "cyclic_coordinate_descent", "iterations": int(iterations),
            "max_iterations": sweeps, "kkt_tolerance": _ELASTIC_TOLERANCE, "kkt_violation": violation,
            "scaled_coefficient_error_bound": coefficient_bound,
        },
    }


def _classification_metrics(actual: np.ndarray, score: np.ndarray | float, positives: int) -> dict:
    positive = actual == 1.0
    losses = np.logaddexp(0, np.where(positive, -score, score))
    incorrect_probability = -np.expm1(-losses)
    negatives = actual.size - positives
    auc = None
    if positives and negatives:
        auc = 0.5
        if isinstance(score, np.ndarray):
            ranks = pd.Series(score).rank(method="average").to_numpy()
            auc = float((ranks[positive].sum() - positives * (positives + 1) / 2) / (positives * negatives))
    return {
        "log_loss": float((losses / actual.size).sum()),
        "brier_score": float(np.mean(incorrect_probability**2)),
        "accuracy": float(np.mean(positive == (score >= 0.0))), "roc_auc": auc,
    }


def run_logistic(frame: pd.DataFrame, *, outcome: str, predictors: list[str], alpha: float,
                 holdout_fraction: float, time_col: str | None = None) -> dict:
    """Fit L2 binary Logistic on a training prefix and score the reserved suffix.

    Alpha multiplies half the squared standardized slopes in the mean Bernoulli
    log-loss objective. The intercept is unpenalized and reports are predictive.
    Scores at or above zero map to class 1. ROC AUC ranks the decision scores.
    """
    checkpoint = current_check()
    if checkpoint is not None:
        checkpoint()
    names = _columns(frame, outcome, predictors, time_col)
    alpha_error = "LOGISTIC_INVALID_ALPHA: alpha must be between 1e-6 and 1e6 inclusive"
    penalty = _number(alpha, error=alpha_error)
    if not 1e-6 <= penalty <= 1e6:
        raise ValueError(alpha_error)
    fraction = _holdout(holdout_fraction)

    rows, columns = len(frame), len(names)
    validate_logistic_size(rows, columns)
    positions, split = _split(frame, time_col, fraction)
    train_rows = split["train_rows"]
    dimension = columns + 1
    if train_rows * dimension * (2 * dimension + 1) > _LOGISTIC_MAX_WORK:
        raise ValueError("LOGISTIC_WORK_LIMIT: training shape exceeds the Newton work budget")
    labels = frame[outcome]
    if (not pandas_types.is_numeric_dtype(labels.dtype) or pandas_types.is_bool_dtype(labels.dtype)
            or pandas_types.is_complex_dtype(labels.dtype) or not (labels.eq(0) | labels.eq(1)).fillna(False).all()):
        raise ValueError("LOGISTIC_INVALID_LABELS: outcome must contain only numeric 0 and 1")
    values = _sample_values(frame, names, outcome, positions, checkpoint)
    train_y, actual = values[:train_rows, -1], values[train_rows:, -1]
    train_positives, test_positives = int(np.count_nonzero(train_y)), int(np.count_nonzero(actual))
    if not 0 < train_positives < train_rows:
        raise ValueError("LOGISTIC_TRAIN_SINGLE_CLASS: training must contain both 0 and 1")

    native, receipt = _loaded()
    fit = getattr(native, "fit_logistic", None)
    if not callable(fit):
        raise RuntimeError("LOGISTIC_BUILD_INVALID: rebuild with native/ridge/build.py and restart Workbench")
    with _binary64_arithmetic(prefix="LOGISTIC"):
        scaled = _scale(values[:train_rows, :-1], values[train_rows:, :-1], include_varying=True)
    packed = fit(scaled[0].tobytes(), train_y.tobytes(), train_rows, columns, penalty,
                 _LOGISTIC_MAX_ITERATIONS, checkpoint)
    result = _native_vector(packed, columns + 4, prefix="LOGISTIC")
    parameters = result[:dimension]
    gradient, objective, iterations = map(float, result[dimension:])
    if not (0 <= gradient <= _LOGISTIC_GRADIENT_TOLERANCE and objective >= 0
            and iterations.is_integer() and 0 <= iterations <= _LOGISTIC_MAX_ITERATIONS):
        raise RuntimeError("LOGISTIC_BUILD_INVALID: native fit returned invalid convergence evidence")

    _, test, center, spread, magnitude, _ = scaled
    beta, offset = parameters[:-1], parameters[-1]
    baseline_score = math.log(train_positives) - math.log(train_rows - train_positives)
    with _binary64_arithmetic(prefix="LOGISTIC"), np.errstate(under="ignore"):
        unstandardized = beta / spread
        coefficients = unstandardized / magnitude
        intercept = float(offset - center @ unstandardized)
        metrics = _classification_metrics(actual, test @ beta + offset, test_positives)
        baseline = _classification_metrics(actual, baseline_score, test_positives)
    basis = _prediction_basis(names, parameters, scaled, 1.0)
    if checkpoint is not None:
        checkpoint()
    return {
        "schema_version": 1, "model_type": "native_logistic", "engine": "cpp17_logistic",
        "outcome": outcome, "predictors": names, "alpha": penalty, "nobs": rows,
        "intercept": intercept, "coefficients": dict(zip(names, map(float, coefficients), strict=True)),
        "link": "logit", "classification_threshold": 0.5, "split": split, "metrics": metrics,
        "prevalence_baseline": {"probability": train_positives / train_rows, **baseline},
        "roc_auc_reason": "single_class_test_outcome" if metrics["roc_auc"] is None else None,
        "class_counts": {
            "train": {"0": train_rows - train_positives, "1": train_positives},
            "test": {"0": actual.size - test_positives, "1": test_positives},
        },
        "native_build": dict(receipt), "prediction_basis": {**basis, "link": "logit"},
        "convergence": {
            "status": "converged", "method": "damped_newton", "iterations": int(iterations),
            "max_iterations": _LOGISTIC_MAX_ITERATIONS, "gradient_tolerance": _LOGISTIC_GRADIENT_TOLERANCE,
            "gradient_infinity_norm": gradient, "objective": objective,
        },
    }
