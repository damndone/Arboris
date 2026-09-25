"""Bounded producer values for C0 sections; not a consumer/raw-file fallback."""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
import copy
import json
import math

from ..canonical import canonical_json_v1
from ..contracts.common.foundation_status import ValidationLevelV1
from ..contracts.evidence.envelope import EvidenceEnvelopeV1, NumericFactV1, ValidationSummaryV1
from ..contracts.evidence.result_sections import (
    MAX_DEPTH, MAX_NODES, MAX_TEXT_BYTES, MAX_SAFE_INTEGER,
    RESULT_SECTIONS_CONTRACT_DIGEST, SECTION_FIELDS, StructuredResultsV1,
    ARMA_REPORT_SCHEMA,
)
from ..evidence.consumer_adapters import EvidenceProjectionError


MAX_RESULT_INPUT_BYTES = 1024 * 1024
_INFERENCE_FIELDS = ("confidence_interval_method", "confidence_level", "reference_distribution",
                     "test_direction", "standard_error_method", "p_value_status")
_FIT_FIELDS = frozenset({"r_squared", "adjusted_r_squared", "f_statistic", "f_p_value", "aic", "bic", "llf", "pseudo_r2"})
_FAMILY_FIELDS = {
    **{name: _FIT_FIELDS for name in ("ols", "ols_robust", "panel_ols", "logit", "probit", "poisson", "poisson_rate")},
    "ordinal_logit": frozenset({"outcome_levels", "link", "odds_ratios"}),
    "multinomial_logit": frozenset({"outcome_levels", "base_category", "relative_risk_ratios"}),
    "survival_cox": frozenset({"hazard_ratios"}),
    "quantile_regression": frozenset({"quantiles", "fits", "bootstrap", "cross_quantile_comparisons"}),
    "time_series.arma_garch": frozenset({"status", "selected_specification", "estimation_strategy",
        "resolved_strategy", "joint_likelihood", "selection_repeated_during_validation", "report"}),
}
_FAMILY_DIAGNOSTIC_FIELDS = {
    "ordinal_logit": frozenset({"parallel_lines"}),
    "multinomial_logit": frozenset({"outcome_levels", "base_category"}),
    "survival_cox": frozenset({"duration_column", "event_column", "entry_column", "censoring",
        "time_to_event", "kaplan_meier", "log_rank", "risk_set", "schoenfeld"}),
    "quantile_regression": _FAMILY_FIELDS["quantile_regression"],
}


def _fields(*names):
    return dict.fromkeys(names)


_ARMA_REPORT_SCHEMA = ARMA_REPORT_SCHEMA

_ARMA_REPORT_SOURCES = frozenset({"ts.analysis_contract", "ts.report", "ts.forecast_metrics",
    "ts.parameters", "ts.final_diagnostics", "ts.arma_selection", "ts.volatility_selection", "ts.next_forecast"})


def report_artifact_refs(model):
    """Select this family's declared presentation inputs, never scan a run.

    Artifact identity/path/hash and execution metadata are admitted by the
    owner. Keeping selection here separates family vocabulary from host IO.
    """
    if model.get("model_type") != "time_series.arma_garch" or "artifact_refs" not in model:
        return {}
    refs = model["artifact_refs"]
    if not isinstance(refs, Mapping) or any(type(key) is not str for key in refs):
        _fail("Model artifact references must be a named map")
    selected = {key: value for key, value in refs.items()
                if key in _ARMA_REPORT_SOURCES or key.startswith("ts.chart.")}
    if any(type(value) is not str or not value for value in selected.values()):
        _fail("Report artifact references require declared paths")
    return selected


def _arma_public_report(artifacts, dependency_ids):
    """Public projection of host-verified ARMA payloads; no filesystem reads."""
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(dependency_ids):
        _fail("ARMA payloads require exact captured artifact dependencies")
    def payload(artifact_id):
        value = artifacts.get(artifact_id)
        if value is not None and not isinstance(value, Mapping):
            _fail("ARMA artifact payload is not a declared record")
        return value
    report = payload("ts.report")
    values = {
        "contract": payload("ts.analysis_contract"),
        "sample": report.get("sample") if report is not None else None,
        "metrics": payload("ts.forecast_metrics"), "parameters": payload("ts.parameters"),
        "diagnostics": payload("ts.final_diagnostics"),
        "selection": {"mean": payload("ts.arma_selection"), "variance": payload("ts.volatility_selection")},
        "next_forecast": payload("ts.next_forecast"),
        "forecast_limitations": report.get("forecast_limitations") if report is not None else None,
        "warnings": report.get("warnings") if report is not None else None,
        "chart_artifacts": sorted(key for key in artifacts if key.startswith("ts.chart.")),
        "artifact_ids": sorted(dependency_ids),
    }
    return _project_record(values, _ARMA_REPORT_SCHEMA)


