"""v1.5.7 adversarial fixes: a degenerate honest-DID CI can be (nan, nan).

Without sanitization that NaN reaches cs_did.json as the bare token ``NaN``
(json.dumps allow_nan=True), which is invalid JSON: the browser's strict
``Response.json()`` throws and the WHOLE CS diagnostics card silently vanishes.
These tests pin the three fixes:
  1. ``_json_safe`` maps non-finite floats -> None (valid JSON, FE renders "—").
  2. ``honest_rm`` reports non-finite sigma as a clean HONEST_DEGENERATE_SIGMA.
  3. the adapter honors its "NEVER throws" contract on a row/IF shape mismatch.
"""
import json

import numpy as np
import pytest

from workbench.engine.stages.diagnostics import _json_safe
from workbench.engine.honest_did import honest_rm, HonestDiDError
from workbench.engine.honest_did_adapter import honest_did_from_cs_dynamic


def test_json_safe_maps_non_finite_floats_to_none():
    out = _json_safe({"lb": float("nan"), "ub": float("inf"),
                      "neg": float("-inf"), "ok": 1.5, "n": None,
                      "arr": [float("nan"), 2.0], "np": np.float64("nan")})
    assert out["lb"] is None and out["ub"] is None and out["neg"] is None
    assert out["ok"] == 1.5 and out["n"] is None
    assert out["arr"] == [None, 2.0]
    assert out["np"] is None


def test_nan_honest_did_block_serializes_to_strict_valid_json():
    # A honest_did block carrying a (nan, nan) CI must serialize to JSON that the
    # browser's strict parser accepts (no bare NaN token). json.loads with
    # parse_constant rejecting NaN/Infinity emulates the browser's strictness.
    block = {"status": "ok", "num_pre": 1, "num_post": 2,
             "post_average": {"results": [{"Mbar": 0.0, "lb": float("nan"),
                                           "ub": float("nan")}],
                              "breakdown": None}}
    safe = _json_safe(block)
    text = json.dumps(safe)  # default allow_nan=True, but there are no NaNs left
    assert "NaN" not in text and "Infinity" not in text

    def _reject(_):  # browser Response.json() rejects NaN/Infinity constants
        raise ValueError("invalid JSON constant")
    parsed = json.loads(text, parse_constant=_reject)
    assert parsed["post_average"]["results"][0]["lb"] is None


def test_honest_rm_non_finite_sigma_clean_degenerate():
    sig = np.eye(4)
    sig[0, 0] = float("nan")
    with pytest.raises(HonestDiDError, match="HONEST_DEGENERATE_SIGMA"):
        honest_rm(betahat=np.zeros(4), sigma=sig, num_pre=2, num_post=2,
                  l_vec=np.ones(2) / 2, mbar_grid=[1.0])


def test_adapter_row_mismatch_skips_not_throws():
    # component_if has 5 rows but row_cluster has 4 -> must skip, not raise.
    agg = {"label": [-1.0, 0.0, 1.0],
           "estimate": [0.0, 0.1, 0.2],
           "component_if": np.zeros((5, 3))}
    out = honest_did_from_cs_dynamic(agg, row_cluster=np.array([0, 1, 2, 3]),
                                     n_total=4, mbar_grid=[0, 1], grid_points=50)
    assert out["rm"]["status"] == "not_available"
    assert "HONEST_BAD_INPUT" in out["rm"]["reason"]
    assert out["sd"]["status"] == "not_available"
    assert "HONEST_BAD_INPUT" in out["sd"]["reason"]
