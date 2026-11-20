"""Test a portable model-result archive through its CLI boundary."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pack_ols_result.py"


def _invoke(action, source, destination):
    return subprocess.run(
        [sys.executable, str(SCRIPT), action, str(source), str(destination)],
        capture_output=True,
        text=True,
    )


def _result(path, *, row_set=None):
    # Includes duplicates, non-numeric sort order, escaped and non-ASCII IDs.
    order = ["10", "2", "10", "é", "e\u0301", "a\nb", '"', "0"]
    payload = {
        "contract_version": "ols_result_contract_v1",
        "model": "ols",
        "coefficients": {"x": {"estimate": -0.0, "std_error": 0.31}},
        "analysis_sample": {
            "row_order": order,
            "fingerprint": "a" * 64,
            "row_set": sorted(order) if row_set is None else row_set,
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path.read_bytes(), order


def test_portable_archive_round_trips_exact_legacy_bytes(tmp_path):
    original, archive, restored = (tmp_path / name for name in ("model.json", "archive.json", "restored.json"))
    raw, order = _result(original)
    assert (run := _invoke("pack", original, archive)).returncode == 0, run.stderr
    packed = json.loads(archive.read_bytes())
    assert packed["result"]["analysis_sample"]["row_order"] == order
    assert "row_set" not in packed["result"]["analysis_sample"]
    assert packed["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert (run := _invoke("restore", archive, restored)).returncode == 0, run.stderr
    assert restored.read_bytes() == original.read_bytes() == raw


def test_pack_refuses_to_discard_a_non_derived_row_set(tmp_path):
    source = tmp_path / "model.json"
    raw, _ = _result(source, row_set=["different"])
    output = tmp_path / "archive.json"
    run = _invoke("pack", source, output)
    assert run.returncode == 2 and "row_set" in run.stderr
    assert not output.exists()
    assert source.read_bytes() == raw


@pytest.mark.parametrize("change", ["digest", "row_order", "version"])
def test_restore_refuses_invalid_archive_without_publishing_result(tmp_path, change):
    source, archive, restored = (tmp_path / name for name in ("model.json", "archive.json", "restored.json"))
    _result(source)
    assert (run := _invoke("pack", source, archive)).returncode == 0, run.stderr
    payload = json.loads(archive.read_bytes())
    if change == "digest":
        payload["source_sha256"] = "0" * 64
    elif change == "row_order":
        payload["result"]["analysis_sample"]["row_order"].reverse()
    else:
        payload["format"] += ".unsupported"
    archive.write_text(json.dumps(payload), encoding="utf-8")
    run = _invoke("restore", archive, restored)
    assert run.returncode == 2
    assert not restored.exists()


def test_neither_existing_output_nor_original_can_be_overwritten(tmp_path):
    source, output = tmp_path / "model.json", tmp_path / "archive.json"
    raw, _ = _result(source)
    output.write_bytes(b"already exists")
    for destination, contents in ((output, b"already exists"), (source, raw)):
        run = _invoke("pack", source, destination)
        assert run.returncode == 2
        assert destination.read_bytes() == contents
    assert source.read_bytes() == raw
