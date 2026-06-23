from workbench.lineage.hashing import (
    PIPELINE_VERSION,
    canonicalize,
    dag_hash,
    override_hash,
)


def test_canonicalize_is_order_independent():
    assert canonicalize({"b": 1, "a": 2}) == canonicalize({"a": 2, "b": 1})


def test_override_hash_deterministic_under_reordering():
    assert override_hash({"x": "1", "y": "2"}) == override_hash({"y": "2", "x": "1"})


def test_override_hash_changes_with_value():
    assert override_hash({"x": "1"}) != override_hash({"x": "2"})


def test_dag_hash_combines_inputs():
    h1 = dag_hash("sha_a", {"y": "z"})
    h2 = dag_hash("sha_b", {"y": "z"})
    assert h1 != h2 and len(h1) == 64


def test_pipeline_version_is_a_nonempty_str():
    assert isinstance(PIPELINE_VERSION, str) and PIPELINE_VERSION
