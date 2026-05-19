"""Unit tests for backend/workbench/graph_store.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.graph_model import (
    AutoChosenReason,
    BranchRef,
    Contestability,
    DecisionPoint,
    Edge,
    Graph,
    Node,
    NodeKind,
    Trust,
)
from workbench.graph_store import (
    GraphDeserializationError,
    GraphLockTimeout,
    GraphSerializationError,
    GraphStore,
    graph_from_json,
    graph_to_json,
)


def _sample_graph() -> Graph:
    dp = DecisionPoint(
        decision_id="model_type_auto_select",
        selected="logit",
        candidates=("ols", "logit", "poisson"),
        source="data_driven_default",
        contestability=Contestability.derive(
            assumption_checks_needed=("variable_role_inference",),
        ),
        reason=AutoChosenReason(
            reason_type="data_driven_default",
            explanation="y is binary",
            chosen_params={"y_unique": 2, "y_dtype": "int64"},
        ),
    )
    node_raw = Node(
        id="stage:raw",
        kind=NodeKind.DATASET_STAGE,
        display_label="Raw data",
        created_at="2026-05-13T10:23:00+00:00",
        parent_stage_id=None,
        branch_id="main",
    )
    node_model = Node(
        id="model:primary",
        kind=NodeKind.MODEL,
        display_label="logit primary",
        created_at="2026-05-13T10:25:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        trust=Trust.CAUTION,
        trust_reason="auto-selected model type",
        decision_points=(dp,),
    )
    edge = Edge(
        id="e1",
        source_id="stage:raw",
        target_id="model:primary",
        op="logit.fit",
        params={},
    )
    return Graph(
        schema_version=2,
        run_id="run_test",
        nodes={node_raw.id: node_raw, node_model.id: node_model},
        edges={edge.id: edge},
        branches={
            "main": BranchRef(id="main", forked_from_node_id=None, head_node_ids=(node_model.id,)),
        },
    )


def test_roundtrip_preserves_full_graph():
    g = _sample_graph()
    data = graph_to_json(g)
    rebuilt = graph_from_json(data)
    assert rebuilt == g


def test_to_json_produces_serializable_dict():
    g = _sample_graph()
    data = graph_to_json(g)
    # Must be JSON-encodable as-is
    encoded = json.dumps(data)
    assert "model_type_auto_select" in encoded
    assert "logit" in encoded


def test_to_json_rejects_non_json_safe_payload():
    """A non-serializable chosen_params value must surface as GraphSerializationError."""
    class _NotJsonSafe:
        pass

    bad_dp = DecisionPoint(
        decision_id="bad",
        reason=AutoChosenReason(
            reason_type="system_default",
            chosen_params={"obj": _NotJsonSafe()},
        ),
    )
    node = Node(
        id="x",
        kind=NodeKind.VARIABLE,
        display_label="x",
        created_at="2026-05-13T10:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        decision_points=(bad_dp,),
    )
    g = Graph(
        schema_version=1, run_id="run_bad",
        nodes={node.id: node}, edges={}, branches={},
    )
    with pytest.raises(GraphSerializationError, match="not JSON-serializable"):
        graph_to_json(g)


def test_store_write_then_read(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    g = _sample_graph()
    run_dir = tmp_path / "run_test"
    run_dir.mkdir()
    store.write(g)
    loaded = store.read("run_test")
    assert loaded == g


def test_store_read_missing_returns_legacy_empty(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    run_dir = tmp_path / "run_old"
    run_dir.mkdir()
    loaded = store.read("run_old")
    assert loaded.legacy is True
    assert loaded.nodes == {}
    assert loaded.edges == {}


def test_store_atomic_write_no_partial_on_crash(tmp_path: Path, monkeypatch):
    """Simulate a crash mid-write: original file must remain untouched."""
    store = GraphStore(runs_root=tmp_path)
    run_dir = tmp_path / "run_crash"
    run_dir.mkdir()

    g1 = _sample_graph()
    object.__setattr__(g1, "run_id", "run_crash")
    store.write(g1)
    assert store.read("run_crash").run_id == "run_crash"

    # Now write a second graph but intercept os.replace to raise mid-write
    import os
    real_replace = os.replace

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(os, "replace", boom)

    g2 = _sample_graph()
    object.__setattr__(g2, "run_id", "run_crash")
    # Tweak something visible so we can detect partial write
    with pytest.raises(RuntimeError, match="simulated crash"):
        store.write(g2)

    # Original file must be intact (we still read the first write's content)
    loaded = store.read("run_crash")
    assert loaded.run_id == "run_crash"
    assert "stage:raw" in loaded.nodes


def test_store_mutate_returns_post_mutation_graph(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    run_dir = tmp_path / "run_mut"
    run_dir.mkdir()

    g = _sample_graph()
    object.__setattr__(g, "run_id", "run_mut")
    store.write(g)

    def archive_main_branch(graph: Graph) -> Graph:
        new_branches = dict(graph.branches)
        old = new_branches["main"]
        new_branches["main"] = BranchRef(
            id=old.id,
            forked_from_node_id=old.forked_from_node_id,
            head_node_ids=old.head_node_ids,
            archived=True,
        )
        return Graph(
            schema_version=graph.schema_version,
            run_id=graph.run_id,
            nodes=graph.nodes,
            edges=graph.edges,
            branches=new_branches,
            legacy=graph.legacy,
        )

    result = store.mutate("run_mut", archive_main_branch)
    assert result.branches["main"].archived is True
    assert store.read("run_mut").branches["main"].archived is True


def test_mutate_rejects_run_id_change(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    run_dir = tmp_path / "run_mut"
    run_dir.mkdir()

    g = _sample_graph()
    object.__setattr__(g, "run_id", "run_mut")
    store.write(g)

    def change_run_id(graph: Graph) -> Graph:
        return Graph(
            schema_version=graph.schema_version,
            run_id="different_run",
            nodes=graph.nodes,
            edges=graph.edges,
            branches=graph.branches,
        )

    with pytest.raises(ValueError, match="changed run_id"):
        store.mutate("run_mut", change_run_id)


def test_graph_from_json_deserialization_error_on_missing_keys():
    from workbench.graph_store import GraphDeserializationError, graph_from_json

    with pytest.raises(GraphDeserializationError):
        graph_from_json({"schema_version": 1})


def test_graph_from_json_deserialization_error_on_corrupt_data():
    from workbench.graph_store import GraphDeserializationError, graph_from_json

    with pytest.raises(GraphDeserializationError):
        graph_from_json({"not": "a valid graph"})


def test_graph_to_json_still_works_with_optimized_path():
    """Verify graph_to_json produces correct output (debug validation path)."""
    g = _sample_graph()
    data = graph_to_json(g)
    assert data["run_id"] == "run_test"
    assert "nodes" in data
    # Output must be JSON-encodable
    import json
    encoded = json.dumps(data)
    assert len(encoded) > 0


def test_store_read_corrupt_json_raises_deserialization_error(tmp_path: Path):
    store = GraphStore(runs_root=tmp_path)
    run_dir = tmp_path / "run_corrupt"
    run_dir.mkdir()
    (run_dir / "graph.json").write_text("{this is not valid json", encoding="utf-8")
    with pytest.raises(GraphDeserializationError, match="Corrupt graph.json"):
        store.read("run_corrupt")


def test_store_mutate_on_legacy_run(tmp_path: Path):
    """Mutate should work on a legacy run (no graph.json yet)."""
    store = GraphStore(runs_root=tmp_path)
    run_dir = tmp_path / "run_legacy"
    run_dir.mkdir()

    def add_node(graph: Graph) -> Graph:
        n = Node(
            id="stage:raw", kind=NodeKind.DATASET_STAGE, display_label="Raw",
            created_at="2026-05-18T12:00:00+00:00", parent_stage_id=None, branch_id="main",
        )
        return Graph(
            schema_version=1, run_id=graph.run_id,
            nodes={"stage:raw": n}, edges={}, branches={
                "main": BranchRef(id="main", forked_from_node_id=None, head_node_ids=("stage:raw",)),
            },
        )

    result = store.mutate("run_legacy", add_node)
    assert not result.legacy
    assert "stage:raw" in result.nodes
    # Now it should be persisted
    assert store.read("run_legacy").nodes == result.nodes


def test_roundtrip_preserves_decision_point_substructure():
    """Full round-trip must preserve Contestability warnings, reason params, etc."""
    g = _sample_graph()
    data = graph_to_json(g)
    rebuilt = graph_from_json(data)

    orig_node = g.nodes["model:primary"]
    rebuilt_node = rebuilt.nodes["model:primary"]
    assert rebuilt_node.decision_points
    assert rebuilt_node.decision_points[0].contestability.warnings == \
        orig_node.decision_points[0].contestability.warnings
    assert rebuilt_node.decision_points[0].contestability.assumption_checks_needed == \
        orig_node.decision_points[0].contestability.assumption_checks_needed
    assert rebuilt_node.decision_points[0].reason.chosen_params == \
        orig_node.decision_points[0].reason.chosen_params  # type: ignore[union-attr]


def test_empty_graph_serialization():
    """An empty (legacy) graph must round-trip correctly."""
    g = Graph(schema_version=1, run_id="empty", nodes={}, edges={}, branches={}, legacy=True)
    data = graph_to_json(g)
    assert data["legacy"] is True
    assert data["nodes"] == {}
    rebuilt = graph_from_json(data)
    assert rebuilt.legacy is True
    assert rebuilt.nodes == {}


def test_write_creates_run_directory_if_needed(tmp_path: Path):
    """write() must create the run directory if it doesn't exist."""
    store = GraphStore(runs_root=tmp_path)
    g = _sample_graph()
    object.__setattr__(g, "run_id", "run_auto_create")
    # No run_dir created beforehand
    store.write(g)
    assert (tmp_path / "run_auto_create" / "graph.json").is_file()
    loaded = store.read("run_auto_create")
    assert loaded == g


