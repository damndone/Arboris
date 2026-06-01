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

    summary: dict[str, Any] = {
        "schema_version": 1,
        "method": "mice",
        "status": "skipped" if not selected_columns else "completed",
        "imputed_columns": selected_columns,
        "selected_columns": selected_columns,
        "skipped_columns": [item["column"] for item in skipped_columns],
        "m": m,
        "max_iter": max_iter,
        "random_seed": random_seed,
        "max_missing_rate": max_missing_rate,
        "row_count": int(len(frame)),
        "warnings": [] if selected_columns else ["No supported numeric columns were available for MICE."],
    }
    decisions = {
        "method": "mice",
        "selected_columns": selected_columns,
        "skipped_columns": skipped_columns,
    }

    if selected_columns:
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
