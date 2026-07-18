from __future__ import annotations

import pytest

from workbench.report_contract import (
    ReportContractError,
    validate_report_packet,
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
    assert validate_report_response(text, packet) == (
        "estimate 2.0 [[c:c1]]; p 0.01 [[c:c5]]\n"
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