def test_lock_acquire_timeout_raises_typed_exception(tmp_path: Path, monkeypatch):
    """A held lock + timeout=0 surfaces as GraphLockTimeout, not filelock.Timeout."""
    store = GraphStore(runs_root=tmp_path)
    g = _sample_graph()
    object.__setattr__(g, "run_id", "run_locked")
    store.write(g)
    monkeypatch.setattr(GraphStore, "LOCK_TIMEOUT_SECONDS", 0.1)

    held = store._lock("run_locked")
    held.acquire()
    try:
        with pytest.raises(GraphLockTimeout, match="run_locked"):
            store.write(g)
    finally:
        held.release()


def test_read_rejects_oversized_graph_json(tmp_path: Path, monkeypatch):
    """graph.json exceeding MAX_GRAPH_BYTES raises GraphDeserializationError
    without invoking json.load (JSON-bomb defense)."""
    store = GraphStore(runs_root=tmp_path)
    monkeypatch.setattr(GraphStore, "MAX_GRAPH_BYTES", 128)

    g = _sample_graph()
    object.__setattr__(g, "run_id", "run_big")
    store.write(g)  # write succeeds (no cap on write)

    # File is well-formed JSON but exceeds cap.
    path = tmp_path / "run_big" / "graph.json"
    assert path.stat().st_size > 128

    called = {"json_load": False}
    orig_load = json.load

    def spy_load(*a, **kw):
        called["json_load"] = True
        return orig_load(*a, **kw)
    monkeypatch.setattr(json, "load", spy_load)

    with pytest.raises(GraphDeserializationError, match="exceeds MAX_GRAPH_BYTES"):
        store.read("run_big")
    assert called["json_load"] is False, "size check must happen before json.load"


