from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from workbench.contracts.common.envelope import PacketEnvelope

from tests.evaluation.linear_mixed_effects._candidate import require_candidate_module


REPO_ROOT = Path(__file__).parents[3]
PACKETS = (
    REPO_ROOT / "tests" / "fixtures" / "models" / "linear_mixed_effects" / "packets"
)


def test_canonical_packets_round_trip_through_the_locked_envelope() -> None:
    for path in sorted(PACKETS.glob("*.json")):
        packet = json.loads(path.read_text(encoding="utf-8"))

        assert PacketEnvelope.from_dict(packet).to_dict() == packet


def test_runtime_result_round_trips_as_a_versioned_packet(tmp_path) -> None:
    runner = require_candidate_module(
        "workbench.engine.packs.linear_mixed_effects.runner"
    )
    result, _ = runner.fit_linear_mixed_effects(
        csv_path=PACKETS.parent / "known_truth.csv",
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
    envelope = PacketEnvelope(
        contract="linear_mixed_effects.result",
        contract_version="1.0",
        producer_version="linear_mixed_effects@1.0",
        payload=result,
    )
    stored = json.loads((tmp_path / "linear_mixed_effects_contract.json").read_text())

    assert PacketEnvelope.from_dict(envelope.to_dict()).to_dict() == envelope.to_dict()
    assert stored == result
    assert result["model_type"] == "linear_mixed_effects"
    assert result["primary_target_id"] == "group_time_interaction"


def test_evidence_collector_requires_an_explicit_candidate_sha(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "collect_v173_lmm_evidence.py"),
            "--output",
            str(tmp_path / "performance.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "--candidate" in completed.stderr
