from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import read_json
from .canonical import sha256_canonical
from .evidence.consumer_adapters import EvidenceProjectionError
# Kept as a module attribute for legacy test/import compatibility.  The typed
# report consumer below never invokes narrative rendering.
from .narrative.render import render_template
from .services.results_service import ReportEvidenceRequestIdentityV1


_DEFAULT_SIGNIFICANCE_LEVELS: dict[str, float] = {
    "***": 0.01,
    "**": 0.05,
    "*": 0.1,
}


def _projection_identity_fields(projection: Mapping[str, Any]) -> dict[str, str]:
    return {
        key: str(projection.get(key, "UNAVAILABLE"))
        for key in (
            "actorRef",
            "projectRef",
            "sessionRef",
            "scopeRef",
            "runId",
            "modelRunId",
            "confirmationRef",
        )
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


def _build_legacy_presentation(
    summary: dict[str, Any],
    run_root: Path,
    *,
    descriptive_stats: list[dict[str, Any]] | None,
    statistical_tests: dict[str, Any] | None,
    statistical_evidence: dict[str, Any] | None,
    regression_table: dict[str, Any] | None,
    exploration: dict[str, Any] | None,
) -> dict[str, Any]:
    """Retain the established report view-model business semantics.

    This helper intentionally operates on presentation inputs only.  Its
    output is not admitted as Report evidence and is never used by the typed
    export writer as a fact source.
    """

    diagnostics = summary.get("diagnostics", {})

    def render_issues(issues: list[dict]) -> list[dict]:
        result: list[dict] = []
        for issue in issues:
            template_key = issue.get("template_key", "")
            params = issue.get("template_params", {})
            if template_key:
                try:
                    text = render_template(template_key, params)
                except (KeyError, ValueError):
                    text = issue.get("message", "")
            else:
                text = issue.get("message", "")
            result.append(
                {
                    "text": text,
                    "code": issue.get("code", ""),
                    "severity": issue.get("severity", ""),
                    "variables": issue.get("variables", []),
                }
            )
        return result

    coeff_rows = summary.get("coefficients_summary", {}).get("rows", [])
    coefficient_interpretations: list[dict[str, Any]] = []
    for row in coeff_rows:
        guide = row.get("interpretation_guide", "standard")
        template_key = row.get("template_key", "")
        if guide == "categorical_levels_vs_reference":
            template_key = "coef_categorical"
        elif template_key == "coef_continuous_association" and row.get("level"):
            template_key = "coef_categorical"
        if template_key:
            try:
                text = render_template(
                    template_key,
                    {
                        "variable": row.get("display_name", row.get("variable", "")),
                        "estimate": _format_estimate(row.get("estimate")),
                        "p_label": row.get("significance_label", "not reported"),
                        "y": summary.get("model_identity", {}).get("y_variable", "y"),
                        "level": row.get("level", ""),
                        "reference": "1",
                    },
                )
            except (KeyError, ValueError):
                text = row.get("message", "")
        else:
            text = ""
        coefficient_interpretations.append(
            {
                "text": text,
                "variable": row.get("variable", ""),
                "interpretation_guide": guide,
            }
        )

    narrative_contract = summary.get("narrative_contract", {})
    constraints = narrative_contract.get("constraints", {})
    if constraints.get("must_not_interpret_treatment_independently", False):
        try:
            causal_caution = render_template("causal_caution_with_treatment", {})
        except (KeyError, ValueError):
            causal_caution = ""
    else:
        try:
            causal_caution = render_template("causal_caution_default", {})
        except (KeyError, ValueError):
            causal_caution = ""

    descriptive = (
        descriptive_stats
        if descriptive_stats is not None
        else _load_if_exists(run_root / "staged" / "data_profile.json")
    )
    statistical = (
        statistical_tests
        if statistical_tests is not None
        else _load_if_exists(run_root / "staged" / "statistical_test_summaries.json")
    )
    model_diagnostics: dict[str, Any] = {}
    diag_dir = run_root / "model_results"
    if diag_dir.is_dir():
        for path in sorted(diag_dir.glob("diagnostics_*.json")):
            try:
                data = read_json(path)
            except Exception:
                continue
            if isinstance(data, dict):
                model_diagnostics[path.stem] = data

    critical_errors = render_issues(diagnostics.get("blockers", []))
    if exploration is not None and exploration.get("status") != "completed":
        critical_errors.append(
            {
                "text": "The statistical workflow did not complete; the final report is blocked.",
                "code": "WORKFLOW_INCOMPLETE",
                "severity": "BLOCKER",
                "variables": [],
            }
        )
    return {
        "title": summary.get("model_identity", {}).get("model_label", "Econometrics Report"),
        "presentation_facts": _build_facts_list(summary) + _survey_design_facts(run_root),
        "critical_errors": critical_errors,
        "warnings": render_issues(diagnostics.get("warnings", [])),
        "cautions": render_issues(diagnostics.get("cautions", [])),
        "system_notes": render_issues(diagnostics.get("info", [])),
        "coefficient_interpretations": coefficient_interpretations,
        "causal_caution": causal_caution,
        "descriptive_stats": descriptive,
        "statistical_tests": statistical,
        "statistical_evidence": (
            statistical_evidence
            if statistical_evidence is not None
            else _load_if_exists(run_root / "statistical_tests" / "evidence.json")
        ),
        "regression_table": regression_table,
        "model_family_evidence": summary.get("model_family_evidence"),
        "exploration": exploration,
        "model_diagnostics": model_diagnostics,
        "model_quality": summary.get("model_quality"),
    }


def _build_facts_list(summary: dict[str, Any]) -> list[str]:
    model_identity = summary.get("model_identity", {})
    preprocessing = summary.get("preprocessing", {})
    exposure_var = preprocessing.get("exposure_variable")
    x_vars = model_identity.get("x_variables", [])
    display_x = [value for value in x_vars if value != exposure_var] if exposure_var else x_vars
    model_label = model_identity.get("model_label", "")
    if exposure_var:
        model_label = f"Poisson rate model with log({exposure_var}) as offset"
    facts = [
        f"Model: {model_label}",
        f"y = {model_identity.get('y_variable', '')};  X = {', '.join(display_x)}",
    ]
    if exposure_var:
        facts.append(f"Exposure/offset: log({exposure_var}), coefficient fixed at 1")
    facts.extend(
        [
            f"Rows used: {model_identity.get('n_observations', 0)} · Columns: {preprocessing.get('column_count_after_encoding', model_identity.get('n_predictors_after_encoding', 0) + 1)}",
            f"Dataset kind: {model_identity.get('dataset_kind', 'unknown')}",
        ]
    )
    imputation = preprocessing.get("imputation", {})
    if isinstance(imputation, dict) and imputation.get("method") == "mice" and imputation.get("status") == "completed":
        facts.append(_mice_imputation_fact(imputation))
    encoded = preprocessing.get("categorical_encoded", [])
    if encoded:
        names = ", ".join(str(item["variable"]) for item in encoded if isinstance(item, dict) and "variable" in item)
        facts.append(f"Categorical variable(s): {names} (dummy-coded in model)")
    return facts


def _mice_imputation_fact(imputation: dict[str, Any]) -> str:
    columns = imputation.get("imputed_columns", [])
    columns_text = ", ".join(str(column) for column in columns) if columns else "none"
    persisted = imputation.get("persisted_datasets", 0)
    persisted_text = "one" if persisted == 1 else str(persisted)
    pooled = "were produced" if imputation.get("pooled_estimates") else "were not produced"
    return f"MICE imputation: {persisted_text} persisted imputed dataset; imputed columns: {columns_text}; pooled estimates {pooled}."


def _format_estimate(estimate: Any) -> str:
    if estimate is None:
        return "N/A"
    try:
        return f"{float(estimate):+.4f}"
    except (ValueError, TypeError):
        return str(estimate)


def _load_if_exists(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def _survey_design_facts(run_root: Path) -> list[str]:
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
            "Standard errors are design-based, not the usual independent-sample kind: "
            f"{design.get('variance_method', 'linearization')} over {design.get('n_strata', 0)} strata and {design.get('n_psu', 0)} PSUs "
            f"(strata = {design.get('strata_column')}, PSU = {design.get('psu_column')})",
            f"Design degrees of freedom: {design.get('degf')} (confidence intervals use this, not the sample size)",
        ]
        if design.get("design_effect") is not None and design.get("effective_sample_size") is not None:
            facts.append(
                f"Design effect {float(design['design_effect']):.2f}; effective sample size "
                f"{float(design['effective_sample_size']):.1f} of {design.get('n_obs')} observations"
            )
        if design.get("subpopulation"):
            facts.append(f"Subpopulation: {design['subpopulation']} (taken on the full design, not by filtering the data first)")
        return facts
    return []


def build_report_view_model(
    summary: dict[str, Any],
    run_root: Path,
    *,
    descriptive_stats: list[dict[str, Any]] | None = None,
    statistical_tests: dict[str, Any] | None = None,
    statistical_evidence: dict[str, Any] | None = None,
    regression_table: dict[str, Any] | None = None,
    exploration: dict[str, Any] | None = None,
    evidence_projection: Mapping[str, Any] | None = None,
    include_legacy_presentation: bool = False,
) -> dict[str, Any]:
    # Preserve report presentation semantics (narrative, diagnostics,
    # exploration, statistical and survey sections) while keeping citable
    # numeric facts on the typed projection lane below.  Presentation fields
    # are bounded view-model material, never an authority source for exports.
    if isinstance(evidence_projection, Mapping) or include_legacy_presentation:
        presentation = _build_legacy_presentation(
            summary,
            run_root,
            descriptive_stats=descriptive_stats,
            statistical_tests=statistical_tests,
            statistical_evidence=statistical_evidence,
            regression_table=regression_table,
            exploration=exploration,
        )
    else:
        presentation = {
            "title": "Econometrics Report",
            "presentation_facts": [],
            "critical_errors": [],
            "warnings": [],
            "cautions": [],
            "system_notes": [],
            "coefficient_interpretations": [],
            "causal_caution": "",
            "descriptive_stats": None,
            "statistical_tests": None,
            "statistical_evidence": None,
            "regression_table": None,
            "model_family_evidence": None,
            "exploration": None,
            "model_diagnostics": {},
            "model_quality": None,
        }
    if not isinstance(evidence_projection, Mapping):
        return {
            **presentation,
            "schemaVersion": 1,
            "status": "unavailable",
            "projectionId": "report:unavailable",
            "commitId": "UNAVAILABLE",
            "envelopeDigest": "UNAVAILABLE",
            "validationStatus": "unavailable",
            "validationSummary": {"status": "unavailable", "reasonCode": "REPORT_EVIDENCE_REQUIRED"},
            "provenance": {},
            "facts": [],
            "typedFacts": [],
            "critical_errors": list(presentation["critical_errors"]),
            "typed_critical_errors": [{"code": "REPORT_EVIDENCE_REQUIRED", "severity": "BLOCKER"}],
            **_projection_identity_fields({}),
        }
    projection = evidence_projection
    if projection.get("status") != "available":
        return {
            **presentation,
            "schemaVersion": 1,
            "status": str(projection.get("status", "unavailable")),
            "projectionId": str(projection.get("projectionId", "report:unavailable")),
            "commitId": str(projection.get("commitId", "UNAVAILABLE")),
            "envelopeDigest": str(projection.get("envelopeDigest", "UNAVAILABLE")),
            "validationStatus": str(projection.get("validationStatus", "unavailable")),
            "validationSummary": dict(projection.get("validationSummary", {})) if isinstance(projection.get("validationSummary"), Mapping) else {},
            "provenance": dict(projection.get("provenance", {})) if isinstance(projection.get("provenance"), Mapping) else {},
            "facts": [],
            "typedFacts": [],
            "critical_errors": list(presentation["critical_errors"]),
            "typed_critical_errors": [{"code": str(projection.get("reasonCode", "REPORT_EVIDENCE_UNAVAILABLE")), "severity": "BLOCKER"}],
            **_projection_identity_fields(projection),
        }
    facts = projection.get("facts")
    required_projection_fields = (
        "projectionId",
        "commitId",
        "envelopeDigest",
        "validationStatus",
    )
    identity_fields = (
        "actorRef",
        "projectRef",
        "sessionRef",
        "scopeRef",
        "runId",
        "modelRunId",
        "confirmationRef",
    )
    typed_projection = (
        projection.get("schemaVersion") == 1
        and all(isinstance(projection.get(key), str) and str(projection[key]).strip() for key in required_projection_fields)
        and isinstance(projection.get("provenance"), Mapping)
        and all(isinstance(projection.get(key), str) and str(projection[key]).strip() != "UNAVAILABLE" for key in identity_fields)
    )
    typed_facts = (
        isinstance(facts, list)
        and len(facts) <= 80
        and all(
            isinstance(fact, Mapping)
            and isinstance(fact.get("factId"), str)
            and isinstance(fact.get("statisticId"), str)
            and "value" in fact
            for fact in facts
        )
    )
    if not typed_projection or not typed_facts:
        return {
            **presentation,
            "schemaVersion": 1,
            "status": "blocked",
            "projectionId": str(projection.get("projectionId", "report:blocked")),
            "commitId": str(projection.get("commitId", "UNAVAILABLE")),
            "envelopeDigest": str(projection.get("envelopeDigest", "UNAVAILABLE")),
            "validationStatus": "unavailable",
            "validationSummary": {"status": "blocked", "reasonCode": "REPORT_EVIDENCE_FACTS_INVALID"},
            "provenance": {},
            "facts": [],
            "typedFacts": [],
            "critical_errors": list(presentation["critical_errors"]),
            "typed_critical_errors": [{"code": "REPORT_EVIDENCE_FACTS_INVALID", "severity": "BLOCKER"}],
            **_projection_identity_fields(projection),
        }
    return {
        **presentation,
        "schemaVersion": 1,
        "status": "available",
        "projectionId": str(projection.get("projectionId")),
        "commitId": str(projection.get("commitId")),
        "envelopeDigest": str(projection.get("envelopeDigest")),
        "validationStatus": str(projection.get("validationStatus", "unavailable")),
        "validationSummary": dict(projection.get("validationSummary", {})) if isinstance(projection.get("validationSummary"), Mapping) else {},
        "provenance": dict(projection.get("provenance", {})) if isinstance(projection.get("provenance"), Mapping) else {},
        "facts": [dict(fact) for fact in facts],
        "typedFacts": [dict(fact) for fact in facts],
        "critical_errors": list(presentation["critical_errors"]),
        "typed_critical_errors": [],
        **_projection_identity_fields(projection),
    }


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
    *,
    owner: object | None = None,
    request_identity: ReportEvidenceRequestIdentityV1 | None = None,
    artifact_admission: "ArtifactAdmissionV1" | None = None,
) -> dict[str, object]:
    """Expose a bounded report view only after exact C0 owner admission."""

    from .evidence.consumer_adapters import (
        EvidenceProjectionError,
        EvidenceProjectionV1,
        default_projection_registry,
    )
    from .evidence.contracts import ArtifactAdmissionV1
    from .services.results_service import ServerOwnedReportEvidencePersistenceV1

    raw_artifact_id = getattr(projection, "artifact_ref", None)
    artifact_id = raw_artifact_id if type(raw_artifact_id) is str and raw_artifact_id else "unknown-artifact"

    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        return _unavailable_report_evidence(
            artifact_id=artifact_id,
            artifact_type="unknown",
            reason_code="EVIDENCE_OWNER_CAPABILITY_REQUIRED",
        )

    try:
        owner._require_report_authority()
        bound_identity = owner._require_report_request_identity(request_identity)
        canonical_artifact = owner._canonical_report_artifact()
        if type(artifact_admission) is not ArtifactAdmissionV1 or artifact_admission is not canonical_artifact:
            raise EvidenceProjectionError(
                "EVIDENCE_PROVENANCE_REQUIRED",
                "Report provenance must be the exact owner-admitted artifact",
            )
        if type(projection) is not EvidenceProjectionV1:
            raise EvidenceProjectionError(
                "EVIDENCE_PROJECTION_INVALID",
                "Report projection must be an admitted typed projection",
            )
        expected_projection = default_projection_registry().project(
            owner._canonical_record,  # type: ignore[attr-defined]
            consumer_id="report",
            destination="local",
        )
        if projection.to_dict() != expected_projection.to_dict():
            raise EvidenceProjectionError(
                "EVIDENCE_PROJECTION_CANONICAL_MISMATCH",
                "Report projection is not the owner-admitted canonical projection",
            )
    except EvidenceProjectionError as exc:
        return _unavailable_report_evidence(
            artifact_id=artifact_id,
            artifact_type="unknown",
            reason_code=exc.code,
            status="blocked",
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return _unavailable_report_evidence(
            artifact_id=artifact_id,
            artifact_type="unknown",
            reason_code="EVIDENCE_PROJECTION_INVALID",
            status="blocked",
        )

    request_identity = bound_identity
    if (
        artifact_admission.artifact_id != projection.artifact_ref
        or artifact_admission.envelope_digest != projection.envelope_digest
        or dict(artifact_admission.envelope.result_identity) != dict(projection.result_identity)
    ):
        return _unavailable_report_evidence(
            artifact_id=projection.artifact_ref,
            artifact_type=artifact_admission.artifact_type,
            reason_code="EVIDENCE_PROVENANCE_MISMATCH",
            request_identity=request_identity,
        )
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
        "schemaVersion": 1,
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
        "validationStatus": str(
            projection.validation_summary.get("requirement_status", "unavailable")
        ),
        "validationSummary": dict(projection.validation_summary),
        "facts": facts,
        "sections": sections,
        "provenance": {
            "artifactRef": projection.artifact_ref,
            "artifactType": artifact_admission.artifact_type,
            "scopeRef": artifact_admission.scope_ref,
            "contentHash": artifact_admission.content_hash,
            "sourceRef": artifact_admission.source_ref,
            "validatorRef": (
                artifact_admission.validator_ref.to_dict()
                if hasattr(artifact_admission.validator_ref, "to_dict")
                else artifact_admission.validator_ref
            ),
            "executionRef": artifact_admission.execution_ref,
            "contractDigest": artifact_admission.contract_digest,
            "commitId": projection.commit_id,
            "envelopeRef": projection.envelope_ref,
            "envelopeDigest": projection.envelope_digest,
            "lineageRefs": list(projection.lineage_refs),
            "projectionRef": projection.projection_ref.to_dict(),
            "resultIdentity": dict(projection.result_identity),
        },
    }
    if projection.audit.restriction_reason:
        view["reasonCode"] = projection.audit.restriction_reason
    view.update(
        {
            "actorRef": request_identity.actor_ref if request_identity else "UNAVAILABLE",
            "projectRef": request_identity.project_ref if request_identity else "UNAVAILABLE",
            "sessionRef": request_identity.session_ref if request_identity else "UNAVAILABLE",
            "scopeRef": request_identity.scope_ref if request_identity else "UNAVAILABLE",
            "runId": request_identity.run_id if request_identity else "UNAVAILABLE",
            "modelRunId": request_identity.model_run_id if request_identity else "UNAVAILABLE",
            "confirmationRef": request_identity.confirmation_ref if request_identity else "UNAVAILABLE",
        }
    )
    from .report_export import report_projection_digest

    view["projectionDigest"] = report_projection_digest(view)
    return view


