"""Column-level checks extracted from orchestrator (V1.5.4.5, behavior-frozen).

Verbatim move. Consumed by pre_estimation_checks/routing/recording stages via
the workbench.orchestrator.* namespace.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..artifacts import register_artifact, write_json
from ..cleaning import normalize_column_name
from ..domain import GuardrailIssue, Severity


def _normalized_existing(candidates: tuple[str, ...], frame: pd.DataFrame) -> list[str]:
    columns = set(frame.columns)
    return [
        normalized
        for candidate in candidates
        if (normalized := normalize_column_name(candidate)) in columns
    ]


def _model_column_issue(
    frame: pd.DataFrame,
    normalized_y: str,
    normalized_x: list[str],
    requested_y: str,
    requested_x: list[str],
) -> GuardrailIssue | None:
    columns = set(frame.columns)
    requested = [normalized_y, *normalized_x]
    missing = [column for column in requested if column not in columns]
    if not missing:
        return None
    return GuardrailIssue(
        Severity.BLOCKER,
        "MODEL_COLUMNS_NOT_FOUND",
        "Requested model columns are not available after cleaning.",
        {
            "missing_columns": missing,
            "available_columns": sorted(str(column) for column in frame.columns),
            "requested_y": requested_y,
            "requested_x": requested_x,
        },
    )


_SUSPICIOUS_NAME_PATTERNS = {"noise", "random", "placebo", "check", "fake", "test"}


def _detect_suspicious_vars(x_vars: list[str]) -> set[str]:
    suspicious: set[str] = set()
    for var in x_vars:
        name_lower = var.lower()
        for pattern in _SUSPICIOUS_NAME_PATTERNS:
            if pattern in name_lower:
                suspicious.add(var)
                break
    return suspicious


def _coerce_x_columns_to_numeric(
    frame: pd.DataFrame,
    x_vars: list[str],
    run_root: Path,
) -> list[dict[str, Any]]:
    """Coerce X columns from datetime/object to numeric if appropriate.

    Returns a list of coercion action dicts and writes a summary artifact.
    """
    heuristics = {
        "year", "month", "age", "miles", "density", "score", "count",
        "claims", "days", "number", "num", "amount", "rate", "price",
        "cost", "value", "size", "weight", "volume", "sum",
    }
    actions: list[dict[str, Any]] = []
    for var in x_vars:
        if var not in frame.columns:
            continue
        if pd.api.types.is_numeric_dtype(frame[var]):
            continue
        is_likely_numeric = any(pat in var.lower() for pat in heuristics)
        threshold = 0.80 if is_likely_numeric else 0.90
        numeric = pd.to_numeric(frame[var], errors="coerce")
        good = numeric.notna().sum()
        total = len(numeric)
        if total > 0 and (good / total) >= threshold:
            original_dtype = str(frame[var].dtype)
            frame[var] = numeric
            actions.append({
                "column": var,
                "original_dtype": original_dtype,
                "conversion_rate": round(good / total, 4),
            })
    if actions:
        path = run_root / "staged" / "x_coercion_summary.json"
        write_json(path, {"coerced_columns": actions})
        try:
            register_artifact(
                run_root,
                "x_coercion_summary",
                path,
                "metadata",
                "cleaning",
                ["cleaned_dataset"],
            )
        except Exception:
            pass
    return actions


def _check_suspicious_dtypes(
    frame: pd.DataFrame,
    x_vars: list[str],
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    x_set = set(x_vars)
    for col in frame.columns:
        if not pd.api.types.is_datetime64_any_dtype(frame[col]):
            continue
        nunique = int(frame[col].nunique())
        is_x = col in x_set
        severity = Severity.WARNING if is_x else Severity.INFO
        if nunique <= 5:
            issue = GuardrailIssue(
                severity,
                "SUSPICIOUS_DTYPE",
                f"Column '{col}' has datetime dtype with only {nunique} unique value(s). "
                f"It may be a binary/categorical variable misread as datetime. "
                f"{'It is used as a predictor — verify its dtype.' if is_x else 'Verify before using it as a predictor.'}",
                {"column": col, "dtype": str(frame[col].dtype), "nunique": nunique, "is_x": is_x},
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
        elif is_x and nunique > 5:
            numeric = pd.to_numeric(frame[col], errors="coerce")
            good = numeric.notna().sum()
            total = len(numeric)
            if total > 0 and (good / total) >= 0.9:
                frame[col] = numeric
                issue = GuardrailIssue(
                    Severity.INFO,
                    "COERCED_X_DTYPE",
                    f"Column '{col}' was datetime dtype with {nunique} unique values; "
                    f"auto-coerced to numeric ({good}/{total}, {good/total:.0%} conversion rate).",
                    {"column": col, "dtype": str(frame[col].dtype), "nunique": nunique},
                )
                issue_dicts.append(issue.to_dict())
                write_json(run_root / "errors.json", {"issues": issue_dicts})


_CATEGORICAL_NAME_PATTERNS = {"code", "region", "category", "group", "type", "class", "level", "tier", "rank"}


def _detect_categorical_x_vars(frame: pd.DataFrame, x_vars: list[str]) -> set[str]:
    """Detect X variables that should use C() encoding in the model formula.

    Name-suggestive numeric columns with 3-20 unique values and non-numeric
    columns with 2-20 unique values are flagged as categorical. Binary 0/1
    columns are excluded since they are handled by _detect_binary_vars.
    """
    categorical: set[str] = set()
    for var in x_vars:
        if var not in frame.columns:
            continue
        series = frame[var].dropna()
        if len(series) < 2:
            continue
        nunique = int(series.nunique())
        if nunique > 20 or nunique >= len(series):
            continue
        name_lower = str(var).lower()
        name_suggests_category = any(
            pat in name_lower for pat in _CATEGORICAL_NAME_PATTERNS
        )
        if pd.api.types.is_numeric_dtype(series):
            if nunique >= 3 and name_suggests_category:
                categorical.add(var)
        else:
            if nunique >= 2:
                categorical.add(var)
    return categorical


def _check_categorical_candidates(
    frame: pd.DataFrame,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
    encoded_categorical_vars: set[str] | None = None,
) -> None:
    """Report categorical handling using the final model preprocessing state."""
    encoded = encoded_categorical_vars or set()
    for col in sorted(encoded):
        col_str = str(col)
        if col_str not in frame.columns:
            continue
        issue_dicts.append(
            GuardrailIssue(
                Severity.INFO,
                "CATEGORICAL_AUTO_DUMMY_CODED",
                f"Column '{col_str}' was detected as categorical and automatically dummy-coded.",
                {"column": col_str, "preprocessing": "dummy_coded"},
            ).to_dict()
        )
        write_json(run_root / "errors.json", {"issues": issue_dicts})

    for col in frame.columns:
        col_str = str(col)
        if col_str in encoded:
            continue
        name_lower = col_str.lower()
        if not any(pat in name_lower for pat in _CATEGORICAL_NAME_PATTERNS):
            continue
        nunique = int(frame[col].nunique())
        if 1 < nunique <= 10:
            issue_dicts.append(
                GuardrailIssue(
                    Severity.INFO,
                    "CATEGORICAL_CANDIDATE",
                    f"Column '{col_str}' may be categorical ({nunique} unique values). Consider one-hot encoding.",
                    {"column": col_str, "nunique": nunique},
                ).to_dict()
            )
            write_json(run_root / "errors.json", {"issues": issue_dicts})


def _check_dropped_variables(
    x_vars: list[str],
    model_results: list[tuple[str, dict[str, Any]]],
    frame: pd.DataFrame,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
    categorical_vars: set[str] | None = None,
    model_declared_variables: set[str] | None = None,
) -> list[dict[str, str]]:
    """Check for user-specified X variables dropped from the model silently.

    Returns structured entries: {"variable", "reason" (normalized id),
    "reason_display" (human string)}. Respects C()-encoded categoricals.
    """
    if categorical_vars is None:
        categorical_vars = set()
    if model_declared_variables is None:
        model_declared_variables = set()

    if not model_results:
        return []

    primary_result = model_results[0][1]
    coefficients = primary_result.get("coefficients", {})
    if not isinstance(coefficients, dict):
        return []

    def _in_coefficients(var: str) -> bool:
        if var in coefficients:
            return True
        if var in categorical_vars:
            sq = f"C(Q('{var}'))[T."
            dq = f'C(Q("{var}"))[T.'
            for cterm in coefficients:
                if isinstance(cterm, str) and (sq in cterm or dq in cterm):
                    return True
        return False

    dropped: list[dict[str, str]] = []
    for var in x_vars:
        # Some estimators (CS/SA/DCDH) expose a compact ATT result whose
        # coefficient table intentionally does not contain each covariate.
        # Their own structured metadata is authoritative; absence from the
        # headline coefficient table is not evidence that a covariate dropped.
        if var in model_declared_variables:
            continue
        if _in_coefficients(var):
            continue
        if var not in frame.columns or frame[var].isna().all():
            reason_id = "all_missing_after_cleaning"
            reason_display = "dropped due to all-missing after cleaning"
        elif frame[var].nunique() <= 1:
            reason_id = "zero_variance"
            reason_display = "dropped due to zero variance"
        elif var in categorical_vars:
            reason_id = "perfect_collinearity_categorical"
            reason_display = "dropped due to perfect collinearity (categories may overlap with other predictors)"
        else:
            reason_id = "perfect_collinearity"
            reason_display = "dropped due to perfect collinearity"

        dropped.append({
            "variable": var,
            "reason": reason_id,
            "reason_display": reason_display,
        })
        issue_dicts.append(
            GuardrailIssue(
                Severity.INFO,
                "VARIABLE_DROPPED",
                f"Variable '{var}' was {reason_display}.",
                {"variable": var, "reason": reason_display},
            ).to_dict()
        )

    if dropped:
        write_json(run_root / "errors.json", {"issues": issue_dicts})

    return dropped
