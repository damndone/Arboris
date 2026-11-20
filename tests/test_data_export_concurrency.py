"""Two exports of one node at once each publish the bytes they wrote.

2026-11-06 risk review, finding 3 (rechecked at 9e09502e): the staging file was named by node
and format only. With A writing column a, then B writing column b, then A publishing, A
reported column a while its file held column b, and B failed with FileNotFoundError.
The real writer runs unchanged; only the order of its returns is arranged.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.artifacts import read_json
from workbench.services import data_export


@pytest.fixture
def project(tmp_path):
    root, run_id, _ = _source_project(tmp_path, pd.DataFrame({"a": range(20), "b": range(100, 120)}))
    (root / "runs" / run_id / "run_inputs.json").write_text("{}")
    return root, run_id


def _exported(root, run_id, result):
    path = root / "runs" / run_id / "exports" / "data" / result["download_url"].rsplit("_", 1)[-1] / result["filename"]
    return path.read_text().splitlines()


def test_interleaved_exports_each_publish_their_own_columns(project, monkeypatch):
    root, run_id = project
    real = data_export.write_prepared
    a_written, b_written = threading.Event(), threading.Event()

    def arranged(prepared, path):
        report = real(prepared, path)
        if list(prepared.data.columns) == ["a"]:
            a_written.set()
            assert b_written.wait(10)  # B writes before A publishes
        else:
            b_written.set()
        return report

    monkeypatch.setattr(data_export, "write_prepared", arranged)

    def export(column):
        return data_export.export_dataset(root, run_id, "stage:source",
                                          {"format": "csv", "columns": [column], "filename": column})

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(export, "a")
        assert a_written.wait(10)
        second = pool.submit(export, "b")
        results = {"a": first.result(timeout=20), "b": second.result(timeout=20)}

    for column, result in results.items():
        assert result["report"]["column_names"] == [column]
        lines = _exported(root, run_id, result)
        assert lines[0] == column and lines[1] == ("0" if column == "a" else "100")
    directory = root / "runs" / run_id / "exports" / "data"
    assert not [path for path in directory.iterdir() if path.name.startswith(".staging")]


def test_the_same_export_twice_at_once_registers_one_artifact(project):
    root, run_id = project
    options = {"format": "csv", "columns": ["a"], "filename": "same"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: data_export.export_dataset(root, run_id, "stage:source", options), range(4)))
    assert len({result["artifact_id"] for result in results}) == 1
    index = read_json(root / "runs" / run_id / "artifacts_index.json")
    assert [record["artifact_id"] for record in index["artifacts"]].count(results[0]["artifact_id"]) == 1


def test_a_failed_write_leaves_no_staging_behind(project, monkeypatch):
    root, run_id = project

    def failing(prepared, path):
        path.write_text("half")
        raise OSError("disk full")

    monkeypatch.setattr(data_export, "write_prepared", failing)
    with pytest.raises(OSError):
        data_export.export_dataset(root, run_id, "stage:source", {"format": "csv", "columns": ["a"]})
    directory = root / "runs" / run_id / "exports" / "data"
    assert not [path for path in directory.iterdir() if path.name.startswith(".staging")]