# Schemas distinguish fixed records from data-keyed maps (terms, categories,
# quantiles). Unknown record members are not presentation data. A scalar slot
# never recursively accepts an object, even if its key is otherwise declared.
_PROVENANCE = _fields("run_id", "source_id", "artifact_id", "producer")
_METADATA = _fields("status", "reason")
_INTERVAL = _fields("lower", "upper", "method", "confidence_level", "level")


def _distribution_parameters(value):
    # Current model producers declare no additional distribution parameters.
    # Degrees of freedom has its own typed field. Do not turn this reserved
    # record into an arbitrary metadata or data-keyed namespace.
    if not isinstance(value, Mapping) or value:
        _fail("Undeclared reference distribution parameters")
    return {}


_DISTRIBUTION = {"name": None, "degrees_of_freedom": ("scalar_or_record", _METADATA),
                 "parameters": _distribution_parameters}
_COEFFICIENT = {
    **_fields("estimate", "std_error", "p_value", "ci_lower", "ci_upper", "t_statistic", "z_statistic",
              "statistic", "hazard_ratio", "odds_ratio", "relative_risk_ratio", "variance_source", "source_id",
              "irr", "irr_ci_lower", "irr_ci_upper", "inference_method", "result_id", "label",
              "display_estimate", "p_value_display",
              "projection_status", "unavailable_reason", *_INFERENCE_FIELDS),
    "confidence_interval": ("interval", _INTERVAL),
    "reference_distribution": ("scalar_or_record", {**_DISTRIBUTION, **_METADATA}),
    "provenance": _PROVENANCE, "warnings": ("list", None),
}
_QUANTILE = {
    "quantiles": ("list", None),
    "fits": ("map", {"quantile": None, "coefficients": ("map", _COEFFICIENT)}),
    "bootstrap": {
        **_fields("repetitions", "random_state"),
        "successful_repetitions": ("map", ("number", None)),
        "intervals": ("map", ("map", ("interval", _INTERVAL))),
        "comparison_uncertainty": _fields("method", "status", "reason", "paired_successful_repetitions",
            "minimum_successful_repetitions", "p_value_method", "p_value_status", "p_value_contract"),
    },
    "cross_quantile_comparisons": ("list", _fields("term", "lower_quantile", "upper_quantile",
                                                   "difference", "std_error", "p_value")),
}


def _project_record(value, schema):
    if value is None:
        return None
    if callable(schema):
        return schema(value)
    if schema is None:
        if type(value) not in (str, int, float, bool):
            _fail("Declared producer scalar contains an undeclared structure")
        return value
    if isinstance(schema, tuple):
        kind, child = schema
        if kind in {"text", "number", "boolean"}:
            valid = type(value) in {"text": (str,), "number": (int, float), "boolean": (bool,)}[kind]
            if not valid:
                _fail("Declared producer scalar has the wrong type")
            return value
        if kind == "scalar_or_record":
            return _project_record(value, child if isinstance(value, Mapping) else None)
        if kind == "interval":
            if isinstance(value, Mapping):
                return _project_record(value, child)
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                _fail("Producer interval must have two endpoints")
            return [_project_record(item, None) for item in value]
        if kind == "map":
            if not isinstance(value, Mapping):
                _fail("Declared producer map is not an object")
            return {key: _project_record(item, child) for key, item in value.items()}
        if kind == "list":
            if not isinstance(value, (list, tuple)):
                _fail("Declared producer rows are not a list")
            return [_project_record(item, child) for item in value]
    if not isinstance(value, Mapping):
        _fail("Declared producer record is not an object")
    return {key: _project_record(value[key], child) for key, child in schema.items() if key in value}


