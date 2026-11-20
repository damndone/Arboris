from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def export_gate():
    path = Path(__file__).parents[1] / "scripts/perf_native_io.py"
    spec = importlib.util.spec_from_file_location("perf_native_io", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (None, []),
        ("json", ["content:json"]),
        ("dta", ["content:dta"]),
        ("footprint", ["resource:footprint_bytes"]),
        ("noise", ["noise:calibration"]),
    ],
)
def test_export_gate_evaluates_every_sample(export_gate, change, expected):
    sample = dict.fromkeys(
        ("seconds", "export_seconds", "json_seconds", "csv_seconds", "dta_seconds", "rss_bytes", "footprint_bytes", "run_bytes"),
        100,
    )
    sample.update(
        downloads={
            "json": {"sha256": "json"},
            "csv": {"sha256": "csv"},
            "dta": {"without_header_timestamp_sha256": "dta"},
        },
        columns={"csv": ["x"], "dta": ["x"]},
    )
    calibration, baseline, candidate = ([deepcopy(sample) for _ in range(5)] for _ in range(3))
    if change == "json":
        candidate[4]["downloads"]["json"]["sha256"] = "different scientific result"
    elif change == "dta":
        baseline[0]["downloads"]["dta"]["without_header_timestamp_sha256"] = "different data"
    elif change == "footprint":
        for row in candidate:
            row["footprint_bytes"] = 106
    elif change == "noise":
        calibration[0]["dta_seconds"] = 200

    report = export_gate.evaluate(calibration, {"A": baseline, "B": candidate})

    assert report["failed"] == expected
