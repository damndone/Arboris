from __future__ import annotations

from workbench.agent.analysis_loop_driver import (
    AnalysisLoopPackets,
    classify_analysis_intent,
    forward_analysis_intent,
)


def test_classifies_only_supported_typed_intents() -> None:
    assert classify_analysis_intent({"intent": "ask"}).to_dict() == {
        "accepted": True,
        "intent": {"kind": "ask"},
        "rejection": None,
    }

    rerun = classify_analysis_intent(
        {
            "intent": "rerun",
            "cluster_variable": " company_id ",
            "result_id": "coef:treatment",
        }
    )
    assert rerun.accepted is True
    assert rerun.intent is not None
    assert rerun.intent.kind == "rerun"
    assert rerun.intent.cluster_variable == " company_id "
    assert rerun.intent.result_id == "coef:treatment"

    compare = classify_analysis_intent(
        {"intent": "compare", "result_id": "coef:treatment"}
    )
    assert compare.accepted is True
    assert compare.intent is not None
    assert compare.intent.kind == "compare"
    assert compare.intent.result_id == "coef:treatment"


def test_rejects_unsupported_patch_and_fuzzy_target_machine_readably() -> None:
    patch = classify_analysis_intent(
        {
            "intent": "rerun",
            "cluster_variable": "company_id",
            "patch": {"covariance": "clustered"},
        }
    )
    assert patch.accepted is False
    assert patch.rejection is not None
    assert patch.rejection.to_dict() == {
        "code": "UNSUPPORTED_PATCH",
        "field": "patch",
        "message": "analysis-loop patches are not accepted by the thin driver",
        "details": {},
    }

    fuzzy = classify_analysis_intent(
        {"intent": "compare", "target": "the treatment coefficient"}
    )
    assert fuzzy.accepted is False
    assert fuzzy.rejection is not None
    assert fuzzy.rejection.code == "FUZZY_TARGET"
    assert fuzzy.rejection.field == "target"


def test_rejects_missing_exact_fields_without_guessing() -> None:
    missing_cluster = classify_analysis_intent({"intent": "rerun"})
    assert missing_cluster.accepted is False
    assert missing_cluster.rejection is not None
    assert missing_cluster.rejection.code == "EXACT_CLUSTER_VARIABLE_REQUIRED"

    missing_result = classify_analysis_intent({"intent": "compare"})
    assert missing_result.accepted is False
    assert missing_result.rejection is not None
    assert missing_result.rejection.code == "EXACT_RESULT_ID_REQUIRED"

    unsupported = classify_analysis_intent({"intent": "patch"})
    assert unsupported.accepted is False
    assert unsupported.rejection is not None
    assert unsupported.rejection.code == "UNSUPPORTED_INTENT"


def test_forwards_packets_unchanged_without_inspecting_or_transforming_them() -> None:
    plan_diff = object()
    validation_packet = object()
    compare_packet = object()
    packets = AnalysisLoopPackets(
        plan_diff=plan_diff,
        validation_packet=validation_packet,
        compare_packet=compare_packet,
    )

    forwarded = forward_analysis_intent(
        {
            "intent": "compare",
            "result_id": "coef:treatment",
        },
        packets=packets,
    )

    assert forwarded.accepted is True
    assert forwarded.packets is packets
    assert forwarded.packets.plan_diff is plan_diff
    assert forwarded.packets.validation_packet is validation_packet
    assert forwarded.packets.compare_packet is compare_packet


def test_driver_has_no_filesystem_or_provider_side_effects(tmp_path) -> None:
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    result = forward_analysis_intent(
        {
            "intent": "rerun",
            "cluster_variable": "company_id",
            "result_id": "coef:treatment",
        }
    )

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert result.accepted is True
    assert before == after == []
