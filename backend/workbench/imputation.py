from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

from .artifacts import register_artifact, write_json


def run_mice_imputation(
    frame: pd.DataFrame,
    run_root: Path,
    columns: list[str],
    m: int = 5,
    max_iter: int = 10,
    random_seed: int = 20260429,
    max_missing_rate: float = 0.4,
) -> dict[str, Any]:
    """Run explicit MICE imputation for selected numeric columns."""
    run_root = Path(run_root)
    imputation_dir = run_root / "imputation"
    processed_dir = run_root / "processed"
    imputation_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    selected_columns: list[str] = []
    imputed_columns: list[str] = []
    skipped_columns: list[dict[str, Any]] = []
    seen: set[str] = set()
    for column in columns:
        if column in seen:
            continue
        seen.add(column)
        if column not in frame.columns:
            skipped_columns.append({"column": column, "reason": "not_found"})
            continue
        if not is_numeric_dtype(frame[column]):
            skipped_columns.append({"column": column, "reason": "non_numeric"})
            continue
        missing_rate = float(frame[column].isna().mean())
        if missing_rate > max_missing_rate:
            skipped_columns.append(
                {
                    "column": column,
                    "reason": "missing_rate_above_threshold",
                    "missing_rate": missing_rate,
                    "max_missing_rate": max_missing_rate,
                }
            )
            continue
        selected_columns.append(column)
        if missing_rate > 0:
            imputed_columns.append(column)

    summary: dict[str, Any] = {
        "schema_version": 1,
        "method": "mice",
        "status": "skipped",
        "imputed_columns": imputed_columns,
        "selected_columns": selected_columns,
        "skipped_columns": [item["column"] for item in skipped_columns],
        "m": m,
        "persisted_datasets": 0,
        "pooled_estimates": False,
        "max_iter": max_iter,
        "random_seed": random_seed,
        "max_missing_rate": max_missing_rate,
        "row_count": int(len(frame)),
        "warnings": [],
    }
    decisions = {
        "method": "mice",
        "selected_columns": selected_columns,
        "imputed_columns": imputed_columns,
        "skipped_columns": skipped_columns,
    }

    if imputed_columns and len(selected_columns) >= 2:
        from statsmodels.imputation.mice import MICEData

        imputed = frame.copy()
        mice_input = frame[selected_columns].copy()
        random_state = np.random.get_state()
        try:
            np.random.seed(random_seed)
            mice_data = MICEData(mice_input)
            for _ in range(max_iter):
                mice_data.update_all()
            imputed.loc[:, selected_columns] = mice_data.data[selected_columns]
        finally:
            np.random.set_state(random_state)

        remaining_missing = [
            column for column in imputed_columns if int(imputed[column].isna().sum()) > 0
        ]
        if remaining_missing:
            summary["warnings"].append(
                "MICE did not fill all selected missing values; no imputed dataset was persisted."
            )
            summary["remaining_missing_columns"] = remaining_missing
        else:
            imputed_path = processed_dir / "imputed_dataset.parquet"
            imputed.to_parquet(imputed_path, index=False)
            register_artifact(
                run_root,
                "imputed_dataset",
                imputed_path,
                "processed_data",
                "imputation",
                ["cleaned_dataset"],
            )
            summary["status"] = "completed"
            summary["persisted_datasets"] = 1

    summary["warnings"].extend(
        _imputation_warnings(selected_columns, imputed_columns, skipped_columns, m)
    )

    summary_path = imputation_dir / "mice_summary.json"
    decisions_path = imputation_dir / "mice_decisions.json"
    write_json(summary_path, summary)
    write_json(decisions_path, decisions)
    register_artifact(
        run_root,
        "mice_summary",
        summary_path,
        "metadata",
        "imputation",
        ["cleaned_dataset"],
    )
    register_artifact(
        run_root,
        "mice_decisions",
        decisions_path,
        "metadata",
        "imputation",
        ["cleaned_dataset"],
    )
    return summary


def _imputation_warnings(
    selected_columns: list[str],
    imputed_columns: list[str],
    skipped_columns: list[dict[str, Any]],
    m: int,
) -> list[str]:
    warnings: list[str] = []
    if not selected_columns:
        warnings.append("No supported numeric columns were available for MICE.")
    elif not imputed_columns:
        warnings.append("No selected numeric columns had missing values to impute.")
    elif len(selected_columns) < 2:
        warnings.append("MICE requires at least two supported numeric columns.")
    if skipped_columns:
        names = ", ".join(str(item["column"]) for item in skipped_columns)
        warnings.append(f"Skipped unsupported columns during MICE: {names}.")
    if m != 1:
        warnings.append(
            "This preprocessing step persists one imputed dataset; pooled multiple-imputation "
            "estimates are not produced."
        )
    return warnings
