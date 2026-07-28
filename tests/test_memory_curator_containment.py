from __future__ import annotations

from pathlib import Path

from workbench.domain_memory.candidate_store import MemoryCandidateStore
from workbench.domain_memory.curator_runtime import CuratorRuntime
from workbench.domain_memory.preferences import DomainMemoryPreferences, resolve_preferences
from workbench.domain_memory.scope import MemoryScope

from test_memory_curator_contracts import _summary


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def test_curator_writes_only_pending_candidates_and_not_official_memory(tmp_path: Path) -> None:
    candidates = MemoryCandidateStore(tmp_path, SCOPE)
    runtime = CuratorRuntime(candidates)
    effective = resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_iteration=True))
    created = runtime.generate(_summary(), effective)
    assert len(created) == 1
    assert created[0].status == "proposed"
    assert candidates.pending(SCOPE) == created
    assert not (tmp_path / "domain-memory.jsonl").exists()


def test_curator_is_idempotent_and_default_off(tmp_path: Path) -> None:
    candidates = MemoryCandidateStore(tmp_path, SCOPE)
    runtime = CuratorRuntime(candidates)
    disabled = resolve_preferences(SCOPE, DomainMemoryPreferences())
    assert runtime.generate(_summary(), disabled) == ()
    enabled = resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_iteration=True))
    assert runtime.generate(_summary(), enabled) == runtime.generate(_summary(), enabled)
