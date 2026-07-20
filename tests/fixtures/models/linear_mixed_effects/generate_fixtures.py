"""Generate deterministic, repository-owned fixtures for the v1 LMM recipe.

Run from the repository root with:

    PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python \
        tests/fixtures/models/linear_mixed_effects/generate_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).parent
PACKETS = ROOT / "packets"
SEED = 20260718
_ARMS = (("control", 0), ("treated", 1))
_PARTICIPANTS_PER_ARM = 40
_WEEKS = range(6)


def build_known_truth() -> pd.DataFrame:
    """Build the fixed-seed, repeated-measures data set used by every lane."""

    rng = np.random.default_rng(SEED)
    rows: list[dict[str, object]] = []
    for arm, group_indicator in _ARMS:
        for participant_number in range(1, _PARTICIPANTS_PER_ARM + 1):
            participant_id = f"{arm[:1].upper()}{participant_number:03d}"
            random_intercept = rng.normal(0.0, 0.75)
            random_slope = rng.normal(0.0, 0.08)
            baseline_score = 10.0 + 1.5 * group_indicator + rng.normal(0.0, 0.5)
            for week in _WEEKS:
                residual = rng.normal(0.0, 0.5)
                score = (
                    10.0
                    + 1.5 * group_indicator
                    + 0.4 * week
                    + 0.9 * group_indicator * week
                    + random_intercept
                    + random_slope * week
                    + residual
                )
                rows.append(
                    {
                        "participant_id": participant_id,
                        "week": week,
                        "arm": arm,
                        "baseline_score": baseline_score,
                        "score": score,
                    }
                )
    return pd.DataFrame(
        rows,
        columns=["participant_id", "week", "arm", "baseline_score", "score"],
    )


def _packet(contract: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": contract,
        "contract_version": "1.0",
        "producer_version": "linear_mixed_effects@1.0",
        "payload": payload,
    }


def _canonical_packets() -> dict[str, dict[str, Any]]:
    recovery_candidate = {
        "action_id": "lmm.simplify_random_effects_v1",
        "operation_id": "model.rerun",
        "patch": {"model_options": {"random_slope": False}},
        "required_confirmation": True,
    }
    return {
        "success.json": _packet(
            "linear_mixed_effects.result",
            {
                "fixture_id": "known_truth_success_v1",
                "status": "complete",
                "result_id": "group_time_interaction",
                "fit_method": "reml",
                "inference_method": "asymptotic_wald_z_v1",
                "estimate": 0.9,
            },
        ),
        "singular_warning.json": _packet(
            "linear_mixed_effects.diagnostic",
            {
                "fixture_id": "singular_random_slope_v1",
                "status": "complete",
                "diagnostics": [
                    {
                        "code": "LMM_RANDOM_EFFECTS_SINGULAR",
                        "severity": "warning",
                        "status": "complete",
                        "evidence": {"slope_variance": 0.0},
                        "action_candidate": None,
                    }
                ],
            },
        ),
        "convergence_failed.json": _packet(
            "linear_mixed_effects.diagnostic",
            {
                "fixture_id": "convergence_failure_v1",
                "status": "failed",
                "diagnostics": [
                    {
                        "code": "LMM_CONVERGENCE_FAILED",
                        "severity": "error",
                        "status": "failed",
                        "evidence": {"optimizer": "lbfgs"},
                        "action_candidate": None,
                    }
                ],
            },
        ),
        "missing_subject_id_blocked.json": _packet(
            "linear_mixed_effects.diagnostic",
            {
                "fixture_id": "missing_subject_id_v1",
                "status": "blocked",
                "diagnostics": [
                    {
                        "code": "LMM_SUBJECT_ID_MISSING",
                        "severity": "error",
                        "status": "blocked",
                        "evidence": {"column": "participant_id"},
                        "action_candidate": None,
                    }
                ],
            },
        ),
        "invalid_random_slope_blocked.json": _packet(
            "linear_mixed_effects.diagnostic",
            {
                "fixture_id": "invalid_random_slope_v1",
                "status": "blocked",
                "diagnostics": [
                    {
                        "code": "LMM_INVALID_RANDOM_SLOPE_CONFIGURATION",
                        "severity": "error",
                        "status": "blocked",
                        "evidence": {"random_slope": True, "time": "week"},
                        "action_candidate": None,
                    }
                ],
            },
        ),
        "recoverable_proposal.json": _packet(
            "linear_mixed_effects.recovery_proposal",
            {
                "fixture_id": "recoverable_random_slope_v1",
                "proposal_status": "pending_confirmation",
                "action_candidate": recovery_candidate,
            },
        ),
        "comparable_child.json": _packet(
            "analysis_loop.compare",
            {
                "fixture_id": "comparable_child_v1",
                "compare_status": "complete",
                "source_run_id": "lmm-source-v1",
                "child_run_id": "lmm-child-v1",
                "result_id": "group_time_interaction",
                "comparison_scope": "same_fixed_effects_ml",
            },
        ),
        "restricted_reml_child.json": _packet(
            "analysis_loop.compare",
            {
                "fixture_id": "restricted_reml_child_v1",
                "compare_status": "restricted",
                "reason_code": "REML_FIXED_EFFECTS_DIFFER",
                "user_safe_message": (
                    "两个模型使用 REML 且固定效应结构不同；似然、AIC 和似然比检验不作为有效的直接比较依据。"
                ),
                "source_run_id": "lmm-source-v1",
                "child_run_id": "lmm-child-v1",
            },
        ),
    }


def write_fixtures(root: Path = ROOT) -> None:
    """Write all checked-in fixture files with deterministic formatting."""

    root.mkdir(parents=True, exist_ok=True)
    packets = root / "packets"
    packets.mkdir(parents=True, exist_ok=True)

    known_truth = build_known_truth()
    known_truth.to_csv(root / "known_truth.csv", index=False, float_format="%.17g")
    (root / "known_truth.json").write_text(
        json.dumps(
            {
                "seed": SEED,
                "n_obs": 480,
                "n_subjects": 80,
                "n_timepoints_per_subject": 6,
                "group_time_interaction": 0.9,
                "interaction_tolerance": 0.35,
                "fit_method": "reml",
                "primary_result_id": "group_time_interaction",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    singular_random_slope = known_truth.copy()
    singular_random_slope["week"] = 0
    singular_random_slope.to_csv(
        root / "singular_random_slope.csv", index=False, float_format="%.17g"
    )
    known_truth.drop(columns=["participant_id"]).to_csv(
        root / "missing_subject_id.csv", index=False, float_format="%.17g"
    )
    known_truth.loc[known_truth["week"] == 0].to_csv(
        root / "single_observation_per_subject.csv", index=False, float_format="%.17g"
    )

    for name, packet in _canonical_packets().items():
        (packets / name).write_text(
            json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    write_fixtures()
