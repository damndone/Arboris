from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tests.fixtures.models.linear_mixed_effects.generate_fixtures import build_known_truth
from workbench.contracts.agent.repeated_measures import (
    LMM_RECOVERY_ACTION_ID,
    LMM_RECOVERY_OPERATION_ID,
    LMM_RECOVERY_PATCH,
)
from workbench.contracts.common.envelope import PacketEnvelope


ROOT = Path(__file__).parents[1] / "fixtures" / "models" / "linear_mixed_effects"
PACKETS = ROOT / "packets"
RESTRICTED_MESSAGE = (
    "两个模型使用 REML 且固定效应结构不同；似然、AIC 和似然比检验不作为有效的直接比较依据。"
)


def _packet(name: str) -> PacketEnvelope:
    return PacketEnvelope.from_dict(
        json.loads((PACKETS / name).read_text(encoding="utf-8"))
    )


def test_known_truth_is_reproducible() -> None:
    assert build_known_truth().equals(build_known_truth())
    frame = build_known_truth()

    assert len(frame) == 480
    assert set(frame["arm"]) == {"control", "treated"}
    assert frame.groupby("participant_id").size().eq(6).all()


def test_committed_known_truth_matches_the_deterministic_generator() -> None:
    # The generator writes 17-digit floats.  pandas' default parser may round
    # those values by one ULP, so use its explicit round-trip parser here.
    committed = pd.read_csv(ROOT / "known_truth.csv", float_precision="round_trip")

    assert committed.equals(build_known_truth())
    assert json.loads((ROOT / "known_truth.json").read_text(encoding="utf-8")) == {
        "seed": 20260718,
        "n_obs": 480,
        "n_subjects": 80,
        "n_timepoints_per_subject": 6,
        "group_time_interaction": 0.9,
        "interaction_tolerance": 0.35,
        "fit_method": "reml",
        "primary_result_id": "group_time_interaction",
    }


def test_derived_input_fixtures_hold_their_single_failure_boundary() -> None:
    singular = pd.read_csv(ROOT / "singular_random_slope.csv")
    missing_subject = pd.read_csv(ROOT / "missing_subject_id.csv")
    single_observation = pd.read_csv(ROOT / "single_observation_per_subject.csv")

    assert singular.groupby("participant_id")["week"].nunique().eq(1).all()
    assert "participant_id" not in missing_subject.columns
    assert single_observation.groupby("participant_id").size().eq(1).all()


def test_every_mock_packet_has_an_envelope() -> None:
    expected_names = {
        "success.json",
        "singular_warning.json",
        "convergence_failed.json",
        "missing_subject_id_blocked.json",
        "invalid_random_slope_blocked.json",
        "recoverable_proposal.json",
        "comparable_child.json",
        "restricted_reml_child.json",
    }
    paths = sorted(PACKETS.glob("*.json"))

    assert {path.name for path in paths} == expected_names
    for path in paths:
        packet = PacketEnvelope.from_dict(json.loads(path.read_text(encoding="utf-8")))
        assert packet.contract_version == "1.0"
        assert packet.payload


def test_recoverable_packet_is_exact_and_confirmation_bound() -> None:
    candidate = _packet("recoverable_proposal.json").to_dict()["payload"][
        "action_candidate"
    ]

    assert candidate == {
        "action_id": LMM_RECOVERY_ACTION_ID,
        "operation_id": LMM_RECOVERY_OPERATION_ID,
        "patch": LMM_RECOVERY_PATCH,
        "required_confirmation": True,
    }


def test_restricted_reml_packet_has_only_the_locked_safe_message() -> None:
    payload = _packet("restricted_reml_child.json").to_dict()["payload"]

    assert payload["compare_status"] == "restricted"
    assert payload["reason_code"] == "REML_FIXED_EFFECTS_DIFFER"
    assert payload["user_safe_message"] == RESTRICTED_MESSAGE
