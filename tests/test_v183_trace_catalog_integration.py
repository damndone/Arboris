from __future__ import annotations

import pytest

from workbench.agent.trace import (
    TraceCatalogCollision,
    TraceSchemaDescriptor,
    register_trace_catalog,
    trace_catalog_snapshot,
)
from workbench.app import app


def test_v183_app_bootstrap_registers_lane_catalogs_once() -> None:
    snapshot = trace_catalog_snapshot()

    assert snapshot["capability_factory"]
    assert snapshot["native_containment"]
    assert snapshot["domain_memory"]
    assert "capability.consumer_projection.validated" in snapshot["capability_factory"]
    assert "host_containment.assessed" in snapshot["native_containment"]
    assert "domain_memory.preference.changed" in snapshot["domain_memory"]
    assert "domain_memory.retrieval.completed" in snapshot["core"]
    assert "/health" in app.openapi()["paths"]


def test_v183_trace_catalog_rejects_cross_owner_schema_collision() -> None:
    descriptor = TraceSchemaDescriptor(
        payload_schema="test-collision/v1",
        required=("ref",),
    )

    with pytest.raises(TraceCatalogCollision, match="already registered"):
        register_trace_catalog(
            "test-collision-owner",
            {"capability.consumer_projection.validated": descriptor},
        )


def test_v183_trace_catalog_registration_is_idempotent_for_same_owner() -> None:
    descriptor = TraceSchemaDescriptor(
        payload_schema="test-idempotent/v1",
        required=("ref",),
    )
    event_type = "test.integration.catalog.event"

    register_trace_catalog("test-idempotent-owner", {event_type: descriptor})
    register_trace_catalog("test-idempotent-owner", {event_type: descriptor})

    assert event_type in trace_catalog_snapshot()["test-idempotent-owner"]


def test_v183_trace_catalog_collision_is_atomic() -> None:
    first = TraceSchemaDescriptor(payload_schema="test-atomic-first/v1", required=("ref",))
    collision = TraceSchemaDescriptor(payload_schema="test-atomic-collision/v1", required=("ref",))

    with pytest.raises(TraceCatalogCollision):
        register_trace_catalog(
            "test-atomic-owner",
            {
                "test.integration.catalog.new": first,
                "capability.consumer_projection.validated": collision,
            },
        )

    assert "test-atomic-owner" not in trace_catalog_snapshot()
