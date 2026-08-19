from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import read_json
from .canonical import sha256_canonical
from .narrative.render import render_template


_DEFAULT_SIGNIFICANCE_LEVELS: dict[str, float] = {
    "***": 0.01,
    "**": 0.05,
    "*": 0.1,
}


def build_regression_table(
    model_results: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    variable_labels: Mapping[str, Any] | None = None,
    significance_levels: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Project multiple model packets into a side-by-side report table.

    This is a report projection only: coefficient values and provenance fields
    are copied as-is, while the significance marker is derived from the packet's
    p-value using the explicitly supplied (or default) cutoffs.
    """

    labels = variable_labels or {}
    cutoffs = dict(significance_levels or _DEFAULT_SIGNIFICANCE_LEVELS)
    ordered_cutoffs = sorted(
        ((str(marker), float(cutoff)) for marker, cutoff in cutoffs.items()),
        key=lambda item: item[1],
    )

    model_views: list[dict[str, Any]] = []
    rows_by_term: dict[str, dict[str, Any]] = {}
    for model_id, model_result in model_results:
        model_key = str(model_id)
        model_views.append(
            {
                "id": model_key,
                "label": (
                    model_result.get("model_label")
                    or model_result.get("model_type")
                    or model_key
                ),
                "model_type": model_result.get("model_type"),
                "nobs": model_result.get("nobs"),
                "r_squared": model_result.get("r_squared"),
                "adjusted_r_squared": model_result.get("adjusted_r_squared"),
                # The terms every standard error in this column is conditional
                # on. A table pasted into a paper without them reports a
                # precision the analysis did not have.
                "survey_design": _design_summary(model_result.get("survey_design")),
            }
        )
        coefficients = model_result.get("coefficients", {})
        if not isinstance(coefficients, Mapping):
            continue
        for term, values in coefficients.items():
            if not isinstance(values, Mapping):
                continue
            term_key = str(term)
            row = rows_by_term.setdefault(
                term_key,
                {
                    "term": term_key,
                    "label": labels.get(term_key, term_key),
                    "models": {},
                },
            )
            cell = dict(values)
            cell["significance"] = _regression_significance_marker(
                values.get("p_value"), ordered_cutoffs
            )
            row["models"][model_key] = cell

    return {
        "payload_schema": "workbench.regression-table",
        "schema_version": 1,
        "models": model_views,
        "rows": [
            {
                **row,
                "models": {
                    model["id"]: row["models"].get(model["id"])
                    for model in model_views
                },
            }
            for row in rows_by_term.values()
        ],
        "significance": {
            "cutoffs": {marker: cutoff for marker, cutoff in ordered_cutoffs},
            "legend": "; ".join(
                f"{marker} p < {cutoff:g}" for marker, cutoff in ordered_cutoffs
            ),
        },
    }


def _regression_significance_marker(
    p_value: Any,
    ordered_cutoffs: Sequence[tuple[str, float]],
) -> str:
    try:
        parsed = float(p_value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(parsed):
        return ""
    for marker, cutoff in ordered_cutoffs:
        if parsed < cutoff:
            return marker
    return ""


def regression_table_export_rows(
    regression_table: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Flatten the side-by-side packet into scalar-friendly XLSX rows."""

    if not isinstance(regression_table, Mapping):
        return []
    raw_models = regression_table.get("models", [])
    models = [model for model in raw_models if isinstance(model, Mapping)]
    raw_rows = regression_table.get("rows", [])
    export_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, Mapping):
            continue
        export_row: dict[str, Any] = {
            "term": row.get("term", ""),
            "label": row.get("label", row.get("term", "")),
        }
        for model in models:
            design = model.get("survey_design")
            if design:
                export_row[f"{model.get('id', '')} survey design"] = design
        cells = row.get("models", {})
        for model in models:
            model_id = str(model.get("id", ""))
            cell = cells.get(model_id) if isinstance(cells, Mapping) else None
            for field in (
                "estimate",
                "std_error",
                "confidence_interval",
                "p_value",
                "significance",
                "source_id",
            ):
                export_row[f"{model_id} {field}"] = (
                    cell.get(field) if isinstance(cell, Mapping) else None
                )
        export_rows.append(export_row)
    return export_rows


