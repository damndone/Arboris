"""Summaries: bounded read-only context projection. (results)."""

from __future__ import annotations

import math
from pathlib import Path
from collections.abc import Mapping
from typing import Any
from ...artifacts import read_json
from ...checks.fit_checks import OUTCOME_TYPE_SERVED
from ..bounds import _bounded_label, _bounded_numeric_fields, _public_stat_number
from ..family_evidence import bounded_model_family_evidence as _bounded_model_family_evidence
from .summaries_facts import (
    _bounded_persisted_model_facts,
)
from .summaries_public_values import (
    _PublicResultBudget,
    _bounded_public_result_value,
    _bounded_test_by_group,
)


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
    comparison_models: list[dict[str, Any]] | None = None,
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
    regression_table = _bounded_regression_table(model_results if comparison_models is None else comparison_models)
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
         "summary": str(item.get("summary") or "")[:300],
         **({"evidence": {
             **_bounded_numeric_fields(item.get("evidence"),
                 fields=("first_stage_statistic", "first_stage_f", "df", "numerator_df", "denominator_df"),
                 string_fields=("test", "reference_distribution", "covariance", "verdict")),
             **({"strength_certified": item["evidence"]["strength_certified"]}
                if isinstance(item.get("evidence"), dict)
                and type(item["evidence"].get("strength_certified")) is bool else {})}}
            if item.get("check_id") == "iv.first_stage_strength" else {}),
         **({"evidence": _outcome_served_evidence(item.get("evidence"))}
            if item.get("check_id") == OUTCOME_TYPE_SERVED.check_id else {})}
        for item in payload.get("checks", []) if isinstance(item, dict)
    ]


def _outcome_served_evidence(evidence: Any) -> dict[str, Any]:
    """What the method check and the Agent need to name the families that serve the outcome."""
    evidence = evidence if isinstance(evidence, dict) else {}
    names = lambda value: [str(item)[:40] for item in value[:12]] if isinstance(value, list) else []  # noqa: E731
    return {"outcome_type": str(evidence.get("outcome_type") or "")[:40], "family": str(evidence.get("family") or "")[:40],
            "families_serving_outcome_type": names(evidence.get("families_serving_outcome_type")),
            "default_family_for_outcome_type": str(evidence.get("default_family_for_outcome_type") or "")[:40]}


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
