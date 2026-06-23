from workbench.lineage.node_store import (
    write_node_result, read_node_result, node_result_exists,
    add_head_ref, heads_for_node,
)


def test_idempotent_write(tmp_path):
    h = "abc123"
    meta = {"status": "ok", "stats": {"r2": 0.4}, "summary": "x"}
    write_node_result(tmp_path, h, meta=meta, artifacts={"model.json": b"{}"})
    write_node_result(tmp_path, h, meta=meta, artifacts={"model.json": b"{}"})  # again, idempotent
    assert node_result_exists(tmp_path, h)
    got = read_node_result(tmp_path, h)
    assert got["meta"]["stats"]["r2"] == 0.4
    assert got["artifacts"]["model.json"] == b"{}"


def test_ref_ledger(tmp_path):
    add_head_ref(tmp_path, head_run_id="run_002", node_hash="abc123")
    add_head_ref(tmp_path, head_run_id="run_002", node_hash="abc123")  # idempotent
    assert heads_for_node(tmp_path, "abc123") == ["run_002"]
