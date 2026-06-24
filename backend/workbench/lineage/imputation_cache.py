"""Materialized MICE imputation cache (Loop 2A.5).

MICE is the one upstream stage that is both genuinely expensive AND cleanly
materializable (its whole contribution is a parquet frame + a summary dict + a
DataHandle swap — no custom-object ctx state). So it is the first real
compute-skip in v1.6.1: a rerun whose imputation node_hash matches a prior run
restores the imputed frame from the CAS instead of re-running MICE.

`restore_imputation` reproduces EXACTLY what `ImputationStage.run` does on a
completed-MICE path, so downstream artifacts are byte-identical:
  - writes processed/imputed_dataset.parquet + imputation_summary.json (run-relative, G2)
  - registers the imputation_summary artifact
  - swaps ctx.data to the imputed DataHandle and sets _imputation_summary / _model_input_ids
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..artifacts import read_json, register_artifact, write_json
from ..engine.context import DataHandle, ModelingContext
from .node_store import node_result_exists, read_node_result, write_node_result

_IMPUTED_PARQUET = "imputed_dataset.parquet"
_SUMMARY_JSON = "imputation_summary.json"


def imputation_cached(project_root: Path, node_hash: str) -> bool:
    return node_result_exists(project_root, node_hash)


def materialize_imputation(project_root: Path, node_hash: str, run_root: Path) -> None:
    """After a completed MICE run, copy its run-relative outputs into the CAS,
    keyed by the imputation node_hash. Idempotent (node_store no-ops on repeat)."""
    parquet = (run_root / "processed" / _IMPUTED_PARQUET).read_bytes()
    summary = read_json(run_root / _SUMMARY_JSON)
    write_node_result(
        project_root, node_hash,
        meta={"summary": summary},
        artifacts={_IMPUTED_PARQUET: parquet, _SUMMARY_JSON: (run_root / _SUMMARY_JSON).read_bytes()},
    )


def restore_imputation(
    project_root: Path, node_hash: str, run_root: Path, ctx: ModelingContext,
) -> ModelingContext:
    """Restore a cached MICE result into this run WITHOUT re-running MICE. Mirrors
    ImputationStage.run's completed path so artifacts are byte-identical."""
    cached = read_node_result(project_root, node_hash)
    summary = cached["meta"]["summary"]

    processed_dir = run_root / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    (processed_dir / _IMPUTED_PARQUET).write_bytes(cached["artifacts"][_IMPUTED_PARQUET])

    summary_path = run_root / _SUMMARY_JSON
    write_json(summary_path, summary)
    register_artifact(
        run_root, "imputation_summary", summary_path,
        "metadata", "imputation", ["cleaned_dataset"],
    )

    imputed = pd.read_parquet(processed_dir / _IMPUTED_PARQUET)
    ctx = ctx.with_data(
        DataHandle.of(imputed, artifact_id="imputed_dataset", provenance=("cleaned_dataset",))
    )
    ctx.artifacts["_imputation_summary"] = summary
    ctx.artifacts["_model_input_ids"] = [ctx.data.artifact_id]
    return ctx
