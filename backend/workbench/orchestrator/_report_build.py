"""Report-building helpers extracted from orchestrator
(V1.5.4.5, behavior-frozen).

Verbatim move. Consumed by report/recording/estimation stages via the
workbench.orchestrator.* namespace.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..artifacts import register_artifact, write_json


def _variable_summary(cat_dp: Any, coer_dp: Any) -> str:
    if cat_dp is not None:
        params = cat_dp.reason.chosen_params if cat_dp.reason else {}
        n_levels = params.get("n_unique", "?")
        ref = params.get("reference_level", "?")
        return f"Dummy-encoded ({n_levels} levels, ref={ref!r})"
    if coer_dp is not None:
        params = coer_dp.reason.chosen_params if coer_dp.reason else {}
        conversion_rate = float(params.get("conversion_rate", 0))
        return f"Coerced to numeric ({conversion_rate:.0%} convertible)"
    return "Kept as numeric"


def _model_summary(
    model_type: str,
    result: dict[str, Any],
    *,
    robust_se_dp: Any,
    exposure_col: str | None,
    fallback_n: int,
) -> str | None:
    n = int(result.get("nobs", fallback_n))
    if model_type in ("ols", "ols_robust"):
        if robust_se_dp is not None and robust_se_dp.reason is not None:
            se_type = robust_se_dp.reason.chosen_params.get("variant", robust_se_dp.selected)
        elif robust_se_dp is not None:
            se_type = robust_se_dp.selected
        else:
            se_type = "HC1"
        return f"OLS ({se_type}, n={n})"
    if model_type == "logit":
        return f"Logit (n={n})"
    if model_type == "poisson_rate":
        exp = result.get("exposure_col") or exposure_col
        return f"Poisson rate (exposure={exp}, n={n})" if exp else f"Poisson (n={n})"
    if model_type == "poisson":
        return f"Poisson (n={n})"
    return None


def _write_model_result(
    run_root: Path,
    model_id: str,
    model_result: dict[str, Any],
    *,
    inputs: list[str] | None = None,
) -> None:
    model_path = run_root / "model_results" / f"{model_id}.json"
    write_json(model_path, model_result)
    register_artifact(
        run_root,
        model_id,
        model_path,
        "model_result",
        "econometrics",
        inputs or ["cleaned_dataset"],
    )


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


def _coefficient_rows(model_result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    coefficients = model_result.get("coefficients", {})
    irr_dict = model_result.get("irr", {})
    if not isinstance(coefficients, dict):
        return rows
    for term, values in coefficients.items():
        if isinstance(values, dict):
            row: dict[str, Any] = {"term": term, **values}
            if isinstance(irr_dict, dict) and term in irr_dict:
                term_irr = irr_dict[term]
                if isinstance(term_irr, dict):
                    row.setdefault("irr", term_irr.get("irr"))
                    row.setdefault("irr_ci_lower", term_irr.get("irr_ci_lower"))
                    row.setdefault("irr_ci_upper", term_irr.get("irr_ci_upper"))
            rows.append(row)
    return rows


def _coefficient_rows_for_models(
    model_results: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id, model_result in model_results:
        for row in _coefficient_rows(model_result):
            rows.append({"model_id": model_id, **row})
    return rows


def _build_variable_importance(
    statistical_tests: dict[str, dict[str, Any]],
    y: str,
    x_vars: list[str],
    model_results: list[tuple[str, dict[str, Any]]] | None = None,
    frame: pd.DataFrame | None = None,
    primary_type: str = "ols",
    exposure_col: str | None = None,
    categorical_vars: set[str] | None = None,
) -> list[dict[str, Any]]:
    cat_set = categorical_vars or set()
    importance: dict[str, dict[str, Any]] = {}
    for var in x_vars:
        if var == exposure_col:
            continue
        importance[var] = {
            "variable": var, "correlation": None, "best_p_value": None, "test_type": None
        }
    if frame is not None:
        cols = [y] + [v for v in x_vars if v in frame.columns]
        if len(cols) >= 2:
            corr = frame[cols].corr(numeric_only=True)
            if y in corr.columns:
                for var in x_vars:
                    if var == exposure_col:
                        continue
                    if var in corr.columns:
                        c = corr[y].get(var)
                        if pd.notna(c):
                            importance[var]["correlation"] = round(float(c), 3)
                            if var in cat_set:
                                importance[var]["correlation_note"] = "Pearson r on categorical codes — prefer ANOVA"
    for row in statistical_tests.get("correlations", {}).get("results", []):
        variables = row.get("variables", [])
        if isinstance(variables, list) and y in variables:
            for var in variables:
                if var != y and var in importance:
                    importance[var]["correlation"] = row.get("effect", {}).get("r")
                    p = row.get("p_value")
                    if p is not None:
                        importance[var]["best_p_value"] = p
                        importance[var]["test_type"] = "correlation"
    for family in ("t_tests", "anova"):
        for row in statistical_tests.get(family, {}).get("results", []):
            outcome = row.get("outcome")
            if outcome != y:
                continue
            group = row.get("group", "")
            if group in importance:
                p = row.get("p_value")
                existing = importance[group]["best_p_value"]
                if p is not None and (existing is None or p < existing):
                    importance[group]["best_p_value"] = p
                    importance[group]["test_type"] = family
    if model_results:
        primary = model_results[0][1] if model_results else {}
        coefficients = primary.get("coefficients", {})
        for var in x_vars:
            if var not in importance:
                continue
            imp = importance[var]
            if imp["best_p_value"] is not None:
                continue
            coeff = coefficients.get(var)
            if isinstance(coeff, dict) and coeff.get("p_value") is not None:
                imp["best_p_value"] = coeff["p_value"]
                imp["test_type"] = f"{primary_type}_coefficient" if primary_type else "model_coefficient"
    for var in x_vars:
        if var not in importance:
            continue
        imp = importance[var]
        corr = imp["correlation"]
        p = imp["best_p_value"]
        if corr is not None and abs(corr) >= 0.3:
            imp["strength"] = "strong"
        elif corr is not None and abs(corr) >= 0.1:
            imp["strength"] = "moderate"
        elif corr is not None:
            imp["strength"] = "weak"
        elif p is not None and p < 0.05:
            imp["strength"] = "significant (no correlation data)"
        else:
            imp["strength"] = ""
    return sorted(importance.values(), key=_importance_sort_key)


def _importance_sort_key(item: dict[str, Any]) -> float:
    p = item.get("best_p_value")
    if p is None:
        return 2.0
    return float(p)


def _build_descriptive_stats(frame: pd.DataFrame, *, categorical_vars: set[str] | None = None) -> list[dict[str, Any]]:
    cat_set = categorical_vars or set()
    stats: list[dict[str, Any]] = []
    for column in frame.columns:
        col_str = str(column)
        series = frame[column]
        present = int(series.notna().sum())
        total = len(series)
        row: dict[str, Any] = {
            "column": col_str,
            "dtype": str(series.dtype),
            "count": present,
            "missing": total - present,
            "missing_rate": round((total - present) / total, 4) if total > 0 else 0.0,
            "unique_count": int(series.nunique()),
        }
        is_categorical = col_str in cat_set
        if pd.api.types.is_numeric_dtype(series) and not is_categorical:
            row["mean"] = round(float(series.mean()), 4)
            row["std"] = round(float(series.std()), 4)
            row["min"] = round(float(series.min()), 4)
            row["max"] = round(float(series.max()), 4)
        else:
            row["mean"] = None
            row["std"] = None
            row["min"] = None
            row["max"] = None
            if is_categorical:
                row["note"] = "categorical — mean/std not meaningful"
        stats.append(row)
    return stats
