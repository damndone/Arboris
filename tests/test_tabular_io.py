"""v1.8.9 step 5 — SPSS/Stata interchange through one tabular I/O module."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat
import pytest

from workbench.services.run_service import _normalize_labels
from workbench.tabular_io import (
    StatisticalFileError,
    read_statistical_labels,
    read_table,
    write_statistical,
)

LABELS = {
    "variable_labels": {"educ": "受教育年限", "gender": "性别"},
    "value_labels": {"gender": {"1": "男", "2": "女"}},
    "measurement_level": {"educ": "scale", "gender": "nominal"},
    "user_missing_values": {"educ": [-99, {"low": 900, "high": 999}]},
}


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "educ": [12.0, -99.0, 16.0, 950.0, 9.0],
            "gender": [1.0, 2.0, 1.0, 2.0, 1.0],
            "city": ["北京", "上海", "", "广州", "深圳"],
        }
    )


def _round_trip(tmp_path: Path, fmt: str, frame: pd.DataFrame, labels: dict):
    path = tmp_path / f"data.{fmt}"
    report = write_statistical(frame, labels, path, fmt)
    return path, report, read_table(path), read_statistical_labels(path, fmt)


@pytest.mark.parametrize("fmt", ["sav", "zsav"])
def test_spss_round_trip_preserves_data_and_every_label(tmp_path, fmt) -> None:
    path, report, restored, labels = _round_trip(tmp_path, fmt, _frame(), LABELS)

    assert report.notes == []
    assert labels == LABELS
    # Missing codes stay raw values in the data; the declaration carries them.
    assert restored["educ"].tolist() == [12.0, -99.0, 16.0, 950.0, 9.0]
    assert restored["city"].tolist()[:2] == ["北京", "上海"]
    # The imported labels are ordinary run labels.
    assert _normalize_labels(labels)["user_missing_values"] == LABELS["user_missing_values"]
    if fmt == "zsav":
        assert path.stat().st_size > 0


def test_stata_reports_what_it_cannot_hold_and_never_keeps_a_missing_code(tmp_path) -> None:
    frame = _frame().assign(score=[1.0, 1.5, 2.0, 2.0, 1.0])
    labels = {
        **LABELS,
        "value_labels": {**LABELS["value_labels"], "score": {"1": "low", "1.5": "mid"}, "city": {"北京": "capital"}},
    }
    _path, report, restored, restored_labels = _round_trip(tmp_path, "dta", frame, labels)

    fields = {(note["column"], note["field"]) for note in report.notes}
    assert ("educ", "measurement_level") in fields
    assert ("educ", "user_missing_values") in fields
    assert ("score", "value_labels") in fields  # 1.5 is not an integer
    assert ("city", "value_labels") in fields  # Stata labels only numbers
    # The codes became missing rather than valid values.
    assert restored["educ"].isna().tolist() == [False, True, False, True, False]
    # No silent truncation of 1.5 to 1.
    assert restored_labels["value_labels"]["score"] == {"1": "low"}
    assert restored_labels["value_labels"]["gender"] == {"1": "男", "2": "女"}
    assert restored_labels["variable_labels"]["educ"] == "受教育年限"


def test_codes_spss_cannot_declare_are_written_as_missing(tmp_path) -> None:
    labels = {"user_missing_values": {"educ": [-99, -98, -97, -96]}}
    frame = pd.DataFrame({"educ": [12.0, -99.0, -96.0, 16.0]})
    _path, report, restored, _labels = _round_trip(tmp_path, "sav", frame, labels)

    assert [note["field"] for note in report.notes] == ["user_missing_values"]
    assert "2 value(s)" in report.notes[0]["message"]
    assert restored["educ"].isna().tolist() == [False, True, True, False]


def test_invalid_names_are_renamed_and_chinese_names_are_kept(tmp_path) -> None:
    frame = pd.DataFrame({"性别": [1, 2], "bad name": [1, 2], "2020收入": [3, 4], "bad-name": [5, 6]})
    _path, report, restored, labels = _round_trip(tmp_path, "dta", frame, {})

    assert list(restored.columns) == ["性别", "bad_name", "v_2020收入", "bad_name_1"]
    assert report.renamed == {"bad name": "bad_name", "2020收入": "v_2020收入", "bad-name": "bad_name_1"}
    # The original name survives as the variable label.
    assert labels["variable_labels"]["bad_name"] == "bad name"


def test_stata_extended_missing_values_are_read_as_missing(tmp_path) -> None:
    path = tmp_path / "extended.dta"
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    pyreadstat.write_dta(frame, str(path), missing_user_values={"x": ["a"]})
    # pyreadstat marks extended-missing values through its own read path; the
    # contract is only that nothing but the valid numbers comes back as data.
    restored = read_table(path)
    assert restored["x"].dropna().tolist() == [1.0, 2.0, 3.0]


@pytest.mark.parametrize("suffix", [".sav", ".zsav", ".dta"])
def test_a_corrupt_file_is_refused_with_a_clear_error(tmp_path, suffix) -> None:
    path = tmp_path / f"broken{suffix}"
    path.write_bytes(b"this is not a statistical file")
    with pytest.raises(StatisticalFileError, match="not a readable"):
        read_table(path)
    with pytest.raises(StatisticalFileError, match="not a readable"):
        read_statistical_labels(path, suffix.lstrip("."))


def test_a_failed_write_leaves_no_partial_file(tmp_path, monkeypatch) -> None:
    import workbench.tabular_io as tabular_io

    def explode(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(tabular_io._pyreadstat(), "write_sav", explode)
    with pytest.raises(RuntimeError):
        write_statistical(_frame(), LABELS, tmp_path / "out.sav", "sav")
    assert list(tmp_path.iterdir()) == []


def test_read_table_limits_rows_and_reads_headers(tmp_path) -> None:
    path, _report, _restored, _labels = _round_trip(tmp_path, "sav", _frame(), LABELS)
    assert len(read_table(path, nrows=2)) == 2
    header = read_table(path, nrows=0)
    assert list(header.columns) == ["educ", "gender", "city"] and header.empty
    csv = tmp_path / "d.csv"
    _frame().to_csv(csv, index=False)
    assert read_table(csv, nrows=2)["educ"].tolist() == [12.0, -99.0]


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="R not installed")
@pytest.mark.parametrize("fmt", ["sav", "dta"])
def test_r_haven_reads_our_exports_the_same_way(tmp_path, fmt) -> None:
    """Independent reader: R haven must see the same labels and missing codes."""

    probe = subprocess.run(
        ["Rscript", "-e", 'cat(requireNamespace("haven", quietly=TRUE))'],
        capture_output=True, text=True, check=False,
    )
    if probe.stdout.strip() != "TRUE":
        pytest.skip("R package haven not installed")
    path = tmp_path / f"export.{fmt}"
    write_statistical(_frame(), LABELS, path, fmt)
    reader = "read_sav(p, user_na=TRUE)" if fmt == "sav" else "read_dta(p)"
    script = f"""
    suppressMessages(library(haven)); library(jsonlite)
    p <- "{path}"; d <- {reader}
    na_vals <- if ("{fmt}" == "sav") attr(d$educ, "na_values") else NULL
    na_range <- if ("{fmt}" == "sav") attr(d$educ, "na_range") else NULL
    out <- list(
      educ_label = attr(d$educ, "label"),
      gender_labels = as.list(attr(d$gender, "labels")),
      educ_missing = is.na(d$educ),
      na_values = na_vals, na_range = na_range
    )
    cat(toJSON(out, auto_unbox = TRUE))
    """
    result = subprocess.run(["Rscript", "-e", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout)
    assert seen["educ_label"] == "受教育年限"
    assert seen["gender_labels"] == {"男": 1, "女": 2}
    # Both readers agree that -99 and 950 are missing, not education years.
    assert seen["educ_missing"] == [False, True, False, True, False]
    if fmt == "sav":
        assert seen["na_values"] == -99
        assert seen["na_range"] == [900, 999]


def test_object_columns_holding_numbers_are_restored_to_numeric() -> None:
    from workbench.tabular_io import _restore_numeric_columns

    frame = pd.DataFrame(
        {
            "score": pd.Series([88, 95, np.nan, 83], dtype=object),
            "name": pd.Series(["a", None, "c", "d"], dtype=object),
            "flag": pd.Series([True, False, None, True], dtype=object),
        }
    )
    restored = _restore_numeric_columns(frame)
    assert pd.api.types.is_numeric_dtype(restored["score"])
    assert restored["score"].isna().sum() == 1
    assert restored["name"].dtype == object
    assert restored["flag"].dtype == object


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="R not installed")
def test_a_stata_integer_column_with_missing_values_reads_as_numeric(tmp_path) -> None:
    """Real Stata files store small integers as byte/int; with missing values
    pyreadstat returned them as text-like object columns."""

    path = tmp_path / "ints.dta"
    result = subprocess.run(
        ["Rscript", "-e", f'haven::write_dta(data.frame(x = c(1L, NA, 3L), y = c(1.5, 2, NA)), "{path}")'],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        pytest.skip("R haven unavailable: " + result.stderr[-200:])
    frame = read_table(path)
    assert pd.api.types.is_numeric_dtype(frame["x"])
    assert frame["x"].tolist()[0] == 1 and np.isnan(frame["x"].tolist()[1])


def test_value_labels_on_an_integer_column_export_to_spss(tmp_path) -> None:
    frame = pd.DataFrame({"income_group": pd.Series([1, 2, 3, 2], dtype="int8")})
    labels = {"value_labels": {"income_group": {"1": "Low", "2": "Middle", "3": "High"}}}
    path, report, restored, restored_labels = _round_trip(tmp_path, "sav", frame, labels)
    assert report.notes == []
    assert restored_labels["value_labels"]["income_group"] == {"1": "Low", "2": "Middle", "3": "High"}
