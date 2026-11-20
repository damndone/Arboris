"""The estimators target the requested population, and refuse what they cannot estimate."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from workbench.contracts.treatment_effects import validate_treatment_effects_result
from workbench.engine.packs.treatment_effects import TreatmentEffectsError, estimate_treatment_effect


def _frame(n: int, seed: int) -> tuple[pd.DataFrame, dict[str, float]]:
    """Effects grow with x, and treatment favours high x, so ATT > ATE > ATC, and an OLS coefficient is none of them."""
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    t = (rng.uniform(size=n) < 1 / (1 + np.exp(-1.2 * x))).astype(float)
    effect = 2.0 + 1.5 * x
    y = 1.0 + x + t * effect + rng.normal(size=n)
    truth = {"ATE": float(effect.mean()), "ATT": float(effect[t == 1].mean()), "ATC": float(effect[t == 0].mean())}
    return pd.DataFrame({"t": t, "y": y, "x": x}), truth


def _fit(frame: pd.DataFrame, estimand: str, method: str = "aipw", **kw) -> dict:
    return estimate_treatment_effect(frame, treatment_column="t", outcome_column="y", covariate_columns=["x"],
                                     estimand=estimand, method=method, **kw)


@pytest.mark.parametrize("estimand", ["ATE", "ATT", "ATC"])
@pytest.mark.parametrize("method", ["aipw", "ipw", "ra"])
def test_each_method_recovers_each_estimand(estimand: str, method: str) -> None:
    frame, truth = _frame(20_000, 1)
    packet = _fit(frame, estimand, method, bootstrap_replications=20)
    validate_treatment_effects_result(packet)
    assert packet["result"]["estimate"] == pytest.approx(truth[estimand], abs=0.08)


def test_the_estimands_differ_where_effects_differ() -> None:
    frame, _truth = _frame(20_000, 2)
    values = {e: _fit(frame, e)["result"]["estimate"] for e in ("ATT", "ATE", "ATC")}
    assert values["ATT"] > values["ATE"] > values["ATC"]


def test_aipw_survives_one_wrong_model() -> None:
    """Doubly robust: an outcome model missing x still recovers the effect through the weights, and the reverse."""
    rng = np.random.default_rng(3)
    x = rng.normal(size=40_000)
    t = (rng.uniform(size=x.size) < 1 / (1 + np.exp(-x))).astype(float)
    frame = pd.DataFrame({"t": t, "x": x, "y": x ** 2 + x + 2.0 * t + rng.normal(size=x.size)})
    assert _fit(frame, "ATT")["result"]["estimate"] == pytest.approx(2.0, abs=0.12)
    assert _fit(frame, "ATT", "ra")["result"]["estimate"] != pytest.approx(2.0, abs=0.12)


@pytest.mark.parametrize("method,upper", [("aipw", 0.985), ("ipw", 1.0)])
def test_intervals_cover_at_about_the_stated_rate(method: str, upper: float) -> None:
    # The target is the population ATT: these intervals also carry the sampling of who gets treated.
    population_att = _frame(4_000_000, 99)[1]["ATT"]
    hits = total = 0
    for seed in range(300):
        result = _fit(_frame(800, 100 + seed)[0], "ATT", method)["result"]
        hits += result["ci_lower"] <= population_att <= result["ci_upper"]
        total += 1
    assert 0.91 <= hits / total <= upper


def test_bootstrap_is_reproducible() -> None:
    frame, _truth = _frame(500, 4)
    first, second = (_fit(frame, "ATC", "ra", bootstrap_replications=50)["result"]["std_error"] for _ in range(2))
    assert first == second


def test_missing_rows_are_dropped_and_reported() -> None:
    frame, _truth = _frame(500, 5)
    complete = _fit(frame, "ATT")
    gaps = pd.concat([frame, pd.DataFrame({"t": [1.0], "y": [np.nan], "x": [0.0]})], ignore_index=True)
    packet = _fit(gaps, "ATT")
    report = packet["result"].pop("missing_rows")
    assert report == {"rows_total": 501, "rows_used": 500, "missing_by_column": {"y": 1}}
    assert packet == complete


def test_clipping_is_reported() -> None:
    frame, _truth = _frame(2_000, 6)
    overlap = _fit(frame, "ATT", trim=0.2)["result"]["overlap"]
    assert overlap["rows_at_trim_bound"] > 0 and overlap["propensity_min"] == pytest.approx(0.2)


@pytest.mark.parametrize(
    "change,code",
    [(lambda f: f.assign(t=f.t * 2), "TREATMENT_EFFECTS_TREATMENT"),
     (lambda f: f.assign(x=f.x.astype(str)), "TREATMENT_EFFECTS_NON_NUMERIC"),
     (lambda f: f.assign(x=np.where(f.index == 0, np.inf, f.x)), "TREATMENT_EFFECTS_NON_FINITE"),
     (lambda f: f.assign(x=1.0), "TREATMENT_EFFECTS_COLLINEAR"),
     (lambda f: f.head(3), "TREATMENT_EFFECTS_T")],
)
def test_refusals_name_the_problem(change, code: str) -> None:
    frame, _truth = _frame(200, 7)
    with pytest.raises(TreatmentEffectsError, match=code):
        _fit(change(frame), "ATT")


def test_perfect_separation_is_refused() -> None:
    x = np.arange(200.0)
    frame = pd.DataFrame({"t": (x > 100).astype(float), "x": x, "y": x})
    with pytest.raises(TreatmentEffectsError, match="TREATMENT_EFFECTS_PROPENSITY"):
        _fit(frame, "ATT")


@pytest.mark.parametrize("estimand,group", [("ATE", "all"), ("ATT", 1), ("ATC", 0)])
def test_ipw_matches_statsmodels_treatment_effect(estimand, group):
    """statsmodels' TreatmentEffect stacks the propensity model, as Stata's teffects does."""
    import statsmodels.api as sm
    from statsmodels.treatment.treatment_effects import TreatmentEffect

    rng = np.random.default_rng(1)
    n = 2000
    x = rng.normal(size=(n, 3))
    t = (rng.random(n) < 1 / (1 + np.exp(-(.5 * x[:, 0] - .4 * x[:, 1])))) * 1
    y = 1 + t * (1 + .5 * x[:, 0]) + x @ [1, .5, -.3] + rng.normal(size=n)
    design = sm.add_constant(x)
    reference = TreatmentEffect(sm.OLS(y, design), t, results_select=sm.Logit(t, design).fit(disp=0)).ipw(effect_group=group).summary_frame()
    frame = pd.DataFrame(x, columns=list("abc")).assign(t=t, y=y)
    result = estimate_treatment_effect(frame, outcome_column="y", treatment_column="t", covariate_columns=list("abc"),
                                       estimand=estimand, method="ipw")["result"]
    assert result["estimate"] == pytest.approx(float(reference.iloc[0, 0]), abs=1e-6)
    assert result["std_error"] == pytest.approx(float(reference.iloc[0, 1]), rel=1e-3)
