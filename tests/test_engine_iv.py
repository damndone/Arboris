import pandas as pd
import numpy as np
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench import orchestrator as orch
from workbench.engine.registry import DEFAULT_BY_Y_TYPE


@pytest.fixture
def iv_frame():
    rng = np.random.default_rng(0)
    n = 400
    z = rng.normal(size=n)
    u = rng.normal(size=n)
    educ = 0.8 * z + u + rng.normal(size=n) * 0.3
    age = rng.normal(size=n)
    wage = 1.0 + 0.5 * educ + 0.2 * age + u + rng.normal(size=n) * 0.5
    return pd.DataFrame({"wage": wage, "educ": educ, "age": age, "dist": z})


def _run_iv(tmp_path, frame, *, endog, instruments, x, model_type="iv_2sls"):
    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(
        project.root, [source], mode="auto", y="wage", x=x,
        model_type=model_type, iv_endog=endog, iv_instruments=instruments,
    )
    # derive run_root the same way test_engine_golden's _run does
    run_root = project.root / "runs" / result["run_id"]
    return run_root, result


def test_iv_run_calls_estimator_with_buckets(monkeypatch, iv_frame, tmp_path):
    captured = {}
    real = orch.run_iv_2sls

    def spy(frame, *, y, exog, endog, instruments, model_id, covariance):
        captured.update(dict(y=y, exog=exog, endog=endog,
                             instruments=instruments, covariance=covariance))
        return real(frame, y=y, exog=exog, endog=endog,
                    instruments=instruments, model_id=model_id, covariance=covariance)

    monkeypatch.setattr(orch, "run_iv_2sls", spy)

    run_root, result = _run_iv(tmp_path, iv_frame, endog=["educ"], instruments=["dist"], x=["age"])

    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "completed"
    assert captured["endog"] == ["educ"]
    assert captured["instruments"] == ["dist"]
    assert "age" in captured["exog"]
    assert captured["covariance"] == "robust"


def test_iv_2sls_is_explicit_only():
    # explicit-only invariant: registered but NEVER an auto default
    assert "iv_2sls" not in DEFAULT_BY_Y_TYPE


def test_iv_run_writes_iv_diagnostics_artifact(iv_frame, tmp_path):
    run_root, result = _run_iv(
        tmp_path, iv_frame, endog=["educ"], instruments=["dist"], x=["age"]
    )
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "completed"

    diag_path = run_root / "iv_diagnostics.json"
    assert diag_path.exists(), "iv_diagnostics.json must be written for an IV run"
    diag = read_json(diag_path)
    for key in ("identification", "weak_instruments", "endogeneity", "overidentification"):
        assert key in diag, f"missing key {key!r} in iv_diagnostics"

    idx = read_json(run_root / "artifacts_index.json")
    ids = {a["artifact_id"] for a in idx["artifacts"]}
    assert "iv_diagnostics" in ids


def test_iv_failure_offers_switch_to_ols(iv_frame, tmp_path):
    # IV run with EMPTY instruments -> IV_SPEC_INCOMPLETE -> failed manifest.
    run_root, result = _run_iv(
        tmp_path, iv_frame, endog=["educ"], instruments=[], x=["age"]
    )
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "failed"

    errors = read_json(run_root / "errors.json")
    fit_issues = [i for i in errors["issues"] if i["code"] == "MODEL_FIT_FAILED"]
    assert fit_issues, "expected a MODEL_FIT_FAILED issue"
    actions = fit_issues[0]["evidence"]["recommended_actions"]
    switch = next(
        (a for a in actions if a["key"] == "iv_switch_to_ols"), None
    )
    assert switch is not None, f"iv_switch_to_ols not in {[a['key'] for a in actions]}"
    assert switch["form_overrides"] == {"model_type": "ols"}


def test_non_iv_run_has_no_iv_diagnostics(tmp_path):
    rng = np.random.default_rng(1)
    n = 200
    x = rng.normal(size=n)
    y = 1.0 + 0.5 * x + rng.normal(size=n)
    frame = pd.DataFrame({"y": y, "x": x})
    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(
        project.root, [source], mode="auto", y="y", x=["x"], model_type="auto"
    )
    run_root = project.root / "runs" / result["run_id"]

    assert not (run_root / "iv_diagnostics.json").exists()
    idx = read_json(run_root / "artifacts_index.json")
    ids = {a["artifact_id"] for a in idx["artifacts"]}
    assert "iv_diagnostics" not in ids
