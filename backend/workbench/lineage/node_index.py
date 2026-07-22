"""node_index.json — the 2A.7 bridge mapping graph node_id → stage-output node_hash.

Written by RecordingStage ONLY when the incremental cache is active (i.e. when
ctx carries `_node_hashes`). graph.json itself stays byte-identical (decorate-only,
same philosophy as v1.6.0's serve-layer editable_schema), so golden 0-drift holds
with the flag off and legacy/flag-off runs simply have no node_index (2B treats
them as opaque/legacy heads).

2B reads node_index.json + graph.json to dedup shared-prefix nodes across the rerun
family by node_hash. Each entry also carries cas_ref (node_hash + run-relative
payload) and the producing stage.
"""
from __future__ import annotations

from pathlib import Path

from ..artifacts import write_json

NODE_INDEX_FILENAME = "node_index.json"


def _entry(node_hash: str, producing_stage: str, payload: str) -> dict:
    return {
        "node_hash": node_hash,
        "producing_stage": producing_stage,
        "cas_ref": {"node_hash": node_hash, "artifact": payload},
    }


def build_node_index(
    node_hashes: dict, *, normalized_y, normalized_x, model_results,
    upload_hash: str = "", raw_payload: str = "_uploads",
    extra_entries: dict[str, dict] | None = None,
) -> dict:
    """Map the graph node_ids RecordingStage records to their stage-output node_hash."""
    idx: dict[str, dict] = {}

    # v1.6.11: stage:raw was the one graph node without an identity hash, which
    # left Ask AI permanently disabled on raw dataset nodes (missing_node_hash).
    # The Merkle chain root (content hash of the upload) is its natural identity;
    # same upload across runs dedups to one forest node, which is semantically right.
    if upload_hash:
        idx["stage:raw"] = _entry(upload_hash, "ingestion", raw_payload)

    clean_h = node_hashes.get("cleaning")
    if clean_h:
        idx["stage:cleaned"] = _entry(clean_h, "cleaning", "processed/cleaned_dataset.parquet")
        for var in [normalized_y, *normalized_x]:
            idx[f"var:{var}:cleaned"] = _entry(
                clean_h, "cleaning", "processed/cleaned_dataset.parquet"
            )

    est_h = node_hashes.get("estimation")
    if est_h and model_results:
        primary_model_id = model_results[0][0]
        idx[f"model:{primary_model_id}"] = _entry(
            est_h, "estimation", f"model_results/{primary_model_id}.json"
        )
        report_h = node_hashes.get("report")
        if report_h:
            idx["report:html"] = _entry(report_h, "report", "reports/report.html")

    if extra_entries:
        idx.update(extra_entries)

    return idx


def write_node_index(
    run_root: Path, node_hashes: dict, *, normalized_y, normalized_x, model_results,
    upload_hash: str = "",
    extra_entries: dict[str, dict] | None = None,
) -> None:
    idx = build_node_index(
        node_hashes, normalized_y=normalized_y,
        normalized_x=normalized_x, model_results=model_results,
        upload_hash=upload_hash, raw_payload=_raw_payload(run_root),
        extra_entries=extra_entries,
    )
    write_json(run_root / NODE_INDEX_FILENAME, idx)


def _raw_payload(run_root: Path) -> str:
    """Run-relative path of the first uploaded file (cas_ref is informational)."""
    uploads = run_root / "_uploads"
    try:
        first = next(p for p in sorted(uploads.iterdir()) if p.is_file())
        return f"_uploads/{first.name}"
    except (OSError, StopIteration):
        return "_uploads"
