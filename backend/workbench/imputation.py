from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

from .artifacts import register_artifact, write_json


MAX_MICE_DATASETS = 1_000
MAX_MICE_ITERATIONS = 10_000
MAX_MICE_SEED = (1 << 63) - 1


def _validate_mice_options(
    *, m: int, max_iter: int, random_seed: int, max_missing_rate: float
) -> None:
    if type(m) is not int or isinstance(m, bool) or not 1 <= m <= MAX_MICE_DATASETS:
        raise ValueError(
            f"MICE_INVALID_M: m must be an integer between 1 and {MAX_MICE_DATASETS}"
        )
    if (
        type(max_iter) is not int
        or isinstance(max_iter, bool)
        or not 1 <= max_iter <= MAX_MICE_ITERATIONS
    ):
        raise ValueError(
            "MICE_INVALID_MAX_ITER: max_iter must be a positive bounded integer"
        )
    if (
        type(random_seed) is not int
        or isinstance(random_seed, bool)
        or not 0 <= random_seed <= MAX_MICE_SEED
    ):
        raise ValueError("MICE_INVALID_SEED: random_seed must be a bounded integer")
    if (
        type(max_missing_rate) not in {int, float}
        or isinstance(max_missing_rate, bool)
        or not math.isfinite(float(max_missing_rate))
        or not 0.0 <= float(max_missing_rate) <= 1.0
    ):
        raise ValueError(
            "MICE_INVALID_MISSING_RATE: max_missing_rate must be between 0 and 1"
        )


