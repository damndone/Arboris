from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.analysis_loop.compare import ComparePacket
from workbench.contracts.common.envelope import PacketEnvelope
from tests.evaluation.linear_mixed_effects._fixtures import lmm_fixture_root


RESTRICTED_MESSAGE = (
    "两个模型使用 REML 且固定效应结构不同；似然、AIC 和似然比检验不作为有效的直接比较依据。"
)


def _payload(name: str) -> dict[str, object]:
    packet = PacketEnvelope.from_dict(
        json.loads((lmm_fixture_root() / "packets" / name).read_text(encoding="utf-8"))
    )
    payload = packet.to_dict()["payload"]
    assert isinstance(payload, dict)
    return payload


def test_slope_removal_fixture_stays_comparable_under_the_locked_scope() -> None:
    payload = _payload("comparable_child.json")

    assert payload["compare_status"] == "complete"
    assert payload["comparison_scope"] == "same_fixed_effects_ml"
    assert payload["result_id"] == "group_time_interaction"


def test_reml_fixed_effect_change_is_restricted_with_no_winner_claim() -> None:
    payload = _payload("restricted_reml_child.json")

    assert payload["compare_status"] == "restricted"
    assert payload["reason_code"] == "REML_FIXED_EFFECTS_DIFFER"
    assert payload["user_safe_message"] == RESTRICTED_MESSAGE
    message = str(payload["user_safe_message"]).lower()
    assert all(term not in message for term in ("winner", "better", "优劣"))


@pytest.mark.parametrize(
    ("reason_code", "message"),
    [
        ("REML_FIXED_EFFECTS_DIFFER", RESTRICTED_MESSAGE),
        (
            "LMM_FIT_METHOD_DIFFER",
            "两个模型使用不同的拟合方法；不能把似然、AIC 或似然比检验作为直接优劣判断。",
        ),
    ],
)
def test_restricted_compare_packet_cannot_hide_a_winner_in_its_conclusion(
    reason_code: str, message: str
) -> None:
    packet = ComparePacket(
        compare_status="restricted",
        source_run_id="source",
        child_run_id="child",
        target={"result_id": "group_time_interaction"},
        data_diff={"sample_changed": False},
        parameter_diff={"fixed_effects_changed": True},
        result_diff={"primary_result_id": "group_time_interaction"},
        conclusion_diff={"classification": "NOT_COMPARABLE"},
        validation_status="pass",
        integrity_findings=(),
        logical_key="compare:lmm-restricted",
        strategy_version="linear_mixed_effects_v1",
        schema_version="compare_packet_v1",
        reason_code=reason_code,
        user_safe_message=message,
    )

    wire = packet.to_dict()
    assert wire["compare_status"] == "restricted"
    assert wire["conclusion_diff"] == {"classification": "NOT_COMPARABLE"}
    assert "winner" not in json.dumps(wire["conclusion_diff"]).lower()
