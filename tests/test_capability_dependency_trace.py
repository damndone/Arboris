from __future__ import annotations

import pytest


def test_dependency_trace_contract_covers_proposal_quarantine_and_admission():
    from workbench.capability_factory.trace_contracts import build_trace_event

    proposal = build_trace_event(
        event_type="capability.dependency.proposed",
        payload={
            "proposal_digest": "a" * 64,
            "lock_ref": "b" * 64,
            "risk_level": "high",
        },
    )
    quarantine = build_trace_event(
        event_type="capability.dependency.quarantined",
        payload={
            "bundle_ref": "c" * 64,
            "lock_ref": "b" * 64,
            "status": "quarantined",
        },
    )
    admission = build_trace_event(
        event_type="capability.dependency.admission.changed",
        payload={
            "bundle_ref": "c" * 64,
            "status": "validated",
            "validity_ref": "d" * 64,
        },
    )

    assert proposal.schema_version == quarantine.schema_version == admission.schema_version
    assert proposal.payload["risk_level"] == "high"
    assert quarantine.payload["status"] == "quarantined"
    assert admission.payload["status"] == "validated"


def test_dependency_trace_rejects_unknown_fields_and_unregistered_events():
    from workbench.capability_factory.trace_contracts import TraceContractError, build_trace_event

    with pytest.raises(TraceContractError):
        build_trace_event(
            event_type="capability.dependency.proposed",
            payload={
                "proposal_digest": "a" * 64,
                "lock_ref": "b" * 64,
                "risk_level": "high",
                "secret": "must-not-leak",
            },
        )
    with pytest.raises(TraceContractError):
        build_trace_event(event_type="capability.dependency.executed", payload={})
