"""Creating a comparison node from two graph nodes, end to end.

The point of the endpoint is that the caller supplies only what a user can
honestly point at -- a run and a node on it -- and the backend re-derives every
fact that makes the comparison citable: node identity, lineage relation, and a
packet read from artifacts that already existed. Nothing is refitted here.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.lineage.project_forest import build_project_forest

from tests.agent.test_arma_garch_agent_compare import _artifacts


client = TestClient(app)
NODE_ID = "model:arma_garch_1"


def _write_run(
    runs_dir: Path,
    run_id: str,
    *,
    node_hash: str,
    rerun_of: str | None = None,
    rmse: float = 1.2,
    pack: str = "time_series.arma_garch",
) -> None:
    run_root = runs_dir / run_id
    (run_root / "artifacts" / "time_series").mkdir(parents=True)
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "started_at": "2026-07-21T00:00:00+00:00",
                "model_routing": {
                    "requested_model_type": pack,
                    "effective_model_type": pack,
                },
            }
        ),
        encoding="utf-8",
    )
    (run_root / "run_inputs.json").write_text(
        json.dumps({"rerun_of": rerun_of, "form": {"model_type": pack}}),
        encoding="utf-8",
    )
    (run_root / "node_index.json").write_text(
        json.dumps({NODE_ID: {"node_hash": node_hash, "producing_stage": "model"}}),
        encoding="utf-8",
    )
    (run_root / "graph.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "run_id": run_id,
                "nodes": {
                    NODE_ID: {
                        "id": NODE_ID,
                        "kind": "model",
                        "display_label": "ARMA-GARCH",
                        "created_at": "2026-07-21T00:00:00+00:00",
                        "parent_stage_id": None,
                        "branch_id": "main",
                        "stage": "model",
                    }
                },
                "edges": {},
                "branches": {},
            }
        ),
        encoding="utf-8",
    )
    for artifact_id, payload in _artifacts(rmse=rmse).items():
        (run_root / "artifacts" / "time_series" / f"{artifact_id}.json").write_text(
            json.dumps(
                {
                    "artifact_id": artifact_id,
                    "metadata": {"run_id": run_id, "source_run_id": rerun_of, "node_id": NODE_ID},
                    "payload": payload,
                }
            ),
            encoding="utf-8",
        )


def _project(tmp_path: Path, **kwargs) -> Path:
    runs_dir = tmp_path / "project" / "runs"
    runs_dir.mkdir(parents=True)
    _write_run(runs_dir, "run-a", node_hash="a" * 64)
    _write_run(runs_dir, "run-b", node_hash="b" * 64, rmse=0.9, **kwargs)
    return runs_dir


def _create(root: Path, left: str = "run-a", right: str = "run-b"):
    return client.post(
        f"/compare-nodes?project_root={root}",
        json={
            "left": {"run_id": left, "node_id": NODE_ID},
            "right": {"run_id": right, "node_id": NODE_ID},
        },
    )


def test_two_model_nodes_become_one_durable_comparison(tmp_path: Path) -> None:
    runs_dir = _project(tmp_path)
    root = runs_dir.parent

    response = _create(root)

    assert response.status_code == 200, response.text
    record = response.json()
    assert record["schema_id"] == "lineage.compare_node.v1"
    assert {record["left"]["run_id"], record["right"]["run_id"]} == {"run-a", "run-b"}
    # The packet is a reading of stored artifacts, not a refit.
    assert record["packet"]["result_diff"]["forecast_metrics"]["changed"] is True


def test_the_comparison_survives_a_reload(tmp_path: Path) -> None:
    """The whole point: the conclusion is still there on the next request."""

    runs_dir = _project(tmp_path)
    root = runs_dir.parent
    created = _create(root).json()

    listed = client.get(f"/compare-nodes?project_root={root}").json()["compare_nodes"]

    assert [item["compare_id"] for item in listed] == [created["compare_id"]]


def test_the_forest_draws_it_as_a_node_joining_both_endpoints(tmp_path: Path) -> None:
    runs_dir = _project(tmp_path)
    root = runs_dir.parent
    created = _create(root).json()

    forest = build_project_forest(runs_dir)

    node = forest["nodes"][created["compare_id"]]
    assert node["kind"] == "compare"
    incoming = [edge for edge in forest["edges"] if edge["target"] == created["compare_id"]]
    assert len(incoming) == 2
    assert {edge["source"] for edge in incoming} == {
        created["left"]["forest_node_key"],
        created["right"]["forest_node_key"],
    }


def test_comparing_the_same_pair_again_returns_the_same_node(tmp_path: Path) -> None:
    runs_dir = _project(tmp_path)
    root = runs_dir.parent
    first = _create(root).json()

    # Swapped: the user clicked the other node first this time.
    second = _create(root, left="run-b", right="run-a").json()

    assert second["compare_id"] == first["compare_id"]
    assert len(client.get(f"/compare-nodes?project_root={root}").json()["compare_nodes"]) == 1


def test_a_rerun_child_is_recorded_as_a_descendant_not_an_unrelated_pair(
    tmp_path: Path,
) -> None:
    runs_dir = _project(tmp_path, rerun_of="run-a")

    record = _create(runs_dir.parent).json()

    assert record["relation"] == "ancestor_descendant"
    # The ancestor is the baseline, whichever way the user clicked.
    assert record["left"]["run_id"] == "run-a"


def test_comparing_a_node_with_itself_is_refused_with_a_reason(tmp_path: Path) -> None:
    runs_dir = _project(tmp_path)

    response = _create(runs_dir.parent, left="run-a", right="run-a")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COMPARE_SELF"


def test_a_pack_without_a_comparison_builder_is_refused_not_faked(
    tmp_path: Path,
) -> None:
    """An empty packet would put a node on the graph claiming a comparison
    nobody computed."""

    runs_dir = _project(tmp_path, pack="ols")

    response = _create(runs_dir.parent)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COMPARE_UNSUPPORTED_PACK"


def test_an_unknown_run_is_refused(tmp_path: Path) -> None:
    runs_dir = _project(tmp_path)

    response = _create(runs_dir.parent, right="run-missing")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COMPARE_RUN_NOT_FOUND"


def test_a_deleted_comparison_leaves_the_forest(tmp_path: Path) -> None:
    runs_dir = _project(tmp_path)
    root = runs_dir.parent
    created = _create(root).json()

    deleted = client.delete(
        f"/compare-nodes/{created['compare_id']}?project_root={root}"
    )

    assert deleted.status_code == 200
    assert created["compare_id"] not in build_project_forest(runs_dir)["nodes"]
    assert (
        client.delete(f"/compare-nodes/{created['compare_id']}?project_root={root}").status_code
        == 404
    )


def test_a_project_with_no_comparisons_is_unchanged(tmp_path: Path) -> None:
    """Golden discipline: the forest only grows when a comparison exists."""

    runs_dir = _project(tmp_path)

    forest = build_project_forest(runs_dir)

    assert all(node["kind"] != "compare" for node in forest["nodes"].values())
    assert all(edge.get("op") != "compare" for edge in forest["edges"])
