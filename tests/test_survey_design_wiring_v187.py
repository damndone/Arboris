"""v1.8.7 block 1 — shared input wiring for complex survey design.

The new fields travel from the HTTP surface through run_service and the
orchestrator into ``ctx.artifacts``. Unsupported declarations may stop at the
typed survey boundary; this file protects that fail-closed behavior.

The load-bearing test in this file is
``test_fpc_without_sampling_weight_fails_closed_at_the_wired_entry`` — an FPC
declaration must never be hidden by an ordinary model fallback.
"""

from __future__ import annotations

import io
import json
import time
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

SURVEY_FIELDS = {
    "survey_strata_col": "region",
    "survey_psu_col": "cluster",
    "survey_fpc_col": "fpc",
    "survey_replicate_weights": '["rw1", "rw2"]',
    "survey_replicate_type": "bootstrap",
    "survey_lonely_psu": "adjust",
    "survey_weight_frame": "cross_sectional",
    "survey_subpop": "region == 'north'",
}


def _csv() -> bytes:
    return _frame().to_csv(index=False).encode()


def _frame() -> pd.DataFrame:
    """A deterministic frame large enough to clear the workflow's minimum sample.

    An 8-row frame is rejected with INSUFFICIENT_SAMPLE before estimation, which
    would make every assertion here pass or fail for reasons unrelated to wiring.
    """
    n = 60
    return pd.DataFrame(
        {
            "y": [float(i % 7) + 0.5 * (i % 3) for i in range(n)],
            "x": [float(i % 5) for i in range(n)],
            "region": ["north" if i % 2 == 0 else "south" for i in range(n)],
            "cluster": [f"c{i // 4}" for i in range(n)],
            "fpc": [1000.0] * n,
            "rw1": [1.0] * n,
            "rw2": [1.0] * n,
        }
    )


def _project(tmp_path, name):
    """Both projects must use an identically named source file.

    The artifact-set comparison below lists file names, and the uploaded CSV is
    one of them -- naming it after the project would make the two runs differ
    for a reason that has nothing to do with survey design.
    """
    project = create_project(tmp_path, name)
    source_dir = tmp_path / f"src_{name}"
    source_dir.mkdir()
    source = source_dir / "data.csv"
    source.write_bytes(_csv())
    return project, source


# --------------------------------------------------------------------------
# 1. HTTP surface forwards the fields
# --------------------------------------------------------------------------

def test_run_endpoint_forwards_survey_design_params(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "svy"}
    ).json()["project_root"]

    with patch(
        "workbench.services.run_service._run_workflow",
        return_value={"run_id": "r", "status": "succeeded"},
    ) as m:
        resp = client.post(
            "/runs",
            data={
                "project_root": root, "mode": "auto", "model_type": "ols",
                "y": "y", "x": "x", "model_options": "{}",
                **SURVEY_FIELDS,
            },
            files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
        )
        for _ in range(100):
            if m.call_args is not None:
                break
            time.sleep(0.05)

    assert resp.status_code == 200
    kw = m.call_args.kwargs
    assert kw["survey_strata_col"] == "region"
    assert kw["survey_psu_col"] == "cluster"
    assert kw["survey_fpc_col"] == "fpc"
    assert kw["survey_replicate_weights"] == ["rw1", "rw2"]
    assert kw["survey_replicate_type"] == "bootstrap"
    assert kw["survey_lonely_psu"] == "adjust"
    assert kw["survey_weight_frame"] == "cross_sectional"
    assert kw["survey_subpop"] == "region == 'north'"


