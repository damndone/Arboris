"""One bounded, typed projection contract for survey result consumers.

Survey estimates are persisted evidence, not a license for consumers to copy
arbitrary JSON scalars.  Agent, diagnostic, Report, and XLSX all use the
validators here so invalid numbers become a typed unavailable projection while
safe provenance remains visible.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
from typing import Any


MAX_SURVEY_PROJECTION_ABS = 1_000_000_000_000.0
MAX_SURVEY_PROJECTION_COUNT = 1_000_000
MAX_SURVEY_PROJECTION_STRING = 128
MAX_SURVEY_PROJECTION_WARNINGS = 16
MAX_SURVEY_PROJECTION_METRICS = 64

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
    bounded = value[:MAX_SURVEY_PROJECTION_WARNINGS]
    if any(not isinstance(item, str) or not item for item in bounded):
        return None
    return [item[:MAX_SURVEY_PROJECTION_STRING] for item in bounded]


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


def survey_payload_sha256(
    payload: Mapping[str, Any], *, binding_key: str = "summary_binding"
) -> str | None:
    """Hash a server-owned payload without making its binding self-referential."""

    if not isinstance(payload, Mapping):
        return None
    unsigned = dict(payload)
    unsigned.pop(binding_key, None)
    try:
        encoded = json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def validate_survey_artifact_binding(
    binding: Any,
    *,
    artifact_id: Any,
    run_id: Any,
    expected_payload_sha256: Any,
) -> bool:
    """Validate the immutable identity carried inside a server-owned packet."""

    if not isinstance(binding, Mapping):
        return False
    if (
        binding.get("artifact_id") != artifact_id
        or binding.get("run_id") != run_id
        or binding.get("status") not in {"complete", "available"}
        or binding.get("provenance") != "server"
    ):
        return False
    digest = binding.get("payload_sha256")
    return (
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        and digest == expected_payload_sha256
    )


def project_survey_result_summary(
    summary: Any,
    *,
    summary_status: Any,
    unavailable_reason: str,
    run_id: Any = None,
    artifact_id: Any = None,
) -> dict[str, Any]:
    """Project diagnostic identity and metrics through the survey contract.

    The summary is a narrative artifact, not an authority to copy arbitrary
    numeric JSON.  Invalid fields are omitted and the packet is marked typed
    unavailable; the raw scalar never crosses this boundary.
    """

    provenance: dict[str, str] = {}
    if isinstance(run_id, str) and run_id:
        provenance["run_id"] = run_id[:MAX_SURVEY_PROJECTION_STRING]
    if isinstance(artifact_id, str) and artifact_id:
        provenance["artifact_id"] = artifact_id[:MAX_SURVEY_PROJECTION_STRING]
    if provenance:
        provenance["producer"] = "server"

    if not isinstance(summary, Mapping):
        return _unavailable(reason=unavailable_reason, provenance=provenance)

    invalid = summary_status != "complete"
    identity: dict[str, Any] = {}
    raw_identity = summary.get("model_identity")
    if raw_identity is not None and not isinstance(raw_identity, Mapping):
        invalid = True
        raw_identity = {}
    raw_identity = raw_identity if isinstance(raw_identity, Mapping) else {}
    for field in ("model_family", "model_label", "y_variable"):
        if field not in raw_identity:
            continue
        value = _bounded_string(raw_identity.get(field))
        if value is None:
            invalid = True
        else:
            identity[field] = value

    if "n_observations" in raw_identity and raw_identity.get("n_observations") is not None:
        count = bounded_survey_integer(raw_identity.get("n_observations"))
        if count is None:
            invalid = True
        else:
            identity["n_observations"] = count
    if "x_variables" in raw_identity:
        variables = raw_identity.get("x_variables")
        if not isinstance(variables, list):
            invalid = True
        else:
            count = bounded_survey_integer(len(variables))
            if count is None:
                invalid = True
            else:
                identity["x_variable_count"] = count
    elif "x_variable_count" in raw_identity and raw_identity.get("x_variable_count") is not None:
        count = bounded_survey_integer(raw_identity.get("x_variable_count"))
        if count is None:
            invalid = True
        else:
            identity["x_variable_count"] = count

    metrics: dict[str, int | float] = {}
    raw_metrics = summary.get("model_quality", {})
    raw_metrics = raw_metrics.get("metrics") if isinstance(raw_metrics, Mapping) else None
    if raw_metrics is not None and not isinstance(raw_metrics, Mapping):
        invalid = True
        raw_metrics = {}
    if isinstance(raw_metrics, Mapping):
        for raw_key, raw_value in list(raw_metrics.items())[:MAX_SURVEY_PROJECTION_METRICS]:
            key = _bounded_string(raw_key)
            if key is None:
                invalid = True
                continue
            normalized_key = key.lower()
            value = bounded_survey_number(
                raw_value,
                probability=(normalized_key == "p_value" or normalized_key.endswith("_p_value")),
            )
            if value is None:
                invalid = True
                continue
            metrics[key] = value

    primary_metric_keys: list[str] = []
    raw_primary_keys = (
        summary.get("model_quality", {}).get("primary_metric_keys")
        if isinstance(summary.get("model_quality"), Mapping)
        else None
    )
    if raw_primary_keys is not None and not isinstance(raw_primary_keys, list):
        invalid = True
    elif isinstance(raw_primary_keys, list):
        for raw_key in raw_primary_keys[:MAX_SURVEY_PROJECTION_METRICS]:
            key = _bounded_string(raw_key)
            if key is None:
                invalid = True
            else:
                primary_metric_keys.append(key)

    expected_digest = survey_payload_sha256(summary)
    if not validate_survey_artifact_binding(
        summary.get("summary_binding"),
        artifact_id=artifact_id,
        run_id=run_id,
        expected_payload_sha256=expected_digest,
    ):
        invalid = True

    projected = {
        "model_identity": identity,
        "metrics": metrics,
        "primary_metric_keys": primary_metric_keys,
    }
    if provenance:
        projected["provenance"] = provenance
    if invalid:
        projected["projection_status"] = "unavailable"
        projected["unavailable_reason"] = unavailable_reason[:MAX_SURVEY_PROJECTION_STRING]
    else:
        projected["projection_status"] = "available"
    return projected


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
    if design.get("projection_status") == "unavailable":
        prior_reason = _bounded_string(design.get("unavailable_reason"))
        safe: dict[str, Any] = {}
        variance_method = _bounded_string(design.get("variance_method"))
        if variance_method is not None:
            safe["variance_method"] = variance_method
        variance_source = _bounded_string(design.get("variance_source"))
        if variance_source is not None:
            safe["variance_source"] = variance_source
        safe_source_id = _bounded_string(design.get("source_id"))
        if safe_source_id is not None:
            safe["source_id"] = safe_source_id
        warnings = _bounded_warnings(design.get("warnings"))
        if warnings is not None:
            safe["warnings"] = warnings
        return _unavailable(
            reason=prior_reason or unavailable_reason,
            provenance=provenance,
            safe=safe,
        )
    if design.get("projection_status") is not None:
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

    for field in ("variance_source", "source_id"):
        if field not in design:
            continue
        value = _bounded_string(design.get(field))
        if value is None:
            invalid = design.get(field) is not None
        else:
            projected[field] = value

    if projected.get("variance_method") not in {"linearization", "replicate"}:
        invalid = True
    if projected.get("variance_source") != "survey_design":
        invalid = True

    if "warnings" in design:
        warnings = _bounded_warnings(design.get("warnings"))
        if warnings is None:
            invalid = design.get("warnings") is not None
        else:
            projected["warnings"] = warnings

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
                if key in _COUNT_FIELDS
                or key in _DEGREE_FIELDS
                or key in _NUMERIC_FIELDS
                or key in _STRING_FIELDS
                or key in {
                    "variance_source",
                    "source_id",
                    "warnings",
                    "replicate_failure_reasons",
                    "replicate_weight_columns",
                    "provenance",
                }
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
    if coefficient.get("projection_status") == "unavailable":
        prior_reason = _bounded_string(coefficient.get("unavailable_reason"))
        safe: dict[str, Any] = {}
        for field in ("variance_source", "source_id"):
            value = _bounded_string(coefficient.get(field))
            if value is not None:
                safe[field] = value
        warnings = _bounded_warnings(coefficient.get("warnings"))
        if warnings is not None:
            safe["warnings"] = warnings
        return _unavailable(
            reason=prior_reason or unavailable_reason,
            provenance=provenance,
            safe=safe,
        )
    if coefficient.get("projection_status") is not None:
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
        elif coefficient.get(field) is not None:
            invalid = True
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
