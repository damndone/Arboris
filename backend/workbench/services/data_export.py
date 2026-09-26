"""Export a run's dataset node to SPSS or Stata, with its declared labels.

The exported file is an immutable run artifact named by its content hash, so
exporting the same data and labels twice returns the same artifact, and a label
edit followed by a re-export produces a new one. The export report lists every
rename and every piece of metadata the target format could not carry.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ..artifacts import read_json, register_artifact, write_json
from ..data_operations import _read_frame, resolve_data_column_cast_context
from ..lineage.run_inputs import read_run_inputs
from ..repository.run_repository import _resolve_run_root
from ..tabular_io import write_statistical

EXPORT_FORMATS = ("sav", "zsav", "dta")


def _slug(node_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", node_id).strip("-") or "dataset"


def _registered(run_root: Path, artifact_id: str) -> bool:
    index = read_json(run_root / "artifacts_index.json")
    return any(record.get("artifact_id") == artifact_id for record in index.get("artifacts", []))


def export_dataset(project_root: Path | str, run_id: str, node_id: str, fmt: str) -> dict[str, Any]:
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"unsupported export format: {fmt}")
    run_root = _resolve_run_root(str(project_root), run_id)
    context = resolve_data_column_cast_context(
        project_root, source_run_id=run_id, source_node_id=node_id
    )
    frame = _read_frame(run_root / context["source_artifact_path"])
    labels = (read_run_inputs(run_root).get("form") or {}).get("labels") or {}

    directory = run_root / "exports" / "data"
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / f".staging-{_slug(node_id)}.{fmt}"
    report = write_statistical(frame, labels, staging, fmt)
    digest = hashlib.sha256(staging.read_bytes()).hexdigest()[:16]
    stem = f"{_slug(node_id)}-{digest}"
    target = directory / f"{stem}.{fmt}"
    staging.replace(target)
    report_path = directory / f"{stem}.{fmt}.report.json"
    payload = {
        "run_id": run_id,
        "node_id": node_id,
        "source_artifact_id": context["source_artifact_id"],
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        **report.to_dict(),
    }
    write_json(report_path, payload)

    artifact_id = f"data_export_{fmt}_{digest}"
    if not _registered(run_root, artifact_id):
        register_artifact(
            run_root, artifact_id, target, "data_export", "export", [context["source_artifact_id"]]
        )
    return {
        "artifact_id": artifact_id,
        "filename": target.name,
        "download_url": f"/runs/{run_id}/artifacts/{artifact_id}",
        "report": payload,
    }