def test_runs_batch_does_not_silently_ignore_survey_design(tmp_path):
    """``/runs/batch`` must not silently drop a declared survey design.

    The batch endpoint deliberately takes a much narrower parameter set than
    ``/runs`` (project_root, mode, y_list, x, file, sheet_name, transpose) — it
    does not even accept ``model_type``.  FastAPI drops unknown form fields
    without complaint, so a user who declares strata and PSU here today gets a
    whole batch of runs computed as if the sample were simple random, with no
    indication anything was discarded.

    That is precisely the silent-wrongness this release exists to remove.  The
    resolution chosen is to honour the design on the batch path too, so this
    test asserts the values actually reach every run in the batch.

    NOTE: asserting ``status_code == 200`` alone would be worthless here — it
    passes with no implementation at all, because FastAPI just drops the
    unknown fields and returns 200 anyway.
    """
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "svybatch"}
    ).json()["project_root"]

    seen: list[dict[str, object]] = []
    from workbench.engine.stages.source import SourceStage

    original = SourceStage.run

    def spy(self, ctx, env):
        seen.append(dict(ctx.artifacts))
        return original(self, ctx, env)

    with patch.object(SourceStage, "run", spy):
        resp = client.post(
            "/runs/batch",
            data={
                "project_root": root, "mode": "auto",
                "y_list": "y", "x": "x",
                **SURVEY_FIELDS,
            },
            files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
        )

    assert resp.status_code == 200
    assert seen, "batch never reached the workflow"
    for artifacts in seen:
        assert artifacts["_survey_strata_col"] == "region"
        assert artifacts["_survey_psu_col"] == "cluster"
        assert artifacts["_survey_replicate_weights"] == ["rw1", "rw2"]
        assert artifacts["_survey_lonely_psu"] == "adjust"
        assert artifacts["_survey_subpop"] == "region == 'north'"


# --------------------------------------------------------------------------
# 2. The fields reach ctx.artifacts under the existing "_" convention
# --------------------------------------------------------------------------

def test_survey_design_params_reach_ctx_artifacts(tmp_path):
    project, source = _project(tmp_path, "ctxsvy")
    seen: dict[str, object] = {}

    from workbench.engine.stages.source import SourceStage

    original = SourceStage.run

    def spy(self, ctx, env):
        seen.update(dict(ctx.artifacts))
        return original(self, ctx, env)

    with patch.object(SourceStage, "run", spy):
        run_workflow(
            project.root, [source], mode="auto", model_type="ols",
            y="y", x=["x"],
            survey_strata_col="region",
            survey_psu_col="cluster",
            survey_fpc_col="fpc",
            survey_replicate_weights=["rw1", "rw2"],
            survey_replicate_type="bootstrap",
            survey_lonely_psu="adjust",
            survey_weight_frame="cross_sectional",
            survey_subpop="region == 'north'",
        )

    assert seen["_survey_strata_col"] == "region"
    assert seen["_survey_psu_col"] == "cluster"
    assert seen["_survey_fpc_col"] == "fpc"
    assert seen["_survey_replicate_weights"] == ["rw1", "rw2"]
    assert seen["_survey_replicate_type"] == "bootstrap"
    assert seen["_survey_lonely_psu"] == "adjust"
    assert seen["_survey_weight_frame"] == "cross_sectional"
    assert seen["_survey_subpop"] == "region == 'north'"


# --------------------------------------------------------------------------
# 3. FAIL-CLOSED SURVEY DECLARATIONS
# --------------------------------------------------------------------------

def test_fpc_without_sampling_weight_fails_closed_at_the_wired_entry(tmp_path):
    """An FPC declaration cannot be carried into a naive model result."""
    bare_project, bare_source = _project(tmp_path, "bare")
    bare = run_workflow(
        bare_project.root, [bare_source], mode="auto", model_type="ols", y="y", x=["x"]
    )

    svy_project, svy_source = _project(tmp_path, "declared")
    declared = run_workflow(
        svy_project.root, [svy_source], mode="auto", model_type="ols", y="y", x=["x"],
        survey_strata_col="region",
        survey_psu_col="cluster",
        survey_fpc_col="fpc",
        survey_replicate_weights=["rw1", "rw2"],
        survey_replicate_type="bootstrap",
        survey_lonely_psu="adjust",
        survey_weight_frame="cross_sectional",
        survey_subpop="region == 'north'",
    )

    assert bare["status"] == "completed"
    assert declared["status"] == "failed"
    run_root = svy_project.root / "runs" / declared["run_id"]
    errors = read_json(run_root / "errors.json")
    assert any(issue["code"] == "SURVEY_FPC_UNSUPPORTED" for issue in errors["issues"])
    assert not (run_root / "model_results" / "ols_1.json").exists()


def test_sampling_weight_fails_closed_without_a_declared_design(tmp_path):
    """The refusal that survives block 3.

    Block 1 refused every sampling weight because no engine existed yet. Block 3
    unlocks the declared case, so what remains here is the undeclared one -- a
    weight with no strata and no PSU still cannot yield a design variance, and
    guessing one would be worse than refusing.
    """
    project, source = _project(tmp_path, "stillclosed")
    outcome = run_workflow(
        project.root, [source], mode="auto", model_type="ols", y="y", x=["x"],
        sampling_weight="rw1",
    )

    assert outcome["status"] == "failed"
    errors = read_json(project.root / "runs" / outcome["run_id"] / "errors.json")
    assert any(
        "SAMPLING_WEIGHT_UNSUPPORTED" in str(issue.get("code", ""))
        or "sampling_weight" in str(issue.get("message", ""))
        for issue in errors["issues"]
    )


