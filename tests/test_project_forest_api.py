"""v1.6.8 Task 6 (spec F1): GET /graph?project_root= — project-level forest.

Shape parity with the per-run headset body (build_headset) is the hard
requirement: `nodes` is a DICT keyed by the dedup key, `edges` a list of
{source, target, op, params}, `heads` a list — the frontend feeds both bodies
through the same adapter (adaptHeadSet).
"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app

# Shared genesis-run helpers (upload / draft / configure / validate / wait).
from test_pipeline_drafts_genesis import (
    _configure_chain,
    _genesis_rich,
    _validate,
    _wait_terminal,
)

client = TestClient(app)


def _mkproject(tmp_path, name="p1"):
    return client.post(
        "/projects", json={"parent": str(tmp_path), "name": name}
    ).json()["project_root"]


def _execute_genesis_run(root):
    """Create + configure + validate + execute a genesis draft; return run_id."""
    d = _genesis_rich(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    v = _validate(root, did).json()
    r = client.post(
        f"/pipeline-drafts/{did}/execute?project_root={root}",
        json={
            "execution_mode": "genesis",
            "validated_draft_hash": v["validated_draft_hash"],
        },
    )
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    status = _wait_terminal(root, run_id)
    assert status == "completed", f"genesis run ended {status!r}"
    return run_id


def test_zero_run_project_returns_empty_forest(tmp_path):
    root = _mkproject(tmp_path)
    r = client.get(f"/graph?project_root={root}")
    assert r.status_code == 200
    body = r.json()
    # Shape parity with build_headset: nodes is a DICT keyed by dedup key.
    assert body["nodes"] == {}
    assert body["edges"] == []
    assert body["heads"] == []
    assert body["families"] == []
    assert body["legacy"] is False
    assert isinstance(body["schema_version"], int)


def test_project_forest_unions_families(tmp_path):
    root = _mkproject(tmp_path)
    run_id = _execute_genesis_run(root)

    body = client.get(f"/graph?project_root={root}").json()
    assert body["nodes"], "run nodes must appear in project forest"

    per_run = client.get(
        f"/runs/{run_id}/graph?project_root={root}&view=headset"
    ).json()
    assert per_run.get("legacy") is False, "genesis run must not be legacy"
    # Per-run headset nodes are a subset of the project forest (dict keys ARE
    # the dedup keys) and shape-identical per node key.
    assert set(per_run["nodes"]).issubset(set(body["nodes"]))
    # Edge + head parity for a single-family project.
    per_run_edges = {
        (e["source"], e["target"], e.get("op")) for e in per_run["edges"]
    }
    forest_edges = {(e["source"], e["target"], e.get("op")) for e in body["edges"]}
    assert per_run_edges.issubset(forest_edges)
    assert [h["run_id"] for h in body["heads"]] == [run_id]
    assert body["families"] == [{"family_root": run_id, "members": [run_id]}]
    # Annotation parity: the model node stays editable in the project view.
    assert any(n.get("editable") for n in body["nodes"].values())


def test_project_forest_two_roots_no_cross_family_edges(tmp_path):
    """Two independent genesis runs = two families, one head each, disjoint union."""
    root = _mkproject(tmp_path)
    run_a = _execute_genesis_run(root)
    run_b = _execute_genesis_run(root)

    body = client.get(f"/graph?project_root={root}").json()
    assert sorted(h["run_id"] for h in body["heads"]) == sorted([run_a, run_b])
    # Heads are unique per run even across overlapping family scans.
    assert len(body["heads"]) == len({h["run_id"] for h in body["heads"]})
    roots = sorted(f["family_root"] for f in body["families"])
    assert roots == sorted([run_a, run_b])


def test_project_forest_unicode_root(tmp_path):
    root = _mkproject(tmp_path, name="中文项目")
    r = client.get(f"/graph?project_root={root}")
    assert r.status_code == 200
    assert r.json()["nodes"] == {}


def test_project_forest_unknown_root_404(tmp_path):
    r = client.get(f"/graph?project_root={tmp_path}/nope")
    assert r.status_code == 404


def test_project_forest_skips_non_run_clutter(tmp_path):
    """Stray files / manifest-less dirs in runs/ are ignored, not crashed on."""
    root = _mkproject(tmp_path)
    runs_dir = Path(root) / "runs"
    (runs_dir / "not_a_run").mkdir()
    (runs_dir / "stray.txt").write_text("x", encoding="utf-8")
    r = client.get(f"/graph?project_root={root}")
    assert r.status_code == 200
    assert r.json()["nodes"] == {} and r.json()["heads"] == []


def test_forest_dataset_nodes_carry_profile_artifacts(tmp_path):
    # v1.6.11 A2 — serve-time dataset decoration: the raw node exposes a compact
    # data_profile preview (rows/cols/dtypes/missingness) and the cleaned node its
    # cleaning actions, so Ask AI can describe the dataset instead of disclosing
    # an empty packet. graph.json on disk stays undecorated.
    root = _mkproject(tmp_path)
    run_id = _execute_genesis_run(root)
    body = client.get("/graph", params={"project_root": root}).json()

    raw_nodes = [n for k, n in body["nodes"].items() if k.endswith("::stage:raw") or k == "stage:raw"]
    assert raw_nodes, f"no raw node in forest keys: {list(body['nodes'])[:8]}"
    artifacts = raw_nodes[0].get("artifacts")
    assert artifacts and artifacts[0]["name"] == "data_profile.json"
    preview = artifacts[0]["preview"]
    assert preview["row_count"] > 0
    assert preview["column_count"] > 0
    assert isinstance(preview["columns"], dict)
    first_col = next(iter(preview["columns"].values()))
    assert "missing_rate" in first_col and "dtype" in first_col

    cleaned = [n for k, n in body["nodes"].items() if k.endswith("::stage:cleaned")]
    assert cleaned and cleaned[0].get("artifacts"), "cleaned node missing artifacts"
    assert cleaned[0]["artifacts"][0]["name"] == "cleaning_actions.json"

    # decorate-only: on-disk graph.json has no artifacts field
    graph = json.loads(
        (Path(root) / "runs" / run_id / "graph.json").read_text()
    )
    assert all("artifacts" not in n or n["artifacts"] is None
               for n in graph["nodes"].values())


def test_forest_model_node_carries_stats(tmp_path):
    # v1.6.11 C-2 — serve-time model decoration: the model node exposes fit
    # metrics + n_observations + compact coefficient rows read from
    # diagnostic_summary.json, so the report fact table can cite R²/coefficients.
    # graph.json on disk stays undecorated.
    root = _mkproject(tmp_path)
    run_id = _execute_genesis_run(root)
    body = client.get("/graph", params={"project_root": root}).json()

    model_nodes = [
        n for n in body["nodes"].values() if n["id"].startswith("model:")
    ]
    assert model_nodes, f"no model node in forest: {list(body['nodes'])[:8]}"
    stats = model_nodes[0].get("stats")
    assert stats, "model node missing stats decoration"
    assert stats["n_observations"] > 0
    coefficients = stats.get("coefficients")
    assert coefficients, "model stats missing coefficient rows"
    first = coefficients[0]
    assert first["variable"] and isinstance(first["estimate"], (int, float))
    assert "p_value" in first and "significance_label" in first
    # Fit metrics from model_quality flow through as scalars.
    summary = json.loads(
        (Path(root) / "runs" / run_id / "diagnostic_summary.json").read_text()
    )
    for key, val in summary["model_quality"]["metrics"].items():
        if isinstance(val, (int, float)):
            assert stats[key] == val

    # Non-model nodes stay undecorated; on-disk graph.json has no stats field.
    assert all(
        "stats" not in n
        for n in body["nodes"].values()
        if not n["id"].startswith("model:")
    )
    graph = json.loads(
        (Path(root) / "runs" / run_id / "graph.json").read_text()
    )
    assert all("stats" not in n or n["stats"] is None
               for n in graph["nodes"].values())