def _unavailable_report_evidence(
    *,
    artifact_id: str,
    artifact_type: str,
    reason_code: str,
    status: str = "unavailable",
    request_identity: ReportEvidenceRequestIdentityV1 | None = None,
) -> dict[str, object]:
    """Return a typed empty view for an artifact that did not pass admission.

    This is deliberately a complete report-view shape.  Consumers can render
    the failure without having to inspect the indexed artifact or its result,
    and the result payload never crosses this boundary.
    """

    safe_artifact_id = artifact_id if artifact_id else "UNAVAILABLE"
    safe_artifact_type = artifact_type if artifact_type else "unknown"
    return {
        "schemaVersion": 1,
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
        "validationStatus": "unavailable",
        "validationSummary": {
            "status": "unavailable",
            "reasonCode": reason_code,
        },
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
            "artifactRef": safe_artifact_id,
            "artifactId": safe_artifact_id,
            "artifactType": safe_artifact_type,
            "scopeRef": request_identity.scope_ref if request_identity else "UNAVAILABLE",
            "contentHash": "UNAVAILABLE",
            "sourceRef": "UNAVAILABLE",
            "validatorRef": "UNAVAILABLE",
            "executionRef": "UNAVAILABLE",
            "contractDigest": "UNAVAILABLE",
            "commitId": "UNAVAILABLE",
            "envelopeRef": "UNAVAILABLE",
            "envelopeDigest": "UNAVAILABLE",
            "lineageRefs": [],
            "projectionRef": {},
            "resultIdentity": {},
            "indexed": True,
            "admissionStatus": status,
        },
        "actorRef": request_identity.actor_ref if request_identity else "UNAVAILABLE",
        "projectRef": request_identity.project_ref if request_identity else "UNAVAILABLE",
        "sessionRef": request_identity.session_ref if request_identity else "UNAVAILABLE",
        "scopeRef": request_identity.scope_ref if request_identity else "UNAVAILABLE",
        "runId": request_identity.run_id if request_identity else "UNAVAILABLE",
        "modelRunId": request_identity.model_run_id if request_identity else "UNAVAILABLE",
        "confirmationRef": request_identity.confirmation_ref if request_identity else "UNAVAILABLE",
    }


