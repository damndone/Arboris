# P7 经典重复测量与混合设计 ANOVA 设计

## 目标

补齐经典 repeated-measures ANOVA 与一 between-factor mixed ANOVA。现有
`linear_mixed_effects` recipe 不被改写或重新解释为 RM-ANOVA；本模块是独立、可验证、
可在未来被 Agent 组合的数值内核。

## 输入边界

- 只接受长表：一行是一个 subject × within-factor cell。
- `response_column`、`subject_column`、至少一个 `within_factor_columns` 必须显式声明。
- mixed 设计必须显式声明恰好一个 `between_factor_column`；同一 subject 的 between
  标签不一致直接拒绝。
- 每个 subject × within cell 必须恰好一行；重复行不自动取均值。
- 所有 subject 必须拥有同一组 within cells；缺失 cell、非有限 response、空因子水平
  都是结构化拒绝。
- v1 不接受任意公式字符串，不猜测测量顺序，不自动排序时间标签。

## 计算与输出

- repeated-only 通过 `statsmodels.AnovaRM`，mixed 通过明确的平衡设计/误差层投影，
  不把普通 OLS residual 当成 subject×within 误差。
- 输出每个效应的 SS、df、MS、F、p、误差层、样本/subject/cell 计数和设计摘要。
- 对需要球形性的 within 效应输出 Mauchly 证据、epsilon、修正后的 df/p；修正方法
  必须是 `none`、`greenhouse_geisser` 或 `huynh_feldt` 之一，不能静默选择。
- 所有数组、标识符和数值经过 JSON-safe bounded projection；不回传原始行。

## Oracle 与安全

- repeated-only 与 `statsmodels.AnovaRM` 逐项对照。
- R base `aov(... + Error(subject/within))` 作为独立 Oracle，覆盖 repeated 与 mixed。
- 非平衡、奇异误差层、非有限修正量 fail closed；不使用伪逆或隐式降级。
- 未来 Agent 只能提交结构化列名和策略，不能提交 formula/eval 文本。

## 非目标

不接 Agent registry、orchestrator、frontend，不修改 LMM、现有 ANOVA pack 或自动
`statistical_tests` stage；随机效应模型另属 LMM。
