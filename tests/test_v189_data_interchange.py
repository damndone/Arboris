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
            assert result.status == "metadata_loss"
            assert result.frame_equal is True
            assert result.schema_equal is True
            assert result.metadata_loss.has_loss is True
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


def test_parquet_dependency_matrix_has_one_truthful_semantic(tmp_path, monkeypatch) -> None:
    api = _api()
    from workbench.data_interchange import InterchangeUnavailableError
    from workbench.ingestion import read_frame_bounded

    frame = pd.DataFrame({"code": [1, 2], "label": ["a", "b"]})
    source = tmp_path / "source.parquet"
    source_result = api.write_interchange_frame(
        frame,
        target_format="parquet",
        path=source,
    )
    assert source_result.status == "written"

    original_has_module = api._has_module
    matrices = (
        ("pyarrow-only", {"pyarrow": True, "fastparquet": False}, "pyarrow", "available"),
        ("fastparquet-only", {"pyarrow": False, "fastparquet": True}, None, "unavailable"),
        ("both", {"pyarrow": True, "fastparquet": True}, "pyarrow", "available"),
        ("neither", {"pyarrow": False, "fastparquet": False}, None, "unavailable"),
    )

    for label, availability, expected_engine, expected_status in matrices:
        with monkeypatch.context() as patch:
            def simulated_has_module(
                name: str,
                availability=availability,
                original_has_module=original_has_module,
            ) -> bool:
                if name in availability:
                    return availability[name]
                return original_has_module(name)

            patch.setattr(api, "_has_module", simulated_has_module)
            capability = api.interchange_capability("parquet")
            assert api._parquet_engine() == expected_engine
            assert capability.status == expected_status

            target = tmp_path / f"{label}.parquet"
            write_result = api.write_interchange_frame(
                frame,
                target_format="parquet",
                path=target,
            )
            round_trip_result = api.round_trip_frame(
                frame,
                metadata={},
                target_format="parquet",
                directory=tmp_path / label,
            )

            if expected_status == "available":
                assert write_result.status == "written"
                assert target.exists()
                assert round_trip_result.status == "verified"
                bounded, truncated = read_frame_bounded(source, max_rows=1)
                assert bounded.to_dict(orient="records") == [{"code": 1, "label": "a"}]
                assert truncated is True
                bounded_capability = capability
            else:
                assert write_result.status == "unavailable"
                assert not target.exists()
                assert round_trip_result.status == "unavailable"
                with pytest.raises(InterchangeUnavailableError) as error:
                    read_frame_bounded(source, max_rows=1)
                bounded_capability = error.value.capability

            assert write_result.capability == capability
            assert round_trip_result.capability == capability
            assert bounded_capability == capability
            assert capability.target_format == "parquet"
            assert capability.status == expected_status
            if expected_status == "unavailable":
                assert capability.reason_code == "optional_dependency"


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


def test_broken_pyarrow_import_is_typed_unavailable_for_every_surface(
    tmp_path, monkeypatch
) -> None:
    api = _api()
    frame = pd.DataFrame({"code": [1]})
    original_has_module = api._has_module
    monkeypatch.setattr(
        api,
        "_has_module",
        lambda name: True if name == "pyarrow" else original_has_module(name),
    )

    real_import_module = importlib.import_module

    def broken_import(name: str, package: str | None = None):
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ModuleNotFoundError("pyarrow is installed but cannot be imported")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", broken_import)

    capability = api.interchange_capability("parquet")
    assert capability.status == "unavailable"
    assert capability.reason_code == "optional_dependency"

    write_result = api.write_interchange_frame(
        frame,
        target_format="parquet",
        path=tmp_path / "broken.parquet",
    )
    round_trip_result = api.round_trip_frame(
        frame,
        metadata={},
        target_format="parquet",
        directory=tmp_path / "roundtrip",
    )

    assert write_result.status == "unavailable"
    assert round_trip_result.status == "unavailable"
    with pytest.raises(api.InterchangeUnavailableError) as error:
        api._read_frame("parquet", tmp_path / "missing.parquet")
    assert error.value.capability == capability


def test_broken_pyreadstat_import_is_typed_unavailable_for_native_surfaces(
    tmp_path, monkeypatch
) -> None:
    api = _api()
    frame = pd.DataFrame({"code": [1]})
    original_has_module = api._has_module
    monkeypatch.setattr(
        api,
        "_has_module",
        lambda name: True if name == "pyreadstat" else original_has_module(name),
    )

    real_import_module = importlib.import_module

    def broken_import(name: str, package: str | None = None):
        if name == "pyreadstat":
            raise ModuleNotFoundError("pyreadstat is installed but cannot be imported")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", broken_import)

    for target_format in ("sav", "zsav", "dta"):
        capability = api.interchange_capability(target_format)
        assert capability.status == "unavailable"
        assert capability.reason_code == "optional_dependency"
        write_result = api.write_interchange_frame(
            frame,
            target_format=target_format,
            path=tmp_path / f"broken.{target_format}",
        )
        assert write_result.status == "unavailable"
        with pytest.raises(api.InterchangeUnavailableError) as error:
            api._read_frame(target_format, tmp_path / f"missing.{target_format}")
        assert error.value.capability == capability


def test_malformed_column_metadata_is_typed_and_not_reported_verified(tmp_path) -> None:
    api = _api()

    with pytest.raises(ValueError) as error:
        api.round_trip_frame(
            pd.DataFrame({"code": [1]}),
            metadata={"columns": {"code": "not-a-mapping"}},
            target_format="csv",
            directory=tmp_path,
        )

    assert error.value.reason_code == "metadata_loss"


def test_round_trip_status_is_schema_mismatch_when_dtype_differs(tmp_path, monkeypatch) -> None:
    api = _api()
    source = pd.DataFrame({"code": pd.Series([1], dtype="int64")})
    restored = pd.DataFrame({"code": pd.Series([1], dtype="float64")})
    monkeypatch.setattr(api, "_read_frame", lambda *_args: restored)

    result = api.round_trip_frame(
        source,
        metadata={},
        target_format="csv",
        directory=tmp_path,
    )

    assert result.frame_equal is True
    assert result.dtype_equal is False
    assert result.schema_equal is False
    assert result.status == "schema_mismatch"


def test_round_trip_status_exposes_declared_metadata_loss(tmp_path) -> None:
    api = _api()
    result = api.round_trip_frame(
        pd.DataFrame({"code": [1]}),
        metadata={"columns": {"code": {"variable_label": "Code"}}},
        target_format="csv",
        directory=tmp_path,
    )

    assert result.frame_equal is True
    assert result.schema_equal is True
    assert result.metadata_loss.has_loss is True
    assert result.status == "metadata_loss"


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
