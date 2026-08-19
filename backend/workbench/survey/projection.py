"""One bounded, typed projection contract for survey result consumers.

Survey estimates are persisted evidence, not a license for consumers to copy
arbitrary JSON scalars.  Agent, diagnostic, Report, and XLSX all use the
validators here so invalid numbers become a typed unavailable projection while
safe provenance remains visible.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any


MAX_SURVEY_PROJECTION_ABS = 1_000_000_000_000.0
MAX_SURVEY_PROJECTION_COUNT = 1_000_000
MAX_SURVEY_PROJECTION_STRING = 128
MAX_SURVEY_PROJECTION_WARNINGS = 16

_COUNT_FIELDS = {
    "n_obs",
    "n_strata",
    "n_psu",
    "replicates_attempted",
    "replicates_succeeded",
    "replicates_failed",
}
_DEGREE_FIELDS = {"df", "degf", "design_df", "residual_df", "residual_degf"}
_NUMERIC_FIELDS = {"design_effect", "effective_sample_size"}
_STRING_FIELDS = {
    "variance_method",
    "strata_column",
    "psu_column",
    "weight_column",
    "replicate_type",
    "lonely_psu_policy",
    "subpopulation",
    "weight_frame",
}


def bounded_survey_number(
    value: Any,
    *,
    nonnegative: bool = False,
    positive: bool = False,
    probability: bool = False,
) -> int | float | None:
    """Return a finite bounded scalar with the requested value semantics."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or abs(parsed) > MAX_SURVEY_PROJECTION_ABS:
        return None
    if probability and not 0 <= parsed <= 1:
        return None
    if positive and parsed <= 0:
        return None
    if nonnegative and parsed < 0:
        return None
    return value


def bounded_survey_integer(
    value: Any, *, nonnegative: bool = True, positive: bool = False
) -> int | None:
    """Return only an actual bounded integer; floats are not coerced."""

    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value > MAX_SURVEY_PROJECTION_COUNT:
        return None
    if positive and value <= 0:
        return None
    if nonnegative and value < 0:
        return None
    return value


def _bounded_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:MAX_SURVEY_PROJECTION_STRING]


def _bounded_warnings(value: Any) -> list[str] | None:
    if not isinstance(value, (list, tuple)):
        return None
    return [
        item[:MAX_SURVEY_PROJECTION_STRING]
        for item in value[:MAX_SURVEY_PROJECTION_WARNINGS]
        if isinstance(item, str) and item
    ]