def _family_projection(model, fields):
    schema = dict.fromkeys(fields)
    if "report" in fields:
        schema["report"] = _ARMA_REPORT_SCHEMA
    schema.update({key: value for key, value in _QUANTILE.items() if key in fields})
    for name, ratio in (("odds_ratios", "odds_ratio"), ("relative_risk_ratios", "relative_risk_ratio")):
        if name in fields:
            schema[name] = ("map", _fields(ratio, "ci_lower", "ci_upper"))
    if "hazard_ratios" in fields:
        schema["hazard_ratios"] = ("map", _NUMBER)
    if "outcome_levels" in fields:
        schema["outcome_levels"] = ("list", None)
    if "selected_specification" in fields:
        schema["selected_specification"] = {
            **_fields("model", "distribution", "estimation_strategy", "resolved_strategy", "joint_likelihood"),
            **_fields("split_hash", "mean_candidate_id", "mean_constant", "variance_candidate_id", "variance_model",
                      "innovation_distribution", "hold_back", "transform", "refit_every"),
            "mean_order": ("list", None), "variance_order": ("list", None),
            "arma": _fields("p", "d", "q", "trend", "include_mean", "constant"),
            "variance": _fields("model", "p", "o", "q", "power", "distribution"),
        }
    if "parallel_lines" in fields:
        schema["parallel_lines"] = {**_fields("status", "method"), "slope_ranges": ("map", _NUMBER),
            "comparisons": ("list", {"threshold": None, "coefficients": ("map", _NUMBER)})}
    for key, child in {
        "censoring": _fields("events", "censored"),
        "time_to_event": _fields("duration_column", "event_column", "entry_column"),
        "kaplan_meier": ("list", _fields("group", "time", "survival", "n_at_risk")),
        "log_rank": {**_fields("status", "statistic", "p_value"), "groups": ("list", None)},
        "risk_set": ("list", _fields("time", "at_risk", "events", "censored")),
        "schoenfeld": ("list", {**_fields("variable", "time_correlation", "status"), "residuals": ("list", None)}),
    }.items():
        if key in fields:
            schema[key] = child
    return _project_record(model, schema)


def _fail(message):
    raise EvidenceProjectionError("REPORT_RESULT_INPUT_INVALID", message)


def bounded_result_input(value):
    """Reject over-budget/non-JSON producer values before recursive copying."""
    count = size = 0
    def visit(item, depth):
        nonlocal count, size
        count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            _fail("Producer input exceeds depth/node budget")
        if isinstance(item, Mapping):
            size += 2 + 2 * len(item)
            for key, child in item.items():
                if type(key) is not str:
                    _fail("Producer object key is not text")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            size += 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        else:
            if type(item) is str:
                if len(item) > MAX_TEXT_BYTES or len(item.encode("utf-8")) > MAX_TEXT_BYTES:
                    _fail("Producer text exceeds byte budget")
            elif type(item) is int:
                if abs(item) > MAX_SAFE_INTEGER:
                    _fail("Producer integer cannot be represented exactly")
            elif type(item) is float:
                if not math.isfinite(item):
                    _fail("Producer number is not finite")
            elif item is not None and type(item) is not bool:
                _fail("Producer input contains a private/non-JSON object")
            size += len(canonical_json_v1(item).encode("utf-8"))
        if size > MAX_RESULT_INPUT_BYTES:
            _fail("Producer input exceeds byte budget")
    visit(value, 0)
    raw = canonical_json_v1(value).encode("utf-8")
    if len(raw) > MAX_RESULT_INPUT_BYTES:
        _fail("Producer input exceeds byte budget")
    return json.loads(raw)


_TEXT = ("text", None)
_NUMBER = ("number", None)
_TEXTS = ("list", _TEXT)
_SURVEY = {
    **_fields("n_obs", "n_strata", "n_psu", "df", "degf", "design_df", "residual_df", "residual_degf",
        "design_effect", "effective_sample_size", "variance_method", "strata_column", "psu_column", "weight_column",
        "replicate_type", "lonely_psu_policy", "subpopulation", "weight_frame", "variance_source", "source_id", "run_id",
        "replicates_attempted", "replicates_succeeded", "replicates_failed", "projection_status", "unavailable_reason"),
    "provenance": _PROVENANCE, "warnings": _TEXTS, "replicate_weight_columns": _TEXTS,
    "replicate_failure_reasons": ("map", _NUMBER),
}
_MODEL_IDENTITY = {**_fields("id", "label", "model_id", "model_label", "model_type", "nobs", "y_variable"),
                   "x_variables": _TEXTS}
_TABLE_MODEL = {**_MODEL_IDENTITY, **_fields("r_squared", "adjusted_r_squared", "projection_status", "unavailable_reason"),
    "survey_design": ("scalar_or_record", _SURVEY), "survey_provenance": _SURVEY}
_DESCRIPTIVE_ROW = {**_fields("column", "label", "label_source", "dtype", "count", "missing", "missing_rate",
    "unique_count", "mean", "std", "min", "max", "note"), "value_labels": ("map", _TEXT)}
_MARGINAL_ROW = {**_COEFFICIENT, **_fields("model_id", "term", "index", "variable", "category", "outcome", "effect", "method",
    "dy/dx", "Std. Err.", "z", "Pr(>|z|)", "Conf. Int. Low", "Cont. Int. Hi.", "Conf. Int. Hi.", "endog", "exog"),
    "average_effect_by_category": ("map", _NUMBER)}