def build_report_view_model(
    summary: dict[str, Any],
    run_root: Path,
    *,
    descriptive_stats: list[dict[str, Any]] | None = None,
    statistical_tests: dict[str, Any] | None = None,
    statistical_evidence: dict[str, Any] | None = None,
    regression_table: dict[str, Any] | None = None,
    exploration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics = summary.get("diagnostics", {})

    def _render_issues(issues: list[dict]) -> list[dict]:
        result: list[dict] = []
        for issue in issues:
            tk = issue.get("template_key", "")
            params = issue.get("template_params", {})
            if tk:
                try:
                    text = render_template(tk, params)
                except (KeyError, ValueError):
                    text = issue.get("message", "")
            else:
                text = issue.get("message", "")
            result.append({
                "text": text,
                "code": issue.get("code", ""),
                "severity": issue.get("severity", ""),
                "variables": issue.get("variables", []),
            })
        return result

    coeff_rows = summary.get("coefficients_summary", {}).get("rows", [])
    coeff_views: list[dict] = []
    for row in coeff_rows:
        guide = row.get("interpretation_guide", "standard")
        tk = row.get("template_key", "")
        # Guardrail: categorical/dummy variables must not use continuous templates
        if guide == "categorical_levels_vs_reference":
            tk = "coef_categorical"
        elif tk in ("coef_continuous_association",) and row.get("level"):
            # Has a level → likely categorical, don't use continuous text
            tk = "coef_categorical"
        if tk:
            try:
                text = render_template(tk, {
                    "variable": row.get("display_name", row.get("variable", "")),
                    "estimate": _format_estimate(row.get("estimate")),
                    "p_label": row.get("significance_label", "not reported"),
                    "y": summary.get("model_identity", {}).get("y_variable", "y"),
                    "level": row.get("level", ""),
                    "reference": "1",
                })
            except (KeyError, ValueError):
                text = row.get("message", "")
        else:
            text = ""
        coeff_views.append({
            "text": text,
            "variable": row.get("variable", ""),
            "interpretation_guide": guide,
        })

    nc = summary.get("narrative_contract", {})
    has_treatment = nc.get("constraints", {}).get("must_not_interpret_treatment_independently", False)
    if has_treatment:
        try:
            causal_text = render_template("causal_caution_with_treatment", {})
        except (KeyError, ValueError):
            causal_text = ""
    else:
        try:
            causal_text = render_template("causal_caution_default", {})
        except (KeyError, ValueError):
            causal_text = ""

    ds = descriptive_stats if descriptive_stats is not None else _load_if_exists(run_root / "staged" / "data_profile.json")
    st = statistical_tests if statistical_tests is not None else _load_if_exists(run_root / "staged" / "statistical_test_summaries.json")

    model_diag: dict[str, Any] = {}
    diag_dir = run_root / "model_results"
    if diag_dir.is_dir():
        for path in sorted(diag_dir.glob("diagnostics_*.json")):
            try:
                data = read_json(path)
                if isinstance(data, dict):
                    model_diag[path.stem] = data
            except Exception:
                pass

    critical_errors = _render_issues(diagnostics.get("blockers", []))
    if exploration is not None and exploration.get("status") != "completed":
        # Report text is read by whoever ran the workflow, so it must describe
        # the workflow, not the exercise this feature was first built for.
        critical_errors.append(
            {
                "text": (
                    "The statistical workflow did not complete; "
                    "the final report is blocked."
                ),
                "code": "WORKFLOW_INCOMPLETE",
                "severity": "BLOCKER",
                "variables": [],
            }
        )

    return {
        "title": summary.get("model_identity", {}).get("model_label", "Econometrics Report"),
        "facts": _build_facts_list(summary) + _survey_design_facts(run_root),
        "critical_errors": critical_errors,
        "warnings": _render_issues(diagnostics.get("warnings", [])),
        "cautions": _render_issues(diagnostics.get("cautions", [])),
        "system_notes": _render_issues(diagnostics.get("info", [])),
        "coefficient_interpretations": coeff_views,
        "causal_caution": causal_text,
        "descriptive_stats": ds,
        "statistical_tests": st,
        "statistical_evidence": (
            statistical_evidence
            if statistical_evidence is not None
            else _load_if_exists(run_root / "statistical_tests" / "evidence.json")
        ),
        "regression_table": regression_table,
        "model_family_evidence": summary.get("model_family_evidence"),
        "exploration": exploration,
        "model_diagnostics": model_diag,
        "model_quality": summary.get("model_quality"),
    }


def _build_facts_list(summary: dict[str, Any]) -> list[str]:
    mi = summary.get("model_identity", {})
    pp = summary.get("preprocessing", {})

    exposure_var = pp.get("exposure_variable")
    x_vars = mi.get("x_variables", [])
    display_x = [v for v in x_vars if v != exposure_var] if exposure_var else x_vars

    model_label = mi.get("model_label", "")
    if exposure_var:
        model_label = f"Poisson rate model with log({exposure_var}) as offset"

    facts = [
        f"Model: {model_label}",
        f"y = {mi.get('y_variable', '')};  X = {', '.join(display_x)}",
    ]
    if exposure_var:
        facts.append(f"Exposure/offset: log({exposure_var}), coefficient fixed at 1")
    facts.extend([
        f"Rows used: {mi.get('n_observations', 0)} · Columns: {pp.get('column_count_after_encoding', mi.get('n_predictors_after_encoding', 0) + 1)}",
        f"Dataset kind: {mi.get('dataset_kind', 'unknown')}",
    ])
    imputation = pp.get("imputation", {})
    if isinstance(imputation, dict) and imputation.get("method") == "mice" and imputation.get("status") == "completed":
        facts.append(_mice_imputation_fact(imputation))
    encoded = pp.get("categorical_encoded", [])
    if encoded:
        names = ", ".join(e["variable"] for e in encoded)
        facts.append(f"Categorical variable(s): {names} (dummy-coded in model)")
    return facts


def _mice_imputation_fact(imputation: dict[str, Any]) -> str:
    columns = imputation.get("imputed_columns", [])
    columns_text = ", ".join(str(column) for column in columns) if columns else "none"
    persisted = imputation.get("persisted_datasets", 0)
    persisted_text = "one" if persisted == 1 else str(persisted)
    pooled = "were produced" if imputation.get("pooled_estimates") else "were not produced"
    return (
        f"MICE imputation: {persisted_text} persisted imputed dataset; "
        f"imputed columns: {columns_text}; pooled estimates {pooled}."
    )


def _format_estimate(estimate: Any) -> str:
    if estimate is None:
        return "N/A"
    try:
        return f"{float(estimate):+.4f}"
    except (ValueError, TypeError):
        return str(estimate)


def _load_if_exists(path: Path) -> Any | None:
    if path.is_file():
        try:
            return read_json(path)
        except Exception:
            return None
    return None


def _survey_design_facts(run_root: Path) -> list[str]:
    """State the design in the report, or say nothing at all.

    A design-based standard error that lives only in a JSON artifact leaves the
    report claiming a precision the analysis did not have -- and the report is
    where the number gets read. Appended to the facts rather than given its own
    section so it sits beside the sample size and the model label, which is
    where a reader looks for the terms an interval is conditional on.

    Nothing is emitted for a run without a declared design: a section present on
    every run stops carrying information.
    """
    for path in sorted((run_root / "model_results").glob("*.json")):
        if path.name.startswith("diagnostics_"):
            continue
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        design = payload.get("survey_design") if isinstance(payload, dict) else None
        if not isinstance(design, dict):
            continue

        facts = [
            "Standard errors are design-based, not the usual independent-sample "
            f"kind: {design.get('variance_method', 'linearization')} over "
            f"{design.get('n_strata', 0)} strata and {design.get('n_psu', 0)} PSUs "
            f"(strata = {design.get('strata_column')}, PSU = {design.get('psu_column')})",
            f"Design degrees of freedom: {design.get('degf')} "
            f"(confidence intervals use this, not the sample size)",
        ]
        deff = design.get("design_effect")
        n_eff = design.get("effective_sample_size")
        if deff is not None and n_eff is not None:
            facts.append(
                f"Design effect {float(deff):.2f}; effective sample size "
                f"{float(n_eff):.1f} of {design.get('n_obs')} observations"
            )
        if design.get("subpopulation"):
            facts.append(
                f"Subpopulation: {design['subpopulation']} "
                "(taken on the full design, not by filtering the data first)"
            )
        return facts
    return []


def _design_summary(design: Any) -> str:
    """One cell's worth of design, or nothing.

    Compressed to a string rather than nested: this travels into XLSX, where a
    cell holds a scalar, and a reader scanning a pasted table needs the terms at
    a glance more than they need the full packet.
    """
    if not isinstance(design, Mapping):
        return ""
    parts = [
        f"{design.get('variance_method', 'linearization')} design-based SE",
        f"strata={design.get('strata_column')}",
        f"PSU={design.get('psu_column')}",
        f"degf={design.get('degf')}",
    ]
    deff = design.get("design_effect")
    if deff is not None:
        parts.append(f"DEFF={float(deff):.2f}")
    return "; ".join(parts)


def build_persisted_evidence_report_view(
    projection: "EvidenceProjectionV1",
) -> dict[str, object]:
    """Expose a bounded report view by copying a typed projection only."""

    from .evidence.consumer_adapters import EvidenceProjectionV1

    if type(projection) is not EvidenceProjectionV1:
        raise TypeError("projection must be EvidenceProjectionV1")
    facts: list[dict[str, object]] = []
    for fact in projection.facts:
        row: dict[str, object] = {
            "factId": fact.fact_id,
            "statisticId": fact.statistic_id,
            "value": fact.value,
        }
        if type(fact.unit) is str:
            row["unit"] = fact.unit
        if type(fact.standard_error) is float:
            row["standardError"] = fact.standard_error
        if hasattr(fact.confidence_interval, "lower") and hasattr(fact.confidence_interval, "upper"):
            row["confidenceInterval"] = {
                "lower": fact.confidence_interval.lower,
                "upper": fact.confidence_interval.upper,
            }
        facts.append(row)
    status = projection.status.value
    sections = []
    if status != "available":
        sections.append({"key": "persisted-evidence", "label": "Persisted evidence", "status": status})
    view: dict[str, object] = {
        "projectionId": f"{projection.consumer_id}:{projection.commit_id}",
        "consumerId": projection.consumer_id,
        "consumerVersion": projection.consumer_version,
        "artifactRef": projection.artifact_ref,
        "envelopeRef": projection.envelope_ref,
        "commitId": projection.commit_id,
        "envelopeDigest": projection.envelope_digest,
        "status": status,
        "executionStatus": projection.execution_status,
        "availability": projection.availability,
        "completenessStatus": projection.completeness_status,
        "facts": facts,
        "sections": sections,
        "provenance": {
            "artifactRef": projection.artifact_ref,
            "commitId": projection.commit_id,
            "envelopeRef": projection.envelope_ref,
            "lineageRefs": list(projection.lineage_refs),
            "projectionRef": projection.projection_ref.to_dict(),
            "resultIdentity": dict(projection.result_identity),
        },
    }
    if projection.audit.restriction_reason:
        view["reasonCode"] = projection.audit.restriction_reason
    return view


def _unavailable_report_evidence(
    *,
    artifact_id: str,
    artifact_type: str,
    reason_code: str,
    status: str = "unavailable",
) -> dict[str, object]:
    """Return a typed empty view for an artifact that did not pass admission.

    This is deliberately a complete report-view shape.  Consumers can render
    the failure without having to inspect the indexed artifact or its result,
    and the result payload never crosses this boundary.
    """

    safe_artifact_id = artifact_id if artifact_id else "UNAVAILABLE"
    safe_artifact_type = artifact_type if artifact_type else "unknown"
    return {
        "projectionId": f"report:unavailable:{safe_artifact_id}",
        "consumerId": "report",
        "consumerVersion": "1.0",
        "artifactRef": safe_artifact_id,
        "envelopeRef": "UNAVAILABLE",
        "commitId": "UNAVAILABLE",
        "envelopeDigest": "UNAVAILABLE",
        "status": status,
        "executionStatus": "unavailable",
        "availability": "unavailable",
        "completenessStatus": "unavailable",
        "facts": [],
        "sections": [
            {
                "key": "persisted-evidence",
                "label": "Persisted evidence",
                "status": status,
            }
        ],
        "reasonCode": reason_code,
        "provenance": {
            "artifactId": safe_artifact_id,
            "artifactType": safe_artifact_type,
            "indexed": True,
            "admissionStatus": status,
        },
    }


def _evidence_wire_fields(
    value: Mapping[str, object],
) -> tuple[object | None, object | None, object | None, object | None, object | None]:
    """Read only explicitly named canonical evidence fields from an index row."""

    nested = value.get("evidence")
    nested_record = nested if isinstance(nested, Mapping) else {}
    binding = (
        value.get("evidence_commit_binding")
        or value.get("commit_binding")
        or value.get("binding")
        or nested_record.get("evidence_commit_binding")
        or nested_record.get("commit_binding")
        or nested_record.get("binding")
    )
    envelope = (
        value.get("evidence_envelope")
        or value.get("envelope")
        or nested_record.get("evidence_envelope")
        or nested_record.get("envelope")
    )
    envelope_ref = (
        value.get("evidence_envelope_ref")
        or nested_record.get("evidence_envelope_ref")
        or nested_record.get("envelope_ref")
    )
    sensitivity = value.get("evidence_sensitivity") or nested_record.get("sensitivity")
    artifact_ref = value.get("evidence_artifact_ref") or nested_record.get("artifact_ref")
    return binding, envelope, envelope_ref, sensitivity, artifact_ref


def _evidence_identity_fields(
    value: Mapping[str, object],
) -> tuple[
    object | None,
    object | None,
    object | None,
    object | None,
    object | None,
    object | None,
    object | None,
    object | None,
    bool,
    object | None,
]:
    """Read index-owned identity fields used to bind a canonical commit.

    These fields are intentionally read from the index row, not synthesized
    from the result payload.  The payload may help confirm source identity,
    but it cannot supply the authoritative artifact admission or content hash.
    """

    nested = value.get("evidence")
    nested_record = nested if isinstance(nested, Mapping) else {}

    def first(*keys: str) -> object | None:
        for source in (value, nested_record):
            for key in keys:
                candidate = source.get(key)
                if candidate is not None:
                    return candidate
        return None

    def all_values(*keys: str) -> list[object]:
        values: list[object] = []
        for source in (value, nested_record):
            for key in keys:
                candidate = source.get(key)
                if candidate is not None:
                    values.append(candidate)
        return values

    content_hash_values = all_values(
        "evidence_content_hash",
        "content_hash",
        "evidence_artifact_content_hash",
        "artifact_content_hash",
    )
    content_hash_conflict = any(
        candidate != content_hash_values[0]
        for candidate in content_hash_values[1:]
    )

    return (
        first("evidence_commit_ref", "commit_ref", "evidence_commit_id", "commit_id"),
        first("evidence_artifact_admission_ref", "artifact_admission_ref"),
        first("run_id", "evidence_run_id"),
        first("model_run_id", "evidence_model_run_id"),
        first("evidence_run_id"),
        first("evidence_model_run_id"),
        first("evidence_content_hash", "content_hash", "evidence_artifact_content_hash", "artifact_content_hash"),
        content_hash_conflict,
        first("sha256", "artifact_sha256"),
        first("evidence_artifact_ref", "artifact_ref"),
    )


def build_indexed_report_evidence(
    indexed_artifact: Mapping[str, object],
    artifact_payload: object | None = None,
    *,
    artifact_content_sha256: str | None = None,
    authoritative_persistence: object | None = None,
) -> dict[str, object]:
    """Project one indexed artifact into the Report consumer boundary.

    An artifact index entry is only an admission/index record.  It is not an
    evidence commit.  The only accepted path is an explicitly supplied,
    canonical commit reference and server-owned admission.  Any wire binding
    or envelope present in the index is only a tamper check; facts are loaded
    from the injected owner capability and never from those mappings.
    """

    if not isinstance(indexed_artifact, Mapping):
        return _unavailable_report_evidence(
            artifact_id="unknown-artifact",
            artifact_type="unknown",
            reason_code="EVIDENCE_INDEX_INVALID",
        )
    raw_artifact_id = indexed_artifact.get("artifact_id")
    artifact_id = raw_artifact_id if isinstance(raw_artifact_id, str) and raw_artifact_id else "unknown-artifact"
    raw_artifact_type = indexed_artifact.get("artifact_type")
    artifact_type = raw_artifact_type if isinstance(raw_artifact_type, str) and raw_artifact_type else "unknown"
    if artifact_id == "unknown-artifact":
        return _unavailable_report_evidence(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            reason_code="EVIDENCE_ARTIFACT_ID_REQUIRED",
        )

    candidates: list[Mapping[str, object]] = [indexed_artifact]
    if isinstance(artifact_payload, Mapping):
        candidates.append(artifact_payload)
    binding_raw: object | None = None
    envelope_raw: object | None = None
    for candidate in candidates:
        fields = _evidence_wire_fields(candidate)
        if binding_raw is None and fields[0] is not None:
            binding_raw = fields[0]
        if envelope_raw is None and fields[1] is not None:
            envelope_raw = fields[1]

    (
        commit_ref_raw,
        admission_ref_raw,
        run_id_raw,
        model_run_id_raw,
        evidence_run_id_raw,
        evidence_model_run_id_raw,
        indexed_content_hash_raw,
        indexed_content_hash_conflict,
        indexed_raw_sha256,
        indexed_artifact_ref_raw,
    ) = _evidence_identity_fields(indexed_artifact)

    if binding_raw is None and (
        envelope_raw is not None
        or not isinstance(commit_ref_raw, str)
        or not commit_ref_raw.strip()
    ):
        return _unavailable_report_evidence(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            reason_code="EVIDENCE_COMMIT_BINDING_REQUIRED",
        )

    from .contracts.evidence.envelope import EvidenceEnvelopeV1
    from .contracts.evidence.persistence import EvidenceCommitBindingV1
    from .evidence.consumer_adapters import (
        EvidenceProjectionError,
        default_projection_registry,
    )
    from .services.results_service import ServerOwnedReportEvidencePersistenceV1

    try:
        def required_text(value: object | None, reason_code: str) -> str:
            if not isinstance(value, str) or not value.strip():
                raise EvidenceProjectionError(reason_code, "authoritative indexed identity is required")
            return value

        commit_ref = required_text(commit_ref_raw, "EVIDENCE_COMMIT_REF_REQUIRED")
        admission_ref = required_text(
            admission_ref_raw,
            "EVIDENCE_ARTIFACT_ADMISSION_REF_REQUIRED",
        )
        indexed_artifact_ref = required_text(
            indexed_artifact_ref_raw,
            "EVIDENCE_ARTIFACT_REF_REQUIRED",
        )
        if indexed_artifact_ref != artifact_id:
            raise EvidenceProjectionError(
                "EVIDENCE_ARTIFACT_ID_MISMATCH",
                "indexed artifact_id differs from the canonical artifact ref",
            )
        indexed_content_hash = required_text(
            indexed_content_hash_raw,
            "EVIDENCE_ARTIFACT_CONTENT_HASH_REQUIRED",
        )
        if indexed_content_hash_conflict:
            raise EvidenceProjectionError(
                "EVIDENCE_ARTIFACT_CONTENT_HASH_MISMATCH",
                "indexed artifact content-hash aliases disagree",
            )
        if (
            indexed_raw_sha256 is not None
            and artifact_content_sha256 is not None
            and indexed_raw_sha256 != artifact_content_sha256
        ):
            raise EvidenceProjectionError(
                "EVIDENCE_ARTIFACT_FILE_HASH_MISMATCH",
                "indexed artifact file hash differs from persisted content",
            )

        run_id = required_text(run_id_raw, "EVIDENCE_RUN_ID_REQUIRED")
        model_run_id = required_text(model_run_id_raw, "EVIDENCE_MODEL_RUN_ID_REQUIRED")
        for name, observed, expected in (
            ("evidence_run_id", evidence_run_id_raw, run_id),
            ("evidence_model_run_id", evidence_model_run_id_raw, model_run_id),
        ):
            if observed is not None and observed != expected:
                raise EvidenceProjectionError(
                    "EVIDENCE_RUN_ID_MISMATCH",
                    f"indexed {name} differs from the authoritative run identity",
                    )

        if isinstance(artifact_payload, Mapping):
            payload_sources: list[Mapping[str, object]] = [artifact_payload]
            source = artifact_payload.get("source")
            if isinstance(source, Mapping):
                payload_sources.append(source)
            for payload_source in payload_sources:
                for name, expected in (("run_id", run_id), ("model_run_id", model_run_id)):
                    payload_value = payload_source.get(name)
                    if payload_value is not None and payload_value != expected:
                        raise EvidenceProjectionError(
                            "EVIDENCE_RUN_ID_MISMATCH",
                            f"artifact payload {name} differs from the indexed run identity",
                        )

        if type(authoritative_persistence) is not ServerOwnedReportEvidencePersistenceV1:
            raise EvidenceProjectionError(
                "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
                "Report evidence requires the server-owned persistence capability",
            )

        candidate_binding: EvidenceCommitBindingV1 | None = None
        if binding_raw is not None:
            if not isinstance(binding_raw, Mapping):
                raise EvidenceProjectionError(
                    "PROJECTION_WIRE_INVALID",
                    "canonical binding must be an object",
                )
            candidate_binding = EvidenceCommitBindingV1.from_dict(dict(binding_raw))
            if candidate_binding.commit_id != commit_ref:
                raise EvidenceProjectionError(
                    "EVIDENCE_COMMIT_REF_MISMATCH",
                    "indexed commit ref differs from the canonical binding",
                )
            if candidate_binding.artifact_admission_ref != admission_ref:
                raise EvidenceProjectionError(
                    "EVIDENCE_ARTIFACT_ADMISSION_MISMATCH",
                    "indexed artifact admission ref differs from the canonical binding",
                )
            if envelope_raw is not None:
                if not isinstance(envelope_raw, Mapping):
                    raise EvidenceProjectionError(
                        "PROJECTION_WIRE_INVALID",
                        "canonical envelope must be an object",
                    )
                candidate_envelope = EvidenceEnvelopeV1.from_dict(dict(envelope_raw))
                if candidate_binding.envelope_digest != sha256_canonical(candidate_envelope.to_dict()):
                    raise EvidenceProjectionError(
                        "PROJECTION_DIGEST_MISMATCH",
                        "indexed envelope does not match its canonical binding",
                    )
        elif envelope_raw is not None:
            raise EvidenceProjectionError(
                "EVIDENCE_COMMIT_BINDING_REQUIRED",
                "a canonical envelope cannot be used without its binding",
            )

        persisted_record = authoritative_persistence.read_bound(
            commit_ref,
            artifact_id=indexed_artifact_ref,
            run_id=run_id,
            model_run_id=model_run_id,
            content_hash=indexed_content_hash,
            admission_ref=admission_ref,
            envelope_digest=(candidate_binding.envelope_digest if candidate_binding is not None else None),
        )
        projection = default_projection_registry().project(
            persisted_record,
            consumer_id="report",
            destination="local",
        )
        return build_persisted_evidence_report_view(projection)
    except EvidenceProjectionError as exc:
        return _unavailable_report_evidence(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            reason_code=exc.code,
            status="blocked",
        )
    except (TypeError, KeyError, ValueError) as exc:
        reason_code = "EVIDENCE_CANONICAL_INVALID"
        if "digest" in str(exc).lower():
            reason_code = "PROJECTION_DIGEST_MISMATCH"
        return _unavailable_report_evidence(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            reason_code=reason_code,
            status="blocked",
        )


def build_report_evidence_bundle(
    views: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    """Combine multiple per-artifact typed views without reading raw results."""

    if not views:
        return None
    if len(views) == 1:
        return dict(views[0])
    first = views[0]
    provenance = {
        "projections": [view.get("provenance") for view in views],
        "envelopeDigests": [view.get("envelopeDigest") for view in views],
    }
    result: dict[str, object] = {
        "projectionId": "report:evidence-bundle",
        "consumerId": "report",
        "consumerVersion": str(first.get("consumerVersion", "1.0")),
        "artifactRef": "report-evidence-bundle",
        "envelopeRef": "UNAVAILABLE",
        "commitId": "UNAVAILABLE",
        "envelopeDigest": "UNAVAILABLE",
        "status": "blocked",
        "executionStatus": str(first.get("executionStatus", "unavailable")),
        "availability": "unavailable",
        "completenessStatus": "unavailable",
        "facts": [],
        "sections": [
            {
                "key": f"projection-{index}",
                "label": f"{view.get('artifactRef', 'artifact')} evidence",
                "status": view.get("status", "unavailable"),
            }
            for index, view in enumerate(views)
        ],
        "provenance": provenance,
        "reasonCode": "REPORT_EVIDENCE_BUNDLE_IDENTITY_UNBOUND",
    }
    return result
