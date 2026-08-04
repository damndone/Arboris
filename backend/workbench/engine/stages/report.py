from __future__ import annotations

import json
from typing import Any

from ..context import ModelingContext, RunEnv


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
            build_regression_table,
        )
        render_html_report = _orch.render_html_report

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
        regression_table = build_regression_table(
            model_results,
            variable_labels=variable_labels,
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
        time_series_deliverables: dict[str, Any] | None = None
        env.step("reporting", "start", "Rendering report...")
        try:
            if primary_type == "time_series.arma_garch":
                from ..packs.arma_garch.deliverables import build_arma_garch_deliverables

                time_series_deliverables = build_arma_garch_deliverables(run_root)
                view_model = time_series_deliverables["report"]
            else:
                from ...report_view_model import build_report_view_model

                view_model = build_report_view_model(
                    diagnostic_summary, run_root,
                    descriptive_stats=descriptive_stats,
                    statistical_tests=statistical_test_summaries,
                    statistical_evidence=statistical_tests.get("evidence"),
                    regression_table=regression_table,
                )
            render_html_report(view_model, run_root)
            report_render_status = "complete"
            report_available = (run_root / "reports" / "report.html").is_file()
            env.step("reporting", "complete", "Rendered HTML report")
        except Exception as exc:
            issue_dicts.append(GuardrailIssue(
                Severity.WARNING,
                "REPORT_RENDER_FAILED",
                f"HTML report generation failed: {exc}. Model results are still available.",
                {"error": str(exc)},
            ).to_dict())
            report_render_status = "failed"
            report_available = False
            write_json(run_root / "errors.json", {"issues": issue_dicts})
            env.step("reporting", "complete", "Report render failed — model results available")

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

        _write_manifest(
            run_root,
            run_id,
            mode,
            "completed",
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
        ctx.terminal_status = "completed"
        return ctx
