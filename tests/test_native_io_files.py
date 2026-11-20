"""Whenever the native CSV and .dta writers write a file, its bytes are the reference's bytes."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench import native_io
from workbench.export_writers import write_csv, write_dta

pytestmark = pytest.mark.skipif(native_io.module() is None, reason="native/io_writers/build.py has not been run")
pyreadstat = pytest.importorskip("pyreadstat")
# Stata 118 files carry the minute they were written; the two writers can straddle a minute.
STATA_TIMESTAMP = re.compile(rb"<timestamp>.{18}</timestamp>", re.S)


def _frames() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(20261106)
    n = 300
    floats = rng.normal(size=n) * 10.0 ** rng.integers(-12, 12, n)
    floats[[0, 1, 2, 3, 4]] = [0.0, -0.0, np.nan, 1e-310, 123456789012345678.0]
    return {
        "floats": pd.DataFrame({"x": floats, "y": rng.normal(size=n).round(3)}),
        "integers": pd.DataFrame({"a": rng.integers(-10**12, 10**12, n), "b": rng.integers(0, 3, n).astype("int8")}),
        "nullable_integers": pd.DataFrame({"a": pd.array([1, None, 3] * 100, dtype="Int64")}),
        "booleans": pd.DataFrame({"flag": rng.integers(0, 2, n).astype(bool)}),
        "text": pd.DataFrame({"s": ["plain", "with,comma", 'with "quote"', "line\nbreak", "", None] * 50}),
        "non_ascii": pd.DataFrame({"s": ["北京", "Zürich", "naïve", "emoji 🙂", "a b", "x"] * 50}),
        "dates": pd.DataFrame({"d": pd.date_range("1960-01-01", periods=n, freq="37D"),
                               "t": pd.date_range("2001-02-03 04:05:06.789", periods=n, freq="91min")}),
        "categories": pd.DataFrame({"c": pd.Categorical(["low", "mid", "high"] * 100)}),
        "mixed": pd.DataFrame({"x": floats, "a": rng.integers(0, 9, n), "s": ["u", "v"] * 150,
                               "d": pd.date_range("2020-01-01", periods=n, freq="D")}),
        "long_text": pd.DataFrame({"s": ["z" * 3000, "short"] * 10}),
        "empty": pd.DataFrame({"x": pd.Series([], dtype=float)}),
    }


@pytest.mark.parametrize("name", sorted(_frames()))
def test_a_native_csv_has_the_bytes_pandas_writes(tmp_path: Path, name: str):
    frame = _frames()[name]
    reference, native = tmp_path / "reference.csv", tmp_path / "native.csv"
    frame.to_csv(reference, index=False, encoding="utf-8")
    if write_csv(frame, native):
        assert native.read_bytes() == reference.read_bytes()


# The product always names a Stata release (tabular_io.prepare_export) and adds labels when it has them.
DTA_OPTIONS = {"stata_13": 13, "stata_14": 14, "stata_15": 15, "stata_14_labels": 14, "stata_15_labels": 15}


def _dta_options(frame: pd.DataFrame, kind: str) -> dict:
    options = {"version": DTA_OPTIONS[kind]}
    if kind.endswith("_labels"):
        options["column_labels"] = {column: f"Label of {column}" for column in frame.columns}
        first = frame.columns[0]
        if pd.api.types.is_integer_dtype(frame[first]) and not pd.api.types.is_bool_dtype(frame[first]):
            options["variable_value_labels"] = {first: {0: "zero", 1: "one", 2: "two"}}
    return options


@pytest.mark.parametrize("kind", sorted(DTA_OPTIONS))
@pytest.mark.parametrize("name", sorted(_frames()))
def test_a_native_dta_has_the_bytes_pyreadstat_writes(tmp_path: Path, name: str, kind: str):
    frame = _frames()[name]
    options = _dta_options(frame, kind)
    reference, native = tmp_path / "reference.dta", tmp_path / "native.dta"
    try:
        pyreadstat.write_dta(frame, str(reference), **options)
    except Exception as refused:  # noqa: BLE001 - whatever pyreadstat refuses, the native writer must not write
        assert not write_dta(frame, native, options, pyreadstat), refused
        return
    if write_dta(frame, native, options, pyreadstat):
        assert STATA_TIMESTAMP.sub(b"", native.read_bytes()) == STATA_TIMESTAMP.sub(b"", reference.read_bytes())


@pytest.mark.parametrize("name", ["floats", "integers", "mixed", "text", "dates"])
def test_the_common_exports_take_the_native_path(tmp_path: Path, name: str):
    frame = _frames()[name]
    assert write_csv(frame, tmp_path / "out.csv")
    assert write_dta(frame, tmp_path / "out.dta", {"version": 15}, pyreadstat)
