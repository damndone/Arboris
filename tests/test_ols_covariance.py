"""OLS covariance honesty (v1.7 smoke finding).

The model editable schema, the rerun UI, and run_inputs.json all accepted
covariance = robust | clustered | unadjusted for plain OLS, but `_fit_ols`
hardcoded HC1 — a silent no-op that violates the explicit-only philosophy.
These tests pin the honest behavior: every accepted value changes the fitted
result (or fails closed), and the recorded decision reflects the actual
covariance plus whether the user chose it explicitly.
"""
import json

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow as _rw
from workbench.projects import create_project


def _noisy_csv(tmp_path):
    rng = np.random.default_rng(11)
    n = 120
    firm = np.repeat([f"f{i}" for i in range(12)], 10)
    x1 = rng.normal(size=n)
    # Heteroskedastic + firm-correlated noise so nonrobust / HC1 / clustered
    # standard errors genuinely differ.
    firm_effect = np.repeat(rng.normal(scale=1.5, size=12), 10)
    y = 1.0 + 2.0 * x1 + firm_effect + rng.normal(scale=np.abs(x1) + 0.3, size=n)
    frame = pd.DataFrame({"y": y, "x1": x1, "firm": firm})
    src = tmp_path / "d.csv"
    frame.to_csv(src, index=False)
    return src, frame


def _run_ols(tmp_path, name, **kwargs):
    src, frame = _noisy_csv(tmp_path)
    project = create_project(tmp_path, name)
    result = _rw(
        project.root, [src], mode="explicit", y="y", x=["x1"],
        model_type="ols", **kwargs,
    )
    run_root = project.root / "runs" / result["run_id"]
    return run_root, frame


def _oracle(frame):
    return smf.ols("y ~ x1", data=frame).fit()


def _primary(run_root):
    return read_json(run_root / "model_results" / "ols_1.json")


def _robust_se_dp(run_root):
    graph = json.loads((run_root / "graph.json").read_text())
    node = graph["nodes"]["model:ols_1"]
    for dp in node["decision_points"]:
        if dp["decision_id"] == "ols_default_robust_se":
            return dp
    raise AssertionError("ols_default_robust_se decision point missing")


def test_ols_default_covariance_stays_hc1(tmp_path):
    run_root, frame = _run_ols(tmp_path, "default")
    primary = _primary(run_root)
    assert primary["model_type"] == "ols_robust"
    oracle = _oracle(frame).get_robustcov_results(cov_type="HC1")
    se = dict(zip(oracle.model.exog_names, oracle.bse))
    assert abs(primary["coefficients"]["x1"]["std_error"] - se["x1"]) < 1e-10
    dp = _robust_se_dp(run_root)
    assert dp["selected"] == "HC1"
    assert dp["source"] == "system_default"


def test_ols_unadjusted_covariance_is_honored(tmp_path):
    run_root, frame = _run_ols(tmp_path, "unadj", covariance="unadjusted")
    primary = _primary(run_root)
    assert primary["model_type"] == "ols"
    oracle = _oracle(frame)
    assert abs(primary["coefficients"]["x1"]["std_error"] - oracle.bse["x1"]) < 1e-10
    dp = _robust_se_dp(run_root)
    assert dp["selected"] == "nonrobust"
    assert dp["source"] == "user_explicit"


def test_ols_clustered_covariance_uses_entity_col(tmp_path):
    run_root, frame = _run_ols(
        tmp_path, "clustered", covariance="clustered", entity_col="firm",
    )
    primary = _primary(run_root)
    assert primary["model_type"] == "ols_clustered"
    oracle = _oracle(frame).get_robustcov_results(
        cov_type="cluster", groups=frame["firm"],
    )
    se = dict(zip(oracle.model.exog_names, oracle.bse))
    assert abs(primary["coefficients"]["x1"]["std_error"] - se["x1"]) < 1e-10
    dp = _robust_se_dp(run_root)
    assert dp["selected"] == "clustered"
    assert dp["source"] == "user_explicit"


def test_ols_clustered_without_entity_field_fails_closed(tmp_path):
    run_root, _ = _run_ols(tmp_path, "noentity", covariance="clustered")
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] in {"failed", "blocked"}
    errors = read_json(run_root / "errors.json")
    assert "OLS_CLUSTER_FIELD_MISSING" in json.dumps(errors)
    assert not (run_root / "model_results" / "ols_1.json").exists()
