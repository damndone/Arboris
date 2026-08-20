from __future__ import annotations

import importlib
import importlib.util

import pandas as pd
import pytest


def _api():
    if importlib.util.find_spec("workbench.data_interchange") is None:
        pytest.fail("workbench.data_interchange is not implemented")
    return importlib.import_module("workbench.data_interchange")


def test_csv_xlsx_and_parquet_round_trip_contract_is_real(tmp_path) -> None:
    api = _api()
    frame = pd.DataFrame({"code": [1, 2], "label": ["a", "b"]})
    metadata = {
        "code": {
            "variable_label": "Code",
            "value_labels": {"1": "One", "2": "Two"},
            "measurement_level": "nominal",
        }
    }

    for target_format in ("csv", "xlsx", "parquet"):
        capability = api.interchange_capability(target_format)
        result = api.round_trip_frame(
            frame,
            metadata=metadata,
            target_format=target_format,
            directory=tmp_path,
        )
        assert result.target_format == target_format
        if capability.status == "available":
            assert result.status == "verified"
            assert result.frame_equal is True
            assert result.schema_equal is True
            assert result.metadata_loss.schema_version == "metadata-loss-manifest/v1"
        else:
            assert result.status == "unavailable"
            assert result.capability.reason_code == "optional_dependency"


def test_public_writer_creates_real_file_and_reports_schema_boundary(tmp_path) -> None:
    api = _api()
    frame = pd.DataFrame({"code": [1, 2], "label": ["a", "b"]})
    target = tmp_path / "data.parquet"

    result = api.write_interchange_frame(
        frame,
        target_format="parquet",
        path=target,
    )

    assert result.status == "written"
    assert result.target_format == "parquet"
    assert result.path is not None
    assert target.exists()
    restored = pd.read_parquet(target)
    assert list(restored.columns) == ["code", "label"]
    assert restored.dtypes.astype(str).tolist() == frame.dtypes.astype(str).tolist()


def test_missing_parquet_dependency_is_typed_for_writer_and_round_trip(
    tmp_path, monkeypatch
) -> None:
    api = _api()
    frame = pd.DataFrame({"code": [1]})
    original_has_module = api._has_module

    def pretend_missing(module_name: str) -> bool:
        if module_name in {"pyarrow", "fastparquet"}:
            return False
        return original_has_module(module_name)

    monkeypatch.setattr(api, "_has_module", pretend_missing)
    target = tmp_path / "missing.parquet"

    write_result = api.write_interchange_frame(
        frame,
        target_format="parquet",
        path=target,
    )
    round_trip_result = api.round_trip_frame(
        frame,
        metadata={},
        target_format="parquet",
        directory=tmp_path,
    )

    assert write_result.status == "unavailable"
    assert write_result.path is None
    assert write_result.capability.status == "unavailable"
    assert write_result.capability.reason_code == "optional_dependency"
    assert not target.exists()
    assert round_trip_result.status == "unavailable"
    assert round_trip_result.capability.reason_code == "optional_dependency"


def test_native_statistical_formats_are_typed_unavailable_without_optional_dependency() -> None:
    api = _api()

    for target_format in ("sav", "zsav", "dta"):
        capability = api.interchange_capability(target_format)
        assert capability.status == "unavailable"
        assert capability.reason_code == "optional_dependency"


def test_native_statistical_writer_is_typed_unavailable_without_optional_dependency(
    tmp_path,
) -> None:
    api = _api()
    frame = pd.DataFrame({"code": [1]})

    for target_format in ("sav", "zsav", "dta"):
        target = tmp_path / f"data.{target_format}"
        result = api.write_interchange_frame(
            frame,
            target_format=target_format,
            path=target,
        )
        assert result.status == "unavailable"
        assert result.path is None
        assert result.capability.reason_code == "optional_dependency"
        assert not target.exists()
