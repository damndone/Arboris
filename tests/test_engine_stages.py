from pathlib import Path

import pandas as pd

from workbench.engine.context import DataHandle, ModelingContext, RunEnv
from workbench.engine.stages import Stage, PIPELINE
from workbench.engine.stages.source import SourceStage
from workbench.graph_recorder import GraphRecorder
from workbench.graph_store import GraphStore
from workbench.projects import create_project, create_run


def test_pipeline_is_ordered_list_of_unique_named_stages():
    assert isinstance(PIPELINE, list)
    names = [s.name for s in PIPELINE]
    assert len(names) == len(set(names))


def test_stage_protocol_shape():
    class Noop:
        name = "noop"

        def run(self, ctx, env):
            return ctx

    s: Stage = Noop()
    assert s.name == "noop"


def test_source_stage_populates_frame_and_schema(tmp_path: Path):
    from workbench.config import load_config

    source = tmp_path / "cross_section.csv"
    pd.DataFrame(
        {
            "y": [1 + 2 * i for i in range(10)],
            "x": list(range(10)),
        }
    ).to_csv(source, index=False)

    project = create_project(tmp_path, "demo")
    run = create_run(project.root, "auto")
    run_root = run.root

    config = load_config(project.root / "config.yml")
    store = GraphStore(runs_root=run_root.parent)
    recorder = GraphRecorder(run_id=run.run_id, store=store)
    env = RunEnv(run_root=run_root, run_id=run.run_id, recorder=recorder, on_step=None)

    input_files = [source]
    ctx = ModelingContext(
        data=DataHandle(
            frame=pd.DataFrame(),
            artifact_id="raw",
            provenance=tuple(f"raw_{p.name}" for p in input_files),
        ),
        y_col="y",
        x_cols=["x"],
    )
    ctx.artifacts["_input_files"] = input_files
    ctx.artifacts["_config"] = config
    ctx.artifacts["_sheet_name"] = None
    ctx.artifacts["_transpose"] = False

    ctx = SourceStage().run(ctx, env)

    assert ctx.data.frame is not None
    assert not ctx.data.frame.empty
    assert ctx.data.artifact_id == "raw"
    assert ctx.artifacts["_schema"] is not None
    assert "_frames" in ctx.artifacts
