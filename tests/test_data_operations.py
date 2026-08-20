from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench import data_interchange
from workbench import data_operations
from workbench.data_operations import DataTransformSpecV1, preview_data_transform


def test_subset_transform_preview_is_bounded_and_typed(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 2], "value": [10, 20], "secret": ["a", "b"]}),
    )

    preview = preview_data_transform(
        project,
        DataTransformSpecV1(
            source_run_id=run_id,
            source_node_id="stage:source",
            source_artifact_id=artifact_id,
            operation="subset",
            parameters={"columns": ["id", "value"], "equals": {"id": 2}},
        ),
    )

    assert preview.status == "ready"
    assert preview.output_columns == ("id", "value")
    assert preview.row_count_before == 2
    assert preview.row_count_after == 1


def test_data_operation_parquet_read_fails_closed_before_pandas_bypass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"not-read")
    monkeypatch.setattr(data_interchange, "_parquet_engine", lambda: None)

    def unexpected_read(*args, **kwargs):
        raise AssertionError("pandas.read_parquet bypassed engine admission")

    monkeypatch.setattr(pd, "read_parquet", unexpected_read)

    with pytest.raises(data_interchange.InterchangeUnavailableError) as error:
        data_operations._read_frame(source)

    assert error.value.capability.target_format == "parquet"
    assert error.value.capability.status == "unavailable"
    assert error.value.capability.reason_code == "optional_dependency"
