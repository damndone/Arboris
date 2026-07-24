"""Every produced packet round-trips through the locked ETS contract."""

from __future__ import annotations

import json

import pytest

from tests.fixtures.models.ets.known_truth import short_stable_series
from workbench.contracts.model.ets import ETSContractError, ETSResultContract
from workbench.engine.packs.ets.runner import fit_ets


def _outcome(**overrides):
    payload: dict[str, object] = {
        "time_column": "date",
        "value_column": "y",
        "error": "add",
        "trend": "add",
        "seasonal": None,
        "damped_trend": False,
    }
    payload.update(overrides)
    return fit_ets(short_stable_series().frame(), payload)


def test_result_round_trips_through_the_contract() -> None:
    outcome = _outcome()
    payload = outcome.result.to_dict()
    restored = ETSResultContract.from_dict(json.loads(json.dumps(payload)))

    assert restored.to_dict() == payload
    assert restored.result_identity == outcome.result.result_identity
    assert restored.contract_version == "1.1"
    assert restored.fit_method == "statsmodels.ets.mle"


def test_packet_is_json_serialisable() -> None:
    packet = _outcome().to_dict()
    text = json.dumps(packet, sort_keys=True)

    assert '"model_type": "time_series.ets"' in text
    assert json.loads(text)["result"]["specification"]["damped_trend"] is False


def test_contract_refuses_a_smuggled_volatility_parameter() -> None:
    payload = _outcome().result.to_dict()
    payload["params"]["conditional_variance"] = 0.5

    with pytest.raises(ETSContractError) as excinfo:
        ETSResultContract.from_dict(payload)
    assert "conditional-mean model" in str(excinfo.value)


def test_contract_refuses_an_extra_top_level_field() -> None:
    payload = _outcome().result.to_dict()
    payload["value_at_risk_95"] = -0.02

    with pytest.raises(Exception) as excinfo:
        ETSResultContract.from_dict(payload)
    assert "unknown ets_result field: value_at_risk_95" in str(excinfo.value)
