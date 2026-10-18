"""Evaluation tasks: each scenario asked three ways.

* ``open`` (Chinese): the research question only, as a researcher would ask it.
* ``specific`` (English): the question plus what the deliverable must contain.
* ``goal`` (Chinese): the end product the person needs (a paper table, a memo),
  so the Agent has to plan backwards from it.

None of the prompts names the right method; choosing it is part of the task.
The held-out set lives in ``heldout.py`` and is not run during development.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dgps import SCENARIOS, Scenario


@dataclass(frozen=True)
class Task:
    id: str
    scenario: Scenario
    variant: str
    language: str
    prompt: str
    seed: int
    #: Naive first model the "person" ran when importing the data (v1.9.0 needs a run to talk to).
    seed_model: dict[str, str]


QUESTIONS: dict[str, dict[str, str]] = {
    "cs_hetero": {
        "open": "这是一份工人调查数据。我想知道多受一年教育，工资大概会高多少？请帮我完成一项完整、经得起审稿的分析。",
        "specific": "Using this worker survey, estimate the return to an extra year of education. I need the estimate with a correctly computed confidence interval, the diagnostics you relied on, at least one robustness check, and a short written report.",
        "goal": "我要在论文里放一张主表：教育回报率，加上必要的控制变量和稳健性列。请把这张表需要的分析都做完，并写一段结果说明。",
    },
    "cs_ovb": {
        "open": "数据里有教育年限、工作经验和一个能力测验分数。教育对（对数）工资的作用到底有多大？请完整分析。",
        "specific": "Estimate how much an extra year of schooling raises log wages. Be explicit about which controls you include and why, check how sensitive the answer is to that choice, and write it up.",
        "goal": "审稿人质疑我们的教育回报估计有能力偏误。请做出能回应这个质疑的分析和一段回复审稿人的文字。",
    },
    "iv_valid": {
        "open": "教育可能是内生的。数据里有'是否住在大学附近'和'母亲受教育年限'。请估计教育对对数工资的因果效应，做完整分析。",
        "specific": "Estimate the causal return to education on log wages. Education is likely endogenous; the data include near_college and mother_educ as candidate instruments. Justify your identification strategy, report diagnostics, and write up the result.",
        "goal": "我要写一节'识别策略与主要结果'，需要工具变量估计、第一阶段、与 OLS 的对比和稳健性。请把这些都做出来并写成文字。",
    },
    "iv_weak": {
        "open": "我想用'是否住在大学附近'作为教育的工具变量，估计教育回报。请做完整分析，告诉我结论有多可靠。",
        "specific": "Use near_college as an instrument for education to estimate the return to schooling on log wages. Tell me how much weight the estimate can bear and why, with the relevant diagnostics.",
        "goal": "合作者想在摘要里写'工具变量估计显示教育回报为 X%'。请做分析并告诉我这句话能不能这样写。",
    },
    "panel_fe": {
        "open": "这是 200 家企业 10 年的面板数据。培训投入对生产率有多大影响？请完整分析。",
        "specific": "Estimate the effect of training on productivity in this firm panel. Address unobserved firm differences, use appropriate standard errors, and report robustness.",
        "goal": "我需要一张面板回归表（不同设定并列）和一段解释，用于给管理层的备忘录。请完成。",
    },
    "did_2x2": {
        "open": "部分门店所在地区在第二期提高了最低工资。这项政策对门店雇佣人数有什么影响？请完整分析。",
        "specific": "Some stores were exposed to a minimum-wage increase in period 1 (treated = 1). Estimate the policy's effect on employment, state the identifying assumption, check what you can, and write it up.",
        "goal": "请给我一个可以直接放进政策简报的结论：效应多大、有多可靠、依据什么假设。分析过程要完整。",
    },
    "did_staggered": {
        "open": "各县在不同年份陆续实施了一项政策（first_treat 是开始年份，0 表示从未实施）。政策对 outcome 的平均效应是多少？请完整分析。",
        "specific": "Counties adopted a policy in different years (first_treat; 0 = never). Estimate the average effect of the policy on the outcome and how it evolves over time since adoption. Use a design that is valid here and explain why.",
        "goal": "我要一张事件研究图和一个总体效应估计，放进论文正文。请把分析做完并说明方法选择。",
    },
    "ts_spurious": {
        "open": "这是 240 个月的广告投入指数和销售指数。广告是否推动了销售？请完整分析。",
        "specific": "Does advertising spend drive sales in these monthly indices? Analyse the time-series properties before drawing any conclusion and write up what the data can and cannot say.",
        "goal": "市场部想在汇报里说'广告每增加 1 个单位，销售增加 b'。请分析这句话是否成立，并给出可以放进汇报的结论。",
    },
    "ts_cointegrated": {
        "open": "这是季度消费和收入数据。两者之间有没有长期稳定的关系？边际消费倾向大概是多少？请完整分析。",
        "specific": "Is there a long-run relationship between consumption and income in this quarterly series? Estimate it with methods appropriate for the series' properties and explain the short-run dynamics.",
        "goal": "我在写宏观课程作业，需要'长期关系检验与估计'一节。请完成分析和文字。",
    },
    "ts_garch": {
        "open": "这是 1500 个交易日的收益率。收益率的波动有没有聚集现象？冲击的影响会持续多久？请完整分析。",
        "specific": "Characterise the volatility of these daily returns: is there volatility clustering, how persistent are shocks, and which model describes it? Include diagnostics.",
        "goal": "我要给风控团队写一页波动率模型的说明，需要模型、参数、持续性和诊断。请完成。",
    },
    "count_overdispersed": {
        "open": "参加项目的人去诊所的次数是否更多？visits 是就诊次数。请完整分析。",
        "specific": "Estimate the effect of the program on the number of clinic visits. Choose a model suited to the outcome, check its assumptions, and report the effect in an interpretable scale.",
        "goal": "我需要在报告里写'项目使就诊次数增加了 X%'。请把支撑这句话的分析做完。",
    },
    "binary_logit": {
        "open": "收入越高的人越可能拥有住房吗？owns_home 是 0/1。请完整分析。",
        "specific": "How does income relate to the probability of owning a home? Use a model suited to a binary outcome, report effects on the probability scale, and check robustness.",
        "goal": "我要一张表和一段话说明收入每增加 1 万元，拥有住房的概率变化多少。请完成。",
    },
    "cluster_rct": {
        "open": "辅导项目是按班级随机分配的（tutoring）。辅导对学生成绩有多大影响？请完整分析。",
        "specific": "Tutoring was randomised at the classroom level. Estimate its effect on test scores with inference that matches the design, and write up the result.",
        "goal": "请写出可以放进实验报告的'主要结果'一节，包括估计、推断方法和稳健性。",
    },
    "lmm_repeated": {
        "open": "这是病人在 5 次随访中的症状评分，分治疗组和对照组。治疗是否让症状下降得更快？请完整分析。",
        "specific": "Patients were followed for five visits in two arms. Does treatment change the trajectory of symptom scores? Account for repeated measures and report the effect with uncertainty.",
        "goal": "我需要一份给临床合作者的统计分析结果：模型、主要效应和诊断。请完成。",
    },
    "missing_mar": {
        "open": "我想知道 x 对 y 的影响，但 x 有不少缺失。请完整分析。",
        "specific": "Estimate the effect of x on y controlling for z. x has missing values; examine the missingness, handle it appropriately, and show how much the choice matters.",
        "goal": "审稿人问'缺失数据是怎么处理的，会不会影响结论'。请做分析并写一段回复。",
    },
    "leverage": {
        "open": "人口密度和租金是什么关系？请完整分析。",
        "specific": "Estimate how rent relates to population density across these cities. Check whether a few observations drive the result and report what is robust.",
        "goal": "我要在城市经济学课堂上展示这个关系，需要一个可靠的估计和一段解释。请完成。",
    },
    "survival": {
        "open": "新药是否延长了复发前的时间？months 是随访月数，event=1 表示复发。请完整分析。",
        "specific": "Does the drug delay relapse? months is follow-up time and event marks relapse (otherwise censored). Use appropriate methods, report the effect with uncertainty, and check assumptions.",
        "goal": "请写出临床试验报告里的生存分析结果：生存曲线比较、效应量和假设检验。",
    },
    "quantile": {
        "open": "职业培训对收入的影响，在低收入和高收入的人身上一样吗？请完整分析。",
        "specific": "Is the effect of training on earnings the same across the earnings distribution? Estimate where it differs and how much, and compare with the average effect.",
        "goal": "我要一张图或表展示培训效应在收入分布不同位置的差别，以及一段解释。请完成。",
    },
    "collinear": {
        "open": "价格对需求量有多大影响？数据里有价格和含税价格两个变量，还有促销。请完整分析。",
        "specific": "Estimate how price affects demand. The data contain price and price_with_tax plus a promotion dummy. Report what the data can identify and how you handled it.",
        "goal": "我需要给定价团队一个价格弹性方向的结论和数字。请完成分析并写成要点。",
    },
    "dirty_data": {
        "open": "这是从人事系统导出的数据，有点乱。工龄对薪水有多大影响？请完整分析。",
        "specific": "This HR extract is messy. Clean what needs cleaning (document every step), then estimate how tenure relates to salary controlling for weekly hours, and write it up.",
        "goal": "请把这份数据整理成可以分析的状态，并给出工龄与薪水关系的结论，所有清理步骤都要能复现。",
    },
    "survey_mean": {
        "open": "这是一份分层抽样的家庭调查，weight 是抽样权重。总体的平均家庭支出是多少？请完整分析。",
        "specific": "Estimate the population mean of household spending from this stratified sample, with a correct standard error, and explain how the design enters the estimate.",
        "goal": "统计局要一个总体平均支出的估计和置信区间。请完成并说明方法。",
    },
}

VARIANT_LANGUAGE = {"open": "zh", "specific": "en", "goal": "zh"}


def _seed_model(scenario: Scenario) -> dict[str, str]:
    frame = scenario.frame(1)
    numeric = [c for c in frame.columns if c != scenario.outcome and str(frame[c].dtype) not in {"object", "str"}]
    others = [c for c in frame.columns if c != scenario.outcome]
    x = scenario.main_term if scenario.main_term in numeric else (numeric[0] if numeric else others[0])
    return {"mode": "auto", "model_type": "ols", "covariance": "unadjusted", "y": scenario.outcome, "x": x}


def dev_tasks() -> list[Task]:
    tasks = []
    for scenario_id, prompts in QUESTIONS.items():
        scenario = SCENARIOS[scenario_id]
        for index, (variant, prompt) in enumerate(prompts.items()):
            tasks.append(Task(
                id=f"{scenario_id}.{variant}",
                scenario=scenario,
                variant=variant,
                language=VARIANT_LANGUAGE[variant],
                prompt=prompt,
                seed=1000 + 7 * index,
                seed_model=_seed_model(scenario),
            ))
    return tasks
