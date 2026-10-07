"""Stata oracle for clustered panel and DID inference (v1.8.11 step 2).

Workbench fits fixed-effects panels, TWFE DID and TWFE event studies with
standard errors clustered by entity by default, as Stata's
`xtreg, fe vce(robust)` does: CR1 with G/(G-1) * (N-1)/(N-K), K counting every
parameter except the fixed effects nested within the clusters, and t(G - 1).

VERIFICATION LEVEL: Stata 18 `xtreg ..., fe vce(cluster <var>)` with the time
effects as explicit i.time regressors (absorbed in Workbench; the slopes and
their sandwich are the same by Frisch-Waugh-Lovell, and K counts them either
way). `test`, `testparm` and `lincom` are Stata's own. The intercept is not
compared: Stata's _cons is the base period's level, Workbench's is the
sum-to-zero intercept.

Data:
  * tests/fixtures/admission/panel_ols/data.csv (work order B; 50 units x 8
    periods). The nested-cluster case adds region = mod(g, 10): 10 clusters,
    every unit inside one.
  * tests/fixtures/admission/did/data.csv (work order B; 2 x 2 DID).
  * staggered.csv (written here, seed 20261004): 60 units, 8 periods,
    adoption in period 3, period 5 or never, for the event study.

Run from the worktree root:
    PYTHONPATH=backend:. .venv/bin/python tests/fixtures/panel_cluster/generate_oracle.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from tests.stata_oracle import emit, run

HERE = Path(__file__).parent
PANEL = Path("tests/fixtures/admission/panel_ols/data.csv").resolve()
DID = Path("tests/fixtures/admission/did/data.csv").resolve()
STAGGERED = (HERE / "staggered.csv").resolve()
EVENT_TIMES = (-5, -4, -3, -2, 0, 1, 2, 3, 4)  # every observed event time but the reference, -1


def _staggered() -> None:
    rng = np.random.default_rng(20261004)
    units, periods = 60, 8
    cohort = np.repeat([3, 5, 0], units // 3)
    rows = []
    unit_effect = rng.normal(0, 1, units)
    time_effect = rng.normal(0, 0.5, periods)
    for unit in range(units):
        for t in range(periods):
            treated = cohort[unit] > 0 and t >= cohort[unit]
            effect = 0.5 + 0.2 * (t - cohort[unit]) if treated else 0.0
            x1 = rng.normal()
            y = 1 + unit_effect[unit] + time_effect[t] + 0.3 * x1 + effect + rng.normal(0, 1)
            rows.append({"g": unit + 1, "time": t, "first_treat": int(cohort[unit]), "x1": round(x1, 8),
                         "y": round(y, 8)})
    pd.DataFrame(rows).to_csv(STAGGERED, index=False)


def _coef(prefix: str, term: str) -> str:
    return "\n".join([
        emit(f"{prefix}b_{term}", f"_b[{term}]"),
        emit(f"{prefix}se_{term}", f"_se[{term}]"),
        emit(f"{prefix}t_{term}", f"_b[{term}] / _se[{term}]"),
        emit(f"{prefix}p_{term}", f"2 * ttail(e(df_r), abs(_b[{term}] / _se[{term}]))"),
        emit(f"{prefix}lo_{term}", f"_b[{term}] - invttail(e(df_r), 0.025) * _se[{term}]"),
        emit(f"{prefix}hi_{term}", f"_b[{term}] + invttail(e(df_r), 0.025) * _se[{term}]"),
    ])


def _postestimation(prefix: str, first: str, second: str) -> str:
    """The hypotheses tests/test_postestimation_registry.py asks every family."""
    return "\n".join([
        f"test {first} {second}",
        emit(f"{prefix}wj_F", "r(F)"), emit(f"{prefix}wj_df", "r(df)"), emit(f"{prefix}wj_df_r", "r(df_r)"),
        emit(f"{prefix}wj_p", "r(p)"),
        f"test {first} - {second} = 1",
        emit(f"{prefix}ws_F", "r(F)"), emit(f"{prefix}ws_df", "r(df)"), emit(f"{prefix}ws_df_r", "r(df_r)"),
        emit(f"{prefix}ws_p", "r(p)"),
        f"lincom {first} + 2*{second} - 0.5",
        emit(f"{prefix}lc_est", "r(estimate)"), emit(f"{prefix}lc_se", "r(se)"),
        f"nlcom _b[{first}] / _b[{second}]",
        emit(f"{prefix}nl_est", "el(r(b), 1, 1)"), emit(f"{prefix}nl_se", "sqrt(el(r(V), 1, 1))"),
    ])


def _fit_meta(prefix: str) -> str:
    return "\n".join([emit(f"{prefix}n", "e(N)"), emit(f"{prefix}g", "e(N_clust)"), emit(f"{prefix}df", "e(df_r)")])


evt_vars = " ".join(f"_evt_{'m' if k < 0 else 'p'}{abs(k)}" for k in EVENT_TIMES)
leads = " ".join(f"_evt_m{abs(k)}" for k in EVENT_TIMES if k < 0)
evt_gen = "\n".join(
    f"gen _evt_{'m' if k < 0 else 'p'}{abs(k)} = (first_treat > 0 & time - first_treat == {k})" for k in EVENT_TIMES
)

_staggered()
BODY = f"""
import delimited using "{PANEL}", asdouble clear case(preserve)
xtset g time
xtreg y x1 x2 i.time, fe vce(robust)
{_fit_meta("panel_")}
{_coef("panel_", "x1")}
{_coef("panel_", "x2")}
test x1 x2
{emit("panel_wald_F", "r(F)")}
{emit("panel_wald_df", "r(df)")}
{emit("panel_wald_df_r", "r(df_r)")}
{emit("panel_wald_p", "r(p)")}
lincom x1 - x2
{emit("panel_lincom_est", "r(estimate)")}
{emit("panel_lincom_se", "r(se)")}
{emit("panel_lincom_p", "r(p)")}
{_postestimation("panel_", "x1", "x2")}
gen region = mod(g, 10)
xtreg y x1 x2 i.time, fe vce(cluster region)
{_fit_meta("region_")}
{_coef("region_", "x1")}
{_coef("region_", "x2")}

import delimited using "{DID}", asdouble clear case(preserve)
xtset g time
xtreg y D i.time, fe vce(robust)
{_fit_meta("did_")}
{_coef("did_", "D")}

import delimited using "{STAGGERED}", asdouble clear case(preserve)
xtset g time
gen D = first_treat > 0 & time >= first_treat
xtreg y D x1 i.time, fe vce(robust)
{_fit_meta("stag_")}
{_coef("stag_", "D")}
{_coef("stag_", "x1")}
{_postestimation("stag_", "D", "x1")}
{evt_gen}
xtreg y {evt_vars} i.time, fe vce(robust)
{_fit_meta("evt_")}
{chr(10).join(_coef("evt_", f"_evt_{'m' if k < 0 else 'p'}{abs(k)}") for k in EVENT_TIMES)}
testparm {leads}
{emit("evt_pre_F", "r(F)")}
{emit("evt_pre_df", "r(df)")}
{emit("evt_pre_df_r", "r(df_r)")}
{emit("evt_pre_p", "r(p)")}
"""

with tempfile.TemporaryDirectory() as workdir:
    results = run(Path(workdir), BODY, name="panel_cluster")

oracle = {
    "generator": "tests/fixtures/panel_cluster/generate_oracle.py",
    "reference": "Stata 18 xtreg, fe vce(cluster)",
    "event_times": list(EVENT_TIMES),
    "results": results,
}
(HERE / "oracle.json").write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n")
print("wrote", HERE / "oracle.json")