def _bounded_provenance(
    value: Any,
    *,
    run_id: Any = None,
    source_id: Any = None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    if isinstance(value, Mapping):
        for key in ("run_id", "source_id", "artifact_id", "producer"):
            label = _bounded_string(value.get(key))
            if label is not None:
                result[key] = label
    for key, raw in (("run_id", run_id), ("source_id", source_id)):
        label = _bounded_string(raw)
        if label is not None:
            result[key] = label
    return result


def _unavailable(
    *,
    reason: str,
    provenance: dict[str, str],
    safe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(safe or {})
    result["projection_status"] = "unavailable"
    result["unavailable_reason"] = reason[:MAX_SURVEY_PROJECTION_STRING]
    if provenance:
        result["provenance"] = provenance
    return result


def project_survey_design(
    design: Any,
    *,
    unavailable_reason: str = "SURVEY_DESIGN_PROJECTION_INVALID",
    run_id: Any = None,
    source_id: Any = None,
) -> dict[str, Any] | None:
    """Project survey design metadata without copying invalid raw scalars."""

    if design is None:
        return None
    raw_provenance = design.get("provenance") if isinstance(design, Mapping) else None
    design_run_id = design.get("run_id") if isinstance(design, Mapping) else None
    provenance = _bounded_provenance(
        raw_provenance,
        run_id=design_run_id or run_id,
        source_id=(design.get("source_id") if isinstance(design, Mapping) else None)
        if (raw_provenance or design_run_id or run_id or source_id)
        else source_id,
    )
    if not isinstance(design, Mapping):
        return _unavailable(reason=unavailable_reason, provenance=provenance)

    projected: dict[str, Any] = {}
    invalid = False
    for field in (*_COUNT_FIELDS, *_DEGREE_FIELDS):
        if field not in design:
            continue
        value = bounded_survey_integer(
            design.get(field),
            nonnegative=field in _COUNT_FIELDS,
            positive=field in _DEGREE_FIELDS,
        )
        if value is None:
            invalid = True
        else:
            projected[field] = value
    for field in _NUMERIC_FIELDS:
        if field not in design:
            continue
        value = bounded_survey_number(
            design.get(field),
            nonnegative=True,
            positive=field == "effective_sample_size",
        )
        if value is None:
            invalid = True
        else:
            projected[field] = value
    for field in _STRING_FIELDS:
        if field not in design:
            continue
        value = _bounded_string(design.get(field))
        if value is None and design.get(field) is not None:
            invalid = True
        elif value is not None:
            projected[field] = value

    if "replicate_failure_reasons" in design:
        raw_reasons = design.get("replicate_failure_reasons")
        if not isinstance(raw_reasons, Mapping):
            invalid = raw_reasons is not None
        else:
            reasons: dict[str, int] = {}
            for raw_key, raw_count in list(raw_reasons.items())[:32]:
                key = _bounded_string(raw_key)
                count = bounded_survey_integer(raw_count)
                if key is None or count is None:
                    invalid = True
                    continue
                reasons[key] = count
            projected["replicate_failure_reasons"] = reasons

    if "replicate_weight_columns" in design:
        raw_columns = design.get("replicate_weight_columns")
        if not isinstance(raw_columns, Sequence) or isinstance(raw_columns, (str, bytes)):
            invalid = raw_columns is not None
        else:
            columns: list[str] = []
            for raw_column in list(raw_columns)[:64]:
                column = _bounded_string(raw_column)
                if column is None:
                    invalid = True
                    continue
                columns.append(column)
            projected["replicate_weight_columns"] = columns

    if provenance:
        projected["provenance"] = provenance
    if invalid:
        return _unavailable(
            reason=unavailable_reason,
            provenance=provenance,
            safe={
                key: value
                for key, value in projected.items()
                if key in _STRING_FIELDS or key in {"replicate_failure_reasons", "replicate_weight_columns", "provenance"}
            },
        )
    return projected or (provenance and {"provenance": provenance}) or None


def project_survey_coefficient(
    coefficient: Any,
    *,
    unavailable_reason: str = "SURVEY_COEFFICIENT_PROJECTION_INVALID",
    run_id: Any = None,
    source_id: Any = None,
) -> dict[str, Any]:
    """Project coefficient inference and provenance under one survey contract."""

    raw_provenance = coefficient.get("provenance") if isinstance(coefficient, Mapping) else None
    coefficient_run_id = coefficient.get("run_id") if isinstance(coefficient, Mapping) else None
    provenance = _bounded_provenance(
        raw_provenance,
        run_id=coefficient_run_id or run_id,
        source_id=(coefficient.get("source_id") if isinstance(coefficient, Mapping) else None)
        if (raw_provenance or coefficient_run_id or run_id or source_id)
        else source_id,
    )
    if not isinstance(coefficient, Mapping):
        return _unavailable(reason=unavailable_reason, provenance=provenance)

    projected: dict[str, Any] = {}
    invalid = False
    for field in ("estimate", "ci_lower", "ci_upper"):
        if field not in coefficient:
            continue
        value = bounded_survey_number(coefficient.get(field))
        if value is None:
            invalid = True
        else:
            projected[field] = value
    if "std_error" in coefficient:
        value = bounded_survey_number(coefficient.get("std_error"), positive=True)
        if value is None:
            invalid = True
        else:
            projected["std_error"] = value
    if "p_value" in coefficient:
        value = bounded_survey_number(coefficient.get("p_value"), probability=True)
        if value is None:
            invalid = True
        else:
            projected["p_value"] = value
    if "confidence_interval" in coefficient:
        raw_interval = coefficient.get("confidence_interval")
        if not isinstance(raw_interval, (list, tuple)) or len(raw_interval) != 2:
            invalid = raw_interval is not None
        else:
            interval = [bounded_survey_number(item) for item in raw_interval]
            if any(item is None for item in interval) or interval[0] > interval[1]:
                invalid = True
            else:
                projected["confidence_interval"] = interval
    if "ci_lower" in projected and "ci_upper" in projected and projected["ci_lower"] > projected["ci_upper"]:
        invalid = True
    for field in ("variance_source", "source_id"):
        if field not in coefficient:
            continue
        value = _bounded_string(coefficient.get(field))
        if value is not None:
            projected[field] = value
    if "warnings" in coefficient:
        warnings = _bounded_warnings(coefficient.get("warnings"))
        if warnings is None:
            invalid = coefficient.get("warnings") is not None
        else:
            projected["warnings"] = warnings
    if provenance:
        projected["provenance"] = provenance
    if invalid:
        safe = {
            key: value
            for key, value in projected.items()
            if key in {"variance_source", "source_id", "warnings", "provenance"}
        }
        return _unavailable(reason=unavailable_reason, provenance=provenance, safe=safe)
    return projected


def project_survey_model_count(
    value: Any,
    *,
    unavailable_reason: str,
) -> tuple[int | None, bool]:
    """Bound a model-level nobs without treating a giant int as public data."""

    if value is None:
        return None, False
    bounded = bounded_survey_integer(value)
    return bounded, bounded is None
