"""Release conformance for the future-shift leakage decoy (design 8.3).

M0 does not execute temporal prediction, so this is a release-suite decoy
rather than a per-run statistical control: a temporally-ordered request that
carries an explicit future derivation must be refused before anything is
fitted, and must leave no prediction evidence behind.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

_REFUSAL_CODES = {
    "PREDICTION_SPLIT_PROFILE_NOT_SUPPORTED",
    "PREDICTION_FUTURE_DERIVATION_FORBIDDEN",
    "PREDICTION_DATA_STRUCTURE_UNKNOWN",
    "PREDICTION_TIME_COLUMN_REQUIRED",
}

_EVIDENCE_DIRS = (
    "prediction_results",
    "evaluation_results",
    "negative_controls",
    "prediction_splits",
)


def _future_shift_frame() -> pd.DataFrame:
    """Time-ordered data whose `lead_target` is tomorrow's outcome.

    `honest_feature` is deliberately uninformative so that a high score can
    only come from the leaked column, not from legitimate signal.
    """
    rng = np.random.default_rng(20260804)
    n = 120
    target = np.cumsum(rng.normal(0.0, 1.0, n)) + 50.0
    lead_target = np.roll(target, -1)
    lead_target[-1] = target[-1]
    return pd.DataFrame({
        "day": np.arange(n),
        "target": target.round(6),
        "honest_feature": rng.normal(0.0, 1.0, n).round(6),
        # lead(target, 1): only knowable after the fact.
        "lead_target": lead_target.round(6),
    })


def _run(tmp_path: Path, name: str, **kwargs):
    source = tmp_path / f"{name}.csv"
    _future_shift_frame().to_csv(source, index=False)
    project = create_project(tmp_path, name)
    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type="ols",
        y="target",
        x=["honest_feature", "lead_target"],
        prediction_model_type="prediction_ridge",
        **kwargs,
    )
    return project.root / "runs" / outcome["run_id"], outcome


def _issue_codes(run_root: Path) -> set[str]:
    path = run_root / "errors.json"
    if not path.exists():
        return set()
    return {issue.get("code") for issue in read_json(path)["issues"]}


def _evidence_files(run_root: Path) -> list[str]:
    found: list[str] = []
    for directory in _EVIDENCE_DIRS:
        target = run_root / directory
        if target.exists():
            found.extend(f"{directory}/{item.name}" for item in target.rglob("*.json"))
    return found


def test_temporal_future_shift_request_is_refused_before_any_fit(
    tmp_path: Path, monkeypatch
) -> None:
    from workbench.predictive_research import prediction_protocol

    fits: list[str] = []
    original = prediction_protocol._fit_estimator

    def _record(*args, **kwargs):
        fits.append("fit")
        return original(*args, **kwargs)

    monkeypatch.setattr(prediction_protocol, "_fit_estimator", _record)

    run_root, _ = _run(
        tmp_path,
        "future-shift",
        prediction_data_structure="temporal",
        prediction_time_column="day",
    )

    assert _issue_codes(run_root) & _REFUSAL_CODES, _issue_codes(run_root)
    # Not merely a message: no estimator may have been fitted.
    assert fits == [], "an estimator was fitted for a refused temporal request"
    assert _evidence_files(run_root) == [], _evidence_files(run_root)


def test_unknown_structure_still_blocks_the_decoy(tmp_path: Path) -> None:
    run_root, _ = _run(tmp_path, "unknown-structure")

    assert "PREDICTION_DATA_STRUCTURE_UNKNOWN" in _issue_codes(run_root)
    assert _evidence_files(run_root) == [], _evidence_files(run_root)


def test_declaring_the_decoy_as_iid_is_a_known_undetected_bypass(tmp_path: Path) -> None:
    """Records the limitation the design states rather than claiming a detector.

    Without availability/provenance metadata M0 cannot tell that a column peeks
    ahead, so a user who declares this temporal fixture as IID gets a run whose
    score comes entirely from the leak. This test pins that behaviour so the
    limitation stays visible; when provenance-based detection lands, it should
    be tightened into a refusal.
    """
    run_root, outcome = _run(tmp_path, "relabelled", prediction_data_structure="iid")

    assert outcome["status"] == "completed"
    packet = read_json(run_root / "evaluation_results" / "prediction_ridge_1.json")
    leaked_r2 = packet["oos"]["metrics"]["r2"]
    baseline_r2 = packet["baseline"]["metrics"]["r2"]

    # The honest feature is noise, so this score is the leak and nothing else.
    assert leaked_r2 > 0.9, leaked_r2
    assert baseline_r2 < 0.1, baseline_r2
