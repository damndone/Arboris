"""A comparison the user can keep: a durable node joining two model nodes.

Until now "compare" was ephemeral React state that vanished on reload, so a
conclusion the user reached could not be revisited, cited, or shown to anyone.
Making it a node raises three questions these tests pin down: what identifies a
comparison, which pairs may be compared at all, and what happens when the same
pair is compared twice.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workbench.lineage.compare_nodes import (
    COMPARE_NODE_SCHEMA_ID,
    CompareEndpoint,
    CompareNodeError,
    CompareNodeStore,
    build_compare_node,
    compare_node_id,
)


LEFT = CompareEndpoint(
    run_id="run-a",
    node_id="model:arma_garch_1",
    node_hash="a" * 64,
    forest_node_key=f"{'a' * 64}::model:arma_garch_1",
)
RIGHT = CompareEndpoint(
    run_id="run-b",
    node_id="model:arma_garch_1",
    node_hash="b" * 64,
    forest_node_key=f"{'b' * 64}::model:arma_garch_1",
)


def _record(left: CompareEndpoint = LEFT, right: CompareEndpoint = RIGHT, **kwargs):
    return build_compare_node(
        left=left,
        right=right,
        packet={"kind": "test", "findings": []},
        created_at="2026-07-21T00:00:00+00:00",
        **kwargs,
    )


def test_identity_is_symmetric_so_one_pair_is_one_node() -> None:
    """A comparison is a relationship, not a direction.

    If A-vs-B and B-vs-A minted different ids, the graph would grow two nodes
    for one question and the user would have to remember which they made.
    """

    assert compare_node_id(LEFT, RIGHT) == compare_node_id(RIGHT, LEFT)


def test_identity_changes_when_either_endpoint_changes() -> None:
    other = CompareEndpoint(
        run_id="run-c",
        node_id="model:arma_garch_1",
        node_hash="c" * 64,
        forest_node_key=f"{'c' * 64}::model:arma_garch_1",
    )

    assert compare_node_id(LEFT, RIGHT) != compare_node_id(LEFT, other)


def test_endpoints_are_stored_in_a_canonical_order_whichever_way_they_arrive() -> None:
    """Swapping sides is a view concern, so it must not create a second record."""

    forward = _record(LEFT, RIGHT)
    reversed_ = _record(RIGHT, LEFT)

    assert forward.left == reversed_.left
    assert forward.right == reversed_.right
    assert forward.to_dict() == reversed_.to_dict()


def test_a_declared_ancestor_is_placed_first() -> None:
    """When one node produced the other, the older side is the baseline."""

    record = _record(RIGHT, LEFT, ancestor_forest_node_key=RIGHT.forest_node_key)

    assert record.left == RIGHT
    assert record.right == LEFT
    assert record.relation == "ancestor_descendant"


def test_an_undeclared_relation_is_reported_as_unrelated_not_guessed() -> None:
    record = _record()

    assert record.relation == "unrelated"


def test_comparing_a_node_with_itself_is_refused() -> None:
    with pytest.raises(CompareNodeError) as excinfo:
        _record(LEFT, LEFT)

    assert excinfo.value.code == "COMPARE_SELF"


def test_an_ancestor_key_that_is_not_an_endpoint_is_refused() -> None:
    # Silently ignoring it would order the record by the wrong rule while
    # still claiming an ancestor relation.
    with pytest.raises(CompareNodeError) as excinfo:
        _record(ancestor_forest_node_key="d" * 64)

    assert excinfo.value.code == "COMPARE_ANCESTOR_NOT_AN_ENDPOINT"


def test_an_endpoint_without_a_node_hash_is_refused() -> None:
    unidentified = CompareEndpoint(
        run_id="run-c", node_id="model:x", node_hash="", forest_node_key="model:x"
    )

    with pytest.raises(CompareNodeError) as excinfo:
        _record(LEFT, unidentified)

    assert excinfo.value.code == "COMPARE_ENDPOINT_NOT_IDENTIFIED"


def test_the_record_declares_its_schema(tmp_path: Path) -> None:
    assert _record().schema_id == COMPARE_NODE_SCHEMA_ID


class TestStore:
    def test_a_created_node_can_be_read_back(self, tmp_path: Path) -> None:
        store = CompareNodeStore(tmp_path)
        record = _record()

        store.create(record)

        assert store.get(record.compare_id).to_dict() == record.to_dict()
        assert [item.compare_id for item in store.list()] == [record.compare_id]

    def test_comparing_the_same_pair_twice_reuses_the_node(self, tmp_path: Path) -> None:
        store = CompareNodeStore(tmp_path)
        store.create(_record())

        again = store.create(_record(RIGHT, LEFT))

        assert [item.compare_id for item in store.list()] == [again.compare_id]

    def test_reuse_is_not_defeated_by_the_clock(self, tmp_path: Path) -> None:
        """Found by the API test: the second request happens at a later instant.

        Treating `created_at` as part of the conflict check made every repeat
        comparison look like a divergent rewrite, so asking the same question
        twice failed instead of returning the answer already stored.
        """

        store = CompareNodeStore(tmp_path)
        first = store.create(_record())
        later = build_compare_node(
            left=LEFT,
            right=RIGHT,
            packet={"kind": "test", "findings": []},
            created_at="2026-08-01T12:00:00+00:00",
        )

        reused = store.create(later)

        assert reused.created_at == first.created_at

    def test_a_conflicting_rewrite_is_refused_rather_than_silently_replacing(
        self, tmp_path: Path
    ) -> None:
        """The stored packet is evidence; overwriting it would rewrite history."""

        store = CompareNodeStore(tmp_path)
        store.create(_record())
        divergent = build_compare_node(
            left=LEFT,
            right=RIGHT,
            packet={"kind": "test", "findings": ["CHANGED"]},
            created_at="2026-07-21T00:00:00+00:00",
        )

        with pytest.raises(CompareNodeError) as excinfo:
            store.create(divergent)

        assert excinfo.value.code == "COMPARE_NODE_CONFLICT"

    def test_a_deleted_node_disappears(self, tmp_path: Path) -> None:
        store = CompareNodeStore(tmp_path)
        record = store.create(_record())

        assert store.delete(record.compare_id) is True
        assert store.list() == []
        assert store.delete(record.compare_id) is False

    def test_an_unreadable_record_is_skipped_rather_than_failing_the_listing(
        self, tmp_path: Path
    ) -> None:
        store = CompareNodeStore(tmp_path)
        store.create(_record())
        (store.root / "not-a-record.json").write_text("{ broken", encoding="utf-8")

        assert len(store.list()) == 1

    def test_listing_an_absent_directory_is_empty_not_an_error(
        self, tmp_path: Path
    ) -> None:
        assert CompareNodeStore(tmp_path / "fresh", create=False).list() == []


class TestForestProjection:
    """A compare node is drawn only where both of its endpoints exist."""

    def _forest_nodes(self) -> dict[str, dict]:
        return {
            LEFT.forest_node_key: {"id": LEFT.node_id, "kind": "model", "runs": ["run-a"]},
            RIGHT.forest_node_key: {"id": RIGHT.node_id, "kind": "model", "runs": ["run-b"]},
        }

    def test_the_comparison_joins_its_two_endpoints(self) -> None:
        from workbench.lineage.compare_nodes import compare_forest_projection

        record = _record()
        nodes, edges = compare_forest_projection(self._forest_nodes(), [record])

        assert list(nodes) == [record.compare_id]
        node = nodes[record.compare_id]
        assert node["kind"] == "compare"
        assert node["runs"] == ["run-a", "run-b"]
        # Two incoming edges is the whole point: this is where the lineage
        # stops being a set of chains and becomes a DAG.
        assert sorted((edge["source"], edge["target"]) for edge in edges) == sorted(
            [
                (LEFT.forest_node_key, record.compare_id),
                (RIGHT.forest_node_key, record.compare_id),
            ]
        )
        assert {edge["op"] for edge in edges} == {"compare"}

    def test_a_comparison_with_a_missing_endpoint_is_not_drawn(self) -> None:
        from workbench.lineage.compare_nodes import compare_forest_projection

        only_left = {LEFT.forest_node_key: {"id": LEFT.node_id, "kind": "model"}}
        nodes, edges = compare_forest_projection(only_left, [_record()])

        # Drawing it would mean an edge from a node that is not on the canvas.
        assert nodes == {}
        assert edges == []

    def test_the_stored_packet_travels_with_the_node(self) -> None:
        from workbench.lineage.compare_nodes import compare_forest_projection

        record = _record()
        nodes, _edges = compare_forest_projection(self._forest_nodes(), [record])

        compare = nodes[record.compare_id]["compare"]
        assert compare["packet"] == record.packet
        assert compare["relation"] == "unrelated"
        assert compare["left"]["run_id"] == "run-a"
