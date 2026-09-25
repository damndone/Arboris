"""Versioned result sections: immutable values, never execution/read authority.

Statistics remain NumericFactV1 values. Trees retain only references and bounded
display metadata; consumer admission must still enforce identity and egress.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from types import MappingProxyType
import unicodedata

from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.contracts.common.envelope import (
    ContractError, freeze_json, require_exact_keys, thaw_json,
)
from workbench.contracts.evidence.envelope import NumericFactV1


class ResultSectionError(ContractError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


MAX_SECTIONS = 128
MAX_DEPTH = 16
MAX_NODES = 16384
MAX_TEXT_BYTES = 4096
MAX_EXTENSION_BYTES = 1048576
MAX_SAFE_INTEGER = 9007199254740991

# Declarative field contracts, not method dispatch or a fixed analysis sequence.
# New declarations change the digest; unknown families cannot opt themselves in.
SECTION_FIELDS = MappingProxyType({
    "model_identity": frozenset({"models", "model_id", "model_type", "model_label", "y_variable", "x_variables", "nobs"}),
    "regression_table": frozenset({"models", "rows", "notes", "significance_levels", "payload_schema", "schema_version"}),
    "descriptive_statistics": frozenset({"rows", "columns", "labels"}),
    "statistical_tests": frozenset({"results", "dataset_ref", "lineage_parent", "warnings", "payload_schema", "schema_version", "correction_scope"}),
    "survey_design": frozenset({"models", "design", "provenance", "warnings"}),
    "marginal_effects": frozenset({"models", "rows", "method", "warnings"}),
    "model_family_evidence": frozenset({"model_family", "models", "results", "diagnostics", "warnings"}),
    "diagnostics": frozenset({"blockers", "warnings", "cautions", "info", "results"}),
    "interpretation_constraints": frozenset({"constraints", "required_mentions", "forbidden_claims"}),
    "variable_importance": frozenset({"rows", "method", "warnings"}),
    "workflow_status": frozenset({"workflow_id", "status", "steps", "artifact_ids", "warnings"}),
})
SECTION_REQUIRED_FIELDS = MappingProxyType({
    "model_identity": frozenset({"models"}),
    "regression_table": frozenset({"models", "rows"}),
    "descriptive_statistics": frozenset({"rows"}),
    "statistical_tests": frozenset({"results"}),
    "survey_design": frozenset({"design", "provenance"}),
    "marginal_effects": frozenset({"rows", "method"}),
    "model_family_evidence": frozenset({"model_family", "results"}),
    "diagnostics": frozenset({"blockers", "warnings", "cautions", "info"}),
    "interpretation_constraints": frozenset({"constraints", "required_mentions", "forbidden_claims"}),
    "variable_importance": frozenset({"rows", "method"}),
    "workflow_status": frozenset({"workflow_id", "status", "steps", "artifact_ids"}),
})
COUNT_FIELDS = frozenset({"nobs", "n_observations", "sample_size", "n", "count", "missing_count",
                          "replicates_attempted", "replicates_succeeded", "replicates_failed"})
NUMERIC_FIELDS = COUNT_FIELDS | frozenset({
    "estimate", "std_error", "standard_error", "statistic", "p_value", "p_value_corrected",
    "confidence_level", "lower", "upper", "r_squared", "adjusted_r_squared", "design_effect",
    "effective_sample_size", "degf", "mean", "median", "variance", "minimum", "maximum",
})
SECTION_NUMERIC_PATHS = MappingProxyType({
    "model_identity": ((), ("models", "*")),
    "regression_table": (("models", "*"), ("rows", "*", "models", "*")),
    "descriptive_statistics": (("rows", "*"),),
    "statistical_tests": (("results", "*"), ("results", "*", "comparisons", "*")),
    "survey_design": (("design",), ("provenance",)),
    "marginal_effects": (("rows", "*"),),
    "model_family_evidence": (("results", "*"),),
    "diagnostics": (("results", "*"),),
    "interpretation_constraints": (),
    "variable_importance": (("rows", "*"),),
    "workflow_status": (("steps", "*"),),
})
FIELD_SHAPES = MappingProxyType({
    **{field: frozenset({"list"}) for field in (
        "rows", "columns", "notes", "warnings", "blockers", "cautions", "info",
        "x_variables", "required_mentions", "forbidden_claims", "steps", "artifact_ids")},
    **{field: frozenset({"object"}) for field in (
        "labels", "dataset_ref", "design", "provenance", "constraints", "significance_levels")},
    **{field: frozenset({"text"}) for field in (
        "model_id", "model_type", "model_label", "y_variable", "payload_schema",
        "lineage_parent", "model_family", "workflow_id", "status", "method", "correction_scope")},
    **{field: frozenset({"fact"}) for field in ("schema_version", "nobs")},
    **{field: frozenset({"list", "object"}) for field in ("models", "results", "diagnostics")},
})

# Public ARMA report records. Parameter names are data keys, not schema keys.
# The same declaration drives producer projection and typed-node validation.
_AN = ("number", None)
_AT = ("text", None)
_AD = {**dict.fromkeys(("statistic", "p_value", "used_lag", "nobs", "lag", "f_statistic",
    "f_p_value", "skew", "kurtosis", "threshold", "count", "rate", "n"), _AN),
    "status": _AT, "reason": _AT}
ARMA_REPORT_SCHEMA = freeze_json({
    "contract": dict.fromkeys(("dataset_ref", "time_column", "value_column", "transform",
        "estimation_strategy", "innovation_distribution"), _AT),
    "sample": {**dict.fromkeys(("source_n", "effective_n", "training_n", "validation_n"), _AN),
        "selection_data_role": _AT, "validation_data_role": _AT},
    "metrics": {**dict.fromkeys(("validation_n", "successful_forecast_n", "mae", "rmse", "mean_error",
        "interval_coverage", "average_interval_width", "coverage_count", "exception_rate", "exception_count",
        "pinball_loss"), _AN), "coverage_uncertainty": {"method": _AT, "lower": _AN, "upper": _AN}},
    "parameters": {key: ("map", _AN) for key in ("mean_candidate", "selected_variance_candidate", "final_fit")},
    "diagnostics": {"adf": _AD, "ljung_box": ("list", _AD), "arch_lm": _AD,
        "normality": {**_AD, "shapiro_wilk": _AD, "shapiro_francia": _AD},
        "residual_exceedance": _AD, "warnings": ("list", _AT)},
    "selection": {key: dict.fromkeys(("final_selected_candidate_id", "final_selection_basis",
        "selected_candidate_id", "selection_basis", "validation_data_role"), _AT) for key in ("mean", "variance")},
    "next_forecast": {**dict.fromkeys(("conditional_mean", "conditional_variance", "conditional_volatility",
        "lower_bound", "upper_bound", "lower_quantile"), _AN),
        **dict.fromkeys(("result_role", "parent_result_id", "target_label", "target_time", "model_scale",
        "fit_method", "predictive_interval", "warning"), _AT), "forecast_origin": {"row_id": _AT, "time": _AT}},
    "forecast_limitations": {"horizon": _AN, "predictive_interval": _AT,
        "parameter_uncertainty_included": ("boolean", None)},
    "warnings": ("list", _AT), "chart_artifacts": ("list", _AT), "artifact_ids": ("list", _AT),
})

# Logical IDs may evolve within this namespace; their exact model-declared
# membership and source hashes remain the host producer's responsibility.
RESULT_DEPENDENCY_NAMESPACES_V1 = freeze_json({
    "ts": {"directory": ["artifacts", "time_series"],
           "artifact_type": "time_series_json", "producer_step": "arma_garch"},
})


def result_sections_declaration() -> dict[str, object]:
    """Return a defensive copy of the same declarations used by validation."""
    return {
    "contract": "workbench.structured-results", "version": 1,
    "fields": {key: sorted(value) for key, value in SECTION_FIELDS.items()},
    "required": {key: sorted(value) for key, value in SECTION_REQUIRED_FIELDS.items()},
    "numerical_roles": sorted(NUMERIC_FIELDS), "count_roles": sorted(COUNT_FIELDS),
    "numeric_paths": dict(SECTION_NUMERIC_PATHS),
    "nodes": {"text": ["value"], "boolean": ["value"], "null": [],
              "object": ["fields"], "list": ["items"],
              "fact": ["fact_id", "representation"], "missing": ["status", "reason"]},
    "limits": [MAX_SECTIONS, MAX_DEPTH, MAX_NODES, MAX_TEXT_BYTES, MAX_EXTENSION_BYTES],
    "field_shapes": {key: sorted(value) for key, value in FIELD_SHAPES.items()},
    "arma_report": thaw_json(ARMA_REPORT_SCHEMA),
    "arma_report_dependency_fields": ["artifact_ids", "chart_artifacts"],
    "result_dependency_namespaces": thaw_json(RESULT_DEPENDENCY_NAMESPACES_V1),
    }


RESULT_SECTIONS_CONTRACT_DIGEST = sha256_canonical(result_sections_declaration())


def _fail(message: str, code: str = "RESULT_SECTION_INVALID") -> None:
    raise ResultSectionError(code, message)


def _text(value: object, *, allow_empty: bool = False) -> str:
    if type(value) is not str or len(value) > MAX_TEXT_BYTES or (not value and not allow_empty) or "\x00" in value:
        _fail("expected bounded text")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        _fail("invalid Unicode text")
    if size > MAX_TEXT_BYTES:
        _fail("text exceeds UTF-8 byte budget")
    return value


def _refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_NODES:
        _fail("references must be a bounded array")
    refs = tuple(_text(item) for item in value)
    if len(refs) != len(set(refs)):
        _fail("duplicate references")
    return refs


def _version(value: object) -> None:
    if type(value) is not int or value != 1:
        _fail("unsupported result section version", "UNSUPPORTED_VERSION")


def _bounded_wire(value: object) -> None:
    """Count canonical bytes incrementally before any recursive copying."""
    total = 0
    def spend(size: int) -> None:
        nonlocal total
        total += size
        if total > MAX_EXTENSION_BYTES:
            _fail("structured results exceed byte budget")
    def visit(item: object, depth: int) -> None:
        if depth > MAX_DEPTH * 3 + 8:
            _fail("wire nesting exceeds budget")
        if isinstance(item, Mapping):
            if len(item) > MAX_NODES:
                _fail("wire object exceeds node budget")
            spend(2 + max(len(item) - 1, 0) + len(item))
            normalized_keys: set[str] = set()
            for key, child in item.items():
                normalized = unicodedata.normalize("NFC", _text(key))
                if normalized in normalized_keys:
                    _fail("Unicode normalization produced duplicate object keys")
                normalized_keys.add(normalized)
                visit(_text(key), depth + 1)
                visit(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            if len(item) > MAX_NODES:
                _fail("wire array exceeds node budget")
            spend(2 + max(len(item) - 1, 0))
            for child in item:
                visit(child, depth + 1)
        else:
            if type(item) is str:
                _text(item, allow_empty=True)
            elif item is not None and type(item) not in (int, float, bool):
                _fail("invalid wire scalar")
            if type(item) is int and abs(item) > MAX_SAFE_INTEGER:
                _fail("unsafe wire integer")
            if type(item) is float and not math.isfinite(item):
                _fail("non-finite wire number")
            spend(len(canonical_json_v1(item).encode("utf-8")))
    visit(value, 0)


def preflight_structured_results(value: Mapping[str, object]) -> None:
    require_exact_keys(value, {"schema_version", "contract_digest", "sections"}, "structured results")
    _version(value["schema_version"])
    if value["contract_digest"] != RESULT_SECTIONS_CONTRACT_DIGEST:
        _fail("structured results contract digest mismatch", "RESULT_SECTION_CONTRACT_MISMATCH")
    if not isinstance(value["sections"], (list, tuple)) or len(value["sections"]) > MAX_SECTIONS:
        _fail("section count exceeds budget")
    _bounded_wire(value)


def _tree(node: object, facts: Mapping[str, NumericFactV1], refs: set[str],
          count: list[int], depth: int = 0) -> object:
    count[0] += 1
    if depth > MAX_DEPTH or count[0] > MAX_NODES:
        _fail("tree depth/node budget exceeded")
    if not isinstance(node, Mapping):
        _fail("content must be a typed node")
    kind = node.get("kind")
    keys = {
        "text": {"kind", "value"}, "boolean": {"kind", "value"},
        "null": {"kind"}, "object": {"kind", "fields"},
        "list": {"kind", "items"}, "fact": {"kind", "fact_id", "representation"},
        "missing": {"kind", "status", "reason"},
    }
    if type(kind) is not str or kind not in keys:
        _fail("unknown node kind; numeric literals are forbidden")
    require_exact_keys(node, keys[kind], "result node")
    if kind == "text":
        return _text(node["value"], allow_empty=True)
    if kind == "boolean":
        if type(node["value"]) is not bool:
            _fail("boolean node requires a boolean")
        return node["value"]
    if kind == "null":
        return None
    if kind == "missing":
        if node["status"] not in ("unavailable", "not_applicable"):
            _fail("invalid missing-field status")
        return {"status": node["status"], "reason": _text(node["reason"])}
    if kind == "fact":
        fact_id = _text(node["fact_id"])
        fact = facts.get(fact_id)
        if type(fact) is not NumericFactV1 or fact.fact_id != fact_id:
            _fail("fact reference is missing or mismatched", "RESULT_SECTION_FACT_MISSING")
        value = fact.value
        representation = node["representation"]
        if representation not in ("integer", "number"):
            _fail("unknown numeric representation")
        if type(value) not in (int, float) or not math.isfinite(value):
            _fail("non-finite fact value")
        if representation == "integer":
            if abs(value) > MAX_SAFE_INTEGER or int(value) != value:
                _fail("integer representation would alter the value")
            value = int(value)
        refs.add(fact_id)
        return value
    if kind == "list":
        items = node["items"]
        if not isinstance(items, (list, tuple)) or len(items) > MAX_NODES:
            _fail("list node requires a bounded array")
        return [_tree(item, facts, refs, count, depth + 1) for item in items]
    fields = node["fields"]
    if not isinstance(fields, Mapping) or len(fields) > MAX_NODES:
        _fail("object node requires bounded fields")
    return {_text(key): _tree(item, facts, refs, count, depth + 1)
            for key, item in fields.items()}


def _validate_fields(section_type: str, content: Mapping[str, object], facts: Mapping[str, NumericFactV1]) -> None:
    """Validate declared presentation roles, without deriving statistics."""
    if not SECTION_REQUIRED_FIELDS[section_type].issubset(content["fields"]):
        _fail("required section fields are missing; use explicit missing nodes")
    for field, node in content["fields"].items():
        kind = node["kind"]
        if kind == "missing":
            continue
        expected = FIELD_SHAPES[field]
        if kind not in expected:
            _fail(f"invalid {section_type}.{field} node shape")
    def numerical_roles(node: Mapping[str, object], path: tuple[str, ...] = ()) -> None:
        numeric_row = any(
            len(pattern) == len(path) and all(expected == "*" or expected == actual
                                            for expected, actual in zip(pattern, path))
            for pattern in SECTION_NUMERIC_PATHS[section_type]
        )
        if node["kind"] == "object":
            for field, child in node["fields"].items():
                if numeric_row and field in NUMERIC_FIELDS and child["kind"] != "missing":
                    if child["kind"] != "fact":
                        _fail(f"numerical field {field} requires a fact or explicit missing node")
                    value = facts[child["fact_id"]].value
                    if field in COUNT_FIELDS and (child["representation"] != "integer" or value < 0):
                        _fail(f"count field {field} requires a nonnegative integer fact")
                    if field in {"p_value", "p_value_corrected"} and not 0 <= value <= 1:
                        _fail("p-value outside zero to one")
                    if field == "confidence_level" and not 0 < value < 1:
                        _fail("confidence level outside zero to one")
                numerical_roles(child, (*path, field))
        elif node["kind"] == "list":
            for child in node["items"]:
                numerical_roles(child, (*path, "*"))
    numerical_roles(content)


def _validate_arma_report(content, dependencies):
    fields = content["fields"]
    if fields.get("model_family") != {"kind": "text", "value": "time_series.arma_garch"}:
        return

    def validate(node, schema):
        if node["kind"] == "missing":
            return
        if isinstance(schema, tuple):
            role, child_schema = schema
            expected = {"number": "fact", "map": "object"}.get(role, role)
            if node["kind"] != expected:
                _fail(f"ARMA report {role} requires {expected} or explicit missing node")
            if role == "map":
                for child in node["fields"].values():
                    validate(child, child_schema)
            elif role == "list":
                for child in node["items"]:
                    validate(child, child_schema)
            return
        if node["kind"] != "object" or not set(node["fields"]).issubset(schema):
            _fail("undeclared ARMA report record fields")
        for key, child in node["fields"].items():
            validate(child, schema[key])

    results = fields["results"]
    if results["kind"] != "object":
        _fail("ARMA results require a model-keyed object")
    for model in results["fields"].values():
        if model["kind"] != "object":
            _fail("ARMA model requires an object")
        report = model["fields"].get("report")
        if report is None or report["kind"] == "missing":
            continue
        validate(report, ARMA_REPORT_SCHEMA)
        for field in ("artifact_ids", "chart_artifacts"):
            refs = report["fields"].get(field)
            if refs is not None and refs["kind"] == "list":
                for ref in refs["items"]:
                    if ref["kind"] != "text" or ref["value"] not in dependencies:
                        _fail("ARMA artifact reference requires section dependency", "RESULT_SECTION_DEPENDENCY_MISSING")


@dataclass(frozen=True, init=False)
class ResultSectionV1:
    _wire: Mapping[str, object]

    @classmethod
    def from_dict(cls, value: Mapping[str, object], *, facts: Mapping[str, NumericFactV1],
                  dependency_ids: set[str] | frozenset[str]) -> "ResultSectionV1":
        require_exact_keys(value, {"section_id", "section_type", "schema_version", "status",
                                  "reason_codes", "fact_refs", "dependency_refs", "content"}, "result section")
        _bounded_wire(value)
        _version(value["schema_version"])
        _text(value["section_id"])
        kind = _text(value["section_type"])
        if kind not in SECTION_FIELDS:
            _fail("undeclared section type")
        refs = _refs(value["fact_refs"])
        dependencies = _refs(value["dependency_refs"])
        reasons = _refs(value["reason_codes"])
        if not set(dependencies).issubset(dependency_ids):
            _fail("unknown section dependency", "RESULT_SECTION_DEPENDENCY_MISSING")
        status = value["status"]
        if status not in ("available", "unavailable", "not_applicable", "blocked"):
            _fail("invalid section status")
        actual: set[str] = set()
        decoded = _tree(value["content"], facts, actual, [0])
        if actual != set(refs):
            _fail("declared fact references differ from content")
        if status == "available":
            if reasons or not dependencies:
                _fail("available section needs dependencies and no failure reasons")
            if not isinstance(decoded, dict) or value["content"]["kind"] != "object":
                _fail("available section must have object content")
            if not decoded or not set(decoded).issubset(SECTION_FIELDS[kind]):
                _fail("undeclared or empty section fields")
            _validate_fields(kind, value["content"], facts)
            if kind == "model_family_evidence":
                _validate_arma_report(value["content"], set(dependencies))
        elif not reasons or refs or dependencies or value["content"] != {"kind": "null"}:
            _fail("unavailable section must have reasons and no hidden content")
        wire = freeze_json(value)
        if len(canonical_json_v1(thaw_json(wire)).encode("utf-8")) > MAX_EXTENSION_BYTES:
            _fail("section exceeds canonical byte budget")
        instance = object.__new__(cls)
        object.__setattr__(instance, "_wire", wire)
        return instance

    @property
    def section_id(self) -> str:
        return self._wire["section_id"]

    @property
    def fact_refs(self) -> tuple[str, ...]:
        return self._wire["fact_refs"]

    @property
    def dependency_refs(self) -> tuple[str, ...]:
        return self._wire["dependency_refs"]

    def to_dict(self) -> dict[str, object]:
        return thaw_json(self._wire)


@dataclass(frozen=True, init=False)
class StructuredResultsV1:
    sections: tuple[ResultSectionV1, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, object], *, facts: Mapping[str, NumericFactV1],
                  dependency_ids: set[str] | frozenset[str]) -> "StructuredResultsV1":
        preflight_structured_results(value)
        raw = value["sections"]
        if not isinstance(raw, (list, tuple)) or len(raw) > MAX_SECTIONS:
            _fail("section count exceeds budget")
        sections = tuple(ResultSectionV1.from_dict(item, facts=facts, dependency_ids=dependency_ids)
                         for item in raw)
        if len({item.section_id for item in sections}) != len(sections):
            _fail("duplicate section IDs")
        instance = object.__new__(cls)
        object.__setattr__(instance, "sections", sections)
        if len(canonical_json_v1(instance.to_dict()).encode("utf-8")) > MAX_EXTENSION_BYTES:
            _fail("structured results exceed byte budget")
        return instance

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "contract_digest": RESULT_SECTIONS_CONTRACT_DIGEST,
                "sections": [section.to_dict() for section in self.sections]}


def resolve_section_content(section: ResultSectionV1, *, facts: Mapping[str, NumericFactV1]) -> object:
    """Lossless dereference only; NOT an authority or consumer admission seam."""
    checked = ResultSectionV1.from_dict(section.to_dict(), facts=facts,
                                        dependency_ids=set(section.dependency_refs))
    return _tree(checked._wire["content"], facts, set(), [0])