_EFFECT_SIZE = _fields("effect_size_name", "value", "pooled_sd", "nobs")
_STATISTICAL_ROW = {
    **_fields("test", "test_id", "test_version", "test_type", "nobs", "statistic", "p_value", "label", "source_id",
        "outcome", "group", "degrees_of_freedom", "correction", "family", "p_value_corrected", "correction_method"),
    "variables": _TEXTS, "groups": _TEXTS, "assumptions": _TEXTS, "warnings": _TEXTS,
    "effect_size": _EFFECT_SIZE,
    "effect": {**_fields("r", "rho", "tau", "mean_difference", "median_difference", "difference", "odds_ratio"),
        "group_means": ("map", _NUMBER), "group_medians": ("map", _NUMBER),
        "contingency_table": ("map", ("map", _NUMBER))},
    "comparisons": ("list", {**_fields("group1", "group2", "statistic", "p_value", "correction", "mean_difference",
        "ci_low", "ci_high", "reject"), "effect_size": _EFFECT_SIZE}),
}
def _public_vif(value):
    if not isinstance(value, Mapping):
        _fail("VIF producer value must be a record")
    return _project_record(value, {"error": _TEXT} if set(value) == {"error"} else ("map", _NUMBER))


_DIAGNOSTIC_MODEL = {
    **_fields("model_id", "model_type", "nobs", "durbin_watson"),
    "vif": _public_vif,
    "breusch_pagan": _fields("lm", "p_value"), "jarque_bera": _fields("statistic", "p_value"),
    "cooks_distance": _fields("max", "threshold", "n_high", "n_severe", "leverage_max"),
    "separation": _fields("converged", "max_abs_coef", "max_std_error", "pred_prob_min", "pred_prob_max", "warning"),
    "overdispersion": _fields("pearson_chi2", "df_resid", "overdispersion_ratio", "deviance_ratio", "mean_y", "var_y",
        "zero_rate", "pred_min", "pred_max", "pred_mean", "zero_inflation_hint", "warning"),
}
_CONSTRAINTS = _fields("causal_language_allowed", "allowed_effect_language", "must_not_claim_policy_effect",
    "must_not_interpret_treatment_independently", "must_acknowledge_treatment_proxy_correlation",
    "must_note_categorical_encoded", "must_not_hide_blockers", "must_not_change_severity", "must_not_add_uncomputed_statistics")
_ISSUE_FIELDS = {**_fields("severity", "code", "message", "issue_id", "affected_stage", "metric", "value", "threshold",
    "template_key", "recommended_action_key", "is_user_action_required", "projection_status", "unavailable_reason"),
    "variables": _TEXTS}


def _public_issue(issue):
    from ..narrative.templates import TEMPLATES
    result = _project_record(issue, _ISSUE_FIELDS)
    template = TEMPLATES.get(issue.get("template_key"))
    params = issue.get("template_params")
    if params is not None:
        if not isinstance(params, Mapping):
            _fail("Diagnostic template params must be a record")
        if template is None:
            result["template_params"] = {}
            if params:
                result.update(projection_status="unavailable", unavailable_reason="PRODUCER_TEMPLATE_UNDECLARED")
        else:
            # Public parameter names come from the actual server template, not
            # from display text or caller-provided parameter names.
            result["template_params"] = _project_record(params, _fields(*template["required_params"]))
            if set(template["required_params"]) - set(params):
                result.update(projection_status="unavailable", unavailable_reason="PRODUCER_TEMPLATE_PARAMS_MISSING")
    if "evidence" in issue:
        evidence = issue["evidence"]
        if not isinstance(evidence, Mapping):
            _fail("Diagnostic evidence must be a record")
        # Until an issue has a declared evidence schema, retain its public
        # diagnostic message, not an arbitrary evidence object.
        result["evidence"] = {}
        if evidence:
            result.update(projection_status="unavailable", unavailable_reason="PRODUCER_ISSUE_EVIDENCE_UNDECLARED")
    return result


def _public_statistical_row(row, *, generic=False):
    if not isinstance(row, Mapping):
        _fail("Statistical result row must be a declared record")
    # Neither the declared evidence-packet row nor the legacy generic row
    # declares these discriminators. Validate before projecting any fields.
    if any(key in row for key in ("contract", "payload_schema", "schema_version")):
        _fail("Unsupported statistical result contract")
    if "test_version" in row and (type(row["test_version"]) is not int or row["test_version"] != 1):
        _fail("Unsupported statistical result version")
    schema = dict(_STATISTICAL_ROW)
    effect_schema = dict(schema["effect"])
    # Legacy statistical producers declare their group-derived measurement
    # keys from the explicit groups array, not a guessed test display name.
    for group in row.get("groups", []):
        if type(group) is not str:
            _fail("Statistical groups must be declared text labels")
        effect_schema[f"mean_{group}"] = _NUMBER
        effect_schema[f"median_{group}"] = _NUMBER
    schema["effect"] = effect_schema
    result = _project_record(row, schema)
    if generic:
        # The generic result-row contract permits named numeric measurements.
        # Extra text/object members are not an arbitrary metadata namespace.
        result.update({key: value for key, value in row.items()
                       if key not in _STATISTICAL_ROW and type(value) in (int, float)})
    return result


