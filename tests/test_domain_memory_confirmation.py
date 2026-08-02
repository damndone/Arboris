from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def test_confirmation_is_single_use_and_bound_to_the_exact_mutation() -> None:
    from workbench.domain_memory.confirmation import (
        MemoryMutationConfirmationError,
        MemoryMutationConfirmationRegistry,
        MemoryMutationIntent,
    )

    now = datetime(2026, 8, 1, tzinfo=UTC)
    registry = MemoryMutationConfirmationRegistry(clock=lambda: now)
    intent = MemoryMutationIntent(
        action="enable_project_memory",
        scope_ref="scope-project-a",
        expected_revision=0,
        target_refs=(),
    )

    confirmation = registry.issue(intent)
    registry.consume(confirmation.receipt, intent)

    with pytest.raises(MemoryMutationConfirmationError, match="consumed"):
        registry.consume(confirmation.receipt, intent)


def test_confirmation_rejects_scope_change_and_expiry() -> None:
    from workbench.domain_memory.confirmation import (
        MemoryMutationConfirmationError,
        MemoryMutationConfirmationRegistry,
        MemoryMutationIntent,
    )

    now = datetime(2026, 8, 1, tzinfo=UTC)
    registry = MemoryMutationConfirmationRegistry(clock=lambda: now, ttl=timedelta(seconds=30))
    original = MemoryMutationIntent("archive_memories", "scope-project-a", 4, ("memory-a@2",))
    changed_scope = MemoryMutationIntent("archive_memories", "scope-project-b", 4, ("memory-a@2",))

    confirmation = registry.issue(original)
    with pytest.raises(MemoryMutationConfirmationError, match="binding"):
        registry.consume(confirmation.receipt, changed_scope)

    confirmation = registry.issue(original)
    now += timedelta(seconds=31)
    with pytest.raises(MemoryMutationConfirmationError, match="expired"):
        registry.consume(confirmation.receipt, original)
