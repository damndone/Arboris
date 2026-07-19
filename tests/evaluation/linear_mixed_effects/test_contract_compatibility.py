from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from workbench.contracts.common.envelope import PacketEnvelope

from tests.evaluation.linear_mixed_effects._candidate import require_candidate_module
from tests.evaluation.linear_mixed_effects._fixtures import lmm_fixture_root


def _packets() -> Path:
    return lmm_fixture_root() / "packets"


def _lmm_result_payload(result: object) -> dict[str, object]:
    assert isinstance(result, Mapping)
    envelope = PacketEnvelope.from_dict(result)
    assert envelope.contract == "linear_mixed_effects.result"
    assert envelope.contract_version == "1.0"
    assert envelope.producer_version == "linear_mixed_effects@1.0"
    payload = envelope.to_dict()["payload"]
    assert isinstance(payload, dict)
    return payload


def test_canonical_packets_round_trip_through_the_locked_envelope() -> None:
    for path in sorted(_packets().glob("*.json")):
        packet = json.loads(path.read_text(encoding="utf-8"))

        assert PacketEnvelope.from_dict(packet).to_dict() == packet


def test_runtime_result_round_trips_as_a_versioned_packet(tmp_path) -> None:
    runner = require_candidate_module(
        "workbench.engine.packs.linear_mixed_effects.runner"
    )
    result, _ = runner.fit_linear_mixed_effects(
        csv_path=_packets().parent / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )
    payload = _lmm_result_payload(result)
    stored = json.loads((tmp_path / "linear_mixed_effects_contract.json").read_text())

    assert stored == PacketEnvelope.from_dict(result).to_dict()
    assert payload["model_type"] == "linear_mixed_effects"
    assert payload["primary_target_id"] == "group_time_interaction"
