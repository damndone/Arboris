from __future__ import annotations

import pytest


def test_cf3_trace_events_have_exact_bounded_payloads():
    from workbench.capability_factory.trace_contracts import TraceContractError, build_trace_event

    event = build_trace_event(
        event_type="capability.validation.completed",
        payload={"validation_run_ref": "a" * 64, "plan_ref": "b" * 64, "outcome": "passed"},
    )
    assert event.payload["outcome"] == "passed"

    with pytest.raises(TraceContractError, match="unknown"):
        build_trace_event(
            event_type="capability.validation.completed",
            payload={
                "validation_run_ref": "a" * 64,
                "plan_ref": "b" * 64,
                "outcome": "passed",
                "raw_output": "should-not-cross-trace",
            },
        )
