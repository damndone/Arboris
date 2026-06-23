"""Loop 2A.5 — materialized MICE imputation cache + identity trace.

Identity reuse (node_hash) + the one real day-1 compute-skip (MICE). Byte-identical
oracle: the cached imputed_dataset.parquet must equal the recomputed one, and the
fitted coefficients must match (proving the cache is faithful, not just present)."""
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
    return {t["stage"]: t["status"]
            for t in json.loads((run_root / "incremental_trace.json").read_text())}


def _coefs(run_root):
    out = {}
    for p in sorted((run_root / "model_results").glob("*.json")):
        m = json.loads(p.read_text())
        out[p.name] = {
            k: (v.get("estimate") if isinstance(v, dict) else v)
            for k, v in m.get("coefficients", {}).items()
        }
    return out


def _imputed_bytes(run_root):
    return (run_root / "processed" / "imputed_dataset.parquet").read_bytes()


def test_mice_hit_reused_and_run_dir_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", "1")
    project = create_project(tmp_path, "demo")
    src = FIX / "forest_min_missing.csv"

    r1 = _run(project.root, src, imputation={"method": "mice"})
    r2 = _run(project.root, src, imputation={"method": "mice"})

    assert _trace(r1)["imputation"] == "miss_executed"
    assert _trace(r2)["imputation"] == "hit_reused"  # MICE truly skipped

    # G2: cache-hit child run dir still has the run-relative artifacts.
    assert (r2 / "processed" / "imputed_dataset.parquet").exists()
    assert list((r2 / "model_results").glob("*.json"))
    assert (r2 / "reports" / "report.html").exists()

    # Byte-identical: restored imputed frame == computed; fitted coefs match.
    assert _imputed_bytes(r1) == _imputed_bytes(r2)
    assert _coefs(r1) == _coefs(r2)


def test_force_full_matches_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", "1")
    project = create_project(tmp_path, "demo")
    src = FIX / "forest_min_missing.csv"

    r1 = _run(project.root, src, imputation={"method": "mice"})        # miss → materialize
    monkeypatch.setenv("WORKBENCH_FORCE_FULL_RECOMPUTE", "1")
    r3 = _run(project.root, src, imputation={"method": "mice"})        # forced recompute

    assert _trace(r3)["imputation"] in ("miss_executed", "recomputed_same_hash")
    assert _imputed_bytes(r1) == _imputed_bytes(r3)
    assert _coefs(r1) == _coefs(r3)


def test_no_mice_identity_reuse(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", "1")
    project = create_project(tmp_path, "demo")
    src = FIX / "forest_min.csv"

    _run(project.root, src)
    r2 = _run(project.root, src)
    t2 = _trace(r2)
    for stage in ("source", "cleaning", "estimation", "report"):
        assert t2[stage] == "recomputed_same_hash", (stage, t2)