def test_stale_tmp_files_cleaned_up_on_write(tmp_path: Path):
    """Orphan .graph.*.tmp files (e.g. from SIGKILL'd writes) are swept on next write."""
    import os
    import time

    store = GraphStore(runs_root=tmp_path)
    run_dir = tmp_path / "run_tmp"
    run_dir.mkdir()
    stale = run_dir / ".graph.abc123.tmp"
    stale.write_text("partial")
    old = time.time() - GraphStore._TMP_STALE_SECONDS - 10
    os.utime(stale, (old, old))
    fresh = run_dir / ".graph.def456.tmp"
    fresh.write_text("still writing")

    g = _sample_graph()
    object.__setattr__(g, "run_id", "run_tmp")
    store.write(g)

    assert not stale.exists(), "stale tmp should have been cleaned"
    assert fresh.exists(), "fresh tmp must not be touched"


def test_atomic_write_failure_does_not_leak_tmp(tmp_path: Path, monkeypatch):
    """If os.replace fails, the freshly-created tmp file is cleaned up."""
    import os

    store = GraphStore(runs_root=tmp_path)
    run_dir = tmp_path / "run_fail"
    run_dir.mkdir()
    g = _sample_graph()
    object.__setattr__(g, "run_id", "run_fail")

    def boom(*a, **kw):
        raise OSError("simulated replace failure")
    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        store.write(g)

    leaked = list(run_dir.glob(".graph.*.tmp"))
    assert leaked == [], f"tmp file leaked: {leaked}"


