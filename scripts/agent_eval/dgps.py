"""Data-generating processes with known truth for the Agent evaluation.

Each scenario returns a data frame and a ``truth`` mapping: the estimand the
analysis should recover, the families that can recover it, the checks a
competent analyst runs, and the traps a naive analysis falls into. Seeds are
fixed so every version of the Agent sees the same data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    outcome: str
    main_term: str | None
    #: Families whose estimate of ``main_term`` answers the question.
    appropriate_families: tuple[str, ...]
    #: Checks a competent analysis runs, scored as coverage. Each entry is one
    #: check; ``a|b`` lists operation ids that equally count for it.
    expected_checks: tuple[str, ...]
    #: Naive choices that answer a different question or are biased here.
    traps: tuple[str, ...]
    truth: float | None
    #: Absolute tolerance around ``truth`` for the main estimate, on top of its CI.
    tolerance: float
    build: Callable[[np.random.Generator], pd.DataFrame]
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def frame(self, seed: int) -> pd.DataFrame:
        return self.build(np.random.default_rng(seed))


def _wage_hetero(rng: np.random.Generator) -> pd.DataFrame:
    n = 600
    education = rng.integers(8, 21, n)
    experience = rng.integers(0, 40, n)
    female = rng.binomial(1, 0.5, n)
    sigma = 0.15 + 0.03 * (education - 8)
    log_wage = 1.0 + 0.08 * education + 0.03 * experience - 0.0005 * experience**2 - 0.15 * female + rng.normal(0, 1, n) * sigma
    return pd.DataFrame({"wage": np.round(np.exp(log_wage), 2), "education": education,
                         "experience": experience, "female": female})


def _wage_ovb(rng: np.random.Generator) -> pd.DataFrame:
    n = 800
    ability = rng.normal(0, 1, n)
    education = np.clip(np.round(13 + 1.5 * ability + rng.normal(0, 1.5, n)), 8, 21)
    test_score = 50 + 10 * ability + rng.normal(0, 3, n)
    experience = rng.integers(0, 35, n)
    log_wage = 1.2 + 0.06 * education + 0.10 * ability + 0.025 * experience + rng.normal(0, 0.3, n)
    return pd.DataFrame({"log_wage": np.round(log_wage, 4), "education": education,
                         "test_score": np.round(test_score, 1), "experience": experience})


def _iv(strength: float) -> Callable[[np.random.Generator], pd.DataFrame]:
    def build(rng: np.random.Generator) -> pd.DataFrame:
        n = 1500
        ability = rng.normal(0, 1, n)
        distance = rng.exponential(20, n)
        near_college = (distance < 15).astype(int)
        mother_educ = np.clip(np.round(12 + 0.8 * ability + rng.normal(0, 2, n)), 6, 20)
        education = 12 + strength * near_college + 0.9 * ability + 0.15 * (mother_educ - 12) + rng.normal(0, 1.5, n)
        education = np.clip(np.round(education), 6, 21)
        experience = rng.integers(0, 30, n)
        # Mother's education affects wages directly: it is not a valid instrument.
        log_wage = 1.0 + 0.10 * education + 0.20 * ability + 0.03 * (mother_educ - 12) + 0.02 * experience + rng.normal(0, 0.35, n)
        return pd.DataFrame({"log_wage": np.round(log_wage, 4), "education": education,
                             "near_college": near_college, "mother_educ": mother_educ,
                             "experience": experience})
    return build


def _panel_fe(rng: np.random.Generator) -> pd.DataFrame:
    firms, years = 200, 10
    alpha = rng.normal(0, 1, firms)
    rows = []
    for i in range(firms):
        for t in range(years):
            training = 2 + 1.5 * alpha[i] + rng.normal(0, 1)
            productivity = 3 + 0.5 * training + 2 * alpha[i] + 0.05 * t + rng.normal(0, 0.8)
            rows.append({"firm": f"F{i:03d}", "year": 2010 + t, "training": round(training, 3),
                         "productivity": round(productivity, 3)})
    return pd.DataFrame(rows)


def _did_2x2(rng: np.random.Generator) -> pd.DataFrame:
    stores = 300
    rows = []
    treated = rng.binomial(1, 0.5, stores)
    base = rng.normal(20, 4, stores)
    for i in range(stores):
        for post in (0, 1):
            y = base[i] + 1.0 * post + 1.5 * treated[i] + 2.0 * treated[i] * post + rng.normal(0, 2)
            rows.append({"store": f"S{i:03d}", "period": post, "treated": int(treated[i]),
                         "post": post, "employment": round(y, 3)})
    return pd.DataFrame(rows)


def _did_staggered(rng: np.random.Generator) -> pd.DataFrame:
    units, periods = 300, 10
    cohorts = rng.choice([0, 4, 6, 8], size=units, p=[0.25, 0.25, 0.25, 0.25])
    unit_fe = rng.normal(0, 1, units)
    rows = []
    for i in range(units):
        for t in range(1, periods + 1):
            g = cohorts[i]
            event = t - g if g else None
            # Effects grow with time since adoption and differ by cohort: TWFE is biased.
            effect = 0.0 if (not g or t < g) else (1.0 + 0.5 * (t - g)) * (1.5 if g == 4 else 1.0)
            y = unit_fe[i] + 0.2 * t + effect + rng.normal(0, 0.5)
            rows.append({"county": f"C{i:03d}", "year": t, "first_treat": int(g), "outcome": round(y, 4)})
    return pd.DataFrame(rows)


def _did_staggered_truth() -> float:
    """Midpoint of the two standard overall-ATT aggregations.

    Weighting treated cells equally gives 2.72; averaging cohort means equally
    gives 2.42 (equal cohort shares). Either is a correct headline, so the
    truth is their midpoint and the tolerance (0.45) covers both; TWFE on this
    design lands well outside it.
    """
    cells = {g: [(1.0 + 0.5 * (t - g)) * (1.5 if g == 4 else 1.0) for t in range(g, 11)] for g in (4, 6, 8)}
    by_cell = float(np.mean([v for values in cells.values() for v in values]))
    by_cohort = float(np.mean([np.mean(values) for values in cells.values()]))
    return (by_cell + by_cohort) / 2


def _spurious_ts(rng: np.random.Generator) -> pd.DataFrame:
    n = 240
    x = np.cumsum(rng.normal(0, 1, n))
    y = np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame({"month": np.arange(1, n + 1), "ad_spend_index": np.round(x, 4), "sales_index": np.round(y, 4)})


def _cointegrated_ts(rng: np.random.Generator) -> pd.DataFrame:
    n = 300
    x = np.cumsum(rng.normal(0, 1, n))
    u = np.zeros(n)
    for t in range(1, n):
        u[t] = 0.5 * u[t - 1] + rng.normal(0, 0.6)
    y = 2.0 + 1.5 * x + u
    return pd.DataFrame({"quarter": np.arange(1, n + 1), "income": np.round(x, 4), "consumption": np.round(y, 4)})


def _garch_returns(rng: np.random.Generator) -> pd.DataFrame:
    n = 1500
    omega, alpha, beta = 0.05, 0.08, 0.90
    h = omega / (1 - alpha - beta)
    r = np.zeros(n)
    for t in range(n):
        e = rng.standard_normal() * np.sqrt(h)
        r[t] = 0.03 + e
        h = omega + alpha * e**2 + beta * h
    return pd.DataFrame({"day": np.arange(1, n + 1), "return_pct": np.round(r, 5)})


def _overdispersed(rng: np.random.Generator) -> pd.DataFrame:
    n = 1000
    treated = rng.binomial(1, 0.4, n)
    age = rng.integers(20, 70, n)
    mu = np.exp(-0.5 + np.log(1.4) * treated + 0.01 * (age - 45))
    # NB2 with dispersion 1.5.
    lam = rng.gamma(shape=1 / 1.5, scale=1.5 * mu)
    visits = rng.poisson(lam)
    return pd.DataFrame({"visits": visits, "program": treated, "age": age})


def _binary(rng: np.random.Generator) -> pd.DataFrame:
    n = 1200
    income = rng.normal(50, 15, n)
    age = rng.integers(18, 75, n)
    urban = rng.binomial(1, 0.6, n)
    eta = -4.0 + 0.06 * income + 0.02 * age + 0.5 * urban
    owns = rng.binomial(1, 1 / (1 + np.exp(-eta)))
    return pd.DataFrame({"owns_home": owns, "income_k": np.round(income, 2), "age": age, "urban": urban})


def _cluster_experiment(rng: np.random.Generator) -> pd.DataFrame:
    classes = 30
    rows = []
    treat_class = rng.permutation([1] * 15 + [0] * 15)
    class_effect = rng.normal(0, 4, classes)
    for c in range(classes):
        for s in range(rng.integers(18, 32)):
            pre = rng.normal(60, 10)
            score = 20 + 0.6 * pre + 3.0 * treat_class[c] + class_effect[c] + rng.normal(0, 6)
            rows.append({"classroom": f"K{c:02d}", "tutoring": int(treat_class[c]), "pretest": round(pre, 1), "score": round(score, 1)})
    return pd.DataFrame(rows)


def _repeated(rng: np.random.Generator) -> pd.DataFrame:
    subjects, waves = 120, 5
    arm = rng.binomial(1, 0.5, subjects)
    b0 = rng.normal(0, 2, subjects)
    rows = []
    for i in range(subjects):
        for t in range(waves):
            y = 50 + b0[i] - 0.5 * t - 1.2 * arm[i] * t + rng.normal(0, 1.5)
            rows.append({"patient": f"P{i:03d}", "visit": t, "arm": "treatment" if arm[i] else "control", "symptom_score": round(y, 2)})
    return pd.DataFrame(rows)


def _missing_mar(rng: np.random.Generator) -> pd.DataFrame:
    n = 1000
    z = rng.normal(0, 1, n)
    x = 0.6 * z + rng.normal(0, 0.8, n)
    y = 1.0 + 0.7 * x + 0.5 * z + rng.normal(0, 1, n)
    frame = pd.DataFrame({"y": np.round(y, 4), "x": np.round(x, 4), "z": np.round(z, 4)})
    # x is missing more often when y is high: listwise deletion biases the slope.
    p = 1 / (1 + np.exp(-(-1.0 + 1.2 * (y - 1))))
    frame.loc[rng.uniform(size=n) < p, "x"] = np.nan
    return frame


def _leverage(rng: np.random.Generator) -> pd.DataFrame:
    n = 80
    x = rng.normal(10, 2, n)
    y = 5 + 1.0 * x + rng.normal(0, 2, n)
    x[:3] = [30, 32, 35]
    y[:3] = [5, 4, 6]
    return pd.DataFrame({"city": [f"city_{i}" for i in range(n)], "density": np.round(x, 3), "rent": np.round(y, 3)})


def _survival(rng: np.random.Generator) -> pd.DataFrame:
    n = 600
    drug = rng.binomial(1, 0.5, n)
    age = rng.integers(40, 80, n)
    rate = 0.05 * np.exp(np.log(0.6) * drug + 0.03 * (age - 60))
    t = rng.exponential(1 / rate)
    c = rng.uniform(5, 40, n)
    return pd.DataFrame({"months": np.round(np.minimum(t, c), 3), "event": (t <= c).astype(int), "drug": drug, "age": age})


def _quantile(rng: np.random.Generator) -> pd.DataFrame:
    n = 2000
    training = rng.binomial(1, 0.5, n)
    base = rng.normal(0, 1, n)
    # Effect grows with the outcome's quantile: location-scale model.
    earnings = 30 + 2 * training + (5 + 3 * training) * base
    return pd.DataFrame({"earnings_k": np.round(earnings, 3), "training": training})


def _collinear(rng: np.random.Generator) -> pd.DataFrame:
    n = 200
    price = rng.normal(10, 1, n)
    price_with_tax = price * 1.08 + rng.normal(0, 0.02, n)
    promo = rng.binomial(1, 0.3, n)
    demand = 100 - 2.0 * price - 1.5 * price_with_tax + 5 * promo + rng.normal(0, 3, n)
    return pd.DataFrame({"demand": np.round(demand, 3), "price": np.round(price, 3),
                         "price_with_tax": np.round(price_with_tax, 3), "promo": promo})


def _dirty(rng: np.random.Generator) -> pd.DataFrame:
    n = 500
    hours = rng.normal(40, 8, n)
    tenure = rng.integers(0, 25, n)
    salary = 30 + 0.5 * hours + 1.2 * tenure + rng.normal(0, 5, n)
    frame = pd.DataFrame({"employee_id": np.arange(1, n + 1), "salary_k": np.round(salary, 2),
                          "weekly_hours": np.round(hours, 1).astype(object), "tenure_years": tenure})
    frame.loc[rng.choice(n, 25, replace=False), "salary_k"] = -99
    frame.loc[rng.choice(n, 10, replace=False), "weekly_hours"] = "n/a"
    duplicates = frame.sample(15, random_state=int(rng.integers(1_000_000)))
    return pd.concat([frame, duplicates], ignore_index=True)


def _survey(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for stratum, (size, share, mean) in {"urban": (8000, 0.2, 60), "rural": (2000, 0.8, 40)}.items():
        sampled = int(1000 * share)
        weight = size / sampled
        for _ in range(sampled):
            rows.append({"stratum": stratum, "weight": round(weight, 4), "spending": round(rng.normal(mean, 8), 2)})
    return pd.DataFrame(rows)


SCENARIOS: dict[str, Scenario] = {s.id: s for s in [
    Scenario("cs_hetero", "Returns to education with heteroskedastic errors", "wage", "education",
             ("ols",), ("diagnostics.breusch_pagan|diagnostics.white|model.white_test", "diagnostics.reset", "diagnostics.vif"),
             ("level wage without log", "conventional standard errors"), 0.08, 0.02, _wage_hetero,
             notes="Estimand is the log-wage semi-elasticity; robust SEs required.", extra={"log_outcome": True}),
    Scenario("cs_ovb", "Education and wages with an ability proxy", "log_wage", "education",
             ("ols",), ("diagnostics.reset|diagnostics.vif",), ("omit test_score",), 0.06, 0.015, _wage_ovb,
             notes="Controlling for test_score removes most ability bias; naive slope is about 0.10."),
    Scenario("iv_valid", "Returns to education with a college-proximity instrument", "log_wage", "education",
             ("iv_2sls", "iv.gmm"), ("iv.weak_instruments",), ("OLS as causal", "mother_educ as instrument"),
             0.10, 0.03, _iv(1.2), notes="near_college is valid; mother_educ violates exclusion."),
    Scenario("iv_weak", "Returns to education with a weak instrument", "log_wage", "education",
             ("iv_2sls", "iv.gmm"), ("iv.weak_instruments",), ("claiming a precise IV estimate",),
             0.10, 0.25, _iv(0.08), notes="First stage is weak; the right answer flags it and avoids strong claims."),
    Scenario("panel_fe", "Training and productivity in a firm panel", "productivity", "training",
             ("panel_ols",), (), ("pooled OLS",), 0.5, 0.06, _panel_fe,
             notes="Firm effects correlate with training; cluster by firm."),
    Scenario("did_2x2", "Minimum wage and employment, two-period DID", "employment", None,
             ("did",), (), ("post-only comparison",), 2.0, 0.4, _did_2x2),
    Scenario("did_staggered", "Staggered policy adoption with dynamic effects", "outcome", None,
             ("cs_did", "sa_did", "dcdh"), (), ("TWFE as the headline estimate",), _did_staggered_truth(), 0.45,
             _did_staggered, notes="Heterogeneous dynamic effects bias TWFE."),
    Scenario("ts_spurious", "Advertising and sales indices (random walks)", "sales_index", "ad_spend_index",
             ("time_series",), ("time_series.adf|time_series.kpss", "time_series.cointegration"),
             ("levels regression as evidence",), 0.0, None, _spurious_ts,
             notes="No relation; levels OLS is spurious. Truth is 'no evidence of a relationship'."),
    Scenario("ts_cointegrated", "Consumption and income (cointegrated)", "consumption", "income",
             ("time_series", "ols"), ("time_series.adf", "time_series.cointegration"), (), 1.5, 0.08, _cointegrated_ts),
    Scenario("ts_garch", "Volatility clustering in daily returns", "return_pct", None,
             ("arma_garch",), ("time_series.acf",), ("constant-variance model",), 0.98, 0.03, _garch_returns,
             notes="Truth is volatility persistence alpha + beta = 0.98."),
    Scenario("count_overdispersed", "Program effect on clinic visits", "visits", "program",
             ("negative_binomial", "glm:negative_binomial", "poisson", "glm:poisson"), (), ("Poisson with model-based SEs",),
             float(np.log(1.4)), 0.12, _overdispersed, notes="Truth on the log scale (IRR 1.4); overdispersion 1.5."),
    Scenario("binary_logit", "Income and home ownership", "owns_home", "income_k",
             ("logit", "probit", "glm:binomial"), ("postestimation.margins",), ("linear probability as the only model",),
             0.06, 0.015, _binary, notes="Truth is the logit coefficient; marginal effects expected."),
    Scenario("cluster_rct", "Classroom-randomized tutoring", "score", "tutoring",
             ("ols", "linear_mixed_effects"), (), ("student-level SEs",), 3.0, 1.5, _cluster_experiment,
             notes="Treatment assigned by classroom (30 clusters); cluster SEs or a multilevel model."),
    Scenario("lmm_repeated", "Treatment and symptom trajectories", "symptom_score", None,
             ("linear_mixed_effects",), (), ("pooled OLS ignoring repeated measures",), -1.2, 0.15, _repeated,
             notes="Estimand is the arm-by-visit interaction."),
    Scenario("missing_mar", "Slope of y on x with outcome-dependent missingness", "y", "x",
             ("ols",), ("missingness.profile|statistical.explore", "imputation.mice"), ("silent listwise deletion",),
             0.7, 0.08, _missing_mar),
    Scenario("leverage", "Rent and density with high-leverage cities", "rent", "density",
             ("ols",), ("diagnostics.influence",), ("reporting the full-sample slope without influence checks",),
             1.0, 0.25, _leverage, notes="Three high-leverage points flatten the slope."),
    Scenario("survival", "Drug and time to relapse", "months", "drug",
             ("survival_cox",), ("survival.kaplan_meier", "survival.log_rank"), ("OLS on duration",),
             float(np.log(0.6)), 0.15, _survival, notes="Truth is the log hazard ratio (HR 0.6)."),
    Scenario("quantile", "Training effects across the earnings distribution", "earnings_k", "training",
             ("quantile_regression",), (), ("mean effect only",), 2.0, 0.6, _quantile,
             notes="Mean effect 2; quantile effects 2 + 3 * z_tau."),
    Scenario("collinear", "Price and demand with near-duplicate prices", "demand", None,
             ("ols",), ("diagnostics.vif", "postestimation.wald|postestimation.lincom|model.joint_f_test"), ("interpreting each price separately",),
             -3.62, 0.6, _collinear, notes="Only the combined price effect (about -2 - 1.5*1.08) is identified."),
    Scenario("dirty_data", "Salary, hours and tenure in a messy HR extract", "salary_k", "tenure_years",
             ("ols",), ("data.dedupe", "data.recode|data.fill_missing|data.subset"), ("treating -99 as a salary",),
             1.2, 0.15, _dirty),
    Scenario("survey_mean", "Average household spending from a stratified sample", "spending", None,
             (), (), ("unweighted mean",), 56.0, 1.5, _survey, notes="Population mean = 0.8*60 + 0.2*40."),
]}
