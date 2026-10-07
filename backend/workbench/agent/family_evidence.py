"""The Agent's view of a family's evidence, driven by its declaration.

Each declared field names a kind; this module maps the kind to its bound. No
family is named here: a new family is a declaration in
``contracts.model.result_envelope_registry``, and if it introduces a new kind,
a test fails until the kind has a bound.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..artifacts import read_json, registered_artifacts_at, sha256_file
from ..contracts.model.result_envelope_registry import (
    EvidenceField,
    ResultEnvelopeDeclaration,
    declaration_for,
)
from .bounds import (
    _bounded_anova_rows,
    _bounded_bootstrap,
    _bounded_cross_quantile_comparisons,
    _bounded_effect_aggregate,
    _bounded_effect_point,
    _bounded_effect_series,
    _bounded_honest_did,
    _bounded_label,
    _bounded_labels,
    _bounded_multinomial_marginal_effects,
    _bounded_numeric_fields,
    _bounded_numeric_list,
    _bounded_numeric_map,
    _bounded_ordinal_marginal_effects,
    _bounded_ordinal_probabilities,
    _bounded_parallel_lines,
    _bounded_probability_map,
    _bounded_quantile_fits,
    _bounded_quantile_intervals,
    _bounded_schoenfeld,
    _bounded_survival_rows,
    _public_positive_int,
    _public_stat_number,
)


def _tuple(options: Mapping[str, Any], key: str) -> tuple[str, ...]:
    return tuple(options.get(key, ()))


BOUNDS_BY_KIND: Mapping[str, Callable[[Any, Mapping[str, Any]], Any]] = {
    "label": lambda value, options: _bounded_label(value),
    "labels": lambda value, options: _bounded_labels(value),
    "positive_int": lambda value, options: _public_positive_int(value),
    "number": lambda value, options: _public_stat_number(value),
    "boolean": lambda value, options: value if type(value) is bool else None,
    "numeric_records": lambda value, options: [
        _bounded_numeric_fields(row, fields=_tuple(options, "fields"),
            string_fields=_tuple(options, "string_fields"))
        for row in (value if isinstance(value, list) else [])[:int(options["limit"])]
        if isinstance(row, dict)
    ],
    "numeric_list": lambda value, options: _bounded_numeric_list(value, limit=int(options["limit"])),
    "numeric_map": lambda value, options: _bounded_numeric_map(value, fields=_tuple(options, "fields")),
    "numeric_fields": lambda value, options: _bounded_numeric_fields(
        value,
        fields=_tuple(options, "fields"),
        string_fields=_tuple(options, "string_fields"),
        list_fields=_tuple(options, "list_fields"),
    ),
    "anova_rows": lambda value, options: _bounded_anova_rows(value, limit=int(options.get("limit", 24))),
    "ordinal_marginal_effects": lambda value, options: _bounded_ordinal_marginal_effects(value),
    "ordinal_probabilities": lambda value, options: _bounded_ordinal_probabilities(value),
    "parallel_lines": lambda value, options: _bounded_parallel_lines(value),
    "multinomial_marginal_effects": lambda value, options: _bounded_multinomial_marginal_effects(value),
    "probability_map": lambda value, options: _bounded_probability_map(value),
    "survival_rows": lambda value, options: _bounded_survival_rows(value, limit=int(options["limit"])),
    "schoenfeld": lambda value, options: _bounded_schoenfeld(value),
    "quantile_fits": lambda value, options: _bounded_quantile_fits(value),
    "quantile_intervals": lambda value, options: _bounded_quantile_intervals(value),
    "bootstrap": lambda value, options: _bounded_bootstrap(value),
    "cross_quantile_comparisons": lambda value, options: _bounded_cross_quantile_comparisons(value),
    "effect_aggregate": lambda value, options: _bounded_effect_aggregate(value),
    "effect_series": lambda value, options: _bounded_effect_series(value),
    "effect_point": lambda value, options: _bounded_effect_point(value),
    "honest_did": lambda value, options: _bounded_honest_did(value),
}


def _read_document(run_root: Path, relative: str | None) -> dict[str, Any] | None:
    if relative is None:
        return None
    path = run_root / relative
    if not path.is_file():
        return None
    loaded = read_json(path)
    return loaded if isinstance(loaded, dict) else None


def _field_value(field: EvidenceField, source: Mapping[str, Any], sidecars: Mapping[str, Mapping[str, Any]]) -> Any:
    origin = sidecars.get(field.sidecar, {}) if field.sidecar else source
    value = origin.get(field.source_key)
    if field.nested_key is not None:
        value = value.get(field.nested_key) if isinstance(value, Mapping) else None
    return value


def project_family_evidence(
    run_root: Path, primary: Mapping[str, Any], declaration: ResultEnvelopeDeclaration
) -> dict[str, Any] | None:
    """Apply a family's declaration to its persisted result, bounded."""
    if not declaration.fields:
        return None
    if declaration.evidence_document is not None:
        source = _read_document(run_root, declaration.evidence_document)
        if source is None:
            return None
        registered = registered_artifacts_at(run_root, declaration.evidence_document)
        document_ref = None
        if registered:
            if len(registered) != 1 or registered[0].get("sha256") != sha256_file(run_root / declaration.evidence_document):
                return None
            document_ref = {key: registered[0].get(key) for key in ("artifact_id", "path", "sha256")}
    else:
        source = dict(primary)
    sidecars = {
        name: _read_document(run_root, relative) or {}
        for name, relative in declaration.sidecars.items()
    }
    projected: dict[str, Any] = {
        "contract": declaration.contract if declaration.contract is not None else source.get("contract"),
        "model_type": primary.get("model_type"),
    }
    # How strongly this family's numbers were checked (v1.8.7 A3), projected for
    # every family: an Agent quoting a figure should be able to say what backs it.
    validation = source.get("validation")
    if isinstance(validation, Mapping):
        projected["validation"] = _bounded_numeric_fields(
            dict(validation), fields=(), string_fields=("level", "external_oracle")
        )
    for field in declaration.fields:
        bound = BOUNDS_BY_KIND[field.kind]
        projected[field.key] = bound(_field_value(field, source, sidecars), field.options)
    model_id = primary.get("model_id")
    if isinstance(model_id, str) and model_id:
        projected["model_id"] = model_id
        projected["evidence_ref"] = {"run_id": run_root.name, "model_id": model_id,
                                     "result_ref": f"model_results:{model_id}"}
        if declaration.evidence_document is not None:
            projected["evidence_ref"].pop("result_ref")
            if document_ref is not None and not any(field.sidecar for field in declaration.fields):
                projected["evidence_ref"].update(document_ref)
    return projected


def bounded_model_family_evidence(run_root: Path, model_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The bounded family evidence of a run's primary model, if it declares any."""
    primary = next((item for item in model_results if isinstance(item, dict)), None)
    if primary is None:
        return None
    declaration = declaration_for(primary.get("kernel_family") or primary.get("model_type"))
    if declaration is None:
        return None
    return project_family_evidence(run_root, primary, declaration)
