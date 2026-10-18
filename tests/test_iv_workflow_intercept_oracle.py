"""The workflow IV path (what the Agent and the Analyze menu call) against oracles.

v1.9.1 M0 found that ``iv.gmm`` and ``iv.weak_instruments`` ran without an
intercept when the data had no constant column: the first-stage partial F was
6223.5 instead of 170.6 on the baseline task. The pack's own oracle tests pass
a hand-built design that already holds a constant, so the consumer path was
never compared with anything. These tests call the registered operation on a
frame without a constant column, as a workflow step does, and compare with
statsmodels and with Stata.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from statsmodels.sandbox.regression.gmm import IV2SLS

from stata_oracle import emit, requires_stata, run

from workbench.agent.p7_pack_registry import p7_pack_registry


def _frame(n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(20261018)
    x = rng.normal(5.0, 2.0, n)
    z1 = rng.binomial(1, 0.5, n).astype(float)
    z2 = rng.normal(12.0, 2.0, n)
    v = rng.normal(0.0, 1.0, n)
    endog = 12.0 + 0.8 * z1 + 0.15 * z2 + 0.1 * x + v
    y = 1.0 + 0.1 * endog + 0.03 * x + 0.5 * v + rng.normal(0.0, 0.4, n)
    return pd.DataFrame({"y": y, "x": x, "endog": endog, "z1": z1, "z2": z2})


def _call(operation_id: str, frame: pd.DataFrame, exog: list[str], options: dict | None = None) -> dict:
    request = {
        "operation_id": operation_id,
        "input_mode": "typed",
        "column_bindings": {"outcome": "y", "exog": exog, "endog": ["endog"], "instruments": ["z1", "z2"]},
        "options": options or {},
    }
    operation = p7_pack_registry.get(operation_id)
    operation.validate(request)
    result = operation.execute(frame, request)
    operation.validate_result(result)
    return result


def _with_constant(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    x = sm.add_constant(frame[["x", "endog"]].to_numpy())
    z = sm.add_constant(frame[["x", "z1", "z2"]].to_numpy())
    return x, z


def test_weak_instruments_partials_out_an_intercept_without_a_constant_column() -> None:
    frame = _frame()
    weak = _call("iv.weak_instruments", frame, ["x"])["result"]["by_endogenous"]["endog"]
    full = sm.OLS(frame["endog"], sm.add_constant(frame[["x", "z1", "z2"]])).fit()
    oracle_f = float(full.f_test("z1 = 0, z2 = 0").fvalue)
    np.testing.assert_allclose(weak["partial_f"], oracle_f, rtol=1e-10)
    restricted = sm.OLS(frame["endog"], sm.add_constant(frame[["x"]])).fit()
    np.testing.assert_allclose(weak["partial_r2"], 1 - full.ssr / restricted.ssr, rtol=1e-10)
    assert weak["residual_degrees_of_freedom"] == len(frame) - 4


def test_an_explicit_constant_column_gives_the_same_answer_and_is_not_doubled() -> None:
    frame = _frame().assign(const=1.0)
    implicit = _call("iv.weak_instruments", frame, ["x"])["result"]
    explicit = _call("iv.weak_instruments", frame, ["const", "x"])["result"]
    for key in ("partial_f", "robust_excluded_wald_f", "partial_r2", "residual_degrees_of_freedom"):
        assert implicit["by_endogenous"]["endog"][key] == pytest.approx(explicit["by_endogenous"]["endog"][key], rel=1e-12)
    assert implicit["exog_names"][0] == "const" and explicit["exog_names"].count("const") == 1


def test_intercept_can_be_turned_off_explicitly() -> None:
    frame = _frame()
    without = _call("iv.weak_instruments", frame, ["x"], {"intercept": False})["result"]
    assert "const" not in without["exog_names"]
    restricted = sm.OLS(frame["endog"], frame[["x"]]).fit()
    full = sm.OLS(frame["endog"], frame[["x", "z1", "z2"]]).fit()
    expected = ((restricted.ssr - full.ssr) / 2) / (full.ssr / full.df_resid)
    np.testing.assert_allclose(without["by_endogenous"]["endog"]["partial_f"], expected, rtol=1e-10)


def test_gmm_estimates_include_the_intercept_and_match_statsmodels() -> None:
    frame = _frame()
    x, z = _with_constant(frame)
    one_step = _call("iv.gmm", frame, ["x"], {"estimator": "one_step"})["result"]
    two_step = _call("iv.gmm", frame, ["x"], {"estimator": "two_step"})["result"]
    assert list(one_step["coefficients"]) == ["const", "x", "endog"]
    np.testing.assert_allclose([c["estimate"] for c in one_step["coefficients"].values()],
                               IV2SLS(frame["y"].to_numpy(), x, z).fit().params, rtol=1e-9)
    # Two-step linear GMM in closed form (statsmodels' IVGMM optimises numerically
    # and stops about 3e-5 short here): 2SLS residuals give the HC0 weight.
    y = frame["y"].to_numpy()
    b1 = IV2SLS(y, x, z).fit().params
    u = y - x @ b1
    weight = np.linalg.inv((z * u[:, None] ** 2).T @ z)
    b2 = np.linalg.solve(x.T @ z @ weight @ z.T @ x, x.T @ z @ weight @ z.T @ y)
    np.testing.assert_allclose([c["estimate"] for c in two_step["coefficients"].values()], b2, rtol=1e-9)


@requires_stata
def test_workflow_iv_path_matches_stata(tmp_path) -> None:
    frame = _frame()
    frame.to_csv(tmp_path / "iv.csv", index=False)
    stata = run(tmp_path, "\n".join([
        'import delimited using "iv.csv", clear asdouble',
        "regress endog x z1 z2",
        "test z1 z2",
        emit("partial_f", "r(F)"),
        emit("df_r", "e(df_r)"),
        "regress endog x z1 z2, vce(robust)",
        "test z1 z2",
        # Stata's robust is HC1; the pack reports the HC0 Wald F.
        emit("robust_f_hc1", "r(F)"),
        emit("n", "e(N)"),
        emit("k", "e(df_m) + 1"),
        "ivregress 2sls y x (endog = z1 z2)",
        emit("b2sls_endog", "_b[endog]"),
        emit("b2sls_cons", "_b[_cons]"),
        "ivregress gmm y x (endog = z1 z2), wmatrix(robust)",
        emit("bgmm_endog", "_b[endog]"),
        emit("bgmm_x", "_b[x]"),
        emit("bgmm_cons", "_b[_cons]"),
    ]), name="iv_workflow_intercept")

    weak = _call("iv.weak_instruments", frame, ["x"])["result"]["by_endogenous"]["endog"]
    assert weak["partial_f"] == pytest.approx(stata["partial_f"], rel=1e-9)
    assert weak["residual_degrees_of_freedom"] == stata["df_r"]
    # HC1 = HC0 * n / (n - k), so the HC0 Wald is the HC1 Wald times n / (n - k).
    hc0_from_hc1 = stata["robust_f_hc1"] * stata["n"] / (stata["n"] - stata["k"])
    assert weak["robust_excluded_wald_f"] == pytest.approx(hc0_from_hc1, rel=1e-9)

    one_step = _call("iv.gmm", frame, ["x"], {"estimator": "one_step"})["result"]["coefficients"]
    assert one_step["endog"]["estimate"] == pytest.approx(stata["b2sls_endog"], rel=1e-9)
    assert one_step["const"]["estimate"] == pytest.approx(stata["b2sls_cons"], rel=1e-9)
    two_step = _call("iv.gmm", frame, ["x"], {"estimator": "two_step"})["result"]["coefficients"]
    assert two_step["endog"]["estimate"] == pytest.approx(stata["bgmm_endog"], rel=1e-8)
    assert two_step["x"]["estimate"] == pytest.approx(stata["bgmm_x"], rel=1e-8)
    assert two_step["const"]["estimate"] == pytest.approx(stata["bgmm_cons"], rel=1e-8)
