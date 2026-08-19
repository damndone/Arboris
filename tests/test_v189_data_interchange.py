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
        result = api.round_trip_frame(
            frame,
            metadata=metadata,
            target_format=target_format,
            directory=tmp_path,
        )
        assert result.status == "verified"
        assert result.target_format == target_format
        assert result.frame_equal is True
        assert result.metadata_loss.schema_version == "metadata-loss-manifest/v1"


def test_native_statistical_formats_are_typed_unavailable_without_optional_dependency() -> None:
    api = _api()

    for target_format in ("sav", "zsav", "dta"):
        capability = api.interchange_capability(target_format)
        assert capability.status == "unavailable"
        assert capability.reason_code == "optional_dependency"