def _public_model_diagnostic(value):
    if not isinstance(value, Mapping):
        _fail("Diagnostic producer value must be a record")
    if "contract" in value:
        family = value.get("model_type")
        if (family not in _FAMILY_DIAGNOSTIC_FIELDS
                or value["contract"] != f"workbench.{family}.diagnostics.v1"
                or value.get("status") != "family_owned"):
            _fail("Unsupported diagnostic producer contract")
        return _project_record(value, {**_fields("contract", "model_type", "status", "source_model_id"),
            "validation": _fields("level", "external_oracle")})
    if "payload_schema" in value or "schema_version" in value:
        _fail("Unsupported diagnostic producer variant")
    return _project_record(value, _DIAGNOSTIC_MODEL)


def _public_statistics(value):
    if not isinstance(value, Mapping):
        _fail("Statistical producer packet must be a record")
    if "contract" in value:
        _fail("Unsupported statistical producer contract")
    schema = value.get("payload_schema")
    if schema not in (None, "workbench.statistics.evidence-packet"):
        _fail("Unsupported statistical producer packet")
    if "schema_version" in value and (type(value["schema_version"]) is not int or value["schema_version"] != 1):
        _fail("Unsupported statistical producer packet version")
    if "correction_scope" in value:
        scope = value["correction_scope"]
        if type(scope) is not str or "\x00" in scope:
            _fail("Statistical correction scope must be declared text")
    result = _project_record(value, {**_fields("payload_schema", "schema_version", "lineage_parent"),
        "dataset_ref": {"dataset_sha256": _TEXT}, "warnings": _TEXTS, "correction_scope": _TEXT})
    if not isinstance(value.get("results"), list):
        _fail("Statistical producer results must be a declared row list")
    result["results"] = [_public_statistical_row(row, generic=schema is None) for row in value["results"]]
    return result


def _validate_family_diagnostic_variant(value, family):
    # Exact producer declarations in v186_model_families/runtime.py; selection
    # uses the bound model family, never a display label or a test name.
    contracts = {
        "ordinal_logit": "workbench.ordinal_logit.diagnostics.v1",
        "multinomial_logit": "workbench.multinomial_logit.diagnostics.v1",
        "survival_cox": "workbench.survival.v1",
        "quantile_regression": "workbench.quantile_regression.result.v1",
    }
    if "contract" in value and (family not in contracts or value["contract"] != contracts[family]):
        _fail("Unsupported family diagnostic producer contract")
    if "model_type" in value and value["model_type"] != family:
        _fail("Family diagnostic producer model type mismatch")
    if "payload_schema" in value or ("schema_version" in value and
            (type(value["schema_version"]) is not int or value["schema_version"] != 1)):
        _fail("Unsupported family diagnostic producer version")


PUBLIC_RESULT_SECTION_SCHEMAS_V1 = MappingProxyType({
    "model_identity": {"models": ("list", _MODEL_IDENTITY)},
    "regression_table": {"models": ("list", _TABLE_MODEL),
        "rows": ("list", {**_fields("term", "label"), "models": ("map", _COEFFICIENT)}),
        "notes": _TEXTS, "significance_levels": ("map", _NUMBER), **_fields("payload_schema", "schema_version")},
    "descriptive_statistics": {"rows": ("list", _DESCRIPTIVE_ROW), "columns": _TEXTS, "labels": ("map", _TEXT)},
    "statistical_tests": _public_statistics,
    "survey_design": {"models": _TEXTS, "design": ("map", _SURVEY),
        "provenance": ("map", {**_PROVENANCE, **_SURVEY}), "warnings": _TEXTS},
    "marginal_effects": {"models": _TEXTS, "rows": ("list", _MARGINAL_ROW), "method": _TEXT, "warnings": _TEXTS},
    "model_family_evidence": None,  # Resolved from actual source model_type below.
    "diagnostics": {**{key: ("list", _public_issue) for key in ("blockers", "warnings", "cautions", "info")},
        "results": ("map", _public_model_diagnostic)},
    "interpretation_constraints": {"constraints": _CONSTRAINTS, "required_mentions": _TEXTS, "forbidden_claims": _TEXTS},
    "variable_importance": {"rows": ("list", _fields("variable", "correlation", "best_p_value", "test_type", "strength")),
        "method": _TEXT, "warnings": _TEXTS},
    "workflow_status": {**_fields("workflow_id", "status"), "steps": ("list", _fields("step", "status")),
        "artifact_ids": _TEXTS, "warnings": _TEXTS},
})


