from __future__ import annotations

from pathlib import Path

from ...graph_model import Stage as DomainStage
from ...ingestion import ingest_files
from ...metadata import infer_schema
from ..context import DataHandle, ModelingContext, RunEnv


class SourceStage:
    """Ingest input files, infer schema, and record the raw-input graph node.

    Extracted verbatim from orchestrator._run_workflow (the ~396-412 block) as
    the first stage of the V1.5.4 engine decomposition. Behavior must stay
    byte-identical.
    """

    name = "source"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        input_files = ctx.artifacts["_input_files"]
        config = ctx.artifacts["_config"]
        sheet_name = ctx.artifacts["_sheet_name"]
        transpose = ctx.artifacts["_transpose"]

        env.step("ingestion", "start", "Ingesting files...")
        frames = ingest_files(
            [Path(path) for path in input_files],
            env.run_root,
            config,
            sheet_name,
            transpose,
        )
        env.step("ingestion", "complete", f"Ingested {len(frames)} file(s)")

        env.step("schema", "start", "Inferring schema...")
        schema = infer_schema("dataset_1", frames, env.run_root)
        env.step(
            "schema", "complete", f"Inferred schema with {len(schema.columns)} columns"
        )
        frame = next(iter(frames.values()))
        labels = ctx.artifacts.get("_labels", {})
        if isinstance(labels, dict):
            variable_labels = labels.get("variable_labels", {})
            value_labels = labels.get("value_labels", {})
            for source_frame in frames.values():
                source_frame.attrs["variable_labels"] = dict(variable_labels)
                source_frame.attrs["value_labels"] = {
                    str(column): dict(mapping)
                    for column, mapping in value_labels.items()
                }
        raw_row_count = len(frame)
        raw_col_count = len(frame.columns)
        env.recorder.record_stage(
            node_id="stage:raw",
            display_label="Raw input data",
            payload_ref=None,
            summary=f"Raw: {raw_row_count} rows × {raw_col_count} cols",
            stage=DomainStage.SOURCE,
        )

        ctx = ctx.with_data(
            DataHandle.of(
                frame,
                artifact_id="raw",
                provenance=tuple(f"raw_{p.name}" for p in input_files),
            )
        )
        ctx.artifacts["_frames"] = frames
        ctx.artifacts["_schema"] = schema
        ctx.artifacts["_raw_row_count"] = raw_row_count
        ctx.artifacts["_raw_col_count"] = raw_col_count
        return ctx
