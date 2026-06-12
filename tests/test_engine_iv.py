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
