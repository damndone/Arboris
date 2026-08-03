# Retrospective — v1-8-6-statistics-toolbox

## Goal

# v1.8.6 S2/S9/S10 Statistics Toolbox Objective  将独立统计工具接入正常 Run 的 evidence packet，并完成回归表、Table 1、变量/值标签的 用户消费端。  ## 必须完成  - \`anova_posthoc\`、Cohen's d、eta/omega squared、Levene/Bartlett/Shapiro 等由正常数据形状   触发并进入 \`workbench.statistics.evidence-packet\` v1。 - one-sample/paired/Wilcoxon 只有在存在显式参考均值/配对语义时触发；缺语义 fail-closed，   不能按列顺序猜配对。 - Table/Report/Agent 消费 assumptions、warnings、effect sizes、校正范围和 CI（适用时）。 - 多模型回归表、显著性标记、Table 1、变量/值标签贯通输出。  ## 可证伪验收  - 含多分类分组的普通真实 Run 的 statistical_tests artifact 出现 \`anova_posthoc\` 与   \`cohens_d\`；后端非自身引用数从 0 变为至少 1。 - 新 packet 可被 Table/Report/Agent 读到精确值；旧八类检验与 FDR/golden 不变。 - 标签从用户声明或支持的导入格式进入表格、报告和图形轴；不支持的导入标签能力明确降级。

## Final status

STARTED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `3f8e6fe8-6fac-4397-ac21-8f0652499c4e` | 2026-08-03T10:17:35.668Z | STATE_CHANGE/line_started | incident=`73549ab1-4640-4b93-abc6-d66800a38ed8` | lesson_key=`frozen-context-before-start` | event_sha256=`ae2a61bfc8249c13b5858f2d71deafb624dc1b32b0cc3eae3e5560f07788baaf`