def project_public_result_sections_v1(sections, *, model_results, primary_model_type):
    """The sole public-schema boundary before immutable result-input sealing."""
    if set(sections) != set(PUBLIC_RESULT_SECTION_SCHEMAS_V1) or set(sections) != set(SECTION_FIELDS):
        _fail("Public producer section schema coverage differs from the contract")
    bounded_result_input(sections)
    result = {}
    for name, value in sections.items():
        if value is None:
            result[name] = None
        elif name == "model_family_evidence":
            projected = {"model_family": value["model_family"], "results": {}}
            for model_id, packet in value["results"].items():
                family = model_results[model_id].get("model_type")
                if family not in _FAMILY_FIELDS:
                    _fail("Unsupported model family producer variant")
                projected["results"][model_id] = _family_projection(packet, _FAMILY_FIELDS[family])
            if "diagnostics" in value:
                if primary_model_type not in _FAMILY_DIAGNOSTIC_FIELDS:
                    _fail("Unsupported family diagnostic producer variant")
                projected["diagnostics"] = _family_projection(value["diagnostics"], _FAMILY_DIAGNOSTIC_FIELDS[primary_model_type])
            result[name] = projected
        else:
            result[name] = _project_record(value, PUBLIC_RESULT_SECTION_SCHEMAS_V1[name])
    return bounded_result_input(result)


def production_regression_table(table, model_results):
    """Keep producer labels, but recover unrounded inference from actual packets."""
    public = {key: value for key, value in table.items() if key != "_server_owned_validation_receipts"}
    checked = bounded_result_input(public)
    rows = checked.get("rows", [])
    models = checked.get("models", [])
    if {model["id"] for model in models} != set(model_results):
        _fail("Table models do not match sealed model artifacts")
    from ..report_view_model import build_regression_table

    # Reuse the producer's declared metadata projection, but derive it from the
    # admitted source, never from the caller's purported source digest alone.
    for index, model in enumerate(models):
        actual = build_regression_table([(model["id"], model_results[model["id"]])])["models"][0]
        for field in set(model) | set(actual):
            if field in {"id", "label", "result_digest"}:
                continue
            if field in model and model[field] != actual.get(field):
                _fail("Table model metadata contradicts the admitted source")
        if "label" in model:
            actual["label"] = _project_record(model["label"], None)
        models[index] = actual
    for row in rows:
        for model_id, cell in row["models"].items():
            if cell is None:
                continue
            source_model = model_results[model_id]
            source = source_model.get("coefficients", {}).get(row["term"])
            if not isinstance(source, Mapping) or source.get("estimate") != cell.get("estimate"):
                _fail("Table coefficient is not the actual model source value")
            replacement = _project_record(source, _COEFFICIENT)
            for field in _INFERENCE_FIELDS:
                if field not in replacement:
                    replacement[field] = _project_record(source_model.get(field), _COEFFICIENT[field])
            row["models"][model_id] = replacement
    checked = bounded_result_input(checked)
    if "_server_owned_validation_receipts" in table:
        checked["_server_owned_validation_receipts"] = table["_server_owned_validation_receipts"]
    return checked


