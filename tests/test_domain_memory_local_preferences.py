from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_local_memory_preferences_are_default_off_scoped_and_persistent(tmp_path: Path) -> None:
    """A project's opt-in must survive restart without granting another project access."""

    from workbench.domain_memory.local_preferences import LocalMemoryPreferenceStore
    from workbench.domain_memory.local_runtime import bootstrap_local_domain_memory_runtime

    root = tmp_path / "memory"
    first_project = tmp_path / "first-project"
    second_project = tmp_path / "second-project"
    first_project.mkdir()
    second_project.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(root)
    preferences = LocalMemoryPreferenceStore(root)
    first_scope = runtime.scope_resolver.project_scope(first_project)
    second_scope = runtime.scope_resolver.project_scope(second_project)

    assert preferences.global_settings().library_enabled is False
    assert preferences.project_settings(first_scope).library_enabled is False
    assert preferences.project_settings(first_scope).inherit_global is False
    assert preferences.project_settings(first_scope).candidate_generation_enabled is False

    preferences.update_global(expected_revision=0, library_enabled=True)
    preferences.update_project(
        first_scope,
        expected_revision=0,
        library_enabled=True,
        inherit_global=True,
        candidate_generation_enabled=True,
    )

    restarted = LocalMemoryPreferenceStore(root)
    assert restarted.global_settings().library_enabled is True
    assert restarted.project_settings(first_scope).library_enabled is True
    assert restarted.project_settings(first_scope).inherit_global is True
    assert restarted.project_settings(first_scope).candidate_generation_enabled is True
    assert restarted.project_settings(second_scope).library_enabled is False
    preference_bytes = (root / ".domain-memory-preferences-v1.json").read_bytes()
    assert str(first_project).encode("utf-8") not in preference_bytes


def test_local_memory_preference_write_handles_partial_os_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atomic replacement is only safe when the temporary payload is complete."""

    from workbench.domain_memory.local_preferences import LocalMemoryPreferenceStore
    from workbench.domain_memory.local_runtime import bootstrap_local_domain_memory_runtime

    root = tmp_path / "memory"
    bootstrap_local_domain_memory_runtime(root)
    preferences = LocalMemoryPreferenceStore(root)
    original_write = os.write

    def partial_write(file_descriptor: int, payload: bytes) -> int:
        return original_write(file_descriptor, payload[: max(1, len(payload) // 2)])

    monkeypatch.setattr(os, "write", partial_write)
    preferences.update_global(expected_revision=0, library_enabled=True)

    assert LocalMemoryPreferenceStore(root).global_settings().library_enabled is True


def test_direct_preference_store_rejects_a_symlinked_ancestor(tmp_path: Path) -> None:
    """Its public constructor must keep the same boundary as bootstrap."""

    from workbench.domain_memory.local_preferences import (
        LocalMemoryPreferenceError,
        LocalMemoryPreferenceStore,
    )

    target = tmp_path / "target"
    target.mkdir()
    parent_link = tmp_path / "memory-link"
    parent_link.symlink_to(target, target_is_directory=True)
    (target / "memory").mkdir()

    with pytest.raises(LocalMemoryPreferenceError, match="root is unavailable"):
        LocalMemoryPreferenceStore(parent_link / "memory")
