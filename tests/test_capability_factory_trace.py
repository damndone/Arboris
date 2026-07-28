from __future__ import annotations

import importlib

import pytest


def _trace():
    try:
        return importlib.import_module("workbench.capability_factory.trace_contracts")
    except ModuleNotFoundError as error:
        pytest.fail(f"CF1 trace contracts are not implemented: {error}")


def test_trace_contracts_are_package_local_and_reject_unknown_payload_fields():
    trace = _trace()
    event = trace.build_trace_event(
        event_type="capability.resolution.decided",
        payload={
            "decision_digest": "a" * 64,
            "outcome": "selected",
        },
    )

    assert event.schema_version == trace.TRACE_CONTRACT_VERSION
    assert event.payload["outcome"] == "selected"
    with pytest.raises(trace.TraceContractError, match="unknown"):
        trace.build_trace_event(
            event_type="capability.resolution.decided",
            payload={
                "decision_digest": "a" * 64,
                "outcome": "selected",
                "host_path": "/tmp/escape",
            },
        )


def test_trace_contracts_bound_event_types_and_digest_shape():
    trace = _trace()
    with pytest.raises(trace.TraceContractError, match="event_type"):
        trace.build_trace_event(event_type="unregistered.event", payload={})
    with pytest.raises(trace.TraceContractError, match="digest"):
        trace.build_trace_event(
            event_type="capability.resolution.decided",
            payload={"decision_digest": "not-a-digest", "outcome": "selected"},
        )


def test_cf3b_trace_contracts_bind_registration_and_admission_refs():
    trace = _trace()
    registered = trace.build_trace_event(
        event_type="capability.implementation.registered",
        payload={
            "implementation_ref": "a" * 64,
            "adapter_ref": "b" * 64,
            "validation_bundle_ref": "c" * 64,
            "evidence_assessment_ref": "d" * 64,
            "host_containment_ref": "e" * 64,
        },
    )
    assert registered.payload["host_containment_ref"] == "e" * 64
    changed = trace.build_trace_event(
        event_type="capability.admission.changed",
        payload={"admission_id": "admission.alpha", "admission_ref": "f" * 64, "status": "admitted"},
    )
    assert changed.payload["status"] == "admitted"
