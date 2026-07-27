from __future__ import annotations

from workbench.capability_factory.notebook_bridge import NotebookCapabilityBridge

from test_capability_execution_receipt import _authorization
from test_capability_custom_dispatcher import _intent_and_records
from datetime import datetime, timezone


def test_notebook_bridge_prepares_one_exact_intent_without_run_side_effect(tmp_path) -> None:
    source_intent, implementation, _adapter, binding = _intent_and_records()
    now = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)
    authorization = _authorization(source_intent, binding, implementation, now=now)
    prepared = NotebookCapabilityBridge.prepare_intent(
        authorization=authorization,
        run_id="run.bridge",
        input_contract_ref="1" * 64,
        output_contract_ref="2" * 64,
        host_containment_ref="3" * 64,
        host_validity_revision=1,
        bundle_validity_revision=1,
        evidence_validity_revision=1,
        admission_validity_revision=1,
    )

    assert prepared.intent.draft_id == authorization.draft_id
    assert prepared.intent.draft_hash == authorization.draft_hash
    assert prepared.intent.run_id == "run.bridge"
    assert prepared.intent.content_digest == prepared.intent.content_digest
    assert list(tmp_path.iterdir()) == []