@pytest.mark.parametrize(
    "survey_declaration",
    [
        {"survey_strata_col": "region"},
        {"survey_psu_col": "cluster"},
        {"survey_subpop": "region == 'north'"},
        {"survey_lonely_psu": "adjust"},
        {
            "survey_replicate_type": "provided",
            "survey_replicate_weights": ["rw1"],
        },
    ],
    ids=["strata", "psu", "subpopulation", "lonely-psu", "provided-replicates"],
)
def test_partial_survey_declarations_fail_closed_at_real_workflow_entry(
    tmp_path, survey_declaration
):
    """A survey declaration must not disappear into an ordinary model run."""
    project, source = _project(tmp_path, f"partial-{next(iter(survey_declaration))}")
    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type="ols",
        y="y",
        x=["x"],
        **survey_declaration,
    )

    assert outcome["status"] == "failed", outcome
    run_root = project.root / "runs" / outcome["run_id"]
    errors = read_json(run_root / "errors.json")
    assert any(issue["code"] == "SURVEY_DESIGN_INCOMPLETE" for issue in errors["issues"])
    assert not (run_root / "model_results" / "ols_1.json").exists()


def test_replicate_weight_columns_without_a_method_fail_closed(tmp_path):
    """Replicate columns are not allowed to be silently ignored by Taylor variance."""
    project, source = _project(tmp_path, "replicate-columns-without-type")
    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type="ols",
        y="y",
        x=["x"],
        sampling_weight="rw1",
        survey_strata_col="region",
        survey_psu_col="cluster",
        survey_replicate_weights=["rw1"],
    )

    assert outcome["status"] == "failed", outcome
    run_root = project.root / "runs" / outcome["run_id"]
    errors = read_json(run_root / "errors.json")
    assert any(
        issue["code"] == "SURVEY_REPLICATE_TYPE_REQUIRED"
        for issue in errors["issues"]
    )
    assert not (run_root / "model_results" / "ols_1.json").exists()


# --------------------------------------------------------------------------
# 4. measurement_level rides the existing labels channel
# --------------------------------------------------------------------------

def test_measurement_level_rides_labels_without_changing_routing(tmp_path):
    """measurement_level is carried by `labels`; block 1 must not let it route."""
    from workbench.engine.stages.ytype import YTypeStage

    original = YTypeStage.run

    def _run(name, **kwargs):
        """Run once, capturing the detected y_type from the ytype stage."""
        project, source = _project(tmp_path, name)
        captured: dict[str, object] = {}

        def spy(self, ctx, env):
            result = original(self, ctx, env)
            captured["y_type"] = result.artifacts.get("_y_type")
            return result

        with patch.object(YTypeStage, "run", spy):
            outcome = run_workflow(
                project.root, [source], mode="auto", model_type="ols",
                y="y", x=["x"], **kwargs,
            )
        models = sorted(
            p.name
            for p in (project.root / "runs" / outcome["run_id"] / "model_results").glob("*.json")
        )
        return outcome, captured.get("y_type"), models

    declared, declared_ytype, declared_models = _run(
        "mlevel", labels={"measurement_level": {"y": "ordinal"}}
    )
    # A control run rather than a guessed literal: the default covariance names
    # the primary model "ols_robust", so hard-coding "ols" would fail while
    # proving nothing about routing.
    control, control_ytype, control_models = _run("mlevel_control")

    assert declared["status"] == control["status"] == "completed"
    assert declared_ytype == control_ytype, (
        "measurement_level must not influence y_type detection in block 1"
    )
    assert declared_models == control_models, (
        "measurement_level changed which models were produced in block 1"
    )


# --------------------------------------------------------------------------
# 5. CLI parity — do not repeat the D3 "CLI is missing parameters" debt
# --------------------------------------------------------------------------

def test_cli_run_accepts_survey_design_params():
    import inspect

    from workbench.cli import run as cli_run

    params = inspect.signature(cli_run).parameters
    for name in SURVEY_FIELDS:
        assert name in params, f"CLI run command is missing --{name.replace('_', '-')}"
