"""Wide tables: the native CSV writer allocates float caches only where floats are written,
and .dta chunks are bounded by bytes; the bytes written are unchanged.

2026-11-06 risk review, finding 5: every CSV column got a 4,096-slot float-text cache, so 1,000
boolean columns took about 100-160 MiB more than pandas' writer for a 1 KB frame; .dta chunks were
65,536 rows whatever the row width (about 500 MiB per chunk at 1,000 double columns).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench import export_writers, native_io

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(native_io.module() is None, reason="native io_writers build not present")

_PROBE = """
import sys
import numpy as np, pandas as pd
sys.path[:0] = ["backend", "scripts"]
from perf_footprint import memory_accounting
from workbench.export_writers import write_csv
frame = pd.DataFrame(np.zeros((100, 1000), dtype=bool), columns=[f"v{i}" for i in range(1000)])
before = memory_accounting()["footprint_bytes"]
assert write_csv(frame, sys.argv[1])
print(memory_accounting()["footprint_bytes"] - before)
"""


def test_a_wide_boolean_table_adds_no_per_column_float_cache(tmp_path):
    if sys.platform != "darwin":
        pytest.skip("footprint is read on macOS")
    done = subprocess.run([sys.executable, "-c", _PROBE, str(tmp_path / "wide.csv")], cwd=ROOT,
                          capture_output=True, text=True, check=True)
    assert int(done.stdout.strip()) < 32 * 2**20  # was about 100 MiB of empty caches


@pytest.mark.parametrize("shape", [(1, 1000), (100, 1000), (5000, 3)])
def test_wide_and_long_mixed_tables_write_pandas_bytes(tmp_path, shape):
    rows, width = shape
    rng = np.random.default_rng(width)
    frame = pd.DataFrame({
        f"c{i}": (rng.normal(size=rows) if i % 3 == 0 else rng.integers(0, 5, size=rows) if i % 3 == 1
                  else rng.random(rows) < 0.5) for i in range(width)})
    native, reference = tmp_path / "native.csv", tmp_path / "reference.csv"
    assert export_writers.write_csv(frame, native)
    frame.to_csv(reference, index=False, encoding="utf-8")
    assert native.read_bytes() == reference.read_bytes()


def test_dta_chunks_bounded_by_bytes_write_the_same_file(tmp_path, monkeypatch):
    pyreadstat = pytest.importorskip("pyreadstat")
    rng = np.random.default_rng(5)
    frame = pd.DataFrame({f"x{i}": rng.normal(size=300) for i in range(20)})
    options = {"version": 15}
    whole, chunked = tmp_path / "whole.dta", tmp_path / "chunked.dta"
    assert export_writers.write_dta(frame, whole, options, pyreadstat)
    monkeypatch.setattr(export_writers, "_DTA_CHUNK_BYTES", 20 * 8 * 7)  # 7 rows per chunk
    assert export_writers.write_dta(frame, chunked, options, pyreadstat)
    a, b = whole.read_bytes(), chunked.read_bytes()
    assert len(a) == len(b) and a[:120] + a[137:] == b[:120] + b[137:]  # 17-byte write timestamp masked
