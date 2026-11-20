"""The comparison phase must not receive persisted fitted relationships."""
import asyncio
import json

import pytest

from workbench.agent.model import ModelStreamEvent
from workbench.agent.notebook.evidence import DataEvidencePackV1, EvidenceRecord
from workbench.agent.planning.agent import NotebookPlanningAgent
from workbench.agent.planning.types import NotebookPlanningContractError
from tests.test_context_compiler_identity import _context


def _pack(inspection_id="profile.v1"):
    return DataEvidencePackV1("run:source", (EvidenceRecord(
        evidence_id="evidence:source", inspection_id=inspection_id,
        source_refs=("profile:source",), protocol_version="profile/v1", status="completed",
        observations={"row_count": 10, "columns": [{"name": "y", "dtype": "float64"}],
                      "rows": [["FIT_SENTINEL"]], "fit_summary": "FIT_SENTINEL"},
        metrics={"p_value": "FIT_SENTINEL", "candidate_scores": {"a": 0.001}},
        warnings=("FIT_SENTINEL",),
    ),))


def _phase(*, mode="plan", evidence=None, executor=None):
    context = _context(
        active_run_summary={"run_id": "source", "p_value": "FIT_SENTINEL"},
        diagnostics=[{"blinding": "post_fit", "summary": "FIT_SENTINEL"}],
        artifact_summaries=[{"summary": "FIT_SENTINEL"}],
        bounded_lineage=[{"node_id": "model", "kind": "model", "summary": "FIT_SENTINEL"}],
        dataset_profile={"columns": [{"name": "y", "dtype": "float64", "fit": "FIT_SENTINEL"}]},
        user_focus={"interaction_mode": mode, "goal": "Compare models for y", "selected_text": "FIT_SENTINEL"},
        analysis_contract={"target": "y", "result": "FIT_SENTINEL"},
    )
    return NotebookPlanningAgent(adapter=object(), capability_catalog={"ols": {}},
        inspection_executor=executor).create_phase(context=context, initial_evidence=evidence or _pack())


def test_initial_comparison_is_allowlisted_but_retains_original_evidence():
    pack = _pack()
    phase = _phase(evidence=pack)
    payload = json.loads(phase.request([]).messages[1]["content"])
    assert "FIT_SENTINEL" not in json.dumps(payload)
    assert payload["context"]["content"]["user_focus"]["goal"] == "Compare models for y"
    assert payload["evidence"]["records"][0]["observations"]["row_count"] == 10
    assert payload["evidence"]["records"][0]["result_hash"] == pack.records[0].to_dict()["result_hash"]
    assert phase.evidence.to_dict() == pack.to_dict()  # evidence is never rewritten
    assert payload["context"]["model_projection_hash"].startswith("sha256:")


def test_action_mode_retains_post_fit_evidence_and_does_not_claim_blinding():
    payload = json.loads(_phase(mode="action").request([]).messages[1]["content"])
    assert "FIT_SENTINEL" in json.dumps(payload)
    assert "comparison_policy" not in payload["context"]


def _inspection_event(inspection_id):
    return [ModelStreamEvent.tool_call_delta("req", {
        "tool_id": "request_notebook_inspections", "tool_call_id": "inspection",
        "arguments": {"requests": [{"inspection_id": inspection_id,
            "target_ref": "run:active", "arguments": {}}]},
    }), ModelStreamEvent.done("req", finish_reason="tool_calls")]


def test_incremental_inspection_uses_same_blind_projection_after_restart():
    phase = _phase(evidence=DataEvidencePackV1("run:source", ()), executor=lambda *_: _pack())
    step = asyncio.run(phase.consume(_inspection_event("profile.v1")))
    assert "FIT_SENTINEL" not in json.dumps(step.append_messages)
    restored = _phase(evidence=DataEvidencePackV1("run:source", ()))
    restored.restore_checkpoint(phase.checkpoint())
    assert "FIT_SENTINEL" not in json.dumps(restored.request(step.append_messages).messages)
    assert "FIT_SENTINEL" in json.dumps(restored.evidence.to_dict())


def test_unsealed_forecast_is_not_advertised_or_executed_in_comparison():
    calls = []
    phase = _phase(executor=lambda *args: calls.append(args))
    inspection_tool = phase.request([]).tools[0]
    ids = inspection_tool["input_schema"]["properties"]["requests"]["items"]["properties"]["inspection_id"]["enum"]
    assert "forecast_rolling_origin.v1" not in ids
    step = asyncio.run(phase.consume(_inspection_event("forecast_rolling_origin.v1")))
    assert calls == []
    assert "inspection is not available" in json.dumps(step.append_messages)


def test_existing_post_fit_pack_cannot_be_cited_in_comparison():
    phase = _phase(evidence=_pack("forecast_rolling_origin.v1"))
    payload = json.loads(phase.request([]).messages[1]["content"])
    assert payload["evidence"]["records"] == []
    assert payload["evidence_citation_policy"]["completed_evidence_refs"] == []


def test_oversized_planning_message_refuses_without_truncating_contract():
    phase = _phase()
    phase.initial_messages[1]["content"] = "x" * 2_000_000
    with pytest.raises(NotebookPlanningContractError, match="message budget"):
        phase.request([])


def test_legacy_comparison_snapshot_does_not_reintroduce_results():
    phase = _phase()
    checkpoint = phase.checkpoint()
    checkpoint.pop("comparison_profile")
    with pytest.raises(NotebookPlanningContractError, match="legacy comparison transcript"):
        _phase().restore_checkpoint(checkpoint)
