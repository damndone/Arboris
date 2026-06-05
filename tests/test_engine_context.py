import pandas as pd
import pytest
from workbench.engine.context import DataHandle


def test_datahandle_binds_frame_and_identity():
    frame = pd.DataFrame({"a": [1, 2, 3]})
    h = DataHandle(frame=frame, artifact_id="cleaned_dataset", provenance=("raw_data.csv",))
    assert h.artifact_id == "cleaned_dataset"
    assert h.provenance == ("raw_data.csv",)
    assert list(h.frame["a"]) == [1, 2, 3]


def test_datahandle_is_frozen():
    h = DataHandle(frame=pd.DataFrame(), artifact_id="x", provenance=())
    with pytest.raises(Exception):
        h.artifact_id = "y"


def test_datahandle_derived_metrics():
    frame = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    h = DataHandle.of(frame, artifact_id="cleaned_dataset", provenance=("r",))
    assert h.row_count == 2
    assert h.column_count == 2


from workbench.engine.context import ModelingContext, RunEnv


def test_modeling_context_with_data_replaces_handle_atomically():
    h1 = DataHandle.of(pd.DataFrame({"a": [1]}), artifact_id="cleaned_dataset", provenance=("r",))
    ctx = ModelingContext(data=h1, y_col="y", x_cols=["x"])
    h2 = DataHandle.of(pd.DataFrame({"a": [2]}), artifact_id="imputed_dataset", provenance=("cleaned_dataset",))
    ctx2 = ctx.with_data(h2)
    assert ctx.data.artifact_id == "cleaned_dataset"
    assert ctx2.data.artifact_id == "imputed_dataset"
    assert ctx2.y_col == "y" and ctx2.x_cols == ["x"]


def test_runenv_holds_side_effect_deps(tmp_path):
    env = RunEnv(run_root=tmp_path, run_id="r1", recorder=object(), on_step=None)
    assert env.run_id == "r1"
    assert env.run_root == tmp_path
