from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..context import ModelingContext, RunEnv


def _report_evidence_admission(ctx: ModelingContext) -> tuple[object, object] | None:
    """Extract the exact C0 Report pair carried by the stage context."""

    from ...report_export import EvidenceProjectionV1, LocalReportCollectionV1
    from ...services.results_service import ServerOwnedReportEvidencePersistenceV1

    owner = ctx.artifacts.get("_report_evidence_owner")
    projection = ctx.artifacts.get("_report_evidence_projection")
    if (
        type(owner) is not ServerOwnedReportEvidencePersistenceV1
        or type(projection) not in (EvidenceProjectionV1, LocalReportCollectionV1)
        or getattr(projection, "_owner", None) is not owner
    ):
        return None
    try:
        owner._require_report_authority()  # type: ignore[attr-defined]
        projection._assert_server_owned()
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return None
    return owner, projection


def _xlsx_export_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialize structured public-result fields before handing them to XLSX.

    The result contract legitimately carries lists such as an LMM confidence
    interval.  Excel cells accept scalar values only; this conversion is for
    the export view and never mutates the authoritative model result packet.
    """

    safe_rows: list[dict[str, Any]] = []
    for row in rows:
        safe_rows.append(
            {
                key: (
                    json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    if isinstance(value, (dict, list, tuple))
                    else value
                )
                for key, value in row.items()
            }
        )
    return safe_rows


def _refresh_artifact_checksum(run_root, artifact_id: str, path) -> None:
    """Keep an artifact index hash correct after serve-time metadata finalization."""

    from ...artifacts import read_json, sha256_file, write_json

    index_path = run_root / "artifacts_index.json"
    try:
        index = read_json(index_path)
        records = index.get("artifacts", [])
        changed = False
        digest = sha256_file(path)
        for record in records:
            if record.get("artifact_id") == artifact_id:
                record["sha256"] = digest
                changed = True
                break
        if changed:
            write_json(index_path, index)
    except (OSError, ValueError, KeyError):
        # The report itself remains authoritative; a malformed index is handled
        # by the existing artifact/preview contract rather than failing a run.
        return


def _admit_report_evidence_from_factory(
    ctx: ModelingContext,
    *,
    run_root: Path,
    run_id: str,
    model_run_id: str,
    primary_model_type: str,
    regression_table: dict[str, object],
    issue_dicts: object,
    report_fields: dict[str, object] | None = None,
    diagnostic_summary: dict[str, object] | None = None,
) -> tuple[object, object] | None:
    """Create the per-run C0 owner at the real Report production boundary.

    The factory is host-installed.  This stage may provide bounded producer
    fields and persist an immutable evidence artifact, but it cannot choose a
    registry, authority, scope, or identity itself.
    """

    from ...report_export import LocalReportCollectionV1
    from ...services.report_evidence_owner_factory import (
        ServerOwnedReportEvidenceOwnerFactoryV1,
        register_report_evidence_artifact,
    )
    from ...services.results_service import (
        ServerOwnedReportEvidencePersistenceV1,
        register_report_evidence_owner,
    )
    from ...evidence.consumer_adapters import EvidenceProjectionError

    # A legacy context value is caller-controlled and is not a production
    # receipt.  Reject it explicitly instead of silently upgrading or
    # ignoring a locally fabricated confirmation at this host boundary.
    if ctx.artifacts.get("_report_confirmation_ref") is not None:
        raise EvidenceProjectionError(
            "EVIDENCE_PRODUCTION_RECEIPT_REQUIRED",
            "confirmation_ref is not production authority; Report admission requires the host-issued production receipt seam",
        )

    factory_context_bound = "_report_evidence_owner_factory" in ctx.artifacts
    factory = ctx.artifacts.get("_report_evidence_owner_factory")
    if not factory_context_bound:
        # Direct stage callers from the compatibility surface do not build a
        # full orchestrator context.  Keep that path tied to the canonical app
        # only; production workflow calls carry the selected app's factory in
        # the context above.
        from ...app import app as workbench_app

        factory = getattr(workbench_app.state, "report_evidence_owner_factory", None)
    if type(factory) is not ServerOwnedReportEvidenceOwnerFactoryV1:
        return None
    if type(regression_table) is not dict:
        raise TypeError("Report evidence factory requires a bounded regression table")
    upload_hash = ctx.artifacts.get("_upload_hash")
    if type(upload_hash) is not str:
        raise ValueError("Report evidence factory requires the upload SHA-256")
    from ...services.report_evidence_owner_factory import (
        build_workflow_report_evidence_envelope,
    )

    if report_fields is None:
        # Compatibility calls without host producer sources remain numeric-only.
        envelope = build_workflow_report_evidence_envelope(
            run_id=run_id, model_run_id=model_run_id, upload_hash=upload_hash,
            primary_model_type=primary_model_type, regression_table=regression_table,
            issue_dicts=issue_dicts,
        )
    else:
        if run_root != factory._canonical_project_root / "runs" / run_id:
            raise EvidenceProjectionError("EVIDENCE_SCOPE_ROOT_MISMATCH", "Producer run root is outside factory scope")
        model_artifact_ids = []
        for model in regression_table["models"]:
            if model.get("model_type") == "linear_mixed_effects":
                from ..packs.linear_mixed_effects.runner import _TERMINAL_RESULT_ARTIFACT_ID

                model_artifact_ids.append(_TERMINAL_RESULT_ARTIFACT_ID)
            else:
                model_artifact_ids.append(model["id"])
        envelope = factory.prepare_report_evidence_envelope(
            run_id=run_id, model_run_id=model_run_id, upload_hash=upload_hash,
            primary_model_type=primary_model_type, regression_table=regression_table,
            issue_dicts=issue_dicts,
            model_artifact_ids=model_artifact_ids,
            report_fields=report_fields, diagnostic_summary=diagnostic_summary or {},
        )
    evidence_path = run_root / "report_evidence.json"
    # Compute the canonical bytes up front, but do not write a project file
    # until the host has created the exact C0 owner for this run.
    artifact_file_sha256 = factory.report_evidence_file_sha256(envelope)
    production_receipt = factory.issue_production_receipt(
        run_id=run_id,
        model_run_id=model_run_id,
        upload_hash=upload_hash,
    )
    owner = factory.create_for_run(
        run_id=run_id,
        model_run_id=model_run_id,
        production_receipt=production_receipt,
        envelope=envelope,
        artifact_file_sha256=artifact_file_sha256,
    )
    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        raise TypeError("Report owner factory returned an invalid capability")
    factory.write_report_evidence_file(
        owner=owner,
        production_receipt=production_receipt,
        envelope=envelope,
    )
    register_report_evidence_owner(owner)
    register_report_evidence_artifact(
        owner,
        run_root=run_root,
        path=evidence_path,
        inputs=[f"model_results/{model_run_id}.json"],
    )
    projection = owner.issue_complete_report_collection()
    if type(projection) is not LocalReportCollectionV1:
        raise TypeError("Report owner did not issue a typed projection")
    ctx.artifacts["_report_evidence_owner"] = owner
    ctx.artifacts["_report_evidence_projection"] = projection
    return owner, projection


class ReportStage:
    """Assemble the report facts/descriptive-stats/variable-importance, build
    the diagnostic summary, render the retained HTML report, flush the
    lineage recorder, and write the final ``completed`` manifest.

    Extracted from the tail of orchestrator._run_workflow (from the
    ``descriptive_stats`` build through ``build_report_view_model`` rendering,
    ``_safe_flush_recorder(..., context="success")`` and the closing
    ``completed`` manifest write/return) as part of the V1.5.4 engine
    decomposition. Presentation exports are deliberately on-demand at the
    Report page; a normal Run retains HTML and evidence artifacts only.

    Report lineage / diagnostic-summary inputs read the working modeling
    handle id via the already-bridged ``model_results``/``coercion_actions``
    etc.; the goldens lock the manifest status and per-artifact ``inputs``.
    """

    name = "report"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        from ... import orchestrator as _orch
        from ...orchestrator import (
            _build_descriptive_stats,
            _build_model_routing_summary,
            _build_variable_importance,
            _lineage,
            _mice_imputation_fact,
            _safe_flush_recorder,
            _write_manifest,
        )
        from ...artifacts import read_json, register_artifact, write_json
        from ...domain import GuardrailIssue, Severity

        build_diagnostic_summary = _orch.build_diagnostic_summary
        from ...diagnostic_summary import finalize_diagnostic_summary
        from ...report_view_model import (
            build_server_owned_ols_validation_receipt,
            build_regression_table,
        )
        # The normal run-stage artifact retains the historical presentation
        # semantics.  It is not the Report-page writer boundary: exports on
        # that page require a committed server-owned projection.
        from ...reporting import render_legacy_html_report

        run_root = env.run_root
        run_id = env.run_id
        _recorder = env.recorder

        cleaned = ctx.artifacts["_cleaned"]
        categorical_vars = ctx.artifacts["_categorical_vars"]
        model_results = ctx.artifacts["_model_results"]
        normalized_y = ctx.artifacts["_normalized_y"]
        normalized_x = ctx.artifacts["_normalized_x"]
        poisson_x = ctx.artifacts["_poisson_x"]
        profile = ctx.artifacts["_profile"]
        routing = ctx.artifacts["_routing"]
        dropped_vars = ctx.artifacts["_dropped_vars"]
        reliability_info = ctx.artifacts["_reliability_info"]
        effective_exposure_col = ctx.artifacts["_effective_exposure_col"]
        imputation_summary = ctx.artifacts["_imputation_summary"]
        diagnostic_artifacts = ctx.artifacts["_diagnostic_artifacts"]
        statistical_tests = ctx.artifacts["_statistical_tests"]
        statistical_test_summaries = ctx.artifacts["_statistical_test_summaries"]
        claims = ctx.artifacts["_claims"]
        issue_dicts = ctx.artifacts["_issue_dicts"]
        coercion_actions = ctx.artifacts["_coercion_actions"]
        exposure_col = ctx.exposure_col
        y_type = ctx.y_type
        variable_roles = ctx.roles
        data_detected_y_type = ctx.artifacts["_data_detected_y_type"]
        input_files = ctx.artifacts["_input_files"]
        mode = ctx.artifacts["_mode"]
        y = ctx.artifacts["_y"]
        x = ctx.artifacts["_x"]
        model_type = ctx.artifacts["_model_type"]
        started_at = ctx.artifacts["_started_at"]

        descriptive_stats = _build_descriptive_stats(cleaned, categorical_vars=categorical_vars)
        variable_labels = {
            str(row["column"]): row.get("label", row["column"])
            for row in descriptive_stats
            if isinstance(row, dict) and row.get("column") is not None
        }
        fitted_models = ctx.artifacts.get("_fitted_models", {})
        validation_receipts = {}
        if isinstance(fitted_models, dict):
            for model_id, model_result in model_results:
                fitted = fitted_models.get(model_id)
                receipt = build_server_owned_ols_validation_receipt(
                    run_id=run_id,
                    model_id=str(model_id),
                    model_result=model_result,
                    fitted=fitted,
                    input_digest=ctx.artifacts.get("_upload_hash"),
                )
                if receipt is not None:
                    validation_receipts[str(model_id)] = receipt
        regression_table = build_regression_table(
            model_results,
            variable_labels=variable_labels,
            validation_receipts=validation_receipts,
        )
        model_family_display = {
            "ols": "OLS",
            "ols_robust": "OLS (robust SE)",
            "logit": "Logit",
            "ordinal_logit": "Ordinal logit",
            "multinomial_logit": "Multinomial logit",
            "survival_cox": "Survival / Cox",
            "quantile_regression": "Quantile regression",
            "poisson": "Poisson",
            "poisson_rate": "Poisson (rate model)",
            "panel_ols": "Panel OLS",
        }
        primary_type = model_results[0][1].get("model_type", "ols") if model_results else "ols"
        family_evidence: dict[str, Any] | None = None
        family_evidence_path = {
            "ordinal_logit": run_root / "model_results" / "diagnostics_ordinal_logit_1.json",
            "multinomial_logit": run_root / "model_results" / "diagnostics_multinomial_logit_1.json",
            "survival_cox": run_root / "survival" / "evidence.json",
        }.get(primary_type)
        if family_evidence_path is not None and family_evidence_path.is_file():
            family_evidence = read_json(family_evidence_path)
        elif primary_type == "quantile_regression" and model_results:
            family_evidence = {
                "contract": "workbench.quantile_regression.result.v1",
                "quantiles": model_results[0][1].get("quantiles", []),
                "fits": model_results[0][1].get("fits", {}),
                "bootstrap": model_results[0][1].get("bootstrap", {}),
                "cross_quantile_comparisons": model_results[0][1].get("cross_quantile_comparisons", []),
            }
        if effective_exposure_col:
            facts = [
                f"Model: Poisson rate model with log({effective_exposure_col}) as offset",
                f"y = {normalized_y};  X = {', '.join(poisson_x)}",
                f"Exposure/offset: log({effective_exposure_col}), coefficient fixed at 1",
                f"Model formula: {normalized_y} ~ {' + '.join(poisson_x)} + offset(log({effective_exposure_col}))",
                f"Rows used: {profile['row_count']} · Columns: {profile['column_count']}",
                f"Dataset kind: {routing['kind']}",
            ]
        else:
            facts = [
                f"Model: {model_family_display.get(primary_type, primary_type)}",
            ]
            facts.extend([
                f"y = {normalized_y};  X = {', '.join(normalized_x)}",
                f"Rows used: {profile['row_count']} · Columns: {profile['column_count']}",
                f"Dataset kind: {routing['kind']}",
            ])
        if dropped_vars:
            facts.append(
                "Variables dropped from model: "
                + "; ".join(f"{e['variable']} ({e['reason_display']})" for e in dropped_vars)
            )
        if categorical_vars:
            facts.append(f"Categorical variable(s): {', '.join(sorted(categorical_vars))} (dummy-coded in model)")
        if reliability_info:
            facts.append(
                f"Model reliability: {reliability_info['reliability']} "
                f"(positive rate: {reliability_info['positive_rate']:.1%}, "
                f"events per predictor: {reliability_info['events_per_predictor']:.1f})"
            )
        if imputation_summary and imputation_summary.get("status") == "completed":
            facts.append(_mice_imputation_fact(imputation_summary))
        if primary_type in ("poisson", "poisson_rate"):
            poisson_diag = diagnostic_artifacts.get("poisson_1", {})
            overdisp = poisson_diag.get("overdispersion", {})
            if isinstance(overdisp, dict):
                zero_rate = overdisp.get("zero_rate")
                if zero_rate is not None:
                    facts.append(f"Zero rate in outcome: {float(zero_rate):.1%}")
                zih = overdisp.get("zero_inflation_hint")
                if zih:
                    facts.append(zih)
                ow = overdisp.get("warning")
                if ow:
                    facts.append(f"Overdispersion: {ow}")
                else:
                    od_ratio = overdisp.get("overdispersion_ratio")
                    if od_ratio is not None:
                        facts.append(f"Overdispersion: not detected (ratio={float(od_ratio):.2f})")
        variable_importance = _build_variable_importance(
            statistical_tests, normalized_y, normalized_x, model_results,
            cleaned, primary_type, exposure_col=effective_exposure_col,
            categorical_vars=categorical_vars,
        )
        facts.append(
            "Note: variable importance is based on marginal (univariate) association "
            "with the outcome and may differ from multivariable regression results "
            "after controlling for other predictors."
        )
        report = {
            "title": "Workbench Report",
            "facts": facts,
            "claims": claims,
            "warnings": issue_dicts,
            "descriptive_stats": descriptive_stats,
            "statistical_tests": statistical_test_summaries,
            "statistical_evidence": statistical_tests.get("evidence"),
            "regression_table": regression_table,
            "variable_importance": variable_importance,
            "diagnostics": diagnostic_artifacts,
            "model_family_evidence": family_evidence,
        }
        if primary_type in ("poisson", "poisson_rate"):
            poisson_diag = diagnostic_artifacts.get("poisson_1", {})
            overdisp = poisson_diag.get("overdispersion", {})
            if isinstance(overdisp, dict) and overdisp:
                report["overdispersion"] = overdisp
        # Generate issue IDs for all collected issues
        for idx, issue in enumerate(issue_dicts):
            if not issue.get("issue_id"):
                issue["issue_id"] = f"diag_{idx + 1:03d}"

        # Build diagnostic_summary.json
        primary_type = model_results[0][1].get("model_type", "ols") if model_results else "ols"
        effective_exposure_col = exposure_col if primary_type == "poisson_rate" else None
        diagnostic_summary = build_diagnostic_summary(
            issue_dicts=issue_dicts,
            model_results=[result for _, result in model_results],
            routing=routing,
            normalized_y=normalized_y,
            normalized_x=normalized_x,
            profile=profile,
            categorical_vars=categorical_vars,
            y_type=y_type,
            primary_type=primary_type,
            variable_roles=variable_roles,
            run_id=run_id,
            exposure_col=effective_exposure_col,
            dropped_vars=dropped_vars,
            coercions=coercion_actions,
            imputation=imputation_summary,
        )
        if family_evidence is not None:
            diagnostic_summary["model_family_evidence"] = family_evidence
        # Keep the deterministic report-side packets on the durable diagnostic
        # summary as well as in the retained HTML view.  The RunDetail endpoint can then
        # expose the exact same Table 1, labels, statistical evidence, and
        # family packet to Table/Report/Agent consumers without adding a second
        # source of truth or changing the legacy artifact set.
        declared_variable_labels = {
            str(row["column"]): row["label"]
            for row in descriptive_stats
            if isinstance(row, dict)
            and row.get("label_source") == "declared"
            and row.get("column") is not None
            and isinstance(row.get("label"), str)
        }
        declared_value_labels = {
            str(row["column"]): row["value_labels"]
            for row in descriptive_stats
            if isinstance(row, dict)
            and row.get("column") is not None
            and isinstance(row.get("value_labels"), dict)
            and row.get("value_labels")
        }
        diagnostic_summary.update(
            {
                "table_1": descriptive_stats,
                "statistical_evidence": statistical_tests.get("evidence"),
                "labels": {
                    "variable_labels": declared_variable_labels,
                    "value_labels": declared_value_labels,
                },
            }
        )
        write_json(run_root / "diagnostic_summary.json", diagnostic_summary)
        register_artifact(run_root, "diagnostic_summary", run_root / "diagnostic_summary.json", "metadata", "diagnostics", [])

        # Write legacy errors.json with superseded_by pointer
        write_json(run_root / "errors.json", {
            "schema_version": "legacy",
            "run_id": run_id,
            "issues": issue_dicts,
            "superseded_by": "diagnostic_summary.json",
        })

        # Render HTML report via view_model
        report_render_status = "pending"
        report_available = False
        report_admission = _report_evidence_admission(ctx)
        report_factory_failure_code: str | None = None
        report_factory_configured = (
            ctx.artifacts.get("_report_evidence_owner_factory") is not None
        )
        if report_admission is None and model_results:
            try:
                generated_admission = _admit_report_evidence_from_factory(
                    ctx,
                    run_root=run_root,
                    run_id=run_id,
                    model_run_id=str(model_results[0][0]),
                    primary_model_type=primary_type,
                    regression_table=regression_table,
                    issue_dicts=issue_dicts,
                    report_fields={key: report[key] for key in (
                        "descriptive_stats", "statistical_evidence", "variable_importance",
                        "diagnostics", "model_family_evidence")},
                    diagnostic_summary=diagnostic_summary,
                )
                if generated_admission is not None:
                    report_admission = generated_admission
            except Exception as exc:
                # An explicitly configured host factory is a hard dependency
                # for a completed model run. Keep the public diagnostic stable
                # and never leak provider, path, or socket exception text.
                report_factory_failure_code = getattr(exc, "code", None)
                if type(report_factory_failure_code) is not str or not report_factory_failure_code:
                    report_factory_failure_code = "REPORT_EVIDENCE_FACTORY_FAILED"
                issue_dicts.append(
                    GuardrailIssue(
                        Severity.BLOCKER,
                        "REPORT_EVIDENCE_FACTORY_FAILED",
                        "Server-owned Report evidence could not be admitted; the run is blocked.",
                        {"reason_code": report_factory_failure_code},
                    ).to_dict()
                )
        if report_admission is not None:
            report_owner, report_projection = report_admission
            expected_model_run_id = (
                str(model_results[0][0])
                if model_results and isinstance(model_results[0], (list, tuple))
                else None
            )
            if (
                not report_owner.accepts_canonical_run_root(run_root)  # type: ignore[attr-defined]
                or report_owner.run_id != run_id  # type: ignore[attr-defined]
                or (
                    expected_model_run_id is not None
                    and report_owner.model_run_id != expected_model_run_id  # type: ignore[attr-defined]
                )
            ):
                report_admission = None
                report_factory_failure_code = "EVIDENCE_SCOPE_ROOT_MISMATCH"
        report_factory_required_failure = (
            report_factory_configured and bool(model_results) and report_admission is None
        )
        if report_factory_required_failure and report_factory_failure_code is None:
            report_factory_failure_code = "REPORT_EVIDENCE_FACTORY_FAILED"
        env.step("reporting", "start", "Rendering report...")
        try:
            if report_admission is None:
                # Every report family, including ARMA-GARCH, must enter the
                # typed unavailable contract before any family-specific raw
                # deliverable is read or constructed.
                from ...report_view_model import build_report_view_model

                view_model = build_report_view_model(
                    diagnostic_summary,
                    run_root,
                    descriptive_stats=descriptive_stats,
                    statistical_tests=statistical_test_summaries,
                    statistical_evidence=statistical_tests.get("evidence"),
                    regression_table=regression_table,
                    include_legacy_presentation=True,
                )
                raise RuntimeError(
                    "REPORT_EVIDENCE_UNAVAILABLE:"
                    + str(view_model.get("reasonCode", "EVIDENCE_OWNER_CAPABILITY_REQUIRED"))
                )
            from ...report_view_model import build_report_view_model

            report_owner, report_projection = report_admission
            # Every family, including ARMA-GARCH, renders only C0-bound sections.
            # Never append a raw family document after projection issuance.
            view_model = build_report_view_model(
                {}, run_root, descriptive_stats=[], statistical_tests={},
                statistical_evidence={}, regression_table={}, exploration=None,
                evidence_projection=report_projection, include_legacy_presentation=False,
                owner=report_owner,
                artifact_admission=report_owner._canonical_report_artifact(),  # type: ignore[attr-defined]
            )
            render_legacy_html_report(
                view_model, run_root, owner=report_owner, projection=report_projection,
            )
            report_render_status = "complete"
            report_available = (run_root / "reports" / "report.html").is_file()
            env.step("reporting", "complete", "Rendered HTML report")
        except Exception as exc:
            if report_factory_required_failure:
                issue_dicts.append(
                    GuardrailIssue(
                        Severity.BLOCKER,
                        "REPORT_EVIDENCE_REQUIRED",
                        "The configured Report evidence boundary was not satisfied; the run is blocked.",
                        {"reason_code": report_factory_failure_code},
                    ).to_dict()
                )
            else:
                issue_dicts.append(GuardrailIssue(
                    Severity.WARNING,
                    "REPORT_RENDER_FAILED",
                    f"HTML report generation failed: {exc}. Model results are still available.",
                    {"error": str(exc)},
                ).to_dict())
            report_render_status = "failed"
            report_available = False
            write_json(run_root / "errors.json", {"issues": issue_dicts})
            env.step(
                "reporting",
                "complete",
                "Report evidence admission failed — run blocked"
                if report_factory_required_failure
                else "Report render failed — model results available",
            )

        # Run completion keeps the durable HTML/JSON/evidence artifacts only.
        # PDF and result-table XLSX are presentation views and are created by
        # explicit Report-page actions, so a normal run never spends time or
        # storage producing files the user did not request.
        env.step(
            "export",
            "complete",
            "HTML retained; PDF and result-table XLSX available on demand",
        )

        # Late issues (render/export) and the actual report file must be
        # reflected in the same summary consumed by diagnostic preview and the
        # Agent. Assign IDs before the final write because the initial summary
        # was intentionally built before rendering.
        for idx, issue in enumerate(issue_dicts):
            if not issue.get("issue_id"):
                issue["issue_id"] = f"diag_{idx + 1:03d}"
        diagnostic_summary = finalize_diagnostic_summary(
            diagnostic_summary,
            issue_dicts=issue_dicts,
            report_render_status=report_render_status,
            report_available=report_available,
            run_id=run_id,
        )
        summary_path = run_root / "diagnostic_summary.json"
        write_json(summary_path, diagnostic_summary)
        _refresh_artifact_checksum(run_root, "diagnostic_summary", summary_path)
        write_json(run_root / "errors.json", {
            "schema_version": "legacy",
            "run_id": run_id,
            "issues": issue_dicts,
            "superseded_by": "diagnostic_summary.json",
        })

        _safe_flush_recorder(_recorder, context="success")

        run_status = "failed" if report_factory_required_failure else "completed"
        _write_manifest(
            run_root,
            run_id,
            mode,
            run_status,
            _lineage(input_files),
            started_at=started_at,
            y=y,
            x=x,
            requested_model_type=model_type,
            model_routing=_build_model_routing_summary(
                cleaned,
                normalized_y,
                requested_model_type=model_type,
                data_detected_y_type=data_detected_y_type,
                effective_y_type=y_type,
                model_results=model_results,
            ),
        )

        ctx.primary_type = primary_type
        ctx.terminal_status = run_status
        return ctx
