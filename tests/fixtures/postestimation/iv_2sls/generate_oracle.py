"""Stata oracle for post-estimation after 2SLS (v1.8.11 step 1).

Data: tests/fixtures/admission/iv_2sls/data.csv (Codex work order B; y on
exogenous x1 and endogenous xe, instrumented by z).

VERIFICATION LEVEL: Stata 18 `ivregress 2sls y x1 (xe = z), vce(robust)` --
HC0 without a small-sample adjustment, z and chi2 inference, which is what
Workbench's iv_2sls reports by default. `test`, `lincom` and `nlcom` are
Stata's own; an independent implementation.

Run from the worktree root:
    PYTHONPATH=backend:. .venv/bin/python tests/fixtures/postestimation/iv_2sls/generate_oracle.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tests.stata_oracle import emit, run

HERE = Path(__file__).parent
DATA = Path("tests/fixtures/admission/iv_2sls/data.csv").resolve()

BODY = f"""
import delimited using "{DATA}", asdouble clear
ivregress 2sls y x1 (xe = z), vce(robust)
{emit("b_x1", "_b[x1]")}
{emit("b_xe", "_b[xe]")}
{emit("n", "e(N)")}
test x1 xe
{emit("wj_stat", "r(chi2)")}
{emit("wj_df", "r(df)")}
{emit("wj_p", "r(p)")}
test x1 - xe = 1
{emit("ws_stat", "r(chi2)")}
{emit("ws_df", "r(df)")}
{emit("ws_p", "r(p)")}
lincom x1 + 2*xe - 0.5
{emit("lc_est", "r(estimate)")}
{emit("lc_se", "r(se)")}
nlcom _b[x1] / _b[xe]
{emit("nl_est", "el(r(b), 1, 1)")}
{emit("nl_se", "sqrt(el(r(V), 1, 1))")}
"""

with tempfile.TemporaryDirectory() as workdir:
    r = run(Path(workdir), BODY, name="iv_postestimation")

oracle = {
    "generator": "tests/fixtures/postestimation/iv_2sls/generate_oracle.py",
    "reference": "Stata 18 ivregress 2sls, vce(robust)",
    "data": "tests/fixtures/admission/iv_2sls/data.csv",
    "terms": ["x1", "xe"],
    "nobs": int(r["n"]),
    "params": {"x1": r["b_x1"], "xe": r["b_xe"]},
    "wald_joint": {"distribution": "chi2", "statistic": r["wj_stat"], "df_num": int(r["wj_df"]), "p_value": r["wj_p"]},
    "wald_shifted": {"distribution": "chi2", "statistic": r["ws_stat"], "df_num": int(r["ws_df"]), "p_value": r["ws_p"]},
    "lincom": {"estimate": r["lc_est"], "std_error": r["lc_se"]},
    "nlcom": {"estimate": r["nl_est"], "std_error": r["nl_se"]},
}
(HERE / "oracle.json").write_text(json.dumps(oracle, indent=2) + "\n")
print("wrote", HERE / "oracle.json")
