"""Descriptive missingness evidence with no mechanism classification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from workbench.canonical import sha256_canonical
from workbench.contracts.model.missing_data import make_missing_data_result

from .errors import MissingDataPackError


MAX_DIAGNOSTIC_ROWS = 100_000
MAX_DIAGNOSTIC_COLUMNS = 1_000


def _reject(reason_code: str, message: str) -> None:
    raise MissingDataPackError(reason_code, message)


def _ordered_columns(frame: pd.DataFrame) -> list[str]:
    if not isinstance(frame, pd.DataFrame):
        _reject("MISSING_DATA_INVALID_INPUT", "frame must be a pandas DataFrame")
    if len(frame) > MAX_DIAGNOSTIC_ROWS:
        _reject("MISSING_DATA_INVALID_INPUT", "row count exceeds the diagnostic bound")
    if len(frame.columns) > MAX_DIAGNOSTIC_COLUMNS:
        _reject("MISSING_DATA_INVALID_INPUT", "column count exceeds the diagnostic bound")
    columns = list(frame.columns)
    if any(type(column) is not str or not column for column in columns):
        _reject("MISSING_DATA_INVALID_INPUT", "column names must be non-empty strings")
    if len(set(columns)) != len(columns):
        _reject("MISSING_DATA_INVALID_INPUT", "column names must be unique")
    return sorted(columns)


def _pattern_counts(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    missing = frame.loc[:, columns].isna()
    for row in missing.itertuples(index=False, name=None):
        pattern = "".join("1" if value else "0" for value in row)
        counts[pattern] = counts.get(pattern, 0) + 1
    return [
        {"pattern": pattern, "count": counts[pattern]}
        for pattern in sorted(counts)
    ]


def diagnose_missingness(frame: pd.DataFrame) -> dict[str, Any]:
    """Return deterministic column and joint-pattern missingness evidence.

    The result is intentionally descriptive.  It does not infer or label a
    missingness mechanism and it does not choose an imputation policy.
    """

    columns = _ordered_columns(frame)
    column_evidence = [
        {
            "column": column,
            "missing_count": int(frame[column].isna().sum()),
            "missing_rate": float(frame[column].isna().mean()) if len(frame) else 0.0,
        }
        for column in columns
    ]
    missing_mask = frame.loc[:, columns].isna()
    complete_case_count = int((~missing_mask.any(axis=1)).sum())
    joint_patterns = _pattern_counts(frame, columns)
    evidence_digest = sha256_canonical(
        {
            "n_rows": int(len(frame)),
            "columns": column_evidence,
            "joint_patterns": joint_patterns,
        }
    )
    payload = make_missing_data_result(
        operation_id="missingness.profile",
        status="completed",
        reason_code="MISSING_DATA_DIAGNOSTICS_COMPLETED",
        n_rows=int(len(frame)),
        columns=column_evidence,
        joint_patterns=joint_patterns,
        complete_case_count=complete_case_count,
        rows_with_missing=int(len(frame) - complete_case_count),
        inference_claims=[],
        evidence_digest=evidence_digest,
    )
    return payload


missingness_diagnostics = diagnose_missingness
profile_missingness = diagnose_missingness


__all__ = [
    "MAX_DIAGNOSTIC_COLUMNS",
    "MAX_DIAGNOSTIC_ROWS",
    "diagnose_missingness",
    "missingness_diagnostics",
    "profile_missingness",
]