def test_concurrent_mutate_serializes_correctly(tmp_path: Path):
    """Two threads racing to mutate the same run must both land in the final
    graph (no lost update, no partial JSON). Without locking, one thread's
    read would precede the other's write and lose its update — the FileLock
    in GraphStore.mutate() prevents that."""
    import threading
    import time

    store = GraphStore(runs_root=tmp_path)
    g = _sample_graph()
    object.__setattr__(g, "run_id", "run_race")
    store.write(g)

    errors: list[BaseException] = []

    def append_node(node_id: str, delay: float):
        def fn(graph: Graph) -> Graph:
            time.sleep(delay)  # widen the read-modify-write window
            new_nodes = dict(graph.nodes)
            new_nodes[node_id] = Node(
                id=node_id, kind=NodeKind.OPERATION, display_label=node_id,
                created_at="2026-05-18T00:00:00Z", parent_stage_id=None,
                branch_id="main",
            )
            return Graph(
                schema_version=graph.schema_version,
                run_id=graph.run_id,
                nodes=new_nodes,
                edges=graph.edges,
                branches=graph.branches,
                legacy=graph.legacy,
            )
        try:
            store.mutate("run_race", fn)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=append_node, args=("op:A", 0.1))
    t2 = threading.Thread(target=append_node, args=("op:B", 0.1))
    t1.start(); t2.start()
    t1.join(timeout=10); t2.join(timeout=10)
    assert not errors, errors

    final = store.read("run_race")
    # If the lock failed, the second writer's `current` would predate the first
    # writer's flush and one node would be missing on disk.
    assert "op:A" in final.nodes
    assert "op:B" in final.nodes
    # JSON file is well-formed (not partial).
    with (tmp_path / "run_race" / "graph.json").open() as fp:
        json.load(fp)


def test_legacy_v1_single_dp_promoted_to_list(tmp_path: Path):
    """V1.4.0 file with decision_point: {...} reads as decision_points: (DP,)."""
    legacy = {
        "schema_version": 1,
        "run_id": "r1",
        "nodes": {
            "n1": {
                "id": "n1", "kind": "model", "display_label": "m",
                "created_at": "2026-05-18T00:00:00Z",
                "parent_stage_id": None, "branch_id": "main",
                "trust": "ok", "trust_reason": None, "archived": False,
                "payload_ref": None,
                "decision_point": {
                    "decision_id": "dp1", "decision_id_alias": [],
                    "selected": "x", "candidates": [], "source": "system_default",
                    "contestability": {"is_contestable": True,
                                       "assumption_checks_needed": [],
                                       "warnings": [], "review_status": "not_needed"},
                    "reason": None,
                },
            },
        },
        "edges": {},
        "branches": {},
        "legacy": False,
    }
    g = graph_from_json(legacy)
    assert len(g.nodes["n1"].decision_points) == 1
    assert g.nodes["n1"].decision_points[0].decision_id == "dp1"


