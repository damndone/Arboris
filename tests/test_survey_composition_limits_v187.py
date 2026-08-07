"""v1.8.7 — the combinations a sampling design must refuse or flag.

Three acceptance criteria that share one theme: a design declaration that is
accepted but means something different from what the user thinks it means.

  A1-11  a panel weight without a stated frame -- cross-sectional and
         longitudinal weights answer different questions, and the engine cannot
         tell which one it was handed
  A1-13  time series with a sampling design -- these do not compose, and saying
         "not supported yet" would imply a later version will add it
  A1-20  a design declared over data that was already filtered upstream -- the
         design describes a population the analysis sample no longer represents

The first two fail closed. The third cannot: filtering is often legitimate, so
it is surfaced as a question rather than a refusal.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "survey"


def _panel_frame(rows_per_entity: int = 5, entities: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(20260812)
    n = rows_per_entity * entities
    return pd.DataFrame(
        {
            "entity": np.repeat(np.arange(entities), rows_per_entity),
            "period": np.tile(np.arange(rows_per_entity), entities),
            "y": rng.normal(size=n),
            "x": rng.normal(size=n),
            "stratum": np.repeat(np.arange(8), n // 8),
            "psu": np.repeat(np.arange(20), n // 20),
            "weight": rng.uniform(5, 15, size=n).round(3),
        }
    )


def _run(tmp_path: Path, name: str, frame: pd.DataFrame, **kwargs):
    source = tmp_path / f"{name}.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, name)
    outcome = run_workflow(project.root, [source], mode="auto", **kwargs)
    return project.root / "runs" / outcome["run_id"], outcome


# ---------------------------------------------------------------------------
# A1-11 -- a panel weight has to say which frame it is on
# ---------------------------------------------------------------------------

def test_panel_survey_weight_without_a_declared_frame_fails_closed(tmp_path):
    """Cross-sectional and longitudinal weights are not interchangeable.

    A cross-sectional weight makes each wave represent the population at that
    wave; a longitudinal weight makes the panel represent those present
    throughout. Applied to the wrong question the estimate is simply of a
    different population, and nothing in the numbers looks wrong.
    """
    # Not `panel_ols`: that family does not accept a sampling weight at all
    # (block 4, deferred), so the combination never reaches this question. The
    # ambiguity is a property of the *data*, not the family -- an OLS over panel
    # data with a sampling weight has exactly the same problem.
    run_root, outcome = _run(
        tmp_path, "panelframe", _panel_frame(),
        model_type="ols", y="y", x=["x"],
        entity_col="entity", time_col="period",
        sampling_weight="weight",
        survey_strata_col="stratum", survey_psu_col="psu",
    )
    assert outcome["status"] in {"failed", "blocked"}, outcome

    issues = read_json(run_root / "errors.json")["issues"]
    codes = {issue["code"] for issue in issues}
    assert "SURVEY_WEIGHT_FRAME_REQUIRED" in codes, codes

    message = " ".join(issue["message"] for issue in issues)
    # It must say what the two options mean, not just name the missing field.
    assert "cross-sectional" in message.lower()
    assert "longitudinal" in message.lower()


def test_declaring_the_frame_lets_the_panel_run(tmp_path):
    """The refusal must be about the missing declaration, nothing else."""
    _run_root, outcome = _run(
        tmp_path, "panelok", _panel_frame(),
        model_type="ols", y="y", x=["x"],
        entity_col="entity", time_col="period",
        sampling_weight="weight",
        survey_strata_col="stratum", survey_psu_col="psu",
        survey_weight_frame="cross_sectional",
    )
    assert outcome["status"] == "completed", outcome


# ---------------------------------------------------------------------------
# A1-13 -- time series and sampling designs do not compose
# ---------------------------------------------------------------------------

def test_time_series_with_a_sampling_design_is_refused_as_incoherent(tmp_path):
    """Not "unsupported" -- the two describe different objects.

    A sampling design says how units were drawn from a population. A time series
    is one realisation of a process observed over time; there is no population of
    units to have sampled. Reporting this as "not supported yet" would promise a
    later version that cannot exist.
    """
    rng = np.random.default_rng(20260813)
    n = 200
    frame = pd.DataFrame(
        {
            "observation_date": pd.date_range("2020-01-01", periods=n, freq="D"),
            "value": rng.normal(size=n).cumsum(),
            "stratum": np.repeat(np.arange(8), n // 8),
            "psu": np.repeat(np.arange(20), n // 20),
            "weight": rng.uniform(5, 15, size=n).round(3),
        }
    )
    run_root, outcome = _run(
        tmp_path, "tssvy", frame,
        model_type="time_series.ets", y="value", x=[],
        sampling_weight="weight",
        survey_strata_col="stratum", survey_psu_col="psu",
        model_options={
            "time_column": "observation_date", "value_column": "value",
            "error": "add", "trend": None, "seasonal": None,
        },
    )
    assert outcome["status"] in {"failed", "blocked"}, outcome

    issues = read_json(run_root / "errors.json")["issues"]
    codes = {issue["code"] for issue in issues}
    assert "SURVEY_DESIGN_DOES_NOT_COMPOSE" in codes, codes

    message = " ".join(issue["message"] for issue in issues).lower()
    for promise in ("not yet", "not supported yet", "coming", "future version"):
        assert promise not in message, (
            f"the refusal implies a later version will add it: {promise!r}"
        )


# ---------------------------------------------------------------------------
# A1-20 -- a design over data that was already filtered
# ---------------------------------------------------------------------------

def test_a_design_declared_over_pre_filtered_data_is_flagged(tmp_path):
    """Rows dropped before the design was applied change what it describes.

    Not refused: dropping incomplete rows is ordinary and often correct. But the
    design still names the original population, and the gap between the two is
    invisible in the output.
    """
    frame = pd.read_csv(FIXTURES / "design.csv")
    # Duplicated rows: cleaning removes them, so the analysis sample is a strict
    # subset of the frame the declared design describes. (NaNs in a modelled
    # column are rejected by the estimator before cleaning can drop them, so
    # they exercise a different path.)
    frame = pd.concat([frame, frame.iloc[:12]], ignore_index=True)

    run_root, outcome = _run(
        tmp_path, "prefiltered", frame,
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight",
        survey_strata_col="stratum", survey_psu_col="psu",
    )
    assert outcome["status"] == "completed", outcome

    findings = read_json(run_root / "measurement" / "design_precheck.json")["findings"]
    filtered = [f for f in findings if f["kind"] == "design_over_filtered_data"]
    assert filtered, [f["kind"] for f in findings]

    evidence = filtered[0]["evidence"]
    assert evidence["rows_before"] == 92
    assert evidence["rows_analysed"] == 80
    assert evidence["rows_dropped"] == 12


def test_an_unfiltered_design_run_is_not_flagged(tmp_path):
    frame = pd.read_csv(FIXTURES / "design.csv")
    run_root, outcome = _run(
        tmp_path, "clean", frame,
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight",
        survey_strata_col="stratum", survey_psu_col="psu",
    )
    assert outcome["status"] == "completed", outcome
    findings = read_json(run_root / "measurement" / "design_precheck.json")["findings"]
    assert not [f for f in findings if f["kind"] == "design_over_filtered_data"]
