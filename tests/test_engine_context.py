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
