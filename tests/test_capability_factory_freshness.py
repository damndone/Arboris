from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest


def _freshness():
    try:
        return importlib.import_module("workbench.capability_factory.freshness")
    except ModuleNotFoundError as error:
        pytest.fail(f"CF1 freshness module is not implemented: {error}")


def test_current_cursor_accepts_matching_ref_and_rejects_stale_or_missing_domains():
    freshness = _freshness()
    cursor = freshness.ValidityCursor(
        domain="implementation",
        sequence=3,
        state_digest="a" * 64,
        authority_ref="b" * 64,
        valid_until=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )
    snapshot = freshness.ValidityCursorSnapshot(
        cursors={"implementation": cursor},
        observed_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )

    current = freshness.assess_freshness(
        required_domains=("implementation",),
        candidate_refs={"implementation": "a" * 64},
        current=snapshot,
    )
    stale = freshness.assess_freshness(
        required_domains=("implementation",),
        candidate_refs={"implementation": "b" * 64},
        current=snapshot,
    )
    missing = freshness.assess_freshness(
        required_domains=("host",),
        candidate_refs={"implementation": "a" * 64},
        current=snapshot,
    )

    assert current.status == "current"
    assert stale.status == "stale"
    assert missing.status == "unavailable"
    assert snapshot.content_digest == snapshot.content_digest


def test_cursor_snapshot_is_immutable_and_sequences_cannot_go_backwards():
    freshness = _freshness()
    cursor = freshness.ValidityCursor(
        domain="implementation",
        sequence=3,
        state_digest="a" * 64,
        authority_ref="b" * 64,
        valid_until=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )
    snapshot = freshness.ValidityCursorSnapshot(
        cursors={"implementation": cursor},
        observed_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )
    with pytest.raises(freshness.FreshnessContractError, match="sequence"):
        freshness.ValidityCursor(
            domain="implementation",
            sequence=0,
            state_digest="a" * 64,
            authority_ref="b" * 64,
            valid_until=datetime(2026, 7, 27, tzinfo=timezone.utc),
        )
    with pytest.raises(TypeError):
        snapshot.cursors["host"] = cursor


def test_revoked_or_expired_cursor_cannot_be_treated_as_current():
    freshness = _freshness()
    observed_at = datetime(2026, 7, 26, tzinfo=timezone.utc)
    for status, valid_until in (
        ("revoked", observed_at + timedelta(days=1)),
        ("valid", observed_at - timedelta(seconds=1)),
    ):
        cursor = freshness.ValidityCursor(
            domain="implementation",
            sequence=3,
            state_digest="a" * 64,
            authority_ref="b" * 64,
            status=status,
            valid_until=valid_until,
        )
        snapshot = freshness.ValidityCursorSnapshot(
            cursors={"implementation": cursor}, observed_at=observed_at
        )
        result = freshness.assess_freshness(
            required_domains=("implementation",),
            candidate_refs={"implementation": "a" * 64},
            current=snapshot,
        )
        assert result.status == "stale"
