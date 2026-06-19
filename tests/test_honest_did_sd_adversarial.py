"""ΔSD/FLCI whole-feature adversarial probes (v1.5.7.1 review).

Hostile probes against the honest-DID ΔSD track + the {rm,sd} adapter contract.
A probe that PASSES confirms safety; a failing probe is a real escape (reported
by the reviewer, NOT fixed here). Covers review areas 1-6:

  1. Degrade-not-fail TOTAL (engine + adapter never raise on degenerate input).
  2. Frozen-snapshot integrity (one Σ, both tracks agree).
  3. The v1.5.7 escape: non-finite -> blank card (real _json_safe + strict JSON).
  4. _debug_ hygiene after the runner strip.
  5. Determinism (no RNG; byte-identical across runs).
  6. FLCI numerical honesty (analytic qfoldednormal oracle; CI width grows w/ M).
"""
from __future__ import annotations

import copy
import json
import math
import os

import numpy as np
import pytest

from workbench.engine.honest_did import (
    flci,
    honest_sd,
    _folded_normal_quantile,
)
from workbench.engine.honest_did_adapter import honest_did_from_cs_dynamic
from workbench.engine.stages.diagnostics import _json_safe

_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "honest_did")
HRM = json.load(open(os.path.join(_FIX, "honest_rm.json")))
FLCI_SD = json.load(open(os.path.join(_FIX, "flci_sd.json")))


def _flci_inputs():
    beta = np.array(HRM["betahat"], dtype=float)
    sigma = np.array(HRM["sigma"], dtype=float)
    return beta, sigma, HRM["numPre"], HRM["numPost"], np.array(FLCI_SD["l_vec"], dtype=float)


def _pd_sigma(n: int, scale: float = 1.0) -> np.ndarray:
    """A well-conditioned PD n×n covariance."""
    rng = np.random.default_rng(0)
    a = rng.standard_normal((n, n))
    return (a @ a.T + n * np.eye(n)) * scale


def _make_agg(event_times, *, n_clusters=6, n_labels=None):
    """Synthesize a CS dynamic aggregation snapshot the adapter can consume."""
    n_labels = len(event_times) if n_labels is None else n_labels
    rng = np.random.default_rng(1)
    estimate = rng.standard_normal(len(event_times)).tolist()
    component_if = rng.standard_normal((n_clusters, n_labels))
    return {
        "label": list(event_times),
        "estimate": estimate,
        "component_if": component_if.tolist(),
    }


# ---------------------------------------------------------------------------
# Area 1: degrade-not-fail TOTAL — neither engine nor adapter may raise.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("event_times", [
    [-1.0, 0.0],                     # num_pre=1, num_post=1 (after dropping -1: 0 pre, 1 post)
    [-2.0, -1.0, 0.0],               # num_pre=1, num_post=1
    [-3.0, -2.0, -1.0],              # all-pre (num_post=0)
    [-1.0, 0.0, 1.0, 2.0],           # all-post after dropping -1 (num_pre=0)
    [-2.0, -1.0, 0.0, 1.0, 2.0],     # nominal
])
def test_adapter_never_raises_on_degenerate_grids(event_times):
    agg = _make_agg(event_times)
    rc = list(range(len(agg["component_if"])))
    out = honest_did_from_cs_dynamic(
        agg, row_cluster=rc, n_total=len(rc),
        mbar_grid=[0.0, 1.0], alpha=0.05, grid_points=50,
    )
    for track in ("rm", "sd"):
        assert track in out
        assert out[track]["status"] in {"ok", "not_available", "degraded"}


def test_adapter_never_raises_on_shape_mismatch():
    agg = _make_agg([-1.0, 0.0, 1.0], n_labels=3)
    # row_cluster shorter than component_if rows -> must NOT raise.
    out = honest_did_from_cs_dynamic(
        agg, row_cluster=[0], n_total=5, mbar_grid=[1.0], grid_points=20,
    )
    assert out["rm"]["status"] == "not_available"
    assert out["sd"]["status"] == "not_available"


def test_adapter_never_raises_near_singular_sigma():
    # Force a near-singular-but-PD Σ via a rank-deficient-ish IF matrix.
    et = [-2.0, -1.0, 0.0, 1.0]
    base = np.array([1.0, 0.0, 1e-7, 1.0])
    cif = np.outer(np.linspace(1, 2, 6), base) + 1e-9 * np.random.default_rng(3).standard_normal((6, 4))
    agg = {"label": et, "estimate": [0.1, 0.0, 0.2, 0.3], "component_if": cif.tolist()}
    out = honest_did_from_cs_dynamic(
        agg, row_cluster=list(range(6)), n_total=6, mbar_grid=[1.0], grid_points=20,
    )
    for t in ("rm", "sd"):
        assert out[t]["status"] in {"ok", "not_available", "degraded"}


