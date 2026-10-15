"""Summaries: bounded read-only context projection."""

from __future__ import annotations
from dataclasses import dataclass
import math
from pathlib import Path
import re
from collections.abc import Mapping
from typing import Any
from ...artifacts import read_json, sha256_file
from ..context_compiler import resolve_registered_artifact
from ..operations import OperationRecord
from ..bounds import _bounded_label, _bounded_labels, _bounded_numeric_fields, _public_positive_int, _public_stat_number
from ..family_evidence import bounded_model_family_evidence as _bounded_model_family_evidence
from ..operation_outcome import produced_run

def _read_manifest(run_root: Path) -> dict[str, Any]:
    try:
        value = read_json(run_root / "run_manifest.json")
    except (FileNotFoundError, OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _analysis_contract_from_run_inputs(
    run_inputs: dict[str, Any],
) -> dict[str, Any] | None:
    """Recover the frozen analysis contract from persisted run inputs.

    A run that failed before its artifacts were written still has the options
    it was asked to execute, and those options are the only honest basis for
    judging a patch against that node.
    """

    for section_name in ("executed_payload", "confirmed_payload", "form"):
        section = run_inputs.get(section_name)
        options = section.get("model_options") if isinstance(section, dict) else None
        if not isinstance(options, dict):
            continue
        try:
            from ...contracts.model.arma_garch import ArmaGarchAnalysisContract

            return ArmaGarchAnalysisContract.from_dict(options).to_dict()
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _read_diagnostic_summary(run_root: Path) -> tuple[dict[str, Any] | None, str]:
    summary_path = run_root / "diagnostic_summary.json"
    if not summary_path.is_file():
        return None, "missing"
    try:
        value = read_json(summary_path)
    except (OSError, ValueError):
        return None, "malformed"
    if not isinstance(value, dict):
        return None, "malformed"
    return value, "complete"


def _bounded_statistics_evidence(
    run_root: Path,
    *,
    limit: int = 8,
) -> dict[str, Any] | None:
    """Expose the typed normal-Run statistics packet to Agent consumers.

    The packet is already schema-owned at write time. This read projection
    keeps the exact numeric fields while applying the same bounded public
    result budget used for other Agent evidence.
    """

    packet_path = run_root / "statistical_tests" / "evidence.json"
    try:
        packet = read_json(packet_path)
    except (FileNotFoundError, OSError, ValueError):
        return None
    if not isinstance(packet, dict):
        return None
    if packet.get("payload_schema") != "workbench.statistics.evidence-packet":
        return None
    raw_results = packet.get("results")
    if not isinstance(raw_results, list):
        return None
    priority_types = {
        "anova_posthoc",
        "posthoc_anova",
        "cohens_d",
        "eta_squared",
        "omega_squared",
        "levene",
        "bartlett",
        "shapiro_wilk",
    }
    # Pairwise Cohen's d outnumbers every other family by an order of
    # magnitude, so a first-N budget would spend the whole allowance on it and
    # the Agent would conclude that post-hoc, effect-size and assumption tests
    # were never run.  Round-robin across families so each one is represented,
    # priority families first, order inside a family preserved.
    families: dict[str, list[dict[str, Any]]] = {}
    for row in raw_results:
        if not isinstance(row, dict):
            continue
        families.setdefault(str(row.get("test_type") or ""), []).append(row)
    ordered_families = sorted(
        families, key=lambda name: (name not in priority_types, name)
    )
    selected_results: list[dict[str, Any]] = []
    depth = 0
    while len(selected_results) < max(0, limit):
        progressed = False
        for name in ordered_families:
            rows = families[name]
            if depth >= len(rows):
                continue
            progressed = True
            selected_results.append(rows[depth])
            if len(selected_results) >= max(0, limit):
                break
        if not progressed:
            break
        depth += 1
    budget = _PublicResultBudget()
    bounded_results: list[dict[str, Any]] = []
    for row in selected_results:
        if not isinstance(row, dict):
            continue
        bounded: dict[str, Any] = {}
        for key in (
            "test_id",
            "test_version",
            "test_type",
            "nobs",
            "statistic",
            "p_value",
            "p_value_corrected",
            "effect_size",
            "assumptions",
            "warnings",
            "correction",
            "family",
            # By-group runs: which group, and the p-value adjusted across groups.
            "group",
            "group_column",
            "p_value_holm_across_groups",
            "p_value_bh_across_groups",
            "groups_in_adjustment",
        ):
            if key not in row:
                continue
            if key in {"test_id", "test_version", "test_type", "family", "correction", "group", "group_column"}:
                # The correction method is what makes a post-hoc p-value
                # interpretable, so it is a short label, not budgeted detail.
                label = _bounded_label(row[key])
                if label is not None:
                    bounded[key] = label
            elif key in {"nobs", "statistic", "p_value", "p_value_corrected", "effect_size",
                         "p_value_holm_across_groups", "p_value_bh_across_groups", "groups_in_adjustment"}:
                number = _public_stat_number(row[key])
                if number is not None:
                    bounded[key] = number
            else:
                bounded[key] = _bounded_public_result_value(row[key], budget=budget)
        comparisons = row.get("comparisons")
        if isinstance(comparisons, list):
            bounded["comparisons"] = [
                _bounded_public_result_value(
                    {
                        key: comparison[key]
                        for key in ("group1", "group2", "mean_difference", "ci_low", "ci_high", "p_value", "correction")
                        if key in comparison
                    },
                    budget=budget,
                )
                for comparison in comparisons[:8]
                if isinstance(comparison, dict)
            ]
        bounded_results.append(bounded)
    return {
        "payload_schema": packet.get("payload_schema"),
        "schema_version": packet.get("schema_version"),
        "dataset_ref": packet.get("dataset_ref"),
        "lineage_parent": packet.get("lineage_parent"),
        "correction_scope": packet.get("correction_scope"),
        **({"by_group": _bounded_test_by_group(packet.get("by_group"))}
           if isinstance(packet.get("by_group"), Mapping) else {}),
        "results": bounded_results,
        "result_count": len(raw_results),
        "results_omitted": max(len(raw_results) - len(bounded_results), 0),
    }


def _bounded_regression_table(
    model_results: list[dict[str, Any]],
    *,
    model_limit: int = 4,
    term_limit: int = 32,
) -> dict[str, Any]:
    """Project the persisted coefficient packets into the report-table schema.

    Agent consumers need the same side-by-side evidence as Report/Table, but
    must not receive an unbounded raw model payload.  Keep the table schema,
    exact scalar estimates and source ids, and bound both model and term
    counts.  Significance markers are derived from the fixed report defaults;
    they are display metadata, never a replacement for the persisted p-value.
    """

    cutoffs = (("***", 0.01), ("**", 0.05), ("*", 0.1))
    models: list[dict[str, Any]] = []
    rows_by_term: dict[str, dict[str, Any]] = {}
    budget = _PublicResultBudget()

    for result in model_results[: max(0, model_limit)]:
        model_id = result.get("model_id")
        if not isinstance(model_id, str) or not model_id:
            continue
        models.append({
            "id": model_id,
            "label": result.get("model_label") or result.get("model_type") or model_id,
            "model_type": result.get("model_type"),
            "nobs": result.get("nobs"),
        })
        coefficients = result.get("coefficients")
        if not isinstance(coefficients, dict):
            continue
        for term, raw_cell in list(coefficients.items())[: max(0, term_limit)]:
            if not isinstance(raw_cell, dict):
                continue
            term_key = str(term)
            row = rows_by_term.setdefault(
                term_key,
                {"term": term_key, "label": term_key, "models": {}},
            )
            cell = {
                key: _bounded_public_result_value(raw_cell[key], budget=budget)
                for key in (
                    "estimate",
                    "std_error",
                    "ci_lower",
                    "ci_upper",
                    "p_value",
                    "source_id",
                )
                if key in raw_cell
            }
            p_value = raw_cell.get("p_value")
            try:
                parsed_p = float(p_value)
            except (TypeError, ValueError):
                parsed_p = math.nan
            cell["significance"] = next(
                (marker for marker, cutoff in cutoffs if math.isfinite(parsed_p) and parsed_p < cutoff),
                "",
            )
            row["models"][model_id] = cell

    model_ids = [model["id"] for model in models]
    rows = [
        {
            **row,
            "models": {
                model_id: row["models"].get(model_id)
                for model_id in model_ids
            },
        }
        for row in rows_by_term.values()
    ]
    return {
        "payload_schema": "workbench.regression-table",
        "schema_version": 1,
        "models": models,
        "rows": rows,
        "significance": {
            "cutoffs": {marker: cutoff for marker, cutoff in cutoffs},
            "legend": "*** p < 0.01; ** p < 0.05; * p < 0.1",
        },
        "models_omitted": max(len(model_results) - len(models), 0),
    }


def _bounded_result_summary(
    summary: dict[str, Any] | None,
    *,
    summary_status: str,
    preview: dict[str, Any],
    model_results: list[dict[str, Any]],
    run_root: Path,
) -> dict[str, Any]:
    identity = summary.get("model_identity") if isinstance(summary, dict) else None
    identity = identity if isinstance(identity, dict) else {}
    x_variables = identity.get("x_variables")
    if not isinstance(x_variables, list):
        x_variable_count = identity.get("x_variable_count")
    else:
        x_variable_count = len(x_variables)

    model_identity = {
        key: value
        for key, value in {
            "model_family": identity.get("model_family"),
            "model_label": identity.get("model_label"),
            "y_variable": identity.get("y_variable"),
            "n_observations": identity.get("n_observations"),
            "x_variable_count": x_variable_count,
        }.items()
        if value is not None
    }

    quality = summary.get("model_quality") if isinstance(summary, dict) else None
    quality = quality if isinstance(quality, dict) else {}
    raw_metrics = quality.get("metrics")
    metric_items = raw_metrics.items() if isinstance(raw_metrics, dict) else ()
    metrics = {
        str(key): value
        for key, value in metric_items
        if isinstance(raw_metrics, dict)
        and isinstance(key, str)
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    }
    primary_metric_keys = quality.get("primary_metric_keys")
    if not isinstance(primary_metric_keys, list):
        primary_metric_keys = []
    primary_metric_keys = [key for key in primary_metric_keys if isinstance(key, str)]

    coefficient_summary = summary.get("coefficients_summary") if isinstance(summary, dict) else None
    coefficient_summary = (
        coefficient_summary if isinstance(coefficient_summary, dict) else {}
    )
    raw_rows = coefficient_summary.get("rows")
    raw_rows = raw_rows if isinstance(raw_rows, list) else []
    coefficient_rows = [
        _bounded_coefficient_row(row)
        for row in raw_rows
        if isinstance(row, dict)
    ]
    coefficient_rows = [row for row in coefficient_rows if row]
    coefficient_rows_omitted = max(len(coefficient_rows) - 8, 0)

    run_status = preview.get("run_status")
    statistical_evidence = _bounded_statistics_evidence(run_root)
    model_family_evidence = _bounded_model_family_evidence(run_root, model_results)
    regression_table = _bounded_regression_table(model_results)
    return {
        "available": summary_status == "complete" and preview.get("available") is True,
        "summary_status": summary_status,
        # v1.8.7. Without these an Agent reads a design-based standard error as
        # an ordinary one: it would speak about the precision of the estimate
        # with no way to know the interval uses 8 degrees of freedom rather than
        # 80 observations. `None` when no design was declared, so absence reads
        # as absence rather than as a field that failed to load.
        "survey_design": _bounded_survey_design(model_results),
        "marginal_effects": _bounded_average_marginal_effects(model_results),
        "run_lifecycle_status": preview.get("run_lifecycle_status"),
        "trust_label": preview.get("trust_label"),
        "model_identity": model_identity,
        "metrics": metrics,
        "primary_metric_keys": primary_metric_keys,
        "coefficient_rows": coefficient_rows[:8],
        "coefficient_row_count": len(coefficient_rows),
        "coefficient_rows_omitted": coefficient_rows_omitted,
        "full_table_ref": (
            coefficient_summary.get("full_table_ref")
            if isinstance(coefficient_summary.get("full_table_ref"), str)
            else None
        ),
        "interpretation_mode": (
            coefficient_summary.get("interpretation_mode")
            if isinstance(coefficient_summary.get("interpretation_mode"), str)
            else None
        ),
        "run_status": run_status if isinstance(run_status, dict) else None,
        # Order is priority when the tool's output budget cuts (agent/tools.py):
        # the selected model's own evidence first, then the coefficient tables,
        # then run-level tests, which also have their own tool.
        "model_family_evidence": model_family_evidence,
        # v1.8.10 check library: what the assumption checks found, with status.
        "checks": _bounded_checks(run_root, model_results),
        "persisted_models": _bounded_persisted_model_facts(model_results, run_root),
        "regression_table": regression_table,
        "statistical_evidence": statistical_evidence,
    }


def _bounded_family_diagnostic(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "contract": _bounded_label(value.get("contract")),
        "model_type": _bounded_label(value.get("model_type")),
        "nobs": _public_positive_int(value.get("nobs")),
        "outcome_levels": _bounded_labels(value.get("outcome_levels")),
        "base_category": _bounded_label(value.get("base_category")),
        "validation": {
            key[:64]: label[:128]
            for key, label in (value.get("validation") or {}).items()
            if isinstance(key, str) and isinstance(label, str)
        } if isinstance(value.get("validation"), dict) else {},
    }


def _bounded_persisted_model_facts(
    model_results: list[dict[str, Any]],
    run_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Project the public facts needed to answer a selected model question.

    Diagnostic summaries are narrative-facing and may intentionally omit a
    coefficient table.  The model-result contract is the durable numerical
    authority, so return a small schema-owned projection rather than forcing
    an Agent to guess from a report or to read a raw result payload.
    """

    projected: list[dict[str, Any]] = []
    # A by-group run is one result per group; two would hide the rest. Each
    # projected group still states n_groups, and the coefficient tool returns all.
    grouped = any(isinstance(result.get("by_group"), Mapping) for result in model_results if isinstance(result, dict))
    for result in model_results[: _MAX_GROUPS_PROJECTED if grouped else 2]:
        model_id = result.get("model_id")
        coefficients = result.get("coefficients")
        if not isinstance(model_id, str) or not isinstance(coefficients, dict):
            continue
        rows: list[dict[str, Any]] = []
        for term, coefficient in list(coefficients.items())[:8]:
            if not isinstance(term, str) or not isinstance(coefficient, dict):
                continue
            rows.append(
                {
                    "term": term,
                    "estimate": _public_stat_number(coefficient.get("estimate")),
                    "std_error": _public_stat_number(coefficient.get("std_error")),
                    "p_value": _public_stat_number(coefficient.get("p_value")),
                    "ci_lower": _public_stat_number(coefficient.get("ci_lower")),
                    "ci_upper": _public_stat_number(coefficient.get("ci_upper")),
                    **_pooled_coefficient_fields(coefficient),
                }
            )
        projected.append(
            {
                "model_id": model_id,
                **({"evidence_ref": {"run_id": run_root.name, "model_id": model_id,
                                     "result_ref": f"model_results:{model_id}"}} if run_root is not None else {}),
                # What n counts: rows, or units for estimators that aggregate
                # over units (v1.8.10: CS reported 12 units beside 120 rows).
                "nobs": result.get("nobs") if isinstance(result.get("nobs"), int) else None,
                "nobs_basis": result.get("nobs_basis") or "rows",
                **_fit_statistics(result),
                "inference": _bounded_inference(result),
                # The estimator that ran, from the kernel; a requested default
                # the family does not use is never shown as if it had run.
                "covariance_executed": _executed_covariance(run_root, model_id),
                "inference_suppressed": result.get("inference_suppressed"),
                "multiple_imputation": _bounded_multiple_imputation(result),
                "by_group": _bounded_by_group(result),
                "coefficients": rows,
            }
        )
    return projected


_MAX_GROUPS_PROJECTED = 12


def _bounded_test_by_group(block: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "column": block.get("column"),
        "estimated_groups": block.get("estimated_groups"),
        "groups": [
            {key: group.get(key) for key in ("key", "nobs", "status", "reason") if group.get(key) is not None}
            for group in (block.get("groups") or [])[:_MAX_GROUPS_PROJECTED] if isinstance(group, Mapping)
        ],
        "adjustment_across_groups": block.get("adjustment_across_groups"),
        "comparing_groups": block.get("comparing_groups"),
    }


def _bounded_by_group(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """Which group this result is, the groups not estimated, and how to compare them."""
    block = result.get("by_group")
    if not isinstance(block, Mapping):
        return None
    return {
        "column": block.get("column"),
        "group": block.get("key"),
        "group_index": block.get("index"),
        "n_groups": block.get("n_groups"),
        "semantics": block.get("semantics"),
        "not_estimable": [
            {"group": item.get("key"), "nobs": item.get("nobs"), "reason": str(item.get("reason") or "")[:300]}
            for item in (block.get("not_estimable") or [])[:10] if isinstance(item, Mapping)
        ],
        "difference_tests": _bounded_difference_tests(block.get("difference_tests")),
        "comparing_groups": (
            "Coefficients of separate groups side by side are not a test of a difference; "
            "cite the group-difference test before saying groups differ."
        ),
    }


def _bounded_difference_tests(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("status") != "estimated":
        return {"status": value.get("status"), "reason": str(value.get("reason") or "")[:300]}
    return {
        "status": "estimated",
        "method": value.get("method"),
        "reference_group": value.get("reference_group"),
        "covariance_estimator": value.get("covariance_estimator"),
        "tests": [
            {key: test.get(key) for key in ("label", "statistic", "df_num", "df_den", "p_value", "distribution",
                                             "status", "reason") if test.get(key) is not None}
            for test in (value.get("tests") or [])[:12] if isinstance(test, Mapping)
        ],
    }


def _pooled_coefficient_fields(coefficient: Mapping[str, Any]) -> dict[str, Any]:
    """A pooled multiple-imputation coefficient's own Barnard-Rubin df and
    fraction of missing information; nothing for an ordinary fit."""
    if "fmi" not in coefficient:
        return {}
    return {"df": _public_stat_number(coefficient.get("df")), "fmi": _public_stat_number(coefficient.get("fmi"))}


def _bounded_multiple_imputation(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """m and the pooling rule, so the Agent says how the figures were combined."""
    block = result.get("multiple_imputation")
    if not isinstance(block, Mapping):
        return None
    return {
        "m": block.get("m"),
        "method": "Rubin's rules, Barnard-Rubin df per coefficient",
        "complete_data_df": block.get("dfcom"),
        "not_reported": "R-squared, residuals and diagnostics (they describe one imputed dataset)",
        "post_estimation": "joint tests on pooled estimates are not available yet (needs D1)",
    }


def _executed_covariance(run_root: Path | None, model_id: Any) -> str | None:
    if run_root is None or not isinstance(model_id, str):
        return None
    from ...contracts.model.inference_kernel import kernel_relative_path, validate_inference_kernel

    path = run_root / kernel_relative_path(model_id)
    try:
        if not path.is_file():
            return None
        kernel = read_json(path)
        validate_inference_kernel(kernel)
        if kernel.get("model_id") != model_id:
            return None
        from ...postestimation.comparison_data import assert_completed_kernel

        assert_completed_kernel(run_root, kernel)
        return kernel.get("covariance_estimator")
    except (OSError, ValueError):
        return None


def _bounded_checks(run_root: Path, model_results: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The primary model's check results: id, status and the one-line finding."""
    primary = next((item for item in model_results if isinstance(item, dict)), None)
    model_id = primary.get("model_id") if primary else None
    path = run_root / "model_results" / f"checks_{model_id}.json"
    if not model_id or not path.is_file():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError):
        return None
    return [
        {"check_id": item.get("check_id"), "status": item.get("status"), "blinding": item.get("blinding"),
         "summary": str(item.get("summary") or "")[:300]}
        for item in payload.get("checks", []) if isinstance(item, dict)
    ]


_INFERENCE_FIELDS = (
    "covariance", "covariance_estimator", "inference_distribution", "effective_df", "df_method",
    "cluster_count", "cluster_variable", "inference_version", "hac",
)


def _fit_statistics(result: Mapping[str, Any]) -> dict[str, Any]:
    """R-squared, unless the result is pooled over imputations.

    A pooled result has no R-squared of its own; any one dataset's would be
    shown as if it were the pooled model's, so the fields are left out rather
    than sent as null (v1.8.10 evaluation A04).
    """
    if result.get("multiple_imputation"):
        return {}
    return {
        "r_squared": _public_stat_number(result.get("r_squared")),
        "r_squared_adj": _public_stat_number(result.get("r_squared_adj")),
    }


def _bounded_inference(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """How the model's standard errors and p-values were computed.

    A result without `inference_version` predates inference engine v2; with a
    robust or clustered covariance its p-values used the normal distribution,
    and the Agent has to be able to say so.
    """
    design = result.get("survey_design")
    if isinstance(design, Mapping):
        # Derive design inference independently of legacy pre-design evidence.
        from ...survey.design import recorded_df_convention

        convention, df = recorded_df_convention(design)
        return {
            "covariance": "survey_design",
            "covariance_estimator": f"survey_design_{design.get('variance_method') or 'linearization'}",
            "inference_distribution": "t", "effective_df": df, "df_method": convention,
            "legacy_asymptotic": False,
        }
    evidence = result.get("covariance_evidence") or result.get("inference_config")
    if not isinstance(evidence, Mapping):
        return None
    out = {key: evidence.get(key) for key in _INFERENCE_FIELDS if evidence.get(key) is not None}
    out["legacy_asymptotic"] = (
        "inference_version" not in evidence
        and evidence.get("inference_distribution") == "normal"
        and evidence.get("covariance") in {"robust", "clustered"}
    )
    # A panel or DID fit (it names its entity) with robust errors did not
    # cluster by entity; since v1.8.11 the default clusters, so an older result
    # is marked and the Agent can offer the rerun.
    if evidence.get("covariance") == "robust" and isinstance(result.get("entity_col"), str) \
            and evidence.get("cluster_entity") is not True:
        out["not_clustered_by_entity"] = True
        out["inference_note"] = (
            "Heteroskedasticity-robust standard errors not clustered by entity: inconsistent with a "
            "fixed number of periods. "
            + ("This result predates v1.8.11; rerunning clusters by entity." if "inference_version" not in evidence
               else "Chosen explicitly; the default clusters by entity.")
        )
    return out


def _bounded_coefficient_row(row: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "variable",
        "display_name",
        "estimate",
        "std_error",
        "p_value",
        "ci_lower",
        "ci_upper",
        "significance_label",
    )
    return {key: row[key] for key in allowed if key in row}


def _bounded_artifact_manifest(
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    allowed = (
        "expected",
        "available",
        "readable",
        "artifact_id",
        "filename",
        "schema_valid",
        "model_id",
        "available_count",
        "legacy_debug_only",
    )
    bounded: dict[str, dict[str, Any]] = {}
    for section, value in manifest.items():
        if not isinstance(section, str) or not isinstance(value, dict):
            continue
        bounded[section] = {key: value[key] for key in allowed if key in value}
    return bounded


def _operation_artifact_ids(record: OperationRecord) -> list[str]:
    """Collect only artifact ids already recorded as this operation's output."""

    artifact_ids: list[str] = []
    direct = record.outputs.get("artifact_ids")
    if isinstance(direct, list):
        artifact_ids.extend(item for item in direct if isinstance(item, str) and item)
    workflow_state = record.outputs.get("workflow_state")
    steps = workflow_state.get("steps") if isinstance(workflow_state, dict) else None
    if isinstance(steps, dict):
        for step in steps.values():
            step_artifacts = step.get("artifact_ids") if isinstance(step, dict) else None
            if isinstance(step_artifacts, list):
                artifact_ids.extend(
                    item for item in step_artifacts if isinstance(item, str) and item
                )
    return list(dict.fromkeys(artifact_ids))


def _bounded_completed_operation(record: OperationRecord) -> dict[str, Any]:
    workflow_state = record.outputs.get("workflow_state")
    steps = workflow_state.get("steps") if isinstance(workflow_state, dict) else None
    workflow_steps: list[dict[str, Any]] = []
    if isinstance(steps, dict):
        for step_id, step in sorted(steps.items()):
            if not isinstance(step_id, str) or not isinstance(step, dict):
                continue
            artifact_ids = step.get("artifact_ids")
            row_counts = step.get("row_counts")
            workflow_steps.append(
                {
                    "step_id": step_id,
                    "status": str(step.get("status") or "unknown"),
                    "artifact_ids": [
                        item
                        for item in (artifact_ids if isinstance(artifact_ids, list) else [])
                        if isinstance(item, str) and item
                    ][:16],
                    "row_counts": {
                        str(key): value
                        for key, value in (row_counts.items() if isinstance(row_counts, dict) else ())
                        if isinstance(value, int) and not isinstance(value, bool)
                    },
                }
            )
    produced = produced_run(record.to_dict())
    return {
        "operation_record_id": record.record_id,
        "operation_id": record.operation_id,
        "operation_version": record.operation_version,
        "status": record.status,
        "artifact_ids": _operation_artifact_ids(record)[:16],
        # A rerun's result is a new run, not artifacts of this node: read it
        # with inspect_project_model_coefficients(run_ids=[produced_run_id]).
        **({"produced_run_id": produced} if produced else {}),
        "workflow": {
            "workflow_id": (
                workflow_state.get("workflow_id")
                if isinstance(workflow_state, dict)
                and isinstance(workflow_state.get("workflow_id"), str)
                else None
            ),
            "status": (
                workflow_state.get("status")
                if isinstance(workflow_state, dict)
                and isinstance(workflow_state.get("status"), str)
                else None
            ),
            "steps": workflow_steps[:16],
        },
    }


_PUBLIC_RESULT_DENIED_KEYS = frozenset(
    {
        "_omitted_item_count",
        "data",
        "dataset",
        "file",
        "filename",
        "path",
        "raw_rows",
        "rows",
        "records",
        "rendered_path",
        "residuals",
        "source_rows",
        "row_ids",
        "fitted_values",
        "values",
    }
)


@dataclass
class _PublicResultBudget:
    """One aggregate budget for a public artifact projection."""

    remaining_items: int = 96
    remaining_string_characters: int = 2048
    remaining_key_characters: int = 1600
    omitted_items: int = 0


def _public_operation_artifact_result(
    artifact_type: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Project a declared result type; unknown types remain deliberately opaque."""

    if artifact_type not in {
        "statistical_exploration",
        "statistical_test",
        "post_estimation",
        "p7_analysis",
        "workflow_capability_result",
    }:
        return None, ["raw_artifact_payloads"]
    result = payload.get("result")
    if not isinstance(result, dict):
        return None, ["raw_artifact_payloads"]
    if artifact_type == "workflow_capability_result" and isinstance(result.get("result"), dict):
        # {operation_id, family, source_columns, result: {...}}: the inner
        # result holds the statistics; lifting it keeps them inside the
        # projection's nesting limit.
        result = {
            "operation_id": result.get("operation_id"),
            "source_columns": result.get("source_columns"),
            **result["result"],
        }
    if (
        artifact_type == "statistical_exploration"
        and result.get("operation") == "tabulate"
        and isinstance(result.get("rows"), list)
    ):
        # A frequency table is an aggregate. Its entries are stored under
        # `rows` for the UI table, a key the projection withholds as raw data.
        result = {**{key: value for key, value in result.items() if key != "rows"}, "frequencies": result["rows"]}
    if artifact_type == "statistical_test" and isinstance(result.get("by_group"), Mapping):
        return _public_test_by_group(result), ["raw_artifact_payloads", "raw_rows", "test_effect_details"]
    if artifact_type == "statistical_exploration":
        # Grouped statistics sit at groups[i].variables[name].percentiles --
        # one level deeper than any other result. Lifting each group's
        # variables into the group, and allowing one more level, keeps every
        # group's numbers; before, the Agent saw only "[omitted: nesting
        # limit]" and could not answer "mean wage by sex".
        if isinstance(result.get("groups"), list):
            result = {**result, "groups": [_lift_group_variables(group) for group in result["groups"]]}
        return (
            _bounded_public_result_value(result, budget=_PublicResultBudget(remaining_items=320), max_depth=5),
            ["raw_artifact_payloads", "raw_rows"],
        )
    return _bounded_public_result_value(result), ["raw_artifact_payloads", "raw_rows"]


_BY_GROUP_TEST_FIELDS = (
    "test_id", "test_type", "group", "nobs", "statistic", "degrees_of_freedom", "p_value",
    "p_value_holm_across_groups", "p_value_bh_across_groups",
)


_MAX_BY_GROUP_TEST_ROWS = 60


def _public_test_by_group(result: Mapping[str, Any]) -> dict[str, Any]:
    """Every group's row of every test, compactly: a generic budget dropped whole groups."""
    rows = [row for row in result.get("results") or () if isinstance(row, Mapping)]
    kept = rows[:_MAX_BY_GROUP_TEST_ROWS]
    return {
        "test_type": result.get("test_type"),
        "by_group": _bounded_test_by_group(result["by_group"]),
        "results": [
            {key: (_public_stat_number(row[key]) if isinstance(row[key], (int, float)) and not isinstance(row[key], bool)
                   else _bounded_label(row[key]))
             for key in _BY_GROUP_TEST_FIELDS if row.get(key) is not None}
            for row in kept
        ],
        "result_count": len(rows),
        "results_omitted": max(len(rows) - len(kept), 0),
    }


def _lift_group_variables(group: Any) -> Any:
    if not isinstance(group, dict) or not isinstance(group.get("variables"), dict):
        return group
    lifted = {key: value for key, value in group.items() if key not in {"variables", "filters"}}
    for name, statistics in group["variables"].items():
        lifted[name if name not in lifted else f"variable:{name}"] = statistics
    return lifted


def _node_public_result_evidence(
    project_root: Path,
    *,
    owner_run_id: str,
    op_node_id: str,
) -> list[dict[str, Any]]:
    """Read statistical results whose declared input is the selected data node.

    This is deliberately a relation check, not a run-wide artifact dump.  A
    UI-created statistical exploration records the selected data artifact in
    its artifact-index inputs; only those descendants become Agent evidence.
    """

    try:
        from ...data_operations import resolve_data_column_cast_context

        source = resolve_data_column_cast_context(
            project_root,
            source_run_id=owner_run_id,
            source_node_id=op_node_id,
        )
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return []
    source_artifact_id = source.get("source_artifact_id")
    if not isinstance(source_artifact_id, str) or not source_artifact_id:
        return []
    run_root = project_root / "runs" / owner_run_id
    try:
        index = read_json(run_root / "artifacts_index.json")
    except (FileNotFoundError, OSError, ValueError):
        return []
    entries = index.get("artifacts") if isinstance(index, dict) else None
    if not isinstance(entries, list):
        return []
    evidence: list[dict[str, Any]] = []
    for entry in entries:
        if len(evidence) >= 8 or not isinstance(entry, dict):
            break
        artifact_id = entry.get("artifact_id")
        artifact_type = entry.get("artifact_type")
        inputs = entry.get("inputs")
        if (
            not isinstance(artifact_id, str)
            or not isinstance(artifact_type, str)
            or not isinstance(inputs, list)
            or source_artifact_id not in inputs
        ):
            continue
        artifact = resolve_registered_artifact(run_root, artifact_id)
        if artifact is None:
            continue
        resolved_type, sha256, payload = artifact
        public_result, _omitted = _public_operation_artifact_result(resolved_type, payload)
        if public_result is None:
            continue
        evidence.append(
            {
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "sha256": sha256,
                "result": public_result,
            }
        )
    return evidence


def _bounded_public_result_value(
    value: Any,
    *,
    depth: int = 0,
    budget: _PublicResultBudget | None = None,
    max_depth: int = 4,
) -> Any:
    """Keep a numerical result compact and reject row-shaped/raw payload fields."""

    budget = budget or _PublicResultBudget()
    if budget.remaining_items <= 0:
        budget.omitted_items += 1
        return "[omitted: result item budget]"
    budget.remaining_items -= 1
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        limit = min(300, budget.remaining_string_characters)
        if limit <= 0:
            budget.omitted_items += 1
            return "[omitted: result string budget]"
        # Charge what is kept, not the cap: charging the cap let seven short
        # labels exhaust the budget and blank out every later test name.
        budget.remaining_string_characters -= min(len(value), limit)
        if len(value) > limit:
            budget.omitted_items += 1
        return value[:limit]
    if depth >= max_depth:
        budget.omitted_items += 1
        return "[omitted: nesting limit]"
    if isinstance(value, list):
        bounded_list: list[Any] = []
        for item in value:
            if len(bounded_list) >= 16 or budget.remaining_items <= 0:
                budget.omitted_items += 1
                break
            if isinstance(item, (dict, list, str, int, float, bool)) or item is None:
                bounded_list.append(
                    _bounded_public_result_value(item, depth=depth + 1, budget=budget, max_depth=max_depth)
                )
        return bounded_list
    if not isinstance(value, dict):
        budget.omitted_items += 1
        return "[omitted: unsupported value]"
    bounded: dict[str, Any] = {}
    omissions_at_entry = budget.omitted_items
    for key in sorted(value):
        if not isinstance(key, str):
            continue
        normalized = key.lower()
        if normalized in _PUBLIC_RESULT_DENIED_KEYS or normalized.startswith("raw_"):
            continue
        if (
            len(bounded) >= 24
            or budget.remaining_items <= 0
            or budget.remaining_key_characters <= 0
        ):
            budget.omitted_items += 1
            break
        key_limit = min(64, budget.remaining_key_characters)
        bounded_key = key[:key_limit]
        budget.remaining_key_characters -= len(bounded_key)
        if len(key) > key_limit:
            budget.omitted_items += 1
        if bounded_key in bounded:
            budget.omitted_items += 1
            continue
        bounded[bounded_key] = _bounded_public_result_value(
            value[key], depth=depth + 1, budget=budget, max_depth=max_depth
        )
    omitted_here = budget.omitted_items - omissions_at_entry
    if omitted_here:
        bounded["_omitted_item_count"] = omitted_here
    return bounded


def _bounded_node(node: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "id",
        "kind",
        "stage",
        "display_label",
        "parent_stage_id",
        "branch_id",
        "trust",
    )
    return {key: node[key] for key in allowed if key in node}


def _resolve_verified_registered_artifact(
    run_root: Path,
    *,
    artifact_id: str,
    expected_type: str,
) -> tuple[dict[str, Any], str] | None:
    """Resolve a known artifact id and verify its registered content digest."""

    resolved = resolve_registered_artifact(run_root, artifact_id)
    if resolved is None:
        return None
    artifact_type, registered_sha256, payload = resolved
    if artifact_type != expected_type or not isinstance(registered_sha256, str):
        return None
    if re.fullmatch(r"[0-9a-f]{64}", registered_sha256) is None:
        return None
    try:
        index = read_json(run_root / "artifacts_index.json")
    except (OSError, ValueError):
        return None
    entries = index.get("artifacts") if isinstance(index, dict) else None
    entry = next(
        (
            item
            for item in entries or ()
            if isinstance(item, dict) and item.get("artifact_id") == artifact_id
        ),
        None,
    )
    relative_path = entry.get("path") if isinstance(entry, dict) else None
    if not isinstance(relative_path, str) or Path(relative_path).is_absolute():
        return None
    try:
        resolved_root = run_root.resolve()
        path = (run_root / relative_path).resolve()
        path.relative_to(resolved_root)
        if not path.is_file() or sha256_file(path) != registered_sha256:
            return None
    except (OSError, ValueError):
        return None
    return payload, registered_sha256


def _bounded_diagnostics(preview: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    allowed = (
        "available",
        "preview_contract_version",
        "source_schema_version",
        "preview_status",
        "contract_warnings",
        "run_lifecycle_status",
        "run_status",
        "trust_label",
        "trust_counts",
        "primary_reasons",
        "diagnostic_highlights",
        "interpretation_restrictions",
        "recommended_actions",
    )
    diagnostics = {key: preview[key] for key in allowed if key in preview}
    omitted_sections = ["artifact_manifest", "coefficient_risk"]

    identity = preview.get("model_identity")
    if isinstance(identity, dict):
        diagnostics["model_identity"] = {
            key: identity[key]
            for key in (
                "primary_model_id",
                "model_label",
                "model_type",
                "y_variable",
                "n_observations",
                "x_variable_count",
            )
            if key in identity
        }

    for key, limit in (
        ("contract_warnings", 8),
        ("diagnostic_highlights", 8),
        ("interpretation_restrictions", 8),
    ):
        values = diagnostics.get(key)
        if not isinstance(values, list) or len(values) <= limit:
            continue
        diagnostics[key] = values[:limit]
        omitted_sections.append(key)
        diagnostics.setdefault("omitted_item_counts", {})[key] = len(values) - limit

    return diagnostics, omitted_sections


@dataclass(frozen=True)
class RecipeResultProjection:
    """A family whose public result comes from its recipe contract.

    Structurally different from `FamilyEvidenceSpec`: this path builds the
    projection from a registered artifact via the family's recipe contract, so
    only the artifact id and the unavailable reason vary. Declaring those two
    keeps the entry condition a lookup rather than a family name in an `if`.
    """

    artifact_id: str
    unavailable_reason_code: str


RECIPE_RESULT_PROJECTIONS: dict[str, RecipeResultProjection] = {
    "time_series.ets": RecipeResultProjection(
        artifact_id="ets_1",
        unavailable_reason_code="ETS_PUBLIC_RESULT_UNAVAILABLE",
    ),
}


def _bounded_survey_design(model_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The terms every interval in this run is conditional on.

    Returned alongside the coefficients rather than behind a separate tool: an
    Agent that has the standard errors already has everything it needs to make a
    claim about precision, so the qualification has to arrive with them.
    """
    for result in model_results:
        if not isinstance(result, dict):
            continue
        design = result.get("survey_design")
        if not isinstance(design, dict):
            continue
        projected = _bounded_numeric_fields(
            design,
            fields=(
                "n_obs", "n_strata", "n_psu", "degf", "residual_degf", "inference_degf",
                "design_effect", "effective_sample_size",
            ),
            string_fields=(
                "df_convention", "variance_method", "strata_column", "psu_column",
                "weight_column", "replicate_type", "lonely_psu_policy",
                "subpopulation",
            ),
        )
        fpc = design.get("fpc")
        if isinstance(fpc, dict):
            projected["fpc"] = _bounded_numeric_fields(fpc, fields=(), string_fields=("column", "units"))
            strata = fpc.get("strata")
            projected["fpc"]["strata"] = [
                _bounded_numeric_fields(row, fields=("sampled_psus", "population_psus",
                    "sampling_fraction", "variance_factor"), string_fields=("stratum",))
                for row in (strata if isinstance(strata, list) else [])[:16]
                if isinstance(row, dict)]
            if isinstance(strata, list) and len(strata) > 16:
                projected["fpc"]["strata_truncated"] = True
        return projected
    return None


def _bounded_average_marginal_effects(
    model_results: list[dict[str, Any]], *, limit: int = 16
) -> list[dict[str, Any]]:
    """A GLM coefficient is a log-odds; the marginal effect is what gets quoted.

    v1.8.7 computes these for logit/probit/poisson and nothing exposed them, so
    an Agent asked "how much does x move y" had only the log-odds to work from.
    """
    for result in model_results:
        if not isinstance(result, dict):
            continue
        effects = result.get("marginal_effects")
        if not isinstance(effects, list):
            continue
        rows: list[dict[str, Any]] = []
        for row in effects[:limit]:
            if not isinstance(row, dict):
                continue
            rows.append(
                _bounded_numeric_fields(
                    row,
                    fields=("estimate", "std_error", "p_value", "ci_lower", "ci_upper"),
                    string_fields=("term", "variable"),
                )
            )
        return rows
    return []

