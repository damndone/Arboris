"""The WO-D harness inventory is verified from an exact Git tree, never a dirty lane."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from workbench.evaluator_harness_manifest import (
    HarnessManifestError,
    load_harness_manifest,
    verify_harness_manifest,
)


LANE = Path("/Users/jiayuanren/项目规划/.worktrees/v173-evaluation-harness")
MANIFEST = Path(__file__).parents[1] / "backend/workbench/evaluator_harness_manifest_v1.json"
INTEGRATION_BASE_SHA = "0251f0a30d984bdbb2cfab404e6c646deab60cae"
LANE_SHA = "97c40de7e5f2e6fb5d97e41ef2831f102aee3229"


def test_manifest_verifies_only_the_exact_committed_lane_tree_despite_dirty_worktree() -> None:
    manifest = load_harness_manifest(MANIFEST)
    verified = verify_harness_manifest(manifest, lane_repository=LANE, integration_base_sha=INTEGRATION_BASE_SHA)

    assert verified.lane_commit_sha == LANE_SHA
    assert verified.file_count == 16
    assert verified.migration_allowed is False
    assert verified.assembled_integration_sha is None
    assert all(command.argv for command in manifest.test_commands)
    assert all(entry.owner == "WO-D evaluation" for entry in manifest.files)


def test_manifest_rejects_integration_binding_hash_drift_and_inventory_changes() -> None:
    manifest = load_harness_manifest(MANIFEST)
    with pytest.raises(HarnessManifestError, match="Integration base SHA"):
        verify_harness_manifest(manifest, lane_repository=LANE, integration_base_sha="0" * 40)
    with pytest.raises(HarnessManifestError, match="file inventory"):
        verify_harness_manifest(replace(manifest, files=manifest.files[:-1]), lane_repository=LANE, integration_base_sha=INTEGRATION_BASE_SHA)
    bad_file = replace(manifest.files[0], sha256="0" * 64)
    with pytest.raises(HarnessManifestError, match="sha256"):
        verify_harness_manifest(replace(manifest, files=(bad_file, *manifest.files[1:])), lane_repository=LANE, integration_base_sha=INTEGRATION_BASE_SHA)


def test_inventory_module_never_imports_or_executes_harness_content() -> None:
    import inspect
    import workbench.evaluator_harness_manifest as inventory

    source = inspect.getsource(inventory)
    assert "importlib" not in source
    assert "Popen(" not in source
    assert "shell=True" not in source
