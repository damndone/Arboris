from __future__ import annotations

import pytest

from workbench.report_contract import (
    ReportContractError,
    bind_report_figures,
    validate_report_packet,
    validate_report_narrative_response,
    validate_report_response,
)


def _packet() -> dict:
    return {
        "fact_table": [
            {"id": "c1", "label": "estimate", "value": 2.0},
            {"id": "c5", "label": "p", "value": 0.01},
        ],
        "figures": [
            {"artifact_id": "coef_plot", "chart_type": "coefficient"},
            {"artifact_id": "event_study", "chart_type": "event study"},
        ],
    }


def test_packet_rejects_duplicate_fact_or_figure_ids() -> None:
    packet = _packet()
    packet["fact_table"].append({"id": "c1", "label": "duplicate", "value": 1})
    with pytest.raises(ReportContractError, match="duplicate fact id"):
        validate_report_packet(packet)

    packet = _packet()
    packet["figures"].append({"artifact_id": "coef_plot", "chart_type": "duplicate"})
    with pytest.raises(ReportContractError, match="duplicate figure artifact_id"):
        validate_report_packet(packet)


def test_response_normalizes_only_existing_numeric_fact_shorthand() -> None:
    packet = validate_report_packet(_packet())
    text = "estimate 2.0 [[c:1]]; p 0.01 [[c:5]]\n[[fig:coef_plot]]\n[[fig:event_study]]"
    normalized = validate_report_response(text, packet)
    assert isinstance(normalized, str)
    assert normalized == (
        "estimate 2.0 [[c:c1]]; p 0.01 [[c:c5]]\n"
        "[[fig:coef_plot]]\n[[fig:event_study]]"
    )


def test_narrative_phase_accepts_citations_without_provider_figures() -> None:
    packet = validate_report_packet(_packet())

    normalized = validate_report_narrative_response(
        "estimate 2.0 [[c:1]]; p 0.01 [[c:5]]",
        packet,
    )

    assert normalized == "estimate 2.0 [[c:c1]]; p 0.01 [[c:c5]]"


def test_narrative_phase_rejects_any_provider_figure_marker() -> None:
    packet = validate_report_packet(_packet())

    with pytest.raises(ReportContractError, match="provider figure marker"):
        validate_report_narrative_response(
            "estimate 2.0 [[c:c1]]\n[[fig:coef_plot]]",
            packet,
        )


def test_server_figure_binding_uses_packet_order_and_validates_exact_once() -> None:
    packet = validate_report_packet(_packet())

    bound = bind_report_figures("estimate 2.0 [[c:c1]]", packet)

    assert bound == (
        "estimate 2.0 [[c:c1]]\n\n"
        "[[fig:coef_plot]]\n[[fig:event_study]]"
    )


@pytest.mark.parametrize(
    "text, message",
    [
        ("[[c:c99]]\n[[fig:coef_plot]]\n[[fig:event_study]]", "unknown citation"),
        ("[[c:c1]]\n[[fig:coef_plot]]", "missing figure marker"),
        (
            "[[c:c1]]\n[[fig:coef_plot]]\n[[fig:coef_plot]]\n[[fig:event_study]]",
            "duplicate figure marker",
        ),
        ("[[c:c1]]\n[[fig:other]]\n[[fig:event_study]]", "unknown figure marker"),
        ("[[c:source:coef_plot]]\n[[fig:coef_plot]]\n[[fig:event_study]]", "unknown citation"),
    ],
)
def test_response_contract_fails_closed(text: str, message: str) -> None:
    packet = validate_report_packet(_packet())
    with pytest.raises(ReportContractError, match=message):
        validate_report_response(text, packet)


def test_packet_preserves_optional_journal_quality_metadata() -> None:
    packet = _packet()
    packet.update(
        {
            "report_standard": "journal_full_v1",
            "required_capabilities": ["regression", "diagnostics.robustness"],
            "excluded_fact_ids": ["c5"],
        }
    )

    contract = validate_report_packet(packet)

    assert contract.report_standard == "journal_full_v1"
    assert contract.required_capabilities == (
        "regression",
        "diagnostics.robustness",
    )
    assert contract.excluded_fact_ids == frozenset({"c5"})


def test_report_packet_preserves_capability_provider_manifest() -> None:
    packet = _packet()
    packet.update(
        {
            "report_standard": "journal_full_v1",
            "required_capabilities": ["regression"],
            "capability_manifest": [
                {
                    "capability_id": "regression",
                    "provider_id": "evidence.estimation.v1",
                    "availability": "available",
                    "validation_level": "internal_only",
                    "report_modules": ["model-estimation"],
                    "limitations": [],
                }
            ],
        }
    )

    contract = validate_report_packet(packet)

    assert contract.capability_manifest[0]["provider_id"] == "evidence.estimation.v1"


def test_packet_preserves_excluded_fact_outside_selected_fact_table() -> None:
    packet = _packet()
    packet["excluded_fact_ids"] = ["c99"]

    contract = validate_report_packet(packet)

    assert contract.excluded_fact_ids == frozenset({"c99"})
