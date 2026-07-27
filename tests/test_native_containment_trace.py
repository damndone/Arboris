from __future__ import annotations

import pytest


def test_native_containment_trace_has_exact_ref_only_payload():
    from workbench.native_containment.trace_contracts import TraceContractError, build_trace_event

    event = build_trace_event(
        event_type="host_containment.assessed",
        payload={"assessment_ref": "a" * 64, "outcome": "unsupported"},
    )
    assert event.payload["outcome"] == "unsupported"
    with pytest.raises(TraceContractError, match="unknown"):
        build_trace_event(
            event_type="host_containment.assessed",
            payload={"assessment_ref": "a" * 64, "outcome": "unsupported", "host_path": "/tmp"},
        )