def test_honest_sd_engine_degrades_not_raises():
    beta, sigma, npre, npost, l = _flci_inputs()
    # num_pre=0 / num_post=0 must raise HonestDiDError (caught by adapter), NOT
    # ZeroDivision / LinAlg. Engine raises a typed error; assert it is that type.
    from workbench.engine.honest_did import HonestDiDError
    with pytest.raises(HonestDiDError):
        honest_sd(betahat=beta, sigma=sigma, num_pre=0, num_post=npost,
                  l_vec=l, m_grid=[1.0])
    with pytest.raises(HonestDiDError):
        honest_sd(betahat=beta, sigma=sigma, num_pre=npre, num_post=0,
                  l_vec=np.array([]), m_grid=[1.0])


def test_flci_m_grid_with_zero_on_degenerate_sigma_no_zerodiv():
    """Historical ZeroDivisionError path: M-grid containing 0.0 with a tiny Σ.
    honest_sd must return finite-or-NaN rows, never raise ZeroDivisionError."""
    beta, sigma, npre, npost, l = _flci_inputs()
    tiny = sigma * 1e-12 + 1e-13 * np.eye(sigma.shape[0])  # PD but ~1e-13 scale
    try:
        out = honest_sd(betahat=beta, sigma=tiny, num_pre=npre, num_post=npost,
                        l_vec=l, m_grid=[0.0, 0.5, 1.0])
    except Exception as exc:  # noqa: BLE001
        from workbench.engine.honest_did import HonestDiDError
        assert isinstance(exc, HonestDiDError), f"unexpected {type(exc)}: {exc}"
        return
    assert [r["M"] for r in out["results"]] == [0.0, 0.5, 1.0]


def test_flci_2x2_sigma_no_crash():
    """Smallest meaningful Σ (2×2: 1 pre + 1 post)."""
    sigma = np.array([[1.0, 0.2], [0.2, 1.0]])
    r = flci(betahat=np.array([0.1, 0.2]), sigma=sigma, num_pre=1, num_post=1,
             l_vec=np.array([1.0]), m=0.5)
    assert set(r) == {"half_length", "lb", "ub"}


# ---------------------------------------------------------------------------
# Area 2: frozen-snapshot integrity — ONE Σ, both tracks read it.
# ---------------------------------------------------------------------------

def test_both_tracks_share_one_sigma():
    et = [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0]
    agg = _make_agg(et, n_clusters=8)
    out = honest_did_from_cs_dynamic(
        agg, row_cluster=list(range(8)), n_total=8,
        mbar_grid=[0.0, 1.0], grid_points=40,
    )
    # exactly one Σ snapshot at top level
    assert "_debug_sigma" in out
    sigma = np.array(out["_debug_sigma"])
    # square, symmetric, and dims == num_pre+num_post echoed by BOTH tracks
    assert sigma.shape[0] == sigma.shape[1]
    assert out["rm"]["num_pre"] == out["sd"]["num_pre"]
    assert out["rm"]["num_post"] == out["sd"]["num_post"]
    assert sigma.shape[0] == out["rm"]["num_pre"] + out["rm"]["num_post"]
    assert np.allclose(sigma, sigma.T)


def test_only_one_sigma_computation_path():
    """The adapter source must compute Sigma_full exactly once."""
    import inspect
    src = inspect.getsource(honest_did_from_cs_dynamic)
    # exactly one assignment of the frozen Σ snapshot
    assert src.count("Sigma_full =") == 1
    # exactly one accumulation into the cluster-score matrix (ignore comment text)
    code_lines = [ln for ln in src.splitlines() if "np.add.at" in ln and "#" not in ln.split("np.add.at")[0]]
    assert len(code_lines) == 1, code_lines


# ---------------------------------------------------------------------------
# Area 3: the v1.5.7 escape — non-finite -> blank card. BOTH tracks.
# ---------------------------------------------------------------------------

def _strict_loads(s: str):
    """Emulate the browser's strict JSON: reject NaN/Infinity tokens."""
    def _raise(tok):
        raise AssertionError(f"bare non-finite token in JSON: {tok!r}")
    return json.loads(s, parse_constant=_raise)


def test_non_finite_sd_ci_serializes_to_null():
    block = {
        "rm": {"status": "ok", "reason": None, "num_pre": 1, "num_post": 1,
               "post_average": {"results": [{"Mbar": 1.0, "lb": float("nan"),
                                             "ub": float("inf")}],
                                "breakdown": None}},
        "sd": {"status": "ok", "reason": None, "method": "FLCI",
               "post_average": {"results": [{"M": 0.0, "lb": float("-inf"),
                                             "ub": float("nan")}],
                                "breakdown": float("nan")}},
    }
    safe = _json_safe(block)
    dumped = json.dumps(safe)  # default allow_nan=True; must contain no NaN
    assert "NaN" not in dumped and "Infinity" not in dumped
    parsed = _strict_loads(dumped)
    assert parsed["sd"]["post_average"]["results"][0]["lb"] is None
    assert parsed["sd"]["post_average"]["results"][0]["ub"] is None
    assert parsed["rm"]["post_average"]["results"][0]["lb"] is None
    assert parsed["rm"]["post_average"]["results"][0]["ub"] is None


