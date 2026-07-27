from __future__ import annotations

import pytest

from workbench.capability_factory.trace_contracts import (
    TRACE_CONTRACT_VERSION,
    TraceContractError,
    build_trace_event,
)


def test_cf4_trace_vocabulary_covers_the_authorization_lifecycle() -> None:
    cases = {
        "option.feasibility.decided": {
            "decision_ref": "1" * 64,
            "candidate_cohort_ref": "2" * 64,
            "outcome": "selected",
        },
        "option.authorization.changed": {
            "authorization_ref": "3" * 64,
            "from_status": "issued",
            "to_status": "claimed",
            "receipt_ref": "4" * 64,
        },
        "option.dispatch.reserved": {
            "authorization_ref": "5" * 64,
            "reservation_ref": "6" * 64,
            "control_sequence": 7,
        },
        "capability.consumer_projection.validated": {
            "adapter_revision_ref": "8" * 64,
            "projection_ref": "9" * 64,
            "outcome": "accepted",
        },
        "artifact_contract.v11.validation.completed": {
            "aggregate_ref": "a" * 64,
            "option_revision_ref": "b" * 64,
            "run_attempt_ref": "c" * 64,
            "outcome": "accepted",
        },
        "option.execution.reconciled": {
            "authorization_ref": "d" * 64,
            "lease_epoch": 1,
            "outcome": "completed",
            "object_graph_ref": "e" * 64,
        },
    }

    for event_type, payload in cases.items():
        event = build_trace_event(event_type=event_type, payload=payload)
        assert event.schema_version == TRACE_CONTRACT_VERSION
        assert event.event_type == event_type


def test_cf4_trace_rejects_unknown_fields_and_unregistered_events() -> None:
    with pytest.raises(TraceContractError, match="unknown fields"):
        build_trace_event(
            event_type="option.dispatch.reserved",
            payload={
                "authorization_ref": "1" * 64,
                "reservation_ref": "2" * 64,
                "control_sequence": "3" * 64,
                "secret": "not persisted",
            },
        )

    with pytest.raises(TraceContractError, match="not registered"):
        build_trace_event(event_type="option.execution.started", payload={})