def test_v2_multi_dp_round_trips(tmp_path: Path):
    """V1.4.1 file with decision_points: [...] reads unchanged."""
    dp_dict = {
        "decision_id": "dp1", "decision_id_alias": [],
        "selected": "x", "candidates": [], "source": "system_default",
        "contestability": {"is_contestable": True, "assumption_checks_needed": [],
                           "warnings": [], "review_status": "not_needed"},
        "reason": None,
    }
    v2 = {
        "schema_version": 2,
        "run_id": "r1",
        "nodes": {
            "n1": {
                "id": "n1", "kind": "model", "display_label": "m",
                "created_at": "2026-05-19T00:00:00Z",
                "parent_stage_id": None, "branch_id": "main",
                "trust": "ok", "trust_reason": None, "archived": False,
                "payload_ref": None,
                "decision_points": [dp_dict, {**dp_dict, "decision_id": "dp2"}],
                "summary": "OLS (HC1, n=10)",
            },
        },
        "edges": {}, "branches": {}, "legacy": False,
    }
    g = graph_from_json(v2)
    assert len(g.nodes["n1"].decision_points) == 2
    assert g.nodes["n1"].decision_points[1].decision_id == "dp2"
    assert g.nodes["n1"].summary == "OLS (HC1, n=10)"


def test_dual_field_uses_decision_points(tmp_path: Path):
    """Both decision_point and decision_points present -> decision_points wins."""
    dp_old = {"decision_id": "old", "decision_id_alias": [],
              "selected": "x", "candidates": [], "source": "system_default",
              "contestability": {"is_contestable": True,
                                 "assumption_checks_needed": [], "warnings": [],
                                 "review_status": "not_needed"},
              "reason": None}
    dp_new = {**dp_old, "decision_id": "new"}
    mixed = {
        "schema_version": 2, "run_id": "r1",
        "nodes": {
            "n1": {
                "id": "n1", "kind": "model", "display_label": "m",
                "created_at": "2026-05-19T00:00:00Z", "parent_stage_id": None,
                "branch_id": "main", "trust": "ok", "trust_reason": None,
                "archived": False, "payload_ref": None,
                "decision_point": dp_old,
                "decision_points": [dp_new],
            }
        },
        "edges": {}, "branches": {}, "legacy": False,
    }
    g = graph_from_json(mixed)
    assert len(g.nodes["n1"].decision_points) == 1
    assert g.nodes["n1"].decision_points[0].decision_id == "new"


def test_missing_dp_field_yields_empty_tuple(tmp_path: Path):
    """Neither decision_point nor decision_points -> empty tuple."""
    missing = {
        "schema_version": 2, "run_id": "r1",
        "nodes": {
            "n1": {
                "id": "n1", "kind": "model", "display_label": "m",
                "created_at": "2026-05-19T00:00:00Z", "parent_stage_id": None,
                "branch_id": "main", "trust": "ok", "trust_reason": None,
                "archived": False, "payload_ref": None,
            }
        },
        "edges": {}, "branches": {}, "legacy": False,
    }
    g = graph_from_json(missing)
    assert g.nodes["n1"].decision_points == ()


def test_writer_emits_schema_version_2(tmp_path: Path):
    """graph_to_json always emits schema_version: 2."""
    g = _sample_graph()
    object.__setattr__(g, "schema_version", 1)  # simulate old in-memory
    data = graph_to_json(g)
    assert data["schema_version"] == 2
    for nd in data["nodes"].values():
        assert "decision_point" not in nd
        assert "decision_points" in nd


def test_trust_warning_and_blocker_round_trip(tmp_path: Path):
    """Trust.WARNING and Trust.BLOCKER serialize and deserialize correctly."""
    for trust_value in (Trust.WARNING, Trust.BLOCKER):
        store = GraphStore(runs_root=tmp_path)
        node = Node(
            id="n1", kind=NodeKind.MODEL, display_label="m",
            created_at="2026-05-19T00:00:00Z", parent_stage_id=None,
            branch_id="main", trust=trust_value,
            trust_reason=f"test reason for {trust_value.value}",
        )
        g = Graph(schema_version=2, run_id=f"run_{trust_value.value}",
                  nodes={"n1": node}, edges={}, branches={})
        store.write(g)
        reloaded = store.read(f"run_{trust_value.value}")
        assert reloaded.nodes["n1"].trust == trust_value
        assert reloaded.nodes["n1"].trust_reason == f"test reason for {trust_value.value}"
