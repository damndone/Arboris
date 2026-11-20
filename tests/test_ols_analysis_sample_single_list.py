"""OLS results store both analysis-row lists as v1.9.0 did; single-list development results still read.

2026-11-09: the v1.9.1 native-io merge stored row_order only, so the downloaded model JSON
differed from v1.9.0 and the exact-bytes export gate failed. Results again store row_set.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from workbench.analysis_loop.fingerprints import analysis_sample_fingerprint
from workbench.analysis_loop.canonical import sha256_canonical
from workbench.econometrics.ols_contract import analysis_sample_row_set
from workbench.econometrics.runner import run_ols

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pack_ols_result.py"


def _fit(frame: pd.DataFrame) -> dict:
    result, _ = run_ols(frame, "y", ["x"], True, "ols_1", dataset_snapshot={"fixture": "single-list"})
    return result


def _frame(index=None) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    frame = pd.DataFrame({"x": rng.normal(size=40), "y": rng.normal(size=40)}, index=index)
    frame.iloc[[3, 17], 1] = np.nan
    return frame


def test_a_new_result_stores_both_lists_in_the_v190_layout_with_their_fingerprint():
    for frame in (_frame(), _frame(index=[f"r{index:03d}" for index in range(40)][::-1])):
        sample = _fit(frame)["analysis_sample"]
        assert list(sample) == ["row_set", "row_order", "fingerprint"] and len(sample["row_order"]) == 38
        assert sample["row_set"] == sorted(sample["row_order"])
        order = sample["row_order"]
        reference = sha256_canonical({"fingerprint_type": "analysis_sample_v1",
                                      "value": {"row_set": sorted(order), "row_order": order}})
        assert sample["fingerprint"] == analysis_sample_fingerprint(sorted(order), order) == reference


def test_the_row_set_reads_the_same_from_old_and_new_results():
    order = ["10", "2", "10", "0"]
    assert analysis_sample_row_set({"row_order": order}) == ["0", "10", "10", "2"]
    assert analysis_sample_row_set({"row_order": order, "row_set": sorted(order)}) == sorted(order)


def test_the_archive_tool_round_trips_a_new_result_and_refuses_a_single_list_one(tmp_path):
    result = _fit(_frame())
    source, archive, restored = (tmp_path / name for name in ("ols_1.json", "archive.json", "restored.json"))
    source.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    def run(*args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)

    assert run("pack", source, archive).returncode == 0
    assert run("restore", archive, restored).returncode == 0 and restored.read_bytes() == source.read_bytes()
    del result["analysis_sample"]["row_set"]
    source.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    done = run("pack", source, tmp_path / "out.json")
    assert done.returncode != 0 and "nothing to archive" in done.stderr
    assert not (tmp_path / "out.json").exists()
