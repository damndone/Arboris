"""Held-out evaluation tasks: families and designs the dev set does not contain.

Written on 2026-10-17 before any v1.9.1 implementation and run exactly once,
at the final evaluation (objective M5). Do not tune prompts, tools or
playbooks against these tasks; changing this file after the baseline needs a
devline GAP event.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .dgps import Scenario
from .tasks import Task, VARIANT_LANGUAGE, _seed_model


def _matching(rng: np.random.Generator) -> pd.DataFrame:
    n = 2000
    age = rng.integers(20, 60, n)
    prior_earn = rng.gamma(4, 5, n)
    married = rng.binomial(1, 0.5, n)
    p = 1 / (1 + np.exp(-(-2 + 0.03 * (40 - age) - 0.05 * (prior_earn - 20) + 0.4 * married)))
    program = rng.binomial(1, p)
    earn = 10 + 0.6 * prior_earn + 0.1 * age + 2 * married + 3.0 * program + rng.normal(0, 4, n)
    return pd.DataFrame({"earnings": np.round(earn, 3), "program": program, "age": age,
                         "prior_earnings": np.round(prior_earn, 3), "married": married})


def _synthetic(rng: np.random.Generator) -> pd.DataFrame:
    regions, years = 20, 30
    factors = rng.normal(0, 1, (years, 2)).cumsum(axis=0)
    loadings = rng.uniform(0.5, 1.5, (regions, 2))
    rows = []
    for i in range(regions):
        for t in range(years):
            y = 50 + loadings[i] @ factors[t] + rng.normal(0, 0.5)
            if i == 0 and t >= 20:
                y -= 4.0
            rows.append({"region": f"R{i:02d}", "year": 1990 + t, "gdp_index": round(float(y), 4),
                         "policy_region": int(i == 0)})
    return pd.DataFrame(rows)


def _meta(rng: np.random.Generator) -> pd.DataFrame:
    k = 25
    se = rng.uniform(0.05, 0.3, k)
    true = 0.3 + rng.normal(0, 0.1, k)
    return pd.DataFrame({"study": [f"S{i:02d}" for i in range(k)], "effect": np.round(true + rng.normal(0, se), 4),
                         "se": np.round(se, 4), "year": rng.integers(1995, 2024, k)})


def _ordinal(rng: np.random.Generator) -> pd.DataFrame:
    n = 1500
    wait = rng.uniform(0, 60, n)
    staff = rng.binomial(1, 0.5, n)
    latent = -0.04 * wait + 0.8 * staff + rng.logistic(0, 1, n)
    cuts = [-2.5, -1.2, 0.0, 1.2]
    rating = 1 + np.searchsorted(cuts, latent)
    return pd.DataFrame({"satisfaction": rating, "wait_minutes": np.round(wait, 1), "new_staff": staff})


def _var(rng: np.random.Generator) -> pd.DataFrame:
    n = 400
    x = np.zeros(n)
    y = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.5 * x[t - 1] + rng.normal()
        y[t] = 0.3 * y[t - 1] + 0.4 * x[t - 1] + rng.normal()
    return pd.DataFrame({"week": np.arange(1, n + 1), "search_volume": np.round(x, 4), "orders": np.round(y, 4)})


def _anova(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for arm, (n, mean, sd) in {"control": (60, 50, 5), "low_dose": (45, 53, 9), "high_dose": (35, 58, 14)}.items():
        rows += [{"arm": arm, "response": round(float(v), 3)} for v in rng.normal(mean, sd, n)]
    return pd.DataFrame(rows)


def _power(rng: np.random.Generator) -> pd.DataFrame:
    n = 80
    group = rng.binomial(1, 0.5, n)
    y = 100 + 4 * group + rng.normal(0, 15, n)
    return pd.DataFrame({"pilot_group": group, "blood_pressure": np.round(y, 2)})


HELDOUT_SCENARIOS: dict[str, Scenario] = {s.id: s for s in [
    Scenario("matching_att", "Job program effect with selection on observables", "earnings", "program",
             ("matching", "ols"), ("matching.balance",), ("raw difference in means",), 3.0, 0.7, _matching),
    Scenario("synthetic_control", "Regional policy and GDP with one treated region", "gdp_index", None,
             ("synthetic_control",), ("synthetic_control.placebo",), ("simple before-after",), -4.0, 1.2, _synthetic),
    Scenario("meta_analysis", "Pooling 25 study effect sizes", "effect", None,
             ("meta",), ("meta.combine",), ("unweighted average",), 0.3, 0.06, _meta,
             notes="Random-effects pooled effect near 0.3 with heterogeneity tau about 0.1."),
    Scenario("ordinal_satisfaction", "Waiting time and satisfaction ratings (1-5)", "satisfaction", "wait_minutes",
             ("ordinal_logit",), (), ("OLS on the rating",), -0.04, 0.01, _ordinal),
    Scenario("var_granger", "Search volume and orders (weekly)", "orders", "search_volume",
             ("time_series",), ("time_series.granger", "time_series.var", "time_series.adf"), ("contemporaneous OLS as causal",),
             0.4, 0.1, _var, notes="Lagged search volume predicts orders with coefficient 0.4."),
    Scenario("anova_unequal", "Three-arm dose response with unequal variances", "response", None,
             ("anova",), ("multiple_comparisons.games_howell",), ("classic ANOVA and Tukey under unequal variances",),
             8.0, 3.0, _anova, notes="High dose minus control is 8."),
    Scenario("power_planning", "Sample size for a confirmatory trial from pilot data", "blood_pressure", "pilot_group",
             ("power_analysis",), ("power_analysis.solve",), ("powering on the noisy pilot estimate alone",),
             None, 0.0, _power, notes="Pilot n=80; a defensible plan states the assumed effect and SD and the resulting n."),
]}

HELDOUT_QUESTIONS: dict[str, dict[str, str]] = {
    "matching_att": {
        "open": "参加职业培训的人收入更高吗？培训不是随机分配的。请完整分析培训对收入的效应。",
        "specific": "Estimate the effect of the job program on earnings for participants. Participation was not random; make the comparison credible, show it worked, and write it up.",
        "goal": "评估报告需要'项目效应'一节：估计值、方法依据和平衡性证据。请完成。",
    },
    "synthetic_control": {
        "open": "R00 地区在 2010 年实施了一项政策。政策对该地区 GDP 指数有什么影响？请完整分析。",
        "specific": "Region R00 adopted a policy in 2010 (policy_region = 1). Estimate the policy's effect on its GDP index using the other regions as comparisons, and assess whether the effect could be chance.",
        "goal": "我要一张'实际 vs 反事实'的对比和一个效应估计，放进政策评估报告。请完成。",
    },
    "meta_analysis": {
        "open": "这是 25 项研究报告的效应量和标准误。综合起来效应有多大？研究之间差异大吗？请完整分析。",
        "specific": "Pool these 25 study estimates (effect, se). Report the combined effect with uncertainty, quantify heterogeneity, and check for small-study effects.",
        "goal": "请写出系统综述里的'定量综合'一节：合并效应、异质性和敏感性分析。",
    },
    "ordinal_satisfaction": {
        "open": "等待时间越长，顾客满意度（1-5 分）越低吗？新员工有没有影响？请完整分析。",
        "specific": "How do waiting time and the new-staff indicator relate to the 1-5 satisfaction rating? Use a model suited to the outcome and report effects people can understand.",
        "goal": "运营部要一个结论：每多等 10 分钟，打 5 分的概率下降多少。请完成分析。",
    },
    "var_granger": {
        "open": "搜索量能不能帮助预测订单量？这是每周数据。请完整分析。",
        "specific": "Does search volume help predict orders in this weekly series? Analyse the dynamics with appropriate time-series methods and report what the evidence supports.",
        "goal": "我要在季度汇报里说明搜索量对订单的领先作用。请把分析和结论做出来。",
    },
    "anova_unequal": {
        "open": "三个剂量组的反应有差异吗？哪几组之间有差异？请完整分析。",
        "specific": "Compare the response across the three arms. Check the assumptions of the comparison you choose, and report which pairs differ with appropriate multiplicity control.",
        "goal": "请写出试验报告里的组间比较结果，包括检验方法和两两比较。",
    },
    "power_planning": {
        "open": "这是一个小规模预实验。如果要做正式试验，每组需要多少人？请完整分析。",
        "specific": "From this pilot (pilot_group, blood_pressure), plan the sample size for a confirmatory two-arm trial with 80% power at alpha 0.05. State every assumption and how sensitive the answer is to it.",
        "goal": "伦理委员会要我们说明样本量是怎么算的。请做分析并写一段说明。",
    },
}


def heldout_tasks() -> list[Task]:
    tasks = []
    for scenario_id, prompts in HELDOUT_QUESTIONS.items():
        scenario = HELDOUT_SCENARIOS[scenario_id]
        for index, (variant, prompt) in enumerate(prompts.items()):
            tasks.append(Task(id=f"heldout.{scenario_id}.{variant}", scenario=scenario, variant=variant,
                              language=VARIANT_LANGUAGE[variant], prompt=prompt, seed=5000 + 11 * index,
                              seed_model=_seed_model(scenario)))
    return tasks
