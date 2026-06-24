"""Loop 2A.6 — Model override identity incrementality (engine-level, no HTTP).

Proves the 2A.1–2A.5 mechanism composes into a model fork:
  - changing a model-layer param (covariance) leaves every UPSTREAM stage's
    node_hash identical (identity reuse — the forest dedups these);
  - the MICE imputation is reused (hit_reused), not recomputed;
  - estimation's node_hash changes (covariance is in its op_spec) and the change
    propagates to downstream node_hashes via the Merkle parent chain;
  - the fork's products are byte-identical to a forced full recompute.

The op_overrides → form merge over HTTP is 2B.3; here the fork is driven directly
through the engine (run_workflow with a different model-layer param).
"""
import json
from pathlib import Path

from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIX = Path(__file__).parent / "fixtures"


def _run(project_root, src, **extra):
    r = run_workflow(project_root, [src], mode="auto", y="wage",
                     x=["education", "experience"], model_type="ols", **extra)
    return project_root / "runs" / r["run_id"]


def _trace(run_root):
    return json.loads((run_root / "incremental_trace.json").read_text())


def _hashes(run_root):
    return {t["stage"]: t["node_hash"] for t in _trace(run_root)}


def _status(run_root):
    return {t["stage"]: t["status"] for t in _trace(run_root)}


def _coefs(run_root):
    out = {}
    for p in sorted((run_root / "model_results").glob("*.json")):
        m = json.loads(p.read_text())
        out[p.name] = {k: (v.get("estimate") if isinstance(v, dict) else v)
                       for k, v in m.get("coefficients", {}).items()}
    return out


def _imputed_bytes(run_root):
    return (run_root / "processed" / "imputed_dataset.parquet").read_bytes()


def test_model_fork_identity_incrementality(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", "1")
    project = create_project(tmp_path, "demo")
    src = FIX / "forest_min_missing.csv"

    rA = _run(project.root, src, imputation={"method": "mice"}, covariance="robust")
    rB = _run(project.root, src, imputation={"method": "mice"}, covariance="unadjusted")

    hA, hB = _hashes(rA), _hashes(rB)

    # Upstream node_hash identity reuse (forest shared prefix).
    for s in ("source", "cleaning", "profile", "validation", "routing", "imputation"):
        assert hA[s] == hB[s], f"upstream {s} hash diverged"

    # MICE truly reused on the fork.
    assert _status(rB)["imputation"] == "hit_reused"

    # Divergence point: estimation hash changes; propagates downstream via Merkle.
    assert hA["estimation"] != hB["estimation"]
    assert hA["diagnostics"] != hB["diagnostics"]
    assert hA["report"] != hB["report"]

    # Byte-identical vs forced full recompute of the same fork.
    monkeypatch.setenv("WORKBENCH_FORCE_FULL_RECOMPUTE", "1")
    rBf = _run(project.root, src, imputation={"method": "mice"}, covariance="unadjusted")
    assert _imputed_bytes(rB) == _imputed_bytes(rBf)
    assert _coefs(rB) == _coefs(rBf)
