"""V1812-LOCAL-EVIDENCE-RETENTION: test evidence in local/ stops growing.

Tests that keep evidence write it under ``local/test-evidence/<category>/<run>``,
one run directory per pytest session. At the end of a session each category
keeps its three newest runs; a run marked failed, or explicitly kept, is never
removed. Nothing outside ``local/test-evidence`` is ever pruned, so older
evidence and the user's archives stay untouched (the user's "never delete
automatically" rule has this one bounded exception, 2026-10-07).
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest

import evidence_retention
from evidence_retention import EvidenceStore


def _session(root, number: int) -> EvidenceStore:
    return EvidenceStore(root, stamp=f"20261007T{number:06d}-{1000 + number}")


def _runs(root, category: str) -> list[str]:
    directory = root / category
    return sorted(path.name for path in directory.iterdir()) if directory.exists() else []


def test_a_store_creates_nothing_until_evidence_is_written(tmp_path):
    store = _session(tmp_path, 1)
    assert list(tmp_path.iterdir()) == []
    path = store.run_dir("lmm-host")
    assert path == tmp_path / "lmm-host" / "20261007T000001-1001"
    assert path.is_dir()
    assert store.run_dir("lmm-host") == path


def test_each_category_keeps_its_three_newest_runs(tmp_path):
    for number in range(1, 5):
        store = _session(tmp_path, number)
        (store.run_dir("script-adapter-runs") / "case").mkdir()
        store.prune()
        assert len(_runs(tmp_path, "script-adapter-runs")) == min(number, 3)
    assert _runs(tmp_path, "script-adapter-runs") == [
        "20261007T000002-1002",
        "20261007T000003-1003",
        "20261007T000004-1004",
    ]


def test_a_failed_run_is_always_kept(tmp_path):
    first = _session(tmp_path, 1)
    first.run_dir("lmm-host")
    first.mark_failed("lmm-host", "tests/test_x.py::test_y")
    first.prune()
    for number in range(2, 7):
        store = _session(tmp_path, number)
        store.run_dir("lmm-host")
        store.prune()
    runs = _runs(tmp_path, "lmm-host")
    assert "20261007T000001-1001" in runs
    assert len(runs) == 4
    marker = tmp_path / "lmm-host" / "20261007T000001-1001" / ".failed"
    assert "tests/test_x.py::test_y" in marker.read_text()


def test_an_explicitly_kept_run_is_always_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_KEEP_EVIDENCE", "1")
    _session(tmp_path, 1).run_dir("lmm-host")
    monkeypatch.delenv("WORKBENCH_KEEP_EVIDENCE")
    for number in range(2, 7):
        store = _session(tmp_path, number)
        store.run_dir("lmm-host")
        store.prune()
    assert "20261007T000001-1001" in _runs(tmp_path, "lmm-host")
    assert (tmp_path / "lmm-host" / "20261007T000001-1001" / ".keep").is_file()


def test_pruning_touches_only_run_directories_of_categories_this_session_used(tmp_path):
    for number in range(1, 5):
        _session(tmp_path, number).run_dir("unused-here")
    legacy = tmp_path / "lmm-host" / "runs"
    legacy.mkdir(parents=True)
    note = tmp_path / "lmm-host" / "README.txt"
    note.write_text("kept")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "lmm-host" / "20261007T000000-999").symlink_to(outside, target_is_directory=True)
    for number in range(1, 5):
        store = _session(tmp_path, number)
        store.run_dir("lmm-host")
        store.prune()
    assert legacy.is_dir() and note.is_file()
    assert (tmp_path / "lmm-host" / "20261007T000000-999").is_symlink()
    assert outside.is_dir()
    assert len(_runs(tmp_path, "unused-here")) == 4


def test_failures_are_attributed_to_the_tests_that_wrote_evidence(tmp_path, monkeypatch):
    store = _session(tmp_path, 1)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_a.py::test_writes (call)")
    store.run_dir("script-adapter-runs")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_b.py::test_other (call)")
    store.run_dir("public-integrity")
    store.test_failed("tests/test_c.py::test_unrelated")
    assert not (store.run_dir("script-adapter-runs") / ".failed").exists()
    store.test_failed("tests/test_a.py::test_writes")
    assert (store.run_dir("script-adapter-runs") / ".failed").is_file()
    assert not (store.run_dir("public-integrity") / ".failed").exists()


def test_importing_an_evidence_writing_test_module_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence_retention, "STORE", EvidenceStore(tmp_path, stamp="20261007T000001-1"))
    monkeypatch.delenv("WB_SCRIPT_PUBLIC_REVIEW_EVIDENCE", raising=False)
    local = evidence_retention.REPO / "local"

    def listing():
        return {str(path) for path in local.glob("*/*")} if local.exists() else set()

    before = listing()
    for name in ("test_script_export_public_integrity", "test_script_export_v1811_statistical_adapters"):
        module = sys.modules.get(name) or importlib.import_module(name)
        importlib.reload(module)
    assert list(tmp_path.iterdir()) == []
    assert listing() == before


def test_evidence_writers_use_the_managed_root():
    root = evidence_retention.STORE.root
    assert root == evidence_retention.REPO / "local" / "test-evidence"
    for name in (
        "test_script_export_public_integrity.py",
        "test_script_export_v1811_statistical_adapters.py",
        "test_admission_oracle_linear_mixed_effects.py",
        "test_script_export_data_oracles.py",
    ):
        source = (evidence_retention.REPO / "tests" / name).read_text(encoding="utf-8")
        assert '"local/v1811-' not in source and "local_runs" not in source, name
        assert "run_dir(" in source, name


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_run_directories_are_private(tmp_path):
    path = _session(tmp_path, 1).run_dir("script-adapter-raw-logs")
    assert path.stat().st_mode & 0o077 == 0
