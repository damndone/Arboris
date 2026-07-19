from __future__ import annotations

import json

import pandas as pd
import pytest

from workbench.contracts.common.envelope import PacketEnvelope
from workbench.contracts.model.linear_mixed_effects import LmmDiagnostic

from tests.evaluation.linear_mixed_effects._candidate import require_candidate_module
from tests.evaluation.linear_mixed_effects._fixtures import lmm_fixture_root


OPTIONS = {
    "subject_id": "participant_id",
    "time": "week",
    "group": "arm",
    "fit_method": "reml",
    "random_slope": True,
}


@pytest.mark.parametrize(
    ("fixture_name", "expected_code", "expected_status"),
    [
        ("invalid_random_slope_blocked.json", "LMM_INVALID_RANDOM_SLOPE_CONFIGURATION", "blocked"),
        ("missing_subject_id_blocked.json", "LMM_SUBJECT_ID_MISSING", "blocked"),
        ("convergence_failed.json", "LMM_CONVERGENCE_FAILED", "failed"),
        ("singular_warning.json", "LMM_RANDOM_EFFECTS_SINGULAR", "complete"),
    ],
)
def test_canonical_fault_packets_are_versioned_diagnostic_envelopes(
    fixture_name: str, expected_code: str, expected_status: str
) -> None:
    packet = PacketEnvelope.from_dict(
        json.loads(
            (lmm_fixture_root() / "packets" / fixture_name).read_text(encoding="utf-8")
        )
    )

    assert packet.contract == "linear_mixed_effects.diagnostic"
    assert packet.contract_version == "1.0"
    assert packet.producer_version == "linear_mixed_effects@1.0"
    payload = packet.to_dict()["payload"]
    assert isinstance(payload, dict)
    diagnostics = payload["diagnostics"]
    assert isinstance(diagnostics, list) and len(diagnostics) == 1
    diagnostic = LmmDiagnostic(**diagnostics[0])
    assert diagnostic.code == expected_code
    assert diagnostic.status == expected_status


def _prepare(frame: pd.DataFrame) -> object:
    module = require_candidate_module("workbench.engine.packs.linear_mixed_effects.input")
    return module.prepare_lmm_input(
        frame,
        outcome="score",
        controls=["baseline_score"],
        options=OPTIONS,
    )


@pytest.mark.parametrize(
    ("fixture_name", "mutate", "expected_code"),
    [
        ("missing_subject_id.csv", lambda frame: frame, "LMM_SUBJECT_ID_MISSING"),
        (
            "known_truth.csv",
            lambda frame: frame.assign(week="not-a-number"),
            "LMM_TIME_NOT_NUMERIC",
        ),
        (
            "known_truth.csv",
            lambda frame: frame.assign(arm=frame["arm"].mask(frame.index == 0, "other")),
            "LMM_GROUP_NOT_BINARY",
        ),
        (
            "known_truth.csv",
            lambda frame: frame.assign(
                arm=frame["arm"].mask(
                    (frame["participant_id"] == "C001") & (frame["week"] == 0),
                    "treated",
                )
            ),
            "LMM_GROUP_VARIES_WITHIN_SUBJECT",
        ),
        (
            "single_observation_per_subject.csv",
            lambda frame: frame,
            "LMM_INSUFFICIENT_REPEATED_OBSERVATIONS",
        ),
    ],
)
def test_invalid_input_fails_with_the_locked_code(
    fixture_name: str, mutate, expected_code: str
) -> None:
    frame = mutate(pd.read_csv(lmm_fixture_root() / fixture_name))
    module = require_candidate_module("workbench.engine.packs.linear_mixed_effects.input")

    with pytest.raises(module.LmmInputError, match=expected_code):
        _prepare(frame)


@pytest.mark.parametrize(
    ("kwargs", "expected_code", "expected_status"),
    [
        (
            {
                "converged": True,
                "random_slope": False,
                "covariance_matrix": [[0.7, 0.1], [0.1, 0.3]],
                "residual_variance": 0.5,
            },
            "LMM_INVALID_RANDOM_SLOPE_CONFIGURATION",
            "blocked",
        ),
        (
            {
                "converged": False,
                "random_slope": True,
                "covariance_matrix": [[0.7, 0.0], [0.0, 0.3]],
                "residual_variance": 0.5,
            },
            "LMM_CONVERGENCE_FAILED",
            "failed",
        ),
        (
            {
                "converged": True,
                "random_slope": True,
                "covariance_matrix": [[0.7, 0.0], [0.0, 0.0]],
                "residual_variance": 0.5,
            },
            "LMM_RANDOM_EFFECTS_SINGULAR",
            "complete",
        ),
    ],
)
def test_diagnostic_faults_have_exact_code_and_status(
    kwargs: dict[str, object], expected_code: str, expected_status: str
) -> None:
    module = require_candidate_module(
        "workbench.engine.packs.linear_mixed_effects.diagnostics"
    )

    diagnostics = module.classify_lmm_diagnostics(**kwargs)

    diagnostic = diagnostics[0]
    wire = diagnostic.to_dict()
    assert LmmDiagnostic(**wire).to_dict() == wire
    assert diagnostic.code == expected_code
    assert diagnostic.status == expected_status
    if expected_status in {"blocked", "failed"}:
        assert diagnostic.action_candidate is None
