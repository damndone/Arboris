"""Manifest / lineage / recorder-flush infra extracted from orchestrator.

Verbatim move from orchestrator.py (V1.5.4.5, behavior-frozen). Consumed by
validation/estimation/pre_estimation/report stages + api.py via the
workbench.orchestrator.* re-export namespace.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..artifacts import read_json, write_json
from ..graph_recorder import GraphRecorder


def _safe_flush_recorder(recorder: GraphRecorder, *, context: str) -> None:
    """Persist lineage best-effort. Lineage is observability, not correctness —
    a write failure must not promote a blocked run to errored."""
    try:
        recorder.flush()
    except Exception as exc:  # noqa: BLE001
        import warnings as _warnings
        _warnings.warn(
            f"Failed to flush lineage graph ({context}): {exc!r}",
            RuntimeWarning, stacklevel=2,
        )


def _primary_model_summary(run_root: Path) -> dict[str, str | None]:
    model_dir = run_root / "model_results"
    if not model_dir.is_dir():
        return {"model_id": None, "model_type": None}
    for model_file in ("ols_1.json", "logit_1.json", "poisson_1.json"):
        path = model_dir / model_file
        if path.is_file():
            data = read_json(path)
            return {
                "model_id": data.get("model_id"),
                "model_type": data.get("model_type"),
            }
    return {"model_id": None, "model_type": None}


def _result_contract_summary(run_root: Path) -> dict[str, Any] | None:
    """Expose persisted OLS contract metadata without deriving legacy fields."""
    model_dir = run_root / "model_results"
    if not model_dir.is_dir():
        return None
    for path in sorted(model_dir.glob("*.json")):
        data = read_json(path)
        if not isinstance(data, dict) or data.get("contract_version") is None:
            continue
        if data.get("model") != "ols":
            continue
        return {
            key: data.get(key)
            for key in (
                "contract_version",
                "model",
                "model_type",
                "covariance",
                "covariance_wire",
                "entity_col",
                "source_eligible",
                "stable_result_ids",
                "candidate_result_ids",
                "primary_estimand",
                "dataset_snapshot_fingerprint",
                "analysis_sample_fingerprint",
                "point_estimation_fingerprint",
                "coefficient_schema_fingerprint",
                "inference_config_fingerprint",
                "covariance_evidence",
            )
        }
    return None


def _lineage(input_files: list[Path]) -> list[dict[str, str]]:
    return [
        {"source": str(path), "artifact_id": f"raw_{Path(path).name}"}
        for path in input_files
    ]


def _build_model_routing_summary(
    frame: pd.DataFrame,
    y: str,
    *,
    requested_model_type: str,
    data_detected_y_type: str,
    effective_y_type: str,
    model_results: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    series = frame[y].dropna() if y in frame.columns else pd.Series(dtype="float64")
    numeric = pd.to_numeric(series, errors="coerce")
    numeric_present = numeric.dropna()
    integer_like = False
    if not numeric_present.empty:
        integer_like = bool((numeric_present == numeric_present.astype(int)).all())
    effective_model_id = model_results[0][0] if model_results else None
    effective_model_type = (
        model_results[0][1].get("model_type") if model_results else None
    )
    return {
        "requested_model_type": requested_model_type,
        "current_y": y,
        "dtype": str(series.dtype),
        "min": float(numeric_present.min()) if not numeric_present.empty else None,
        "max": float(numeric_present.max()) if not numeric_present.empty else None,
        "unique": int(series.nunique()),
        "integer_like": integer_like,
        "data_detected_y_type": data_detected_y_type,
        "effective_y_type": effective_y_type,
        "effective_model_id": effective_model_id,
        "effective_model_type": effective_model_type,
    }


def _write_manifest(
    run_root: Path,
    run_id: str,
    mode: str,
    status: str,
    lineage: list[dict[str, str]],
    *,
    started_at: str,
    y: str,
    x: list[str],
    requested_model_type: str | None = None,
    model_routing: dict[str, Any] | None = None,
    rerun_of: str | None = None,
) -> None:
    existing_lineage: dict[str, Any] = {}
    existing_path = run_root / "run_manifest.json"
    if existing_path.is_file():
        try:
            existing = read_json(existing_path)
        except (OSError, ValueError, TypeError):
            existing = None
        if isinstance(existing, dict):
            for field in (
                "rerun_of",
                "from_node",
                "rerun_reason",
                "source_lineage",
                "rerun_from",
                "source_run_id",
            ):
                if field in existing:
                    existing_lineage[field] = existing[field]
    payload: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "status": status,
        "started_at": started_at,
        "y": y,
        "x": list(x),
        "lineage": lineage,
    }
    payload.update(existing_lineage)
    if requested_model_type is not None:
        payload["requested_model_type"] = requested_model_type
    if model_routing is not None:
        payload["model_routing"] = model_routing
    if rerun_of is not None:
        payload["rerun_of"] = rerun_of
    contract = _result_contract_summary(run_root)
    if contract is not None:
        payload["result_contract"] = contract
    write_json(
        run_root / "run_manifest.json",
        payload,
    )
