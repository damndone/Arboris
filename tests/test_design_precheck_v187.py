"""v1.8.7 A2b — check the sampling-design preconditions, and ask about them.

This is the part SPSS and Stata structurally cannot do. They will run an
analysis whose assumptions are plainly violated and say nothing; noticing is the
user's job. An assistant that can read the data can notice on their behalf.

The red line from the positioning document holds throughout:

  ask   "region looks like a stratum variable -- if this was a stratified
         sample, the standard errors here are wrong"
  never "you should use a stratified design" / "your conclusion does not hold"

Every number an Agent may quote is computed here, deterministically, and stored
in an artifact. The Agent references it; it never recomputes or paraphrases a
figure. A statistic a language model produced is not evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "survey"


def _run(tmp_path: Path, name: str, frame: pd.DataFrame, **kwargs) -> Path:
    source = tmp_path / f"{name}.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, name)
    outcome = run_workflow(project.root, [source], mode="auto", **kwargs)
    assert outcome["status"] == "completed", outcome
    return project.root / "runs" / outcome["run_id"]


def _precheck(run_root: Path) -> dict:
    path = run_root / "measurement" / "design_precheck.json"
    return read_json(path) if path.exists() else {"findings": []}


def _findings(run_root: Path, kind: str) -> list[dict]:
    return [f for f in _precheck(run_root)["findings"] if f["kind"] == kind]


# ---------------------------------------------------------------------------
# A2b-1 -- a design that was never declared
# ---------------------------------------------------------------------------

def test_undeclared_but_plausible_design_columns_are_raised(tmp_path):
    """The committed survey fixture, analysed as if it were a simple sample.

    `stratum` and `psu` are right there in the data. Nothing today looks.
    """
    frame = pd.read_csv(FIXTURES / "design.csv")
    run_root = _run(tmp_path, "undeclared", frame, y="y", x=["x1", "x2"])

    findings = _findings(run_root, "possible_undeclared_design")
    assert findings, "no design question was raised at all"

    columns = {entry["column"] for entry in findings}
    assert {"stratum", "psu"} <= columns, columns

    stratum = next(f for f in findings if f["column"] == "stratum")
    # Structural evidence, extracted -- not an assertion that it *is* a stratum.
    assert stratum["evidence"]["n_distinct"] == 8
    assert stratum["evidence"]["rows_per_level"]["min"] >= 1
    assert stratum["evidence"]["nests_within"] is None
    psu = next(f for f in findings if f["column"] == "psu")
    assert psu["evidence"]["nests_within"] == "stratum", (
        "the nesting that makes psu a plausible PSU was not detected"
    )


def test_nothing_is_raised_once_the_design_is_declared(tmp_path):
    """Having declared it, the user must not keep being asked."""
    frame = pd.read_csv(FIXTURES / "design.csv")
    run_root = _run(
        tmp_path, "declared", frame, y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    assert not _findings(run_root, "possible_undeclared_design")


def test_a_plain_dataset_raises_no_design_question(tmp_path):
    """A question on every run is a question on none."""
    rng = np.random.default_rng(20260810)
    frame = pd.DataFrame(
        {
            "y": rng.normal(size=200),
            "x1": rng.normal(size=200),
            "x2": rng.normal(size=200),
        }
    )
    run_root = _run(tmp_path, "plain", frame, y="y", x=["x1", "x2"])
    assert not _findings(run_root, "possible_undeclared_design")


# ---------------------------------------------------------------------------
# A2b-2 -- DEFF in plain language, quoting the backend's own number
# ---------------------------------------------------------------------------

def test_design_effect_is_reported_in_plain_language_from_the_engine_number(tmp_path):
    """The figure must be the engine's, to the last digit.

    A model re-deriving `n_eff` from a rounded DEFF would produce a number that
    looks authoritative and disagrees with the result panel. The finding carries
    the value so there is nothing to re-derive.
    """
    frame = pd.read_csv(FIXTURES / "design.csv")
    run_root = _run(
        tmp_path, "deff", frame, y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )

    findings = _findings(run_root, "design_effect")
    assert findings, "a design effect above 1 was not surfaced"
    finding = findings[0]

    model = read_json(run_root / "model_results" / "ols_1.json")
    design = model["survey_design"]
    assert finding["evidence"]["design_effect"] == design["design_effect"]
    assert finding["evidence"]["effective_sample_size"] == design["effective_sample_size"]

    # Plain language, with the two numbers a reader needs to weigh it.
    message = finding["message"]
    assert str(int(design["n_obs"])) in message
    assert str(int(round(design["effective_sample_size"]))) in message


# ---------------------------------------------------------------------------
# A2b-3 -- extreme weights
# ---------------------------------------------------------------------------

def test_extreme_weights_are_reported_as_a_question(tmp_path):
    rng = np.random.default_rng(20260811)
    n = 200
    weights = np.full(n, 10.0)
    weights[:3] = 900.0  # a handful of observations dominating the estimate
    frame = pd.DataFrame(
        {
            "y": rng.normal(size=n),
            "x1": rng.normal(size=n),
            "stratum": np.repeat(np.arange(10), n // 10),
            "psu": np.repeat(np.arange(20), n // 20),
            "weight": weights,
        }
    )
    run_root = _run(
        tmp_path, "extreme", frame, y="y", x=["x1"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )

    findings = _findings(run_root, "extreme_weights")
    assert findings, "a 90x weight ratio was not surfaced"
    evidence = findings[0]["evidence"]
    assert evidence["max_over_median"] > 50
    assert evidence["max"] == 900.0


def test_even_weights_raise_nothing(tmp_path):
    frame = pd.read_csv(FIXTURES / "design.csv")
    run_root = _run(
        tmp_path, "even", frame, y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    assert not _findings(run_root, "extreme_weights")


# ---------------------------------------------------------------------------
# A2b-4 -- the red line
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "banned",
    [
        "you should", "you must", "your conclusion", "is invalid", "is wrong",
        "incorrect analysis", "we recommend", "the correct",
    ],
)
def test_no_finding_asserts_rather_than_asks(tmp_path, banned):
    """Wording is the contract here, so it is asserted rather than reviewed."""
    frame = pd.read_csv(FIXTURES / "design.csv")
    undeclared = _run(tmp_path, "words_a", frame, y="y", x=["x1", "x2"])
    declared = _run(
        tmp_path, "words_b", frame, y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )

    text = (json.dumps(_precheck(undeclared)) + json.dumps(_precheck(declared))).lower()
    assert banned not in text, f"a finding asserts rather than asks: {banned!r}"


def test_every_quoted_number_exists_in_a_backend_artifact(tmp_path):
    """A2b-5, the anti-fabrication rule, checked structurally.

    Each finding must carry its figures in `evidence`, so an Agent has a value
    to cite rather than a sentence to parse. A message with no evidence behind it
    is the shape of an invented statistic.
    """
    frame = pd.read_csv(FIXTURES / "design.csv")
    run_root = _run(
        tmp_path, "cited", frame, y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )

    findings = _precheck(run_root)["findings"]
    assert findings
    for finding in findings:
        assert finding["evidence"], f"{finding['kind']} carries no evidence"
        assert finding["message"], f"{finding['kind']} carries no message"
        assert finding["kind"]
        # `column` is null for a whole-design finding such as the design effect,
        # and must be present as a key either way so a consumer never has to
        # guess whether the finding is about one column.
        assert "column" in finding


# ---------------------------------------------------------------------------
# the Agent has to be able to reach this, or it may as well not exist
# ---------------------------------------------------------------------------

def test_the_agent_has_a_tool_that_reads_these_findings():
    """v1.8.6 shipped code nothing called; v1.8.7 shipped a form nobody opened.

    Producing an artifact no tool exposes would be the same mistake a third time.
    Tool choice is name-driven in practice, so this is its own tool rather than a
    field buried in a general context call.
    """
    from workbench.agent.context_tools import NodeOperationContextProvider

    assert hasattr(NodeOperationContextProvider, "inspect_design_advisories")

    source = (
        Path(__file__).parent.parent
        / "backend/workbench/agent/context_tools.py"
    ).read_text()
    assert 'tool_id="inspect_design_advisories"' in source, (
        "the method exists but no ToolDefinition exposes it to a model"
    )
    # The description has to carry the boundary, since that is all the model sees.
    start = source.index('tool_id="inspect_design_advisories"')
    window = source[start:start + 2600].lower()
    assert "quote these values" in window or "quote these figures" in window
    assert "never as a verdict" in window
