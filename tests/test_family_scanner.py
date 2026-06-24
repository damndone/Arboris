"""2B.1 — serve-layer family scanner over the rerun forest.

Builds the cross-run lineage family (ancestors / descendants / siblings) by walking
each run's `run_inputs.json::rerun_of`. Pure serve-layer: it never touches graph.json.
A run is `legacy` when it has no node_index.json (flag-off / pre-v1.6.1 runs), so a
mixed legacy/new family must degrade without crashing.
"""
import json
from pathlib import Path

from workbench.lineage.family import scan_family


def _make_run(runs_dir: Path, run_id: str, *, rerun_of: str | None, node_index: bool) -> None:
    run_root = runs_dir / run_id
    run_root.mkdir(parents=True)
    (run_root / "run_inputs.json").write_text(
        json.dumps({"run_input_schema_version": 1, "rerun_of": rerun_of, "form": {}})
    )
    if node_index:
        (run_root / "node_index.json").write_text(json.dumps({}))


def test_family_ancestors_descendants_siblings(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _make_run(runs, "run_001", rerun_of=None, node_index=True)
    _make_run(runs, "run_002", rerun_of="run_001", node_index=True)
    _make_run(runs, "run_003", rerun_of="run_001", node_index=True)

    fam = scan_family(runs, "run_002")

    assert fam.self_id == "run_002"
    assert fam.ancestors == ["run_001"]
    assert fam.descendants == []
    assert fam.siblings == ["run_003"]
    assert set(fam.members) == {"run_001", "run_002", "run_003"}
    assert fam.members["run_002"].legacy is False


def test_family_descendants_chain(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _make_run(runs, "run_001", rerun_of=None, node_index=True)
    _make_run(runs, "run_002", rerun_of="run_001", node_index=True)
    _make_run(runs, "run_003", rerun_of="run_002", node_index=True)

    fam = scan_family(runs, "run_001")
    assert fam.ancestors == []
    assert set(fam.descendants) == {"run_002", "run_003"}
    assert fam.siblings == []


def test_family_mixed_legacy_does_not_crash(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    # Legacy root: no node_index.json, and even missing run_inputs is tolerated.
    _make_run(runs, "run_legacy", rerun_of=None, node_index=False)
    _make_run(runs, "run_new", rerun_of="run_legacy", node_index=True)

    fam = scan_family(runs, "run_new")
    assert fam.ancestors == ["run_legacy"]
    assert fam.members["run_legacy"].legacy is True
    assert fam.members["run_new"].legacy is False


def test_family_run_inputs_missing_is_opaque_root(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_root = runs / "run_opaque"
    run_root.mkdir(parents=True)  # no run_inputs.json at all

    fam = scan_family(runs, "run_opaque")
    assert fam.self_id == "run_opaque"
    assert fam.ancestors == []
    assert fam.descendants == []
    assert fam.siblings == []
    assert fam.members["run_opaque"].legacy is True
    assert fam.members["run_opaque"].rerun_of is None


def test_family_unknown_run_returns_singleton(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _make_run(runs, "run_001", rerun_of=None, node_index=True)

    fam = scan_family(runs, "run_404")
    assert fam.self_id == "run_404"
    assert fam.ancestors == []
    assert fam.descendants == []
    assert fam.siblings == []
    assert fam.members["run_404"].legacy is True