def _nested_evidence_record(value: Mapping[str, object]) -> Mapping[str, object]:
    if "evidence" not in value:
        return {}
    nested = value["evidence"]
    if not isinstance(nested, Mapping):
        raise EvidenceProjectionError(
            "EVIDENCE_WIRE_FIELD_INVALID",
            "the nested evidence record must be an object",
        )
    return nested


def _strict_index_field(
    outer: Mapping[str, object],
    nested: Mapping[str, object],
    keys: Sequence[str],
    *,
    invalid_code: str = "EVIDENCE_WIRE_FIELD_INVALID",
    conflict_code: str = "EVIDENCE_WIRE_FIELD_CONFLICT",
) -> object | None:
    """Resolve aliases without hiding a present invalid or conflicting value."""

    observed: list[object] = []
    for source in (outer, nested):
        for key in keys:
            if key not in source:
                continue
            candidate = source[key]
            if candidate is None or (
                type(candidate) is str and not candidate.strip()
            ) or (
                isinstance(candidate, Mapping) and not candidate
            ):
                raise EvidenceProjectionError(
                    invalid_code,
                    f"indexed {key} is present but invalid",
                )
            observed.append(candidate)
    if not observed:
        return None
    first = observed[0]
    if any(candidate != first for candidate in observed[1:]):
        raise EvidenceProjectionError(
            conflict_code,
            "outer and nested indexed evidence fields disagree",
        )
    return first