def _derive_mice_seed(base_seed: int, replicate_index: int) -> int:
    if replicate_index == 0:
        # Preserve the established single-imputation seed semantics.  Adding
        # m>1 must not silently perturb existing m=1 artifacts or their model
        # results.
        return base_seed % (1 << 32)
    material = f"mice:v1:{base_seed}:{replicate_index}".encode("ascii")
    # statsmodels' MICEData uses numpy's legacy seed API, whose accepted range
    # is uint32.  The seed is still derived cryptographically and recorded in
    # the manifest so the dataset order remains explicit and reproducible.
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big")


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

    _validate_mice_options(
        m=m,
        max_iter=max_iter,
        random_seed=random_seed,
        max_missing_rate=max_missing_rate,
    )
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
        "mode": "single_imputation" if m == 1 else "multiple_imputation",
        "status": "skipped",
        "input_artifact": "cleaned_dataset",
        "output_artifact": None,
        "output_artifacts": [],
        "imputed_columns": imputed_columns,
        "selected_columns": selected_columns,
        "skipped_columns": [item["column"] for item in skipped_columns],
        "m": m,
        "persisted_datasets": 0,
        "pooled_estimates": False,
        "dataset_artifacts": [],
        "manifest_artifact": None,
        "derived_seeds": [],
        "max_iter": max_iter,
        "random_seed": random_seed,
        "max_missing_rate": max_missing_rate,
        "row_count": int(len(frame)),
        "rows_imputed": int(frame[imputed_columns].isna().sum().sum())
        if imputed_columns
        else 0,
        "warnings": [],
    }
    decisions = {
        "method": "mice",
        "mode": "single_imputation" if m == 1 else "multiple_imputation",
        "selected_columns": selected_columns,
        "imputed_columns": imputed_columns,
        "skipped_columns": skipped_columns,
    }

    if imputed_columns and len(selected_columns) >= 2:
        from statsmodels.imputation.mice import MICEData

        mice_input = frame[selected_columns].copy()
        completed_datasets: list[tuple[int, pd.DataFrame]] = []
        remaining_by_dataset: dict[int, list[str]] = {}
        for replicate_index in range(m):
            derived_seed = _derive_mice_seed(random_seed, replicate_index)
            summary["derived_seeds"].append(derived_seed)
            imputed = frame.copy()
            random_state = np.random.get_state()
            try:
                np.random.seed(derived_seed)
                mice_data = MICEData(mice_input.copy(deep=True))
                for _ in range(max_iter):
                    mice_data.update_all()
                imputed.loc[:, selected_columns] = mice_data.data[selected_columns]
            except Exception as exc:
                summary["status"] = "failed"
                summary["failure_reason"] = "MICE_COMPLETION_FAILED"
                summary["warnings"].append(
                    f"MICE dataset {replicate_index + 1} failed closed: {type(exc).__name__}."
                )
                break
            finally:
                np.random.set_state(random_state)

            remaining_missing = [
                column for column in imputed_columns if int(imputed[column].isna().sum()) > 0
            ]
            try:
                finite_values = imputed.loc[:, selected_columns].to_numpy(dtype=float)
            except (TypeError, ValueError):
                finite_values = np.array([], dtype=float)
            if remaining_missing or not np.isfinite(finite_values).all():
                remaining_by_dataset[replicate_index] = remaining_missing
                break
            completed_datasets.append((derived_seed, imputed))

        if len(completed_datasets) != m:
            if summary["status"] != "failed":
                summary["warnings"].append(
                    "MICE did not fill all selected missing values; no imputed dataset was persisted."
                )
                summary["status"] = "skipped"
            if remaining_by_dataset:
                summary["remaining_missing_columns"] = sorted(
                    {
                        column
                        for columns in remaining_by_dataset.values()
                        for column in columns
                    }
                )
            # No dataset is written until every requested replicate has passed
            # validation; a partial MI set cannot be mistaken for a valid pool.
        elif m == 1:
            derived_seed, imputed = completed_datasets[0]
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
            summary["dataset_artifacts"] = [
                {
                    "artifact_id": "imputed_dataset",
                    "path": "processed/imputed_dataset.parquet",
                    "seed": derived_seed,
                }
            ]
            summary["output_artifact"] = "imputed_dataset"
            summary["output_artifacts"] = ["imputed_dataset"]
        else:
            dataset_records: list[dict[str, str]] = []
            seed_bindings: list[dict[str, Any]] = []
            for index, (derived_seed, imputed) in enumerate(completed_datasets, start=1):
                artifact_id = f"imputed_dataset_{index:04d}"
                relative_path = f"processed/{artifact_id}.parquet"
                imputed_path = processed_dir / f"{artifact_id}.parquet"
                imputed.to_parquet(imputed_path, index=False)
                register_artifact(
                    run_root,
                    artifact_id,
                    imputed_path,
                    "processed_data",
                    "imputation",
                    ["cleaned_dataset"],
                )
                dataset_records.append({"artifact_id": artifact_id, "path": relative_path})
                seed_bindings.append({"artifact_id": artifact_id, "seed": derived_seed})
            manifest = {
                "schema_version": 1,
                "method": "mice",
                "mode": "multiple_imputation",
                "count": m,
                "selected_columns": list(selected_columns),
                "datasets": dataset_records,
                "seed_bindings": seed_bindings,
                "base_seed": random_seed,
                "max_iter": max_iter,
            }
            manifest_path = imputation_dir / "mice_manifest.json"
            write_json(manifest_path, manifest)
            register_artifact(
                run_root,
                "mice_manifest",
                manifest_path,
                "metadata",
                "imputation",
                ["cleaned_dataset"],
            )
            summary["status"] = "completed"
            summary["persisted_datasets"] = m
            summary["dataset_artifacts"] = [
                {
                    "artifact_id": record["artifact_id"],
                    "path": record["path"],
                    "seed": binding["seed"],
                }
                for record, binding in zip(dataset_records, seed_bindings)
            ]
            summary["manifest_artifact"] = "mice_manifest"
            summary["output_artifact"] = "mice_manifest"
            summary["output_artifacts"] = [
                record["artifact_id"] for record in dataset_records
            ]

    summary["warnings"].extend(
        _imputation_warnings(
            selected_columns,
            imputed_columns,
            skipped_columns,
            m,
            int(summary["persisted_datasets"]),
        )
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
    persisted_datasets: int,
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
    if m > 1 and persisted_datasets == m:
        warnings.append(
            "Multiple-imputation datasets were persisted; pooled estimates require a declared "
            "model adapter and are not produced by preprocessing alone."
        )
    return warnings
