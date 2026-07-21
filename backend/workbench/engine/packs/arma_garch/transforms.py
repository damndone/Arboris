"""Pure, lineage-preserving transforms and advisory profiles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from types import MappingProxyType
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError, diagnostic
from workbench.engine.packs.arma_garch.input import (
    PARSED_VALUE_COLUMN,
    ROW_ID_COLUMN,
)


TRANSFORMED_VALUE_COLUMN = "__wb_transformed_value__"
LINEAGE_COLUMN = "__wb_source_row_ids__"
TRANSFORM_IDS = ("level", "log_level", "diff_1", "log_return_pct")


@dataclass(frozen=True)
class TransformProfile:
    transform_id: str
    eligible: bool
    n_effective: int
    lost_rows: tuple[str, ...]
    adf_statistic: float | None
    adf_p_value: float | None
    adf_variants: tuple[Mapping[str, object], ...]
    acf_decay_summary: Mapping[str, object]
    variance_stability_summary: Mapping[str, object]
    outlier_sensitivity_summary: Mapping[str, object]
    semantic_interpretation: str
    recommendation_score: float
    recommendation_reason: str
    ineligibility_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "transform_id": self.transform_id,
            "eligible": self.eligible,
            "n_effective": self.n_effective,
            "lost_rows": list(self.lost_rows),
            "adf_statistic": self.adf_statistic,
            "adf_p_value": self.adf_p_value,
            "adf_variants": [dict(item) for item in self.adf_variants],
            "acf_decay_summary": dict(self.acf_decay_summary),
            "variance_stability_summary": dict(self.variance_stability_summary),
            "outlier_sensitivity_summary": dict(self.outlier_sensitivity_summary),
            "semantic_interpretation": self.semantic_interpretation,
            "recommendation_score": self.recommendation_score,
            "recommendation_reason": self.recommendation_reason,
            "ineligibility_code": self.ineligibility_code,
        }


def apply_transform(analysis_view: pd.DataFrame, transform_id: str) -> pd.DataFrame:
    """Return a new analysis view; source and parsed columns remain untouched."""

    if transform_id not in TRANSFORM_IDS:
        raise ValueError(f"unknown transform_id: {transform_id}")
    values = analysis_view[PARSED_VALUE_COLUMN].to_numpy(dtype=float)
    row_ids = analysis_view[ROW_ID_COLUMN].astype(str).tolist()
    if transform_id in {"log_level", "log_return_pct"} and np.any(values <= 0.0):
        raise ArmaGarchInputError(
            diagnostic(
                "LOG_REQUIRES_POSITIVE_VALUES",
                "log transforms require every participating source value to be positive",
                evidence={
                    "zero_value_count": int(np.count_nonzero(values == 0.0)),
                    "negative_value_count": int(np.count_nonzero(values < 0.0)),
                },
                impact="v1.8 will not shift, take absolute values, or otherwise alter the source series.",
            )
        )
    if transform_id in {"diff_1", "log_return_pct"} and len(values) < 2:
        raise ArmaGarchInputError(
            diagnostic(
                "INSUFFICIENT_OBSERVATIONS",
                "first differences require at least two observations",
                evidence={"observation_count": len(values)},
                impact="No differenced analysis row can be created.",
            )
        )

    result = analysis_view.copy(deep=True)
    if transform_id == "level":
        transformed = values
        lineage = [(row_id,) for row_id in row_ids]
    elif transform_id == "log_level":
        transformed = np.log(values)
        lineage = [(row_id,) for row_id in row_ids]
    elif transform_id == "diff_1":
        result = result.iloc[1:].copy()
        transformed = np.diff(values)
        lineage = list(zip(row_ids[:-1], row_ids[1:], strict=True))
    else:
        result = result.iloc[1:].copy()
        transformed = 100.0 * np.diff(np.log(values))
        lineage = list(zip(row_ids[:-1], row_ids[1:], strict=True))
    result[TRANSFORMED_VALUE_COLUMN] = transformed
    result[LINEAGE_COLUMN] = lineage
    return result.reset_index(drop=True)


def build_transform_profiles(
    analysis_view: pd.DataFrame,
) -> dict[str, TransformProfile]:
    """Build advisory evidence for all four transforms without choosing one."""

    profiles: dict[str, TransformProfile] = {}
    row_ids = tuple(analysis_view[ROW_ID_COLUMN].astype(str))
    values = analysis_view[PARSED_VALUE_COLUMN].to_numpy(dtype=float)
    for transform_id in TRANSFORM_IDS:
        log_transform = transform_id in {"log_level", "log_return_pct"}
        differenced = transform_id in {"diff_1", "log_return_pct"}
        eligible = bool(
            np.isfinite(values).all()
            and (not log_transform or np.all(values > 0.0))
            and (not differenced or len(values) >= 2)
        )
        ineligibility_code = None
        if not eligible:
            ineligibility_code = (
                "LOG_REQUIRES_POSITIVE_VALUES"
                if log_transform and np.any(values <= 0.0)
                else "INSUFFICIENT_OBSERVATIONS"
            )
            transformed = np.array([], dtype=float)
            lost_rows = row_ids
        else:
            transformed_frame = apply_transform(analysis_view, transform_id)
            transformed = transformed_frame[TRANSFORMED_VALUE_COLUMN].to_numpy(
                dtype=float
            )
            lost_rows = row_ids[:1] if differenced else ()
        adf_statistic, adf_p_value = _adf_evidence(transformed)
        score, reason = _recommendation(
            transform_id, eligible, adf_p_value, transformed
        )
        profiles[transform_id] = TransformProfile(
            transform_id=transform_id,
            eligible=eligible,
            n_effective=int(len(transformed)),
            lost_rows=tuple(lost_rows),
            adf_statistic=adf_statistic,
            adf_p_value=adf_p_value,
            adf_variants=_adf_variants(transformed),
            acf_decay_summary=MappingProxyType(_acf_decay(transformed)),
            variance_stability_summary=MappingProxyType(_variance_stability(transformed)),
            outlier_sensitivity_summary=MappingProxyType(_outlier_sensitivity(transformed)),
            semantic_interpretation=_semantic_interpretation(transform_id),
            recommendation_score=score,
            recommendation_reason=reason,
            ineligibility_code=ineligibility_code,
        )
    return profiles


def _adf_evidence(values: np.ndarray) -> tuple[float | None, float | None]:
    if len(values) < 8 or not np.isfinite(values).all() or float(np.ptp(values)) == 0.0:
        return None, None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = adfuller(values, autolag="AIC")
    except (ValueError, np.linalg.LinAlgError):
        return None, None
    statistic = float(result[0])
    p_value = float(result[1])
    if not math.isfinite(statistic) or not math.isfinite(p_value):
        return None, None
    return statistic, p_value


def _acf_decay(values: np.ndarray) -> dict[str, object]:
    if len(values) < 3 or float(np.ptp(values)) == 0.0:
        return {"lag_1": None, "first_lag_below_abs_0_2": None}
    max_lag = min(20, len(values) - 1)
    correlations: list[float | None] = []
    for lag in range(1, max_lag + 1):
        left = values[:-lag]
        right = values[lag:]
        if float(np.ptp(left)) == 0.0 or float(np.ptp(right)) == 0.0:
            correlations.append(None)
            continue
        correlation = float(np.corrcoef(left, right)[0, 1])
        correlations.append(correlation if math.isfinite(correlation) else None)
    first_decay = next(
        (lag for lag, value in enumerate(correlations, start=1) if value is not None and abs(value) < 0.2),
        None,
    )
    return {"lag_1": correlations[0], "first_lag_below_abs_0_2": first_decay}


def _variance_stability(values: np.ndarray) -> dict[str, object]:
    midpoint = len(values) // 2
    if midpoint < 2 or len(values) - midpoint < 2:
        return {"first_half_variance": None, "second_half_variance": None, "variance_ratio": None}
    first = float(np.var(values[:midpoint], ddof=1))
    second = float(np.var(values[midpoint:], ddof=1))
    ratio = None if min(first, second) <= 0.0 else max(first, second) / min(first, second)
    return {
        "first_half_variance": first,
        "second_half_variance": second,
        "variance_ratio": ratio,
    }


def _outlier_sensitivity(values: np.ndarray) -> dict[str, object]:
    if len(values) < 3:
        return {"robust_z_above_4_count": 0, "share": 0.0}
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad == 0.0:
        count = int(np.count_nonzero(values != median))
    else:
        robust_z = 0.6745 * np.abs(values - median) / mad
        count = int(np.count_nonzero(robust_z > 4.0))
    return {"robust_z_above_4_count": count, "share": count / len(values)}


def _recommendation(
    transform_id: str,
    eligible: bool,
    adf_p_value: float | None,
    values: np.ndarray,
) -> tuple[float, str]:
    if not eligible:
        return 0.0, "Transform is ineligible under the source-value constraints."
    base_score = {
        "level": 0.45,
        "log_level": 0.5,
        "diff_1": 0.55,
        "log_return_pct": 0.6,
    }[transform_id]
    stationarity_evidence = adf_p_value is not None and adf_p_value < 0.05
    score = min(1.0, base_score + (0.2 if stationarity_evidence else 0.0))
    reason = (
        "ADF and correlation evidence support reviewing this transform; user confirmation remains required."
        if stationarity_evidence
        else "Transform is eligible, but the advisory evidence is not sufficient for automatic selection."
    )
    return score, reason


def _semantic_interpretation(transform_id: str) -> str:
    return {
        "level": "Model the observed numeric level.",
        "log_level": "Model proportional movement on the log level.",
        "diff_1": "Model one-observation absolute changes.",
        "log_return_pct": "Model one-observation percentage log changes.",
    }[transform_id]


__all__ = [
    "LINEAGE_COLUMN",
    "TRANSFORMED_VALUE_COLUMN",
    "TRANSFORM_IDS",
    "TransformProfile",
    "apply_transform",
    "build_transform_profiles",
]


# A single ADF specification is weak evidence, so several are reported side by
# side, mirroring the usual Stata `dfuller` forms:
#   lags(0) / lags(5)   -> automatic and fixed-lag forms
#   drift               -> constant           (statsmodels regression="c")
#   trend               -> constant + trend   (regression="ct")
_ADF_SPECS: tuple[tuple[str, int | None], ...] = (
    ("n", None),
    ("c", None),
    ("ct", None),
    ("c", 5),
    ("ct", 5),
)


def _adf_variants(values: np.ndarray) -> tuple[Mapping[str, object], ...]:
    return tuple(
        _adf_variant(values, regression=regression, lags=lags)
        for regression, lags in _ADF_SPECS
    )


def _adf_variant(
    values: np.ndarray, *, regression: str, lags: int | None
) -> dict[str, object]:
    unavailable = {
        "regression": regression,
        "lags": lags,
        "status": "unavailable",
        "statistic": None,
        "p_value": None,
        "used_lag": None,
        "nobs": None,
    }
    if len(values) < 8 or not np.isfinite(values).all() or float(np.ptp(values)) == 0.0:
        return unavailable
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if lags is None:
                result = adfuller(values, regression=regression, autolag="AIC")
            else:
                result = adfuller(values, maxlag=lags, regression=regression, autolag=None)
    except (ValueError, np.linalg.LinAlgError):
        return unavailable
    statistic = float(result[0])
    p_value = float(result[1])
    if not math.isfinite(statistic) or not math.isfinite(p_value):
        return unavailable
    return {
        "regression": regression,
        "lags": lags,
        "status": "ok",
        "statistic": statistic,
        "p_value": p_value,
        "used_lag": int(result[2]),
        "nobs": int(result[3]),
    }