def _evidence_wire_fields(
    value: Mapping[str, object],
) -> tuple[object | None, object | None, object | None, object | None, object | None]:
    """Read canonical wire fields with strict outer/nested presence semantics."""

    nested_record = _nested_evidence_record(value)
    return (
        _strict_index_field(
            value,
            nested_record,
            ("evidence_commit_binding", "commit_binding", "binding"),
        ),
        _strict_index_field(
            value,
            nested_record,
            ("evidence_envelope", "envelope"),
        ),
        _strict_index_field(
            value,
            nested_record,
            ("evidence_envelope_ref", "envelope_ref"),
        ),
        _strict_index_field(
            value,
            nested_record,
            ("evidence_sensitivity", "sensitivity"),
        ),
        _strict_index_field(
            value,
            nested_record,
            ("evidence_artifact_ref", "artifact_ref"),
        ),
    )


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
    object | None,
    object | None,
    object | None,
]:
    """Read index-owned identity fields used to bind a canonical commit.

    These fields are intentionally read from the index row, not synthesized
    from the result payload.  The payload may help confirm source identity,
    but it cannot supply the authoritative artifact admission or content hash.
    """

    nested_record = _nested_evidence_record(value)

    def strict(*keys: str, invalid_code: str, conflict_code: str) -> object | None:
        return _strict_index_field(
            value,
            nested_record,
            keys,
            invalid_code=invalid_code,
            conflict_code=conflict_code,
        )

    indexed_content_hash = strict(
        "evidence_content_hash",
        "content_hash",
        "evidence_artifact_content_hash",
        "artifact_content_hash",
        invalid_code="EVIDENCE_ARTIFACT_CONTENT_HASH_REQUIRED",
        conflict_code="EVIDENCE_ARTIFACT_CONTENT_HASH_MISMATCH",
    )

    return (
        strict("actor_ref", "evidence_actor_ref", invalid_code="EVIDENCE_ACTOR_REF_REQUIRED", conflict_code="EVIDENCE_OWNER_CONTEXT_MISMATCH"),
        strict("evidence_commit_ref", "commit_ref", "evidence_commit_id", "commit_id", invalid_code="EVIDENCE_COMMIT_REF_REQUIRED", conflict_code="EVIDENCE_COMMIT_REF_MISMATCH"),
        strict("evidence_artifact_admission_ref", "artifact_admission_ref", invalid_code="EVIDENCE_ARTIFACT_ADMISSION_REF_REQUIRED", conflict_code="EVIDENCE_ARTIFACT_ADMISSION_MISMATCH"),
        strict("project_ref", "evidence_project_ref", invalid_code="EVIDENCE_PROJECT_REF_REQUIRED", conflict_code="EVIDENCE_OWNER_CONTEXT_MISMATCH"),
        strict("session_ref", "evidence_session_ref", invalid_code="EVIDENCE_SESSION_REF_REQUIRED", conflict_code="EVIDENCE_OWNER_CONTEXT_MISMATCH"),
        strict("scope_ref", "evidence_scope_ref", invalid_code="EVIDENCE_SCOPE_REF_REQUIRED", conflict_code="EVIDENCE_OWNER_CONTEXT_MISMATCH"),
        strict("confirmation_ref", "evidence_confirmation_ref", invalid_code="EVIDENCE_CONFIRMATION_REF_REQUIRED", conflict_code="EVIDENCE_OWNER_CONTEXT_MISMATCH"),
        strict("run_id", "evidence_run_id", invalid_code="EVIDENCE_RUN_ID_REQUIRED", conflict_code="EVIDENCE_RUN_ID_MISMATCH"),
        strict("model_run_id", "evidence_model_run_id", invalid_code="EVIDENCE_MODEL_RUN_ID_REQUIRED", conflict_code="EVIDENCE_RUN_ID_MISMATCH"),
        strict("evidence_run_id", invalid_code="EVIDENCE_RUN_ID_REQUIRED", conflict_code="EVIDENCE_RUN_ID_MISMATCH"),
        strict("evidence_model_run_id", invalid_code="EVIDENCE_MODEL_RUN_ID_REQUIRED", conflict_code="EVIDENCE_RUN_ID_MISMATCH"),
        indexed_content_hash,
        False,
        strict("sha256", "artifact_sha256", invalid_code="EVIDENCE_ARTIFACT_FILE_HASH_REQUIRED", conflict_code="EVIDENCE_ARTIFACT_FILE_HASH_MISMATCH"),
        strict("evidence_artifact_ref", "artifact_ref", invalid_code="EVIDENCE_ARTIFACT_REF_REQUIRED", conflict_code="EVIDENCE_ARTIFACT_ID_MISMATCH"),
    )


