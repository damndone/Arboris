"""Confirmation-time materialization for upload-rooted Notebook workflows."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from filelock import FileLock

from ..agent.notebook.store import ProjectionSource
from ..artifacts import (
    read_json,
    register_artifact,
    write_environment_snapshot,
    write_json,
    write_text_durable,
)
from ..config import load_config
from ..data_operations import resolve_data_column_cast_context
from ..graph_model import Stage
from ..graph_recorder import GraphRecorder
from ..graph_store import GraphStore
from ..ingestion import read_frame_bounded
from ..lineage.run_family import assert_run_in_family, bind_run_to_family
from ..lineage.run_inputs import read_run_inputs, write_run_inputs
from ..lineage.upload_store import verify_upload


SOURCE_RUN_MODE = "notebook_source"


def _verified_upload_source(
    project_root: Path,
    source: ProjectionSource,
) -> tuple[Path, Any]:
    """Resolve one deferred upload source and read it under the execution limits."""

    if source.kind != "dataset" or source.workflow_source is None:
        raise ValueError("upload source requires a dataset workflow source")
    workflow_source = source.workflow_source
    if workflow_source.source_kind != "dataset_upload":
        raise ValueError("only a deferred dataset upload may be read directly")
    if Path(str(source.filename)).name != source.filename:
        raise ValueError("dataset upload filename must be pathless")
    if workflow_source.node_ref != "stage:raw":
        raise ValueError("dataset upload workflow source must target stage:raw")
    if workflow_source.artifact_id != f"raw_{source.filename}":
        raise ValueError("dataset upload workflow artifact identity is inconsistent")
    if workflow_source.source_sha256 != source.upload_sha256:
        raise ValueError("dataset upload workflow fingerprint is inconsistent")

    upload_path = verify_upload(project_root, str(source.upload_sha256))
    config = load_config(project_root / "config.yml")
    if upload_path.stat().st_size / (1024**3) > config.max_single_file_gb:
        raise ValueError("dataset upload exceeds the configured source size limit")
    frame, truncated = read_frame_bounded(
        upload_path,
        max_rows=config.max_rows,
        max_excel_sheets=config.max_excel_sheets,
        sheet_name=source.sheet_names[0] if source.sheet_names else None,
        file_suffix=Path(str(source.filename)).suffix.lower(),
    )
    if truncated:
        raise ValueError("dataset upload exceeds the configured row limit")
    return upload_path, frame


def read_notebook_upload_frame(
    project_root: Path,
    source: ProjectionSource,
):
    """Read a verified upload for planning checks without materializing a Run."""

    _path, frame = _verified_upload_source(project_root, source)
    return frame


def _verify_existing_source(
    project_root: Path,
    *,
    source: ProjectionSource,
    run_family_id: str,
) -> dict[str, Any]:
    workflow_source = source.workflow_source
    if workflow_source is None:
        raise ValueError("dataset projection has no workflow source")
    run_root = project_root / "runs" / workflow_source.run_id
    manifest = read_json(run_root / "run_manifest.json")
    if (
        manifest.get("run_id") != workflow_source.run_id
        or manifest.get("mode") != SOURCE_RUN_MODE
        or manifest.get("status") != "completed"
    ):
        raise ValueError("reserved Notebook source Run is incomplete or inconsistent")
    assert_run_in_family(
        project_root,
        run_family_id=run_family_id,
        run_id=workflow_source.run_id,
    )
    inputs = read_run_inputs(run_root)
    upload = inputs.get("upload")
    if not isinstance(upload, dict) or upload != {
        "sha256": source.upload_sha256,
        "filename": source.filename,
    }:
        raise ValueError("reserved Notebook source Run upload identity changed")
    context = resolve_data_column_cast_context(
        project_root,
        source_run_id=workflow_source.run_id,
        source_node_id=workflow_source.node_ref,
    )
    if (
        context.get("source_artifact_id") != workflow_source.artifact_id
        or context.get("source_sha256") != workflow_source.source_sha256
    ):
        raise ValueError("reserved Notebook source artifact identity changed")
    return context


def materialize_notebook_upload_source(
    project_root: Path,
    *,
    source: ProjectionSource,
    run_family_id: str,
) -> dict[str, Any]:
    """Create or verify the exact source-only Run reserved during planning.

    Nothing is materialized until the user confirms a typed workflow.  An
    existing directory is never repaired or replaced: it must verify exactly,
    otherwise confirmation fails closed.
    """

    upload_path, _frame = _verified_upload_source(project_root, source)
    workflow_source = source.workflow_source
    assert workflow_source is not None
    config_path = project_root / "config.yml"
    config = load_config(config_path)

    runs_root = project_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    run_root = runs_root / workflow_source.run_id
    lock = FileLock(str(runs_root / f".{workflow_source.run_id}.materialize.lock"))
    with lock:
        if run_root.exists():
            return _verify_existing_source(
                project_root,
                source=source,
                run_family_id=run_family_id,
            )
        run_root.mkdir(parents=False, exist_ok=False)
        for dirname in (
            "raw_snapshot",
            "staged",
            "processed",
            "model_results",
            "figures",
            "tables",
            "reports",
            "exports",
        ):
            (run_root / dirname).mkdir(parents=False, exist_ok=False)
        write_json(
            run_root / "run_manifest.json",
            {
                "run_id": workflow_source.run_id,
                "mode": SOURCE_RUN_MODE,
                "status": "created",
                "lineage": [],
            },
        )
        write_environment_snapshot(
            run_root / "environment.json",
            config_path=config_path,
            random_seed=config.random_seed,
        )
        write_text_durable(run_root / "workflow_log.jsonl", "")
        write_json(run_root / "decisions.json", {"decisions": []})
        write_json(run_root / "errors.json", {"issues": []})
        write_json(run_root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})

        raw_path = run_root / "raw_snapshot" / str(source.filename)
        shutil.copy2(upload_path, raw_path)
        raw_record = register_artifact(
            run_root,
            workflow_source.artifact_id,
            raw_path,
            "raw_data",
            "notebook.source.materialize",
            [],
        )
        if raw_record.sha256 != workflow_source.source_sha256:
            raise ValueError("materialized Notebook source fingerprint changed")
        write_run_inputs(
            run_root,
            form={
                **(
                    {"sheet_name": source.sheet_names[0]}
                    if source.sheet_names
                    else {}
                )
            },
            upload={"sha256": source.upload_sha256, "filename": source.filename},
            rerun_of=None,
            from_node=None,
            rerun_reason="notebook_source_materialization",
            override_hash=None,
            dag_hash=workflow_source.source_sha256,
            source_lineage={
                "kind": "dataset_upload",
                "workflow_source_run_id": workflow_source.run_id,
            },
        )
        bind_run_to_family(
            run_root,
            run_family_id=run_family_id,
            bound_by="notebook_source_materialization",
        )
        recorder = GraphRecorder(
            run_id=workflow_source.run_id,
            store=GraphStore(runs_root),
        )
        recorder.record_stage(
            node_id=workflow_source.node_ref,
            display_label="Uploaded source",
            payload_ref=raw_path.relative_to(run_root).as_posix(),
            stage=Stage.SOURCE,
            node_hash=workflow_source.source_sha256,
        )
        recorder.flush()
        write_json(
            run_root / "run_manifest.json",
            {
                "run_id": workflow_source.run_id,
                "mode": SOURCE_RUN_MODE,
                "status": "completed",
                "lineage": [
                    {
                        "step": "notebook.source.materialize",
                        "artifact_id": workflow_source.artifact_id,
                        "source_sha256": workflow_source.source_sha256,
                    }
                ],
            },
        )
        return _verify_existing_source(
            project_root,
            source=source,
            run_family_id=run_family_id,
        )


__all__ = [
    "SOURCE_RUN_MODE",
    "materialize_notebook_upload_source",
    "read_notebook_upload_frame",
]
