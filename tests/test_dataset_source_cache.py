"""Paging a verified dataset decodes it once; a changed file is still caught; memory stays bounded.

2026-11-06 risk review, finding 6: every page resolved the cast context, which hashed and decoded
the whole table and dropped it, before the page cache was consulted: three 5-row pages of a 20-row
CSV cost four full decodes, and the page cache kept up to eight whole tables regardless of size.
"""
from __future__ import annotations

import json
import os

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.data_operations import casts, source_cache
from workbench.data_operations.specs import DataColumnCastValidationError
from workbench.services import dataset_view
from workbench.statistical_exploration import resolve_statistical_source


@pytest.fixture
def project(tmp_path):
    source_cache.clear()
    root, run_id, _ = _source_project(tmp_path, pd.DataFrame({"a": range(20), "b": range(100, 120)}))
    yield root, run_id
    source_cache.clear()


@pytest.fixture
def decodes(monkeypatch):
    calls = []
    original = casts._read_frame

    def counted(path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(casts, "_read_frame", counted)
    return calls


def _source_file(root, run_id):
    context, _ = dataset_view.load_dataset(root, run_id, "stage:source")
    return root / "runs" / run_id / context["source_artifact_path"]


def test_paging_decodes_the_table_once(project, decodes):
    root, run_id = project
    pages = [dataset_view.dataset_page(root, run_id, "stage:source", offset=offset, limit=5) for offset in (0, 5, 10)]
    assert [page["rows"][0]["a"] for page in pages] == [0, 5, 10]
    assert len(decodes) == 1


def test_a_changed_source_is_refused_even_with_size_and_mtime_restored(project):
    root, run_id = project
    path = _source_file(root, run_id)
    original = path.read_bytes()
    stat = path.stat()
    changed = original.replace(b"100", b"999", 1)
    assert len(changed) == len(original)
    path.write_bytes(changed)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(DataColumnCastValidationError, match="fingerprint changed"):
        dataset_view.dataset_page(root, run_id, "stage:source", offset=0, limit=5)


@pytest.mark.parametrize("resolver", ["paging", "statistical"])
@pytest.mark.parametrize("replace", [True, False], ids=["replacement", "in-place"])
def test_source_change_during_decode_never_publishes_a_frame(project, monkeypatch, replace, resolver):
    root, run_id = project
    path = _source_file(root, run_id)
    original = path.read_bytes()
    changed = original.replace(b"100", b"999", 1)
    source_cache.clear()
    read_frame = casts._read_frame

    def load_source():
        if resolver == "statistical":
            return resolve_statistical_source(
                root, source_run_id=run_id, source_node_id="stage:source",
                source_artifact_id="source_data",
            )
        return dataset_view.load_dataset(root, run_id, "stage:source")

    def change_then_read(source_path, *args, **kwargs):
        if replace:
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(changed)
            replacement.replace(path)
        else:
            path.write_bytes(changed)
        return read_frame(source_path, *args, **kwargs)

    with monkeypatch.context() as during_decode:
        during_decode.setattr(casts, "_read_frame", change_then_read)
        with pytest.raises(DataColumnCastValidationError, match="fingerprint changed"):
            load_source()
    assert source_cache.cached_bytes() == 0

    with pytest.raises(DataColumnCastValidationError, match="fingerprint changed"):
        load_source()
    path.write_bytes(original)
    context, frame = load_source()
    assert frame.loc[0, "b"] == 100
    assert context["source_sha256"] == casts.sha256_file(path)
    if resolver == "statistical":
        assert source_cache.cached_bytes() == 0


def test_cached_paging_reloads_a_changed_dtype_sidecar(project):
    root, run_id = project
    path = _source_file(root, run_id)
    assert dataset_view.dataset_page(root, run_id, "stage:source")["rows"][0]["b"] == 100

    path.with_suffix(".schema.json").write_text(json.dumps({"dtypes": {"b": "string"}}))
    assert dataset_view.dataset_page(root, run_id, "stage:source")["rows"][0]["b"] == "100"


def test_a_caller_changing_its_frame_leaves_the_cached_frame_alone(project):
    root, run_id = project
    _, first = dataset_view.load_dataset(root, run_id, "stage:source")
    first.loc[0, "a"] = -1
    first["new"] = 1
    _, second = dataset_view.load_dataset(root, run_id, "stage:source")
    assert second.loc[0, "a"] == 0 and "new" not in second.columns


def test_cached_frames_stay_within_the_byte_budget(project, decodes, monkeypatch):
    root, run_id = project
    monkeypatch.setattr(source_cache, "MAX_CACHED_BYTES", 1)
    dataset_view.dataset_page(root, run_id, "stage:source", offset=0, limit=5)
    dataset_view.dataset_page(root, run_id, "stage:source", offset=5, limit=5)
    assert source_cache.cached_bytes() == 0 and len(decodes) == 2


def test_exports_and_previews_keep_nothing_between_requests(project):
    from workbench.services import data_export

    root, run_id = project
    (root / "runs" / run_id / "run_inputs.json").write_text("{}")
    data_export.preview_export(root, run_id, "stage:source", "csv")
    assert source_cache.cached_bytes() == 0