def build_indexed_report_evidence(
    indexed_artifact: Mapping[str, object],
    artifact_payload: object | None = None,
    *,
    artifact_content_sha256: str | None = None,
    authoritative_persistence: object | None = None,
    request_identity: ReportEvidenceRequestIdentityV1 | None = None,
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
    if artifact_type == "unknown":
        return _unavailable_report_evidence(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            reason_code="EVIDENCE_ARTIFACT_TYPE_REQUIRED",
        )

    # The artifact payload is deliberately not a source for identity, binding,
    # envelope, or facts.  It is an untrusted compatibility input retained in
    # the function signature so old callers fail closed through the same gate.
    try:
        binding_raw, envelope_raw, *_ = _evidence_wire_fields(indexed_artifact)

        (
            actor_ref_raw,
            commit_ref_raw,
            admission_ref_raw,
            project_ref_raw,
            session_ref_raw,
            scope_ref_raw,
            confirmation_ref_raw,
            run_id_raw,
            model_run_id_raw,
            evidence_run_id_raw,
            evidence_model_run_id_raw,
            indexed_content_hash_raw,
            indexed_content_hash_conflict,
            indexed_raw_sha256,
            indexed_artifact_ref_raw,
        ) = _evidence_identity_fields(indexed_artifact)
    except EvidenceProjectionError as exc:
        return _unavailable_report_evidence(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            reason_code=exc.code,
            status="blocked",
        )

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
    from .evidence.consumer_adapters import default_projection_registry
    from .services.results_service import ServerOwnedReportEvidencePersistenceV1

    try:
        def required_text(value: object | None, reason_code: str) -> str:
            if not isinstance(value, str) or not value.strip():
                raise EvidenceProjectionError(reason_code, "authoritative indexed identity is required")
            return value

        actor_ref = required_text(actor_ref_raw, "EVIDENCE_ACTOR_REF_REQUIRED")
        commit_ref = required_text(commit_ref_raw, "EVIDENCE_COMMIT_REF_REQUIRED")
        admission_ref = required_text(
            admission_ref_raw,
            "EVIDENCE_ARTIFACT_ADMISSION_REF_REQUIRED",
        )
        project_ref = required_text(project_ref_raw, "EVIDENCE_PROJECT_REF_REQUIRED")
        session_ref = required_text(session_ref_raw, "EVIDENCE_SESSION_REF_REQUIRED")
        scope_ref = required_text(scope_ref_raw, "EVIDENCE_SCOPE_REF_REQUIRED")
        confirmation_ref = required_text(
            confirmation_ref_raw,
            "EVIDENCE_CONFIRMATION_REF_REQUIRED",
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
        indexed_file_sha256 = required_text(
            indexed_raw_sha256,
            "EVIDENCE_ARTIFACT_FILE_HASH_REQUIRED",
        )
        artifact_file_sha256 = required_text(
            artifact_content_sha256,
            "EVIDENCE_ARTIFACT_FILE_HASH_REQUIRED",
        )
        if indexed_file_sha256 != artifact_file_sha256:
            raise EvidenceProjectionError(
                "EVIDENCE_ARTIFACT_FILE_HASH_MISMATCH",
                "indexed artifact file hash differs from persisted content",
            )

        nested_index = _nested_evidence_record(indexed_artifact)

        def required_index_provenance(*keys: str, reason_code: str) -> object:
            candidate = _strict_index_field(
                indexed_artifact,
                nested_index,
                keys,
                invalid_code=reason_code,
                conflict_code="EVIDENCE_PROVENANCE_CONFLICT",
            )
            if candidate is None:
                raise EvidenceProjectionError(
                    reason_code,
                    "canonical indexed artifact provenance is required",
                )
            return candidate

        source_ref = required_text(
            required_index_provenance(
                "source_ref",
                "evidence_source_ref",
                reason_code="EVIDENCE_SOURCE_REF_REQUIRED",
            ),
            "EVIDENCE_SOURCE_REF_REQUIRED",
        )
        validator_ref = required_index_provenance(
            "validator_ref",
            "evidence_validator_ref",
            reason_code="EVIDENCE_VALIDATOR_REF_REQUIRED",
        )
        if type(validator_ref) not in {str, dict}:
            raise EvidenceProjectionError(
                "EVIDENCE_VALIDATOR_REF_REQUIRED",
                "canonical validator reference is required",
            )
        execution_ref = required_text(
            required_index_provenance(
                "execution_ref",
                "evidence_execution_ref",
                reason_code="EVIDENCE_EXECUTION_REF_REQUIRED",
            ),
            "EVIDENCE_EXECUTION_REF_REQUIRED",
        )
        contract_digest = required_text(
            required_index_provenance(
                "contract_digest",
                "evidence_contract_digest",
                reason_code="EVIDENCE_CONTRACT_DIGEST_REQUIRED",
            ),
            "EVIDENCE_CONTRACT_DIGEST_REQUIRED",
        )

        run_id = required_text(run_id_raw, "EVIDENCE_RUN_ID_REQUIRED")
        model_run_id = required_text(model_run_id_raw, "EVIDENCE_MODEL_RUN_ID_REQUIRED")
        if request_identity is not None and (
            actor_ref != request_identity.actor_ref
            or project_ref != request_identity.project_ref
            or session_ref != request_identity.session_ref
            or scope_ref != request_identity.scope_ref
            or run_id != request_identity.run_id
            or model_run_id != request_identity.model_run_id
            or confirmation_ref != request_identity.confirmation_ref
        ):
            raise EvidenceProjectionError(
                "EVIDENCE_OWNER_CONTEXT_MISMATCH",
                "indexed evidence identity differs from server-observed request identity",
            )
        for name, observed, expected in (
            ("evidence_run_id", evidence_run_id_raw, run_id),
            ("evidence_model_run_id", evidence_model_run_id_raw, model_run_id),
        ):
            if observed is not None and observed != expected:
                raise EvidenceProjectionError(
                    "EVIDENCE_RUN_ID_MISMATCH",
                    f"indexed {name} differs from the authoritative run identity",
                    )

        if type(authoritative_persistence) is not ServerOwnedReportEvidencePersistenceV1:
            raise EvidenceProjectionError(
                "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
                "Report evidence requires the server-owned persistence capability",
            )
        if request_identity is not None:
            authoritative_persistence._require_report_request_identity(request_identity)

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
            actor_ref=actor_ref,
            project_ref=project_ref,
            session_ref=session_ref,
            scope_ref=scope_ref,
            artifact_id=indexed_artifact_ref,
            run_id=run_id,
            model_run_id=model_run_id,
            content_hash=indexed_content_hash,
            admission_ref=admission_ref,
            confirmation_ref=confirmation_ref,
            artifact_file_sha256=artifact_file_sha256,
            envelope_digest=(candidate_binding.envelope_digest if candidate_binding is not None else None),
        )
        canonical_artifact = authoritative_persistence._canonical_report_artifact()
        canonical_validator_ref = (
            canonical_artifact.validator_ref.to_dict()
            if hasattr(canonical_artifact.validator_ref, "to_dict")
            else canonical_artifact.validator_ref
        )
        for name, observed, expected, reason_code in (
            ("artifact_type", artifact_type, canonical_artifact.artifact_type, "EVIDENCE_ARTIFACT_TYPE_MISMATCH"),
            ("source_ref", source_ref, canonical_artifact.source_ref, "EVIDENCE_SOURCE_REF_MISMATCH"),
            ("validator_ref", validator_ref, canonical_validator_ref, "EVIDENCE_VALIDATOR_REF_MISMATCH"),
            ("execution_ref", execution_ref, canonical_artifact.execution_ref, "EVIDENCE_EXECUTION_REF_MISMATCH"),
            ("contract_digest", contract_digest, canonical_artifact.contract_digest, "EVIDENCE_CONTRACT_DIGEST_MISMATCH"),
        ):
            if observed != expected:
                raise EvidenceProjectionError(
                    reason_code,
                    f"indexed {name} differs from the server-owned artifact admission",
                )
        projection = default_projection_registry().project(
            persisted_record,
            consumer_id="report",
            destination="local",
        )
        canonical_view = build_persisted_evidence_report_view(
            projection,
            owner=authoritative_persistence,
            artifact_admission=authoritative_persistence._canonical_report_artifact(),
        )
        # Some historical index/payload writers copied the projected facts and
        # digest into their outer records.  If those optional fields are
        # present, they are assertions about the canonical server-owned view,
        # never alternate sources of facts.  Reject even a synchronized forged
        # pair instead of allowing the outer records to shadow the envelope.
        for source_name, source in (
            ("index", indexed_artifact),
            ("payload", artifact_payload if isinstance(artifact_payload, Mapping) else None),
        ):
            if source is None:
                continue
            for field, reason_code in (
                ("facts", "REPORT_EVIDENCE_FACTS_MISMATCH"),
                ("projectionDigest", "REPORT_EVIDENCE_PROJECTION_DIGEST_MISMATCH"),
            ):
                if field in source and source[field] != canonical_view.get(field):
                    raise EvidenceProjectionError(
                        reason_code,
                        f"{source_name} {field} differs from the canonical server-owned evidence view",
                    )
        return canonical_view
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
        "schemaVersion": 1,
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
        "validationStatus": "unavailable",
        "validationSummary": {
            "status": "unavailable",
            "reasonCode": "REPORT_EVIDENCE_BUNDLE_IDENTITY_UNBOUND",
        },
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
        "actorRef": first.get("actorRef", "UNAVAILABLE"),
        "projectRef": first.get("projectRef", "UNAVAILABLE"),
        "sessionRef": first.get("sessionRef", "UNAVAILABLE"),
        "scopeRef": first.get("scopeRef", "UNAVAILABLE"),
        "runId": first.get("runId", "UNAVAILABLE"),
        "modelRunId": first.get("modelRunId", "UNAVAILABLE"),
        "confirmationRef": first.get("confirmationRef", "UNAVAILABLE"),
    }
    return result
