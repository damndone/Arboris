"""Versioned, JSON-safe contracts for the standalone meta-analysis pack."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import (
    ContractError,
    freeze_json,
    require_exact_keys,
    thaw_json,
)


META_ANALYSIS_CONTRACT = "meta_analysis.result"
META_ANALYSIS_CONTRACT_VERSION = "1.0"
META_ANALYSIS_OPERATION_IDS = frozenset({"meta.effect_size", "meta.combine"})
META_ANALYSIS_EFFECT_MEASURES = frozenset(
    {
        "direct",
        "mean_difference",
        "standardized_mean_difference",
        "log_risk_ratio",
        "log_odds_ratio",
    }
)
META_ANALYSIS_COMBINE_METHODS = frozenset(
    {"fixed_effect", "derSimonian_laird", "paule_mandel"}
)
META_ANALYSIS_CI_METHODS = frozenset({"normal_z", "t", "hksj"})
META_ANALYSIS_STATUSES = frozenset({"completed", "rejected", "failed"})
META_ANALYSIS_REASON_CODES = frozenset(
    {"META_ANALYSIS_COMPLETED", "META_ANALYSIS_REJECTED", "META_ANALYSIS_FAILED"}
)
META_ANALYSIS_EVIDENCE_DIGEST_ALGORITHM = "sha256"
META_ANALYSIS_MAX_STUDIES = 1000
META_ANALYSIS_MAX_OUTPUT_ROWS = 2000

META_ANALYSIS_COMPLETED = "META_ANALYSIS_COMPLETED"
META_ANALYSIS_REJECTED = "META_ANALYSIS_REJECTED"
META_ANALYSIS_FAILED = "META_ANALYSIS_FAILED"

_RESULT_FIELDS = {
    "contract",
    "contract_version",
    "operation_id",
    "status",
    "reason_code",
    "result",
    "evidence_digest",
}
_OPERATION_RESULT_FIELDS = MappingProxyType(
    {
        "meta.effect_size": frozenset(
            {"effect_measure", "alpha", "study_count", "studies", "conversion"}
        ),
        "meta.combine": frozenset(
            {
                "effect_measure",
                "method",
                "alpha",
                "ci_method",
                "ci_semantics",
                "study_count",
                "studies",
                "weights",
                "pooled_effect",
                "pooled_se",
                "ci",
                "heterogeneity",
                "prediction_interval",
            }
        ),
    }
)
_STUDY_ROW_FIELDS = frozenset(
    {
        "study_id",
        "effect_measure",
        "effect",
        "variance",
        "yi",
        "vi",
        "standard_error",
        "fixed_weight",
        "random_weight",
        "fixed_relative_weight",
        "relative_weight",
        "contribution",
    }
)
_STUDY_ROW_NUMERIC_FIELDS = frozenset(
    {
        "effect",
        "variance",
        "yi",
        "vi",
        "standard_error",
        "fixed_weight",
        "random_weight",
        "fixed_relative_weight",
        "relative_weight",
        "contribution",
    }
)
_STATUS_REASON_CODES = MappingProxyType(
    {
        "completed": "META_ANALYSIS_COMPLETED",
        "rejected": "META_ANALYSIS_REJECTED",
        "failed": "META_ANALYSIS_FAILED",
    }
)
_CONVERSION_FIELDS = frozenset(
    {
        "kind",
        "effect_measure",
        "effect_semantics",
        "variance_semantics",
        "continuity_correction",
        "correction_applied_count",
        "zero_cell_policy",
        "input",
    }
)
_CI_FIELDS = frozenset({"lower", "upper"})
_CI_SEMANTICS_FIELDS = frozenset(
    {
        "method",
        "distribution",
        "alpha",
        "confidence_level",
        "degrees_of_freedom",
        "scale_estimator",
        "scale",
    }
)
_HETEROGENEITY_FIELDS = frozenset(
    {"Q", "q", "df", "p", "p_value", "tau2", "tau2_raw_dl", "I2", "i2", "H2", "h2"}
)
_PREDICTION_INTERVAL_FIELDS = frozenset(
    {"lower", "upper", "standard_error", "critical_value", "distribution", "tau2_included"}
)
_WEIGHTS_FIELDS = frozenset(
    {"study_ids", "fixed", "random", "selected", "relative_fixed", "relative_selected"}
)
_LEAVE_ONE_OUT_FIELDS = frozenset(
    {
        "excluded_study_id",
        "effect_measure",
        "method",
        "ci_method",
        "study_count",
        "pooled_effect",
        "pooled_se",
        "ci",
        "q",
        "df",
        "p_value",
        "tau2",
        "i2",
        "h2",
        "prediction_interval",
        "delta_pooled_effect",
    }
)
_INFLUENCE_FIELDS = frozenset({"kind", "bounded", "row_count", "leave_one_out"})


def _require_fields(
    value: Mapping[str, Any], required: frozenset[str], label: str
) -> None:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be a mapping")
    missing = required - set(value)
    if missing:
        raise ContractError(f"missing {label} field(s): {', '.join(sorted(missing))}")


def _require_exact_fields(
    value: Mapping[str, Any], required: frozenset[str], label: str
) -> None:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be a mapping")
    actual = set(value)
    unknown = actual - required
    missing = required - actual
    if unknown:
        raise ContractError(f"unknown {label} field(s): {', '.join(sorted(unknown))}")
    if missing:
        raise ContractError(f"missing {label} field(s): {', '.join(sorted(missing))}")


def _result_number(
    value: Any,
    field_name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise ContractError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ContractError(f"{field_name} must be finite")
    if minimum is not None and number < minimum:
        raise ContractError(f"{field_name} is below its supported bound")
    if maximum is not None and number > maximum:
        raise ContractError(f"{field_name} is above its supported bound")
    return number


def _result_integer(
    value: Any,
    field_name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        raise ContractError(f"{field_name} must be an integer")
    if minimum is not None and value < minimum:
        raise ContractError(f"{field_name} is below its supported bound")
    if maximum is not None and value > maximum:
        raise ContractError(f"{field_name} is above its supported bound")
    return value


def _result_probability(value: Any, field_name: str) -> float:
    return _result_number(value, field_name, minimum=0.0, maximum=1.0)


def _validate_interval(value: Mapping[str, Any], label: str) -> None:
    _require_exact_fields(value, _CI_FIELDS, label)
    _validate_bounds(value, label)


def _validate_bounds(value: Mapping[str, Any], label: str) -> None:
    _require_fields(value, _CI_FIELDS, label)
    lower = _result_number(value["lower"], f"{label}.lower")
    upper = _result_number(value["upper"], f"{label}.upper")
    if lower > upper:
        raise ContractError(f"{label} lower bound exceeds upper bound")


def _validate_prediction_interval(value: Mapping[str, Any], label: str) -> None:
    _require_exact_fields(value, _PREDICTION_INTERVAL_FIELDS, label)
    _validate_bounds(value, label)
    _result_number(value["standard_error"], f"{label}.standard_error", minimum=0.0)
    _result_number(value["critical_value"], f"{label}.critical_value", minimum=0.0)
    if value["critical_value"] == 0:
        raise ContractError(f"{label}.critical_value must be positive")
    distribution = value["distribution"]
    if type(distribution) is not str or distribution not in {"normal", "student_t"}:
        raise ContractError(f"{label}.distribution is not declared")
    _result_number(value["tau2_included"], f"{label}.tau2_included", minimum=0.0)


def _validate_ci_semantics(
    value: Mapping[str, Any], *, ci_method: str, alpha: float, study_count: int
) -> None:
    _require_exact_fields(value, _CI_SEMANTICS_FIELDS, "result.ci_semantics")
    method = value["method"]
    if type(method) is not str or method not in META_ANALYSIS_CI_METHODS:
        raise ContractError("result.ci_semantics.method is not declared")
    if method != ci_method:
        raise ContractError("result.ci_semantics.method must match result.ci_method")
    expected_distribution = "normal" if method == "normal_z" else "student_t"
    if value["distribution"] != expected_distribution:
        raise ContractError("result.ci_semantics.distribution does not match ci_method")
    alpha_value = _result_number(value["alpha"], "result.ci_semantics.alpha")
    if not 0.0 < alpha_value < 1.0 or alpha_value != alpha:
        raise ContractError("result.ci_semantics.alpha must match result.alpha")
    confidence_level = _result_number(
        value["confidence_level"], "result.ci_semantics.confidence_level"
    )
    if confidence_level != 1.0 - alpha:
        raise ContractError("result.ci_semantics.confidence_level does not match alpha")
    degrees_of_freedom = value["degrees_of_freedom"]
    if method == "normal_z":
        if degrees_of_freedom is not None:
            raise ContractError("normal_z confidence intervals must not declare degrees_of_freedom")
    elif degrees_of_freedom != study_count - 1:
        raise ContractError("student-t confidence intervals must use study_count - 1 degrees of freedom")
    elif type(degrees_of_freedom) is not int or degrees_of_freedom < 1:
        raise ContractError("result.ci_semantics.degrees_of_freedom must be a positive integer")
    scale_estimator = value["scale_estimator"]
    expected_scale_estimator = "hksj" if method == "hksj" else "unit"
    if scale_estimator != expected_scale_estimator:
        raise ContractError("result.ci_semantics.scale_estimator does not match ci_method")
    _result_number(value["scale"], "result.ci_semantics.scale", minimum=0.0)


def _validate_heterogeneity(value: Mapping[str, Any], study_count: int) -> None:
    _require_exact_fields(value, _HETEROGENEITY_FIELDS, "result.heterogeneity")
    q = _result_number(value["Q"], "result.heterogeneity.Q", minimum=0.0)
    if value["q"] != q:
        raise ContractError("result.heterogeneity.q must match Q")
    df = _result_integer(value["df"], "result.heterogeneity.df", minimum=1)
    if df != study_count - 1:
        raise ContractError("result.heterogeneity.df must equal study_count - 1")
    p_value = _result_probability(value["p"], "result.heterogeneity.p")
    if value["p_value"] != p_value:
        raise ContractError("result.heterogeneity.p_value must match p")
    _result_number(value["tau2"], "result.heterogeneity.tau2", minimum=0.0)
    _result_number(value["tau2_raw_dl"], "result.heterogeneity.tau2_raw_dl")
    i2 = _result_probability(value["I2"], "result.heterogeneity.I2")
    if value["i2"] != i2:
        raise ContractError("result.heterogeneity.i2 must match I2")
    h2 = _result_number(value["H2"], "result.heterogeneity.H2", minimum=0.0)
    if value["h2"] != h2:
        raise ContractError("result.heterogeneity.h2 must match H2")


def _validate_weights(
    value: Mapping[str, Any], *, study_ids: list[str], study_count: int
) -> None:
    _require_exact_fields(value, _WEIGHTS_FIELDS, "result.weights")
    ids = value["study_ids"]
    if not isinstance(ids, (list, tuple)) or len(ids) != study_count:
        raise ContractError("result.weights.study_ids must match study_count")
    if list(ids) != study_ids:
        raise ContractError("result.weights.study_ids must match result.studies")
    for index, identifier in enumerate(ids):
        if type(identifier) is not str or not identifier.strip():
            raise ContractError(f"result.weights.study_ids[{index}] must be a stable string")
    for field_name in ("fixed", "random", "selected"):
        values = value[field_name]
        if not isinstance(values, (list, tuple)) or len(values) != study_count:
            raise ContractError(f"result.weights.{field_name} must match study_count")
        for index, item in enumerate(values):
            _result_number(item, f"result.weights.{field_name}[{index}]", minimum=0.0)
            if item == 0:
                raise ContractError(f"result.weights.{field_name}[{index}] must be positive")
    for field_name in ("relative_fixed", "relative_selected"):
        values = value[field_name]
        if not isinstance(values, (list, tuple)) or len(values) != study_count:
            raise ContractError(f"result.weights.{field_name} must match study_count")
        for index, item in enumerate(values):
            _result_probability(item, f"result.weights.{field_name}[{index}]")


def _validate_conversion(
    value: Mapping[str, Any], *, effect_measure: str, operation_id: str, study_count: int
) -> None:
    common_fields = frozenset({"kind", "effect_measure", "variance_semantics"})
    allowed_fields = common_fields | _CONVERSION_FIELDS
    _require_fields(value, common_fields, "result.conversion")
    unknown = set(value) - allowed_fields
    if unknown:
        raise ContractError(
            f"unknown result.conversion field(s): {', '.join(sorted(unknown))}"
        )
    if value["effect_measure"] != effect_measure:
        raise ContractError("result.conversion.effect_measure must match result.effect_measure")
    if type(value["kind"]) is not str or value["kind"] not in {
        "direct_yi_vi",
        "summary_to_effect",
        "2x2_summary_to_effect",
    }:
        raise ContractError("result.conversion.kind is not declared")
    if type(value["variance_semantics"]) is not str or not value["variance_semantics"]:
        raise ContractError("result.conversion.variance_semantics must be a non-empty string")
    if operation_id == "meta.effect_size" and "input" in value:
        raise ContractError("result.conversion.input is not valid for meta.effect_size")
    if operation_id == "meta.combine" and "input" in value:
        if value["input"] != "meta.effect_size_evidence":
            raise ContractError("result.conversion.input is not declared")
    if effect_measure == "standardized_mean_difference":
        if value.get("effect_semantics") != "hedges_g_bias_corrected":
            raise ContractError("SMD conversion must declare Hedges-g semantics")
    elif "effect_semantics" in value:
        raise ContractError("effect_semantics is not valid for this effect measure")
    binary = effect_measure in {"log_risk_ratio", "log_odds_ratio"}
    if binary:
        binary_fields = frozenset(
            {
                "continuity_correction",
                "correction_applied_count",
                "zero_cell_policy",
            }
        )
        _require_fields(value, binary_fields, "result.conversion")
        correction = value["continuity_correction"]
        if correction is not None:
            _result_number(
                correction,
                "result.conversion.continuity_correction",
                minimum=0.0,
            )
            if correction == 0:
                raise ContractError("result.conversion.continuity_correction must be positive")
        _result_integer(
            value["correction_applied_count"],
            "result.conversion.correction_applied_count",
            minimum=0,
            maximum=study_count,
        )
        if value["zero_cell_policy"] != "explicit_continuity_correction_required":
            raise ContractError("result.conversion.zero_cell_policy is not declared")
    else:
        if "continuity_correction" in value or "correction_applied_count" in value or "zero_cell_policy" in value:
            raise ContractError("continuity correction metadata is not valid for this effect measure")


def _validate_leave_one_out(
    value: list[Any] | tuple[Any, ...],
    *,
    study_ids: list[str],
    effect_measure: str,
    method: str,
    ci_method: str,
    study_count: int,
) -> None:
    if len(value) != study_count:
        raise ContractError("result.leave_one_out must contain one row per study")
    seen: set[str] = set()
    for index, row in enumerate(value):
        label = f"result.leave_one_out[{index}]"
        _require_exact_fields(row, _LEAVE_ONE_OUT_FIELDS, label)
        excluded = row["excluded_study_id"]
        if type(excluded) is not str or excluded not in study_ids or excluded in seen:
            raise ContractError(f"{label}.excluded_study_id is not a unique study ID")
        seen.add(excluded)
        if row["effect_measure"] != effect_measure:
            raise ContractError(f"{label}.effect_measure must match result.effect_measure")
        if row["method"] != method:
            raise ContractError(f"{label}.method must match result.method")
        if row["ci_method"] != ci_method:
            raise ContractError(f"{label}.ci_method must match result.ci_method")
        row_study_count = _result_integer(
            row["study_count"], f"{label}.study_count", minimum=2, maximum=study_count - 1
        )
        if row_study_count != study_count - 1:
            raise ContractError(f"{label}.study_count must equal result.study_count - 1")
        _result_number(row["pooled_effect"], f"{label}.pooled_effect")
        _result_number(row["pooled_se"], f"{label}.pooled_se", minimum=0.0)
        _validate_interval(row["ci"], f"{label}.ci")
        _result_number(row["q"], f"{label}.q", minimum=0.0)
        row_df = _result_integer(row["df"], f"{label}.df", minimum=1)
        if row_df != row_study_count - 1:
            raise ContractError(f"{label}.df must equal row study_count - 1")
        _result_probability(row["p_value"], f"{label}.p_value")
        _result_number(row["tau2"], f"{label}.tau2", minimum=0.0)
        _result_probability(row["i2"], f"{label}.i2")
        _result_number(row["h2"], f"{label}.h2", minimum=0.0)
        _validate_prediction_interval(row["prediction_interval"], f"{label}.prediction_interval")
        _result_number(row["delta_pooled_effect"], f"{label}.delta_pooled_effect")
    if seen != set(study_ids):
        raise ContractError("result.leave_one_out must cover every study exactly once")


def _study_row_number(value: Any, field_name: str, *, positive: bool = False) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise ContractError(f"study row {field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ContractError(f"study row {field_name} must be finite")
    if positive and number <= 0.0:
        raise ContractError(f"study row {field_name} must be strictly positive")
    return number


def _validate_study_rows(
    studies: list[Any] | tuple[Any, ...], *, effect_measure: str
) -> None:
    seen_ids: set[str] = set()
    for index, row in enumerate(studies):
        label = f"result.studies[{index}]"
        if not isinstance(row, Mapping):
            raise ContractError(f"{label} must be a mapping")
        unknown = set(row) - _STUDY_ROW_FIELDS
        if unknown:
            raise ContractError(
                f"{label} contains unsafe field(s): {', '.join(sorted(unknown))}"
            )
        study_id = row.get("study_id")
        if type(study_id) is not str or not study_id.strip():
            raise ContractError(f"{label}.study_id must be a stable non-empty string")
        if study_id in seen_ids:
            raise ContractError("result.studies must contain unique study_id values")
        seen_ids.add(study_id)

        row_measure = row.get("effect_measure")
        if type(row_measure) is not str or row_measure != effect_measure:
            raise ContractError(
                f"{label}.effect_measure must match result.effect_measure"
            )

        has_effect = "effect" in row
        has_yi = "yi" in row
        if not has_effect and not has_yi:
            raise ContractError(f"{label} must contain effect or yi")
        if has_effect:
            effect = _study_row_number(row["effect"], f"{label}.effect")
        else:
            effect = _study_row_number(row["yi"], f"{label}.yi")
        if has_effect and has_yi:
            yi = _study_row_number(row["yi"], f"{label}.yi")
            if effect != yi:
                raise ContractError(f"{label}.effect and yi disagree")

        has_variance = "variance" in row
        has_vi = "vi" in row
        if not has_variance and not has_vi:
            raise ContractError(f"{label} must contain variance or vi")
        if has_variance:
            variance = _study_row_number(
                row["variance"], f"{label}.variance", positive=True
            )
        else:
            variance = _study_row_number(row["vi"], f"{label}.vi", positive=True)
        if has_variance and has_vi:
            vi = _study_row_number(row["vi"], f"{label}.vi", positive=True)
            if variance != vi:
                raise ContractError(f"{label}.variance and vi disagree")

        for field_name in _STUDY_ROW_NUMERIC_FIELDS:
            if field_name in row:
                _study_row_number(row[field_name], f"{label}.{field_name}")


def compute_meta_analysis_evidence_digest(payload: Mapping[str, Any]) -> str:
    """Hash a result envelope while excluding its self-referential digest."""

    if not isinstance(payload, Mapping):
        raise ContractError("meta-analysis evidence payload must be a mapping")
    projection = {
        key: thaw_json(value)
        for key, value in payload.items()
        if key != "evidence_digest"
    }
    try:
        return sha256_canonical(projection)
    except (TypeError, ValueError) as exc:
        raise ContractError("meta-analysis evidence payload is not canonical JSON") from exc


def _validate_digest(value: Any, expected: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or value.lower() != value
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ContractError("evidence_digest must be a lowercase SHA-256 hexadecimal digest")
    if value != expected:
        raise ContractError("evidence_digest does not match the result evidence")


def _validate_result(result: Mapping[str, Any], operation_id: str) -> None:
    _require_fields(
        result,
        _OPERATION_RESULT_FIELDS[operation_id],
        f"{operation_id} result",
    )
    effect_measure = result["effect_measure"]
    if type(effect_measure) is not str or effect_measure not in META_ANALYSIS_EFFECT_MEASURES:
        raise ContractError("result.effect_measure is not a declared meta-analysis scale")

    alpha = result["alpha"]
    if type(alpha) not in {int, float} or isinstance(alpha, bool):
        raise ContractError("result.alpha must be a finite number")
    if not math.isfinite(float(alpha)) or not 0.0 < float(alpha) < 1.0:
        raise ContractError("result.alpha must be strictly between 0 and 1")

    study_count = result["study_count"]
    if (
        type(study_count) is not int
        or not 2 <= study_count <= META_ANALYSIS_MAX_STUDIES
    ):
        raise ContractError("result.study_count is outside the supported bound")
    studies = result["studies"]
    if not isinstance(studies, (list, tuple)) or len(studies) != study_count:
        raise ContractError("result.studies must contain exactly study_count rows")
    if len(studies) > META_ANALYSIS_MAX_OUTPUT_ROWS:
        raise ContractError("result.studies exceeds the supported output bound")
    _validate_study_rows(studies, effect_measure=effect_measure)
    _validate_conversion(
        result["conversion"],
        effect_measure=effect_measure,
        operation_id=operation_id,
        study_count=study_count,
    )

    if operation_id != "meta.combine":
        return

    method = result["method"]
    if type(method) is not str or method not in META_ANALYSIS_COMBINE_METHODS:
        raise ContractError("result.method is not a declared meta-analysis method")
    ci_method = result["ci_method"]
    if type(ci_method) is not str or ci_method not in META_ANALYSIS_CI_METHODS:
        raise ContractError("result.ci_method is not declared")
    _validate_ci_semantics(
        result["ci_semantics"],
        ci_method=ci_method,
        alpha=float(alpha),
        study_count=study_count,
    )
    _validate_interval(result["ci"], "result.ci")
    _validate_heterogeneity(result["heterogeneity"], study_count)
    _validate_prediction_interval(result["prediction_interval"], "result.prediction_interval")
    study_ids = [str(row["study_id"]) for row in studies]
    _validate_weights(
        result["weights"],
        study_ids=study_ids,
        study_count=study_count,
    )
    if "leave_one_out" in result:
        leave_one_out = result["leave_one_out"]
        if (
            not isinstance(leave_one_out, (list, tuple))
            or len(leave_one_out) > META_ANALYSIS_MAX_OUTPUT_ROWS
        ):
            raise ContractError("result.leave_one_out exceeds the supported output bound")
        _validate_leave_one_out(
            leave_one_out,
            study_ids=study_ids,
            effect_measure=effect_measure,
            method=method,
            ci_method=ci_method,
            study_count=study_count,
        )
    if "influence" in result:
        influence = result["influence"]
        _require_exact_fields(influence, _INFLUENCE_FIELDS, "result.influence")
        if influence["kind"] != "leave_one_out" or influence["bounded"] is not True:
            raise ContractError("result.influence must declare bounded leave-one-out evidence")
        row_count = _result_integer(
            influence["row_count"],
            "result.influence.row_count",
            minimum=1,
            maximum=META_ANALYSIS_MAX_OUTPUT_ROWS,
        )
        nested = influence["leave_one_out"]
        if "leave_one_out" not in result:
            raise ContractError("result.influence requires result.leave_one_out")
        if not isinstance(nested, (list, tuple)) or len(nested) > META_ANALYSIS_MAX_OUTPUT_ROWS:
            raise ContractError("result.influence.leave_one_out exceeds the supported output bound")
        if row_count != len(nested) or nested != result["leave_one_out"]:
            raise ContractError("result.influence.leave_one_out must match result.leave_one_out")
    for field_name in ("pooled_effect", "pooled_se"):
        _result_number(
            result[field_name],
            f"result.{field_name}",
            minimum=0.0 if field_name == "pooled_se" else None,
        )


@dataclass(frozen=True)
class MetaAnalysisResultEnvelope:
    """Immutable envelope for conversion and combination evidence."""

    operation_id: str
    status: str
    reason_code: str
    result: Mapping[str, Any]
    evidence_digest: str

    def __post_init__(self) -> None:
        if type(self.operation_id) is not str or self.operation_id not in META_ANALYSIS_OPERATION_IDS:
            raise ContractError("operation_id is not a declared meta-analysis operation")
        if type(self.status) is not str or self.status not in META_ANALYSIS_STATUSES:
            raise ContractError("status is not a declared meta-analysis status")
        if type(self.reason_code) is not str or self.reason_code not in META_ANALYSIS_REASON_CODES:
            raise ContractError("reason_code is not a declared meta-analysis reason")
        if _STATUS_REASON_CODES[self.status] != self.reason_code:
            raise ContractError("status and reason_code must be a matching meta-analysis pair")
        if not isinstance(self.result, Mapping):
            raise ContractError("result must be a mapping")
        frozen_result = freeze_json(self.result, "result")
        _validate_result(frozen_result, self.operation_id)
        object.__setattr__(self, "result", frozen_result)
        packet_without_digest = {
            "contract": META_ANALYSIS_CONTRACT,
            "contract_version": META_ANALYSIS_CONTRACT_VERSION,
            "operation_id": self.operation_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "result": thaw_json(frozen_result),
        }
        _validate_digest(
            self.evidence_digest,
            compute_meta_analysis_evidence_digest(packet_without_digest),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": META_ANALYSIS_CONTRACT,
            "contract_version": META_ANALYSIS_CONTRACT_VERSION,
            "operation_id": self.operation_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "result": thaw_json(self.result),
            "evidence_digest": self.evidence_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MetaAnalysisResultEnvelope":
        require_exact_keys(value, _RESULT_FIELDS, "meta-analysis result envelope")
        if value["contract"] != META_ANALYSIS_CONTRACT:
            raise ContractError("contract is not the declared meta-analysis result contract")
        if value["contract_version"] != META_ANALYSIS_CONTRACT_VERSION:
            raise ContractError("contract_version is not the declared meta-analysis version")
        return cls(
            operation_id=value["operation_id"],
            status=value["status"],
            reason_code=value["reason_code"],
            result=value["result"],
            evidence_digest=value["evidence_digest"],
        )


def make_meta_analysis_envelope(
    *,
    operation_id: str,
    status: str,
    reason_code: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Build and validate a mutable JSON-shaped evidence envelope."""

    packet_without_digest = {
        "contract": META_ANALYSIS_CONTRACT,
        "contract_version": META_ANALYSIS_CONTRACT_VERSION,
        "operation_id": operation_id,
        "status": status,
        "reason_code": reason_code,
        "result": thaw_json(freeze_json(result, "result")),
    }
    digest = compute_meta_analysis_evidence_digest(packet_without_digest)
    return MetaAnalysisResultEnvelope(
        operation_id=operation_id,
        status=status,
        reason_code=reason_code,
        result=result,
        evidence_digest=digest,
    ).to_dict()


def read_meta_analysis_evidence(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a bounded packet and return its JSON-shaped readback."""

    return MetaAnalysisResultEnvelope.from_dict(value).to_dict()


__all__ = [
    "META_ANALYSIS_COMPLETED",
    "META_ANALYSIS_CONTRACT",
    "META_ANALYSIS_CONTRACT_VERSION",
    "META_ANALYSIS_CI_METHODS",
    "META_ANALYSIS_COMBINE_METHODS",
    "META_ANALYSIS_EFFECT_MEASURES",
    "META_ANALYSIS_EVIDENCE_DIGEST_ALGORITHM",
    "META_ANALYSIS_FAILED",
    "META_ANALYSIS_MAX_OUTPUT_ROWS",
    "META_ANALYSIS_MAX_STUDIES",
    "META_ANALYSIS_OPERATION_IDS",
    "META_ANALYSIS_REASON_CODES",
    "META_ANALYSIS_REJECTED",
    "META_ANALYSIS_STATUSES",
    "MetaAnalysisResultEnvelope",
    "compute_meta_analysis_evidence_digest",
    "make_meta_analysis_envelope",
    "read_meta_analysis_evidence",
]