def build_report_result_input(*, run_id, model_run_id, primary_model_type,
                              regression_table, model_results, report_fields, diagnostic_summary,
                              arma_artifacts=None, arma_dependency_ids=None):
    public_table = {key: value for key, value in regression_table.items()
                    if key != "_server_owned_validation_receipts"}
    # Bounds are also applied to input fields that are not presentation fields;
    # an opaque/private value must not get silently copied into a snapshot.
    report = bounded_result_input(report_fields)
    summary = bounded_result_input(diagnostic_summary)
    models = [{key: model[key] for key in ("id", "label", "model_type", "nobs") if key in model}
              for model in public_table["models"]]
    for model in models:
        source = model_results[model["id"]]
        for key in ("y_variable", "x_variables"):
            if key in source:
                model[key] = source[key]
    sections = {name: None for name in SECTION_FIELDS}
    sections["model_identity"] = {"models": models}
    sections["regression_table"] = {key: value for key, value in public_table.items()
                                     if key in SECTION_FIELDS["regression_table"]}
    sections["regression_table"]["models"] = [
        {key: value for key, value in model.items() if key != "result_digest"}
        for model in public_table["models"]
    ]
    if "descriptive_stats" in report:
        sections["descriptive_statistics"] = {"rows": report["descriptive_stats"]}
    if "statistical_evidence" in report:
        statistical = report["statistical_evidence"]
        if not isinstance(statistical, dict):
            _fail("Statistical producer packet must be a record")
        # Keep discriminators until the single public boundary validates the
        # producer variant. Removing them here could disguise it as generic.
        sections["statistical_tests"] = statistical
        if "results" not in sections["statistical_tests"]:
            _fail("Statistical producer packet has no declared results")
    survey = {key: model["survey_design"] for key, model in model_results.items()
              if model.get("survey_design") is not None}
    if survey:
        sections["survey_design"] = {"models": list(survey), "design": survey,
            "provenance": {key: model.get("survey_provenance") for key, model in model_results.items()
                           if key in survey}}
    marginal = [(key, model) for key, model in model_results.items() if model.get("marginal_effects") is not None]
    if marginal:
        rows = []
        for key, model in marginal:
            effects = model["marginal_effects"]
            if not isinstance(effects, list):
                _fail("Marginal effects must be a declared row list")
            rows.extend({**row, "model_id": key} for row in effects)
        methods = {model.get("marginal_effects_method") for _, model in marginal}
        sections["marginal_effects"] = {"models": [key for key, _ in marginal], "rows": rows,
            "method": next(iter(methods)) if len(methods) == 1 else None}
    family_results = {}
    for identity, model in model_results.items():
        fields = _FAMILY_FIELDS.get(model.get("model_type"), frozenset())
        projected = {key: model[key] for key in fields if key in model and key != "report"}
        if model.get("model_type") == "time_series.arma_garch":
            projected["report"] = (_arma_public_report(arma_artifacts[identity], arma_dependency_ids[identity])
                if arma_artifacts is not None and identity in arma_artifacts else None)
        if projected:
            family_results[identity] = projected
    extra_family = report.get("model_family_evidence")
    family_diagnostics = {}
    if isinstance(extra_family, dict):
        _validate_family_diagnostic_variant(extra_family, primary_model_type)
        family_diagnostics = {key: extra_family[key] for key in _FAMILY_DIAGNOSTIC_FIELDS.get(primary_model_type, ()) if key in extra_family}
    if family_results or family_diagnostics:
        sections["model_family_evidence"] = {"model_family": primary_model_type, "results": family_results}
        if family_diagnostics:
            sections["model_family_evidence"]["diagnostics"] = family_diagnostics
    if isinstance(summary.get("diagnostics"), dict):
        sections["diagnostics"] = {key: summary["diagnostics"].get(key) for key in ("blockers", "warnings", "cautions", "info")}
        if "diagnostics" in report:
            sections["diagnostics"]["results"] = report["diagnostics"]
    if isinstance(summary.get("narrative_contract"), dict):
        sections["interpretation_constraints"] = {key: summary["narrative_contract"].get(key)
            for key in ("constraints", "required_mentions", "forbidden_claims")}
    if "variable_importance" in report:
        sections["variable_importance"] = {"rows": report["variable_importance"],
            "method": report.get("variable_importance_method")}
    state = summary.get("run_status", {})
    sections["workflow_status"] = {"workflow_id": run_id,
        "status": state.get("report_render_status", "pending"),
        "steps": [{"step": key, "status": state[key]} for key in ("model_fit_status", "report_render_status") if key in state],
        "artifact_ids": list(model_results)}
    section_models = {name: [] for name in SECTION_FIELDS}
    for name in ("model_identity", "regression_table", "diagnostics", "variable_importance"):
        section_models[name] = list(model_results)
    section_models["survey_design"] = list(survey)
    section_models["marginal_effects"] = [key for key, _ in marginal]
    section_models["model_family_evidence"] = list(model_results) if family_diagnostics else list(family_results)
    sections = project_public_result_sections_v1(sections, model_results=model_results, primary_model_type=primary_model_type)
    return bounded_result_input({"schema_version": 1, "run_id": run_id, "model_run_id": model_run_id,
                                 "sections": sections, "section_model_ids": section_models})


def _na(reason="Not declared by this producer source"):
    return {"status": "not_applicable", "reason": reason}


