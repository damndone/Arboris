from __future__ import annotations

from dataclasses import replace

import pytest

from workbench.capability_factory.consumer import (
    ConsumerProjectionError,
    build_consumer_projection,
)

from test_capability_custom_dispatcher import _records


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def test_consumer_projection_requires_explicit_supported_slots() -> None:
    implementation, adapter, _binding = _records()
    projection = build_consumer_projection(
        adapter=adapter,
        implementation=implementation,
        requested_slots=("report_projection",),
        projection_refs={"report_projection": _digest("a")},
        payload_schema_refs={"report_projection": _digest("b")},
        artifact_facets={"report_projection": ("parameters",)},
    )

    assert projection.slot_names == ("report_projection",)
    assert projection.slot("report_projection").source_eligible is False
    assert projection.content_digest == projection.content_digest
    assert projection.to_dict()["content_digest"] == projection.content_digest

    with pytest.raises(ConsumerProjectionError, match="unsupported"):
        projection.slot("diagnostic_adapter")


def test_consumer_projection_does_not_inherit_a_different_slot() -> None:
    implementation, adapter, _binding = _records()
    with pytest.raises(ConsumerProjectionError, match="unsupported"):
        build_consumer_projection(
            adapter=adapter,
            implementation=implementation,
            requested_slots=("diagnostic_adapter",),
            projection_refs={"diagnostic_adapter": _digest("a")},
            payload_schema_refs={"diagnostic_adapter": _digest("b")},
            artifact_facets={"diagnostic_adapter": ("parameters",)},
        )

    with pytest.raises(ConsumerProjectionError, match="cover"):
        build_consumer_projection(
            adapter=adapter,
            implementation=implementation,
            requested_slots=("report_projection",),
            projection_refs={},
            payload_schema_refs={"report_projection": _digest("b")},
            artifact_facets={"report_projection": ("parameters",)},
        )


def test_consumer_projection_rejects_rebound_adapter_identity() -> None:
    implementation, adapter, _binding = _records()
    forged = replace(implementation, implementation_id="implementation.other")
    with pytest.raises(ConsumerProjectionError, match="identity"):
        build_consumer_projection(
            adapter=adapter,
            implementation=forged,
            requested_slots=("report_projection",),
            projection_refs={"report_projection": _digest("a")},
            payload_schema_refs={"report_projection": _digest("b")},
            artifact_facets={"report_projection": ("parameters",)},
        )


def test_consumer_projection_can_publish_its_bounded_validation_event() -> None:
    implementation, adapter, _binding = _records()
    events = []
    projection = build_consumer_projection(
        adapter=adapter,
        implementation=implementation,
        requested_slots=("report_projection",),
        projection_refs={"report_projection": _digest("a")},
        payload_schema_refs={"report_projection": _digest("b")},
        artifact_facets={"report_projection": ("parameters",)},
        trace_sink=events.append,
    )

    assert projection.content_digest == events[0].payload["projection_ref"]
    assert events[0].event_type == "capability.consumer_projection.validated"
