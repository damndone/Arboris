"""v1.8.7 A2 — measurement level: declare it, or be told what was assumed.

`detect_y_kind` sends a non-negative integer column with few levels to Poisson.
A Likert 1-4 lands there exactly, and the run completes: rate ratios, standard
errors, a rendered report, nothing marking the outcome as a scale that was
treated as a count of events.

The routing is deliberately **not** changed. The same column `1,2,3,4` may be a
satisfaction rating (ordinal), a visit count (count), an encoded region
(nominal) or a 4-point GPA (near-continuous); they are numerically identical and
the difference lives in how the variable was measured. Guessing would move the
silent failure to a different set of users rather than remove it.

What changes is that the assumption stops being invisible, and that a user who
*does* know can say so and have it obeyed.

Every piece of evidence in an advisory is extracted deterministically from the
data. None of it may be produced by a language model -- an advisory a model
wrote is an assertion wearing evidence's clothes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _likert_frame() -> pd.DataFrame:
    """A satisfaction rating that `detect_y_kind` sends to Poisson today.

    `x` is distinct per row on purpose: cleaning drops duplicate rows, and a
    coarse covariate collapsed an earlier version of this fixture to 28 rows,
    below the modelling minimum, so every run came back blocked.
    """
    import numpy as np

    rng = np.random.default_rng(20260807)
    n = 200
    return pd.DataFrame(
        {
            "satisfaction": rng.integers(1, 5, size=n),
            "x": np.round(rng.normal(size=n), 6),
        }
    )


def _run(tmp_path: Path, name: str, frame: pd.DataFrame, **kwargs) -> Path:
    source = tmp_path / f"{name}.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, name)
    outcome = run_workflow(project.root, [source], mode="auto", **kwargs)
    assert outcome["status"] == "completed", outcome
    return project.root / "runs" / outcome["run_id"]


# ---------------------------------------------------------------------------
# the advisory
# ---------------------------------------------------------------------------

def test_an_undeclared_integer_scale_produces_an_advisory_naming_the_column(tmp_path):
    """The failure this exists to end: Poisson on a rating, with no notice."""
    run_root = _run(tmp_path, "likert", _likert_frame(), y="satisfaction", x=["x"])

    advisory = read_json(run_root / "measurement" / "advisory.json")
    entries = {entry["column"]: entry for entry in advisory["entries"]}
    assert "satisfaction" in entries, "the outcome column is not named"

    entry = entries["satisfaction"]
    assert entry["declared"] == "unspecified"
    assert entry["routed_as"] == "count"
    # Evidence, not a verdict: the values it saw and how many.
    assert entry["evidence"]["distinct_values"] == [1, 2, 3, 4]
    assert entry["evidence"]["n_levels"] == 4
    assert entry["evidence"]["includes_zero"] is False


def test_value_labels_are_treated_as_strong_evidence(tmp_path):
    """Nobody labels a visit count `1 = very dissatisfied`.

    A value label is a statement that the numbers stand for categories. It is
    already in the data and nothing reads it today.
    """
    frame = _likert_frame()
    run_root = _run(
        tmp_path, "labelled", frame, y="satisfaction", x=["x"],
        labels={
            "value_labels": {
                "satisfaction": {
                    "1": "very dissatisfied", "2": "dissatisfied",
                    "3": "satisfied", "4": "very satisfied",
                }
            }
        },
    )

    entry = {
        e["column"]: e
        for e in read_json(run_root / "measurement" / "advisory.json")["entries"]
    }["satisfaction"]

    assert entry["evidence"]["has_value_labels"] is True
    assert entry["confidence"] == "high"
    assert entry["suggested"] == "ordinal"


def test_an_advisory_without_labels_states_lower_confidence(tmp_path):
    """Same shape, weaker evidence -- and it must say so rather than round up."""
    run_root = _run(tmp_path, "unlabelled", _likert_frame(), y="satisfaction", x=["x"])
    entry = {
        e["column"]: e
        for e in read_json(run_root / "measurement" / "advisory.json")["entries"]
    }["satisfaction"]

    assert entry["evidence"]["has_value_labels"] is False
    assert entry["confidence"] == "low"


def test_the_advisory_asks_and_never_asserts(tmp_path):
    """The red line from the positioning doc, asserted rather than hoped for."""
    run_root = _run(tmp_path, "wording", _likert_frame(), y="satisfaction", x=["x"])
    advisory = read_json(run_root / "measurement" / "advisory.json")
    text = json.dumps(advisory).lower()

    for banned in (
        "your conclusion", "is invalid", "is wrong", "you must", "you should use",
    ):
        assert banned not in text, f"advisory asserts rather than asks: {banned!r}"


def test_a_genuine_count_column_is_not_flagged(tmp_path):
    """An advisory on everything is an advisory on nothing.

    A column with many levels including zero looks like a count and must pass
    without comment, or users learn to dismiss the notice.
    """
    import numpy as np

    rng = np.random.default_rng(20260808)
    n = 200
    frame = pd.DataFrame(
        {
            "visits": rng.poisson(3.0, size=n),
            "x": np.round(rng.normal(size=n), 6),
        }
    )
    run_root = _run(tmp_path, "visits", frame, y="visits", x=["x"])

    path = run_root / "measurement" / "advisory.json"
    entries = read_json(path)["entries"] if path.exists() else []
    assert not [e for e in entries if e["column"] == "visits"]


# ---------------------------------------------------------------------------
# declaring it changes the routing
# ---------------------------------------------------------------------------

def test_declaring_ordinal_routes_to_the_ordinal_family(tmp_path):
    """Not a guess -- executing what the user said."""
    run_root = _run(
        tmp_path, "declared", _likert_frame(), y="satisfaction", x=["x"],
        labels={"measurement_level": {"satisfaction": "ordinal"}},
    )

    produced = sorted(p.name for p in (run_root / "model_results").glob("*.json"))
    assert any(name.startswith("ordinal_logit") for name in produced), produced


def test_declaring_count_keeps_the_historical_route(tmp_path):
    run_root = _run(
        tmp_path, "declcount", _likert_frame(), y="satisfaction", x=["x"],
        labels={"measurement_level": {"satisfaction": "count"}},
    )
    produced = sorted(p.name for p in (run_root / "model_results").glob("*.json"))
    assert any("poisson" in name for name in produced), produced


def test_a_declared_column_is_not_second_guessed_by_an_advisory(tmp_path):
    """Having answered, the user must not keep being asked."""
    run_root = _run(
        tmp_path, "quiet", _likert_frame(), y="satisfaction", x=["x"],
        labels={"measurement_level": {"satisfaction": "ordinal"}},
    )
    path = run_root / "measurement" / "advisory.json"
    entries = read_json(path)["entries"] if path.exists() else []
    assert not [e for e in entries if e["column"] == "satisfaction"]


# ---------------------------------------------------------------------------
# the undeclared path must not move
# ---------------------------------------------------------------------------

def test_an_undeclared_run_routes_and_estimates_exactly_as_before(tmp_path):
    """A2-7: the advisory is additive. Any drift here is a silent regression."""
    frame = _likert_frame()
    baseline = _run(tmp_path, "base", frame, y="satisfaction", x=["x"])
    advised = _run(tmp_path, "advised", frame, y="satisfaction", x=["x"])

    def _model(run_root: Path) -> dict:
        path = next(
            p for p in sorted((run_root / "model_results").glob("*.json"))
            if not p.name.startswith("diagnostics")
        )
        return read_json(path)

    left, right = _model(baseline), _model(advised)
    assert left["model_type"] == right["model_type"] == "poisson"
    assert left["coefficients"] == right["coefficients"]


# ---------------------------------------------------------------------------
# A2-4/5/6 -- the Agent declares many columns at once
# ---------------------------------------------------------------------------

def _survey_frame() -> pd.DataFrame:
    """A questionnaire: several Likert items plus one genuine count."""
    import numpy as np

    rng = np.random.default_rng(20260809)
    n = 200
    return pd.DataFrame(
        {
            "q1": rng.integers(1, 6, size=n),
            "q2": rng.integers(1, 6, size=n),
            "q3": rng.integers(1, 6, size=n),
            "visits": rng.poisson(3.0, size=n),
            "x": np.round(rng.normal(size=n), 6),
        }
    )


def test_the_agent_may_declare_measurement_levels_in_one_proposal():
    """Fifty columns declared one at a time means nobody declares anything.

    Friction is the metric here, so the declaration has to be a single batch.
    It rides `labels` on a rerun rather than a bespoke data operation: a
    measurement level is run metadata, not a transformation of the data, and a
    rerun already provides the child node, the lineage and the confirmation gate.
    """
    from workbench.agent.operations import OperationRegistry

    definition = OperationRegistry().require("model.rerun")
    target = {
        "run_id": "r1", "node_ref": "model:poisson_1",
        "node_hash": "h1", "forest_node_key": "k1",
    }
    preconditions = {
        "context_version": "v1", "context_fingerprint": "fp1",
        "active_head_run_id": "r1", "owner_resolution": "explicit",
    }
    definition.validator(
        target, preconditions,
        {"labels": {"measurement_level": {"q1": "ordinal", "q2": "ordinal", "q3": "ordinal"}}},
    )

    branch = next(
        option
        for option in definition.proposal_schema["properties"]["changes"]["oneOf"]
        if "model_options" in option.get("properties", {})
    )
    assert "labels" in branch["properties"], "the model is never shown the channel"


def test_declaring_many_columns_lands_in_one_child_run(tmp_path):
    """A2-5: one confirmation, N columns declared, lineage intact."""
    from fastapi.testclient import TestClient

    from workbench.api import app

    frame = _survey_frame()
    source = tmp_path / "survey.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "batch")

    client = TestClient(app)
    with source.open("rb") as handle:
        created = client.post(
            "/runs",
            files={"file": ("survey.csv", handle, "text/csv")},
            data={
                "project_root": str(project.root), "mode": "auto",
                "model_type": "auto", "y": "q1", "x": "x",
            },
        )
    assert created.status_code == 200, created.text
    parent_id = created.json()["run_id"]
    _await(client, project.root, parent_id)

    rerun = client.post(
        f"/runs/{parent_id}/rerun",
        params={"project_root": str(project.root)},
        json={
            "from_node": "model:poisson_1",
            "op_overrides": {
                "labels": {
                    "measurement_level": {"q1": "ordinal", "q2": "ordinal", "q3": "ordinal"}
                }
            },
            "rerun_reason": "agent_confirmed",
        },
    )
    assert rerun.status_code == 200, rerun.text
    child_id = rerun.json()["run_id"]
    _await(client, project.root, child_id)

    produced = sorted(
        p.name
        for p in (project.root / "runs" / child_id / "model_results").glob("*.json")
    )
    assert any(name.startswith("ordinal_logit") for name in produced), produced
    assert child_id != parent_id


def test_a_declaration_naming_a_column_that_does_not_exist_is_refused(tmp_path):
    """A2-6, the anti-fabrication guard.

    An Agent that invents a column name must not have it accepted: the run would
    complete, the declaration would apply to nothing, and the user would believe
    a variable was declared that never was.
    """
    from fastapi.testclient import TestClient

    from workbench.api import app

    frame = _survey_frame()
    source = tmp_path / "survey.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "fabricated")

    client = TestClient(app)
    with source.open("rb") as handle:
        created = client.post(
            "/runs",
            files={"file": ("survey.csv", handle, "text/csv")},
            data={
                "project_root": str(project.root), "mode": "auto",
                "model_type": "auto", "y": "q1", "x": "x",
            },
        )
    parent_id = created.json()["run_id"]
    _await(client, project.root, parent_id)

    rerun = client.post(
        f"/runs/{parent_id}/rerun",
        params={"project_root": str(project.root)},
        json={
            "from_node": "model:poisson_1",
            "op_overrides": {
                "labels": {"measurement_level": {"not_a_column": "ordinal"}}
            },
            "rerun_reason": "agent_confirmed",
        },
    )
    assert rerun.status_code == 422, rerun.text
    assert "not_a_column" in rerun.text


def _await(client, project_root, run_id, timeout=90.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(
            f"/runs/{run_id}", params={"project_root": str(project_root)}
        ).json()
        if payload.get("status") in {"completed", "succeeded", "failed", "error"}:
            assert payload["status"] in {"completed", "succeeded"}, payload
            return
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} never reached a terminal status")