def extend_report_evidence(envelope, *, snapshot, manifest):
    """Losslessly lift every selected numeric scalar into a source-bound fact."""
    result = copy.deepcopy(envelope)
    snapshot_id = f"result-input:{snapshot['run_id']}"
    snapshot_record = next(row for row in manifest["records"] if row["artifact_id"] == snapshot_id)
    dependencies = [row["artifact_id"] for row in manifest["records"]]
    checked_coefficients = {fact["fact_id"]: fact for fact in result["numeric_facts"]}
    facts, sections, path_facts = {}, [], {}
    allowed_numbers = result["availability"] == "available" and result["execution_status"] == "completed"

    def node(value, path, refs):
        if value is None:
            return {"kind": "missing", "status": "unavailable", "reason": "PRODUCER_FIELD_UNDECLARED"}
        if type(value) is bool:
            return {"kind": "boolean", "value": value}
        if type(value) is str:
            return {"kind": "text", "value": value}
        if isinstance(value, dict):
            return {"kind": "object", "fields": {key: node(child, (*path, key), refs) for key, child in value.items()}}
        if isinstance(value, list):
            return {"kind": "list", "items": [node(child, (*path, index), refs) for index, child in enumerate(value)]}
        # Model-column metadata is the same producer field in identity/table;
        # share its exact snapshot selector rather than minting duplicate facts.
        if len(path) == 5 and path[:3] == ("sections", "regression_table", "models"):
            identity_model = snapshot["sections"]["model_identity"]["models"][path[3]]
            if path[4] in identity_model and identity_model[path[4]] == value:
                path = ("sections", "model_identity", *path[2:])
        if path in path_facts:
            fact_id = path_facts[path]
            if fact_id not in refs:
                refs.append(fact_id)
            return {"kind": "fact", "fact_id": fact_id, "representation": "integer" if type(value) is int else "number"}
        selector = "$" + "".join(f"[{json.dumps(part, ensure_ascii=False)}]" for part in path)
        fact_id = f"fact:{snapshot['run_id']}:section:{len(facts)}"
        coefficient_id = None
        if len(path) == 7 and path[:3] == ("sections", "regression_table", "rows") and path[4] == "models" and path[6] == "estimate":
            coefficient_id = f"fact:{snapshot['run_id']}:{path[5]}:{path[3]}"
        if coefficient_id in checked_coefficients:
            fact = copy.deepcopy(checked_coefficients[coefficient_id])
            if fact["value"] != value:
                _fail("Receipt-bound coefficient changed before snapshot")
            fact_id = coefficient_id
        else:
            fact = dict(fact_id=fact_id, estimand_id=_na(), statistic_id=str(path[-1]), value=value,
                denominator=_na(), weight=_na(), unit=_na(), scale=_na(), standard_error=_na(),
                confidence_interval=_na(), confidence_level=_na(), test_direction=_na(),
                reference_distribution=_na(), multiple_comparison=_na(), evaluation_design="not_applicable",
                oracle_checks=[], validation_level="none")
        fact["source_selector"] = {"artifact_ref": snapshot_id, "selector": selector,
                                   "artifact_digest": snapshot_record["sha256"]}
        facts[fact_id] = NumericFactV1.from_dict(fact)
        path_facts[path] = fact_id
        refs.append(fact_id)
        return {"kind": "fact", "fact_id": fact_id, "representation": "integer" if type(value) is int else "number"}

    for name, content in snapshot["sections"].items():
        refs = []
        blocked = not allowed_numbers and name not in {"workflow_status", "interpretation_constraints"}
        if content is None or blocked:
            sections.append(dict(section_id=name, section_type=name, schema_version=1,
                status="blocked" if blocked else "unavailable",
                reason_codes=["RESULT_EXECUTION_BLOCKED" if blocked else "PRODUCER_SECTION_UNDECLARED"],
                fact_refs=[], dependency_refs=[], content={"kind": "null"}))
        else:
            tree = node(content, ("sections", name), refs)
            if not allowed_numbers and refs:
                _fail("Failed workflow metadata cannot release numeric facts")
            extra_dependencies = []
            if name == "model_family_evidence" and content.get("model_family") == "time_series.arma_garch":
                for family in content.get("results", {}).values():
                    report = family.get("report")
                    if isinstance(report, dict):
                        extra_dependencies.extend(report["artifact_ids"])
            sections.append(dict(section_id=name, section_type=name, schema_version=1,
                status="available", reason_codes=[], fact_refs=refs,
                dependency_refs=list(dict.fromkeys([snapshot_id, *snapshot["section_model_ids"][name], *extra_dependencies])), content=tree))
    structured = StructuredResultsV1.from_dict({"schema_version": 1,
        "contract_digest": RESULT_SECTIONS_CONTRACT_DIGEST, "sections": sections},
        facts=facts, dependency_ids=set(dependencies))
    result["numeric_facts"] = [fact.to_dict() for fact in facts.values()]
    result["validation_summary"] = ValidationSummaryV1.from_facts(facts.values(),
        ValidationLevelV1(result["validation_summary"]["minimum_required"])).to_dict()
    result["dependencies"] += [{"artifact_ref": identity} for identity in dependencies]
    result["family_evidence"].update(structured_results=structured.to_dict(), result_dependencies=manifest)
    return EvidenceEnvelopeV1.from_dict(result).to_dict()
