from __future__ import annotations

import pytest

from workbench.contracts.model.survival import SurvivalEvidenceContract


def _packet() -> dict[str, object]:
    return {
        "contract": "workbench.survival.v1",
        "model_type": "survival_cox",
        "duration_column": "duration",
        "event_column": "event",
        "entry_column": None,
        "nobs": 4,
        "censoring": {"events": 2, "censored": 2},
        "time_to_event": {"min": 1.0, "max": 4.0},
        "kaplan_meier": [{"time": 1.0, "survival": 0.75, "n_at_risk": 4}],
        "log_rank": {"status": "not_requested"},
        "risk_set": [{"time": 1.0, "n_at_risk": 4, "events": 1, "censored": 0}],
        "schoenfeld": [{"variable": "x", "status": "computed"}],
        "validation": {"level": "internal_consistency_only", "external_oracle": "not_verified"},
    }


def test_survival_contract_is_independent_and_round_trips_time_to_event_evidence() -> None:
    packet = SurvivalEvidenceContract.from_dict(_packet())

    assert packet.to_dict() == _packet()
    assert packet.duration_column == "duration"
    assert packet.event_column == "event"
    assert packet.risk_set[0]["n_at_risk"] == 4


def test_survival_contract_rejects_missing_censoring_and_risk_set_evidence() -> None:
    payload = _packet()
    payload.pop("censoring")

    with pytest.raises(Exception, match="survival_evidence"):
        SurvivalEvidenceContract.from_dict(payload)