def test_real_adapter_output_strict_json_safe():
    """A real adapter run on a near-singular Σ must survive _json_safe +
    strict JSON for BOTH tracks (no bare NaN/Infinity)."""
    et = [-2.0, -1.0, 0.0, 1.0]
    base = np.array([1.0, 0.5, 1e-6, 1.0])
    cif = np.outer(np.linspace(1, 3, 7), base)
    agg = {"label": et, "estimate": [0.1, 0.0, 0.2, 0.3], "component_if": cif.tolist()}
    out = honest_did_from_cs_dynamic(
        agg, row_cluster=list(range(7)), n_total=7, mbar_grid=[0.0, 1.0],
        grid_points=20,
    )
    safe = _json_safe(out)
    dumped = json.dumps(safe)
    assert "NaN" not in dumped and "Infinity" not in dumped
    _strict_loads(dumped)  # raises if any bare non-finite token survives


# ---------------------------------------------------------------------------
# Area 4: _debug_ hygiene after the runner strip.
# ---------------------------------------------------------------------------

def test_debug_keys_stripped_like_runner():
    et = [-2.0, -1.0, 0.0, 1.0]
    agg = _make_agg(et, n_clusters=6)
    hd = honest_did_from_cs_dynamic(
        agg, row_cluster=list(range(6)), n_total=6, mbar_grid=[1.0], grid_points=20,
    )
    # raw adapter output HAS the top-level _debug_* snapshot
    assert any(k.startswith("_debug_") for k in hd)
    # runner strip: dict-comp on top-level keys
    shipped = {k: v for k, v in hd.items() if not k.startswith("_debug_")}
    assert not any(k.startswith("_debug_") for k in shipped)
    # and NONE leaked into rm/sd
    for track in ("rm", "sd"):
        assert not any(k.startswith("_debug_") for k in shipped[track])


# ---------------------------------------------------------------------------
# Area 5: determinism — no RNG anywhere.
# ---------------------------------------------------------------------------

def test_flci_and_honest_sd_byte_identical_across_runs():
    beta, sigma, npre, npost, l = _flci_inputs()
    m_grid = [0.0, 0.5, 1.0, 1.5]
    runs = [
        honest_sd(betahat=beta, sigma=sigma, num_pre=npre, num_post=npost,
                  l_vec=l, m_grid=m_grid, alpha=0.05)
        for _ in range(3)
    ]
    blobs = [json.dumps(_json_safe(r), sort_keys=True) for r in runs]
    assert blobs[0] == blobs[1] == blobs[2]


def test_folded_normal_quantile_is_deterministic_analytic():
    # Brent root-find, not a sampler: repeated calls byte-identical, and the
    # t=0 value equals the analytic two-sided normal quantile.
    from scipy.stats import norm
    vals = [_folded_normal_quantile(0.7, alpha=0.05) for _ in range(5)]
    assert len(set(vals)) == 1
    assert abs(_folded_normal_quantile(0.0, alpha=0.05) - norm.ppf(0.975)) < 1e-10


# ---------------------------------------------------------------------------
# Area 6: FLCI numerical honesty — analytic oracle + CI width monotone in M.
# ---------------------------------------------------------------------------

def test_oracle_m0_halflength_is_analytic_not_mc():
    # Analytic qfoldednormal gives M=0 half-length ~1.0548, NOT R's MC ~1.0560.
    m0 = next(r for r in FLCI_SD["results"] if r["M"] == 0)
    assert abs(m0["optimalHalfLength"] - 1.0548296499) < 1e-6
    assert abs(m0["optimalHalfLength"] - 1.0560) > 5e-4  # demonstrably NOT the MC value


def test_flci_ci_width_strictly_grows_with_m():
    """Discriminating (non-grid-saturated) M values must yield strictly wider
    CIs — a vacuous oracle (all rows equal) would fail this."""
    beta, sigma, npre, npost, l = _flci_inputs()
    ms = [0.0, 0.25, 0.5, 1.0, 1.5]
    widths = []
    for m in ms:
        r = flci(betahat=beta, sigma=sigma, num_pre=npre, num_post=npost,
                 l_vec=l, m=m, alpha=0.05)
        widths.append(r["ub"] - r["lb"])
    for a, b in zip(widths, widths[1:]):
        assert b > a + 1e-6, (widths,)


def test_flci_matches_recomputed_oracle_over_full_grid():
    """Re-load the committed oracle and recompute every row independently."""
    beta, sigma, npre, npost, l = _flci_inputs()
    alpha = FLCI_SD["alpha"]
    for row in FLCI_SD["results"]:
        r = flci(betahat=beta, sigma=sigma, num_pre=npre, num_post=npost,
                 l_vec=l, m=row["M"], alpha=alpha)
        assert abs(r["half_length"] - row["optimalHalfLength"]) < 1e-6, row["M"]
