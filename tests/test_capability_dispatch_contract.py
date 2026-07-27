from __future__ import annotations

from dataclasses import replace

import pytest

from workbench.capability_factory.dispatch import (
    PREPARED_RUN_INTENT_CONTRACT_VERSION,
    PreparedRunIntent,
    PreparedRunIntentError,
)


def _intent() -> PreparedRunIntent:
    return PreparedRunIntent(
        intent_id="intent.alpha",
        draft_id="draft.alpha",
        draft_hash="sha256:" + "1" * 64,
        binding_ref="a" * 64,
        binding_revision=2,
        capability_ref="b" * 64,
        bundle_ref="c" * 64,
        evidence_ref="d" * 64,
        admission_ref="e" * 64,
        runtime_policy_ref="f" * 64,
        host_containment_ref="0" * 64,
        operation_id="fit",
        run_id="run.alpha",
        input_graph_fingerprint="graph.alpha",
        input_contract_ref="1" * 64,
        output_contract_ref="2" * 64,
        consumer_projection_ref="3" * 64,
        host_validity_revision=1,
        bundle_validity_revision=1,
        evidence_validity_revision=1,
        admission_validity_revision=1,
        artifact_namespace="artifact.alpha",
        graph_edge_namespace="graph-edge.alpha",
        trace_event_namespace="trace.alpha",
        namespace_derivation_revision=1,
        artifact_producer_revision=1,
        graph_producer_revision=1,
        trace_producer_revision=1,
        slot_mapping_revision=1,
        harness_abi_revision=1,
        protocol_revision=1,
    )


def test_prepared_run_intent_is_content_addressed_and_round_trips():
    intent = _intent()
    payload = intent.to_dict()
    restored = PreparedRunIntent.from_dict(payload)

    assert payload["contract_version"] == PREPARED_RUN_INTENT_CONTRACT_VERSION
    assert payload["content_digest"] == intent.content_digest
    assert restored == intent
    assert restored.to_dict() == payload


def test_prepared_run_intent_digest_binds_every_execution_identity_field():
    intent = _intent()

    assert replace(intent, run_id="run.beta").content_digest != intent.content_digest
    assert replace(intent, draft_hash="sha256:" + "2" * 64).content_digest != intent.content_digest
    assert replace(intent, admission_validity_revision=2).content_digest != intent.content_digest
    assert replace(intent, graph_edge_namespace="graph-edge.beta").content_digest != intent.content_digest
    assert replace(intent, harness_abi_revision=2).content_digest != intent.content_digest


@pytest.mark.parametrize(
    "field,value",
    [
        ("intent_id", "../intent"),
        ("run_id", "runs/run.alpha"),
        ("artifact_namespace", "artifact/escape"),
        ("binding_ref", "not-a-digest"),
        ("draft_hash", "sha256:not-a-digest"),
        ("binding_revision", 0),
        ("protocol_revision", 0),
    ],
)
def test_prepared_run_intent_rejects_untrusted_identity_values(field, value):
    with pytest.raises(PreparedRunIntentError):
        replace(_intent(), **{field: value})


def test_prepared_run_intent_rejects_unknown_fields_and_tampered_digest():
    payload = _intent().to_dict()
    payload["unexpected"] = "not-accepted"
    with pytest.raises(PreparedRunIntentError):
        PreparedRunIntent.from_dict(payload)

    payload = _intent().to_dict()
    payload["content_digest"] = "0" * 64
    with pytest.raises(PreparedRunIntentError):
        PreparedRunIntent.from_dict(payload)


def test_prepared_run_intent_has_no_persistence_or_run_side_effects(tmp_path):
    intent = _intent()
    assert intent.run_id == "run.alpha"
    assert list(tmp_path.iterdir()) == []
