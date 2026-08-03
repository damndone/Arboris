# Retrospective — v1-8-6-model-families

## Goal

# v1.8.6 S6/S7/S8 Model Families Objective  在 S0 可追加 registry 上增加 ordinal/nominal y_type、有序/多项 logit、生存分析和分位数 回归；每族独立契约、pack、诊断和 evidence，不改变既有三种 y_type。  ## 可证伪验收  - ordinal/nominal 真实 Run 分别产出预测概率、优势比/相对风险比、边际效应；有序模型有平行线诊断。 - Kaplan–Meier、log-rank、Cox 与 Schoenfeld 诊断使用独立 survival contract，risk set/censoring   证据可追溯。 - QuantReg 支持多个 quantile、区间/bootstrap 和跨 quantile 比较。 - 既有 golden 23 逐位 0-drift；Stata/R oracle 验证等级如实记录，不能以内部测试冒充外部一致。 - Graph/Report/Table/Agent 读取新增 packet 的精确数值，不只显示 artifact metadata。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 1/4 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-03T11:14:39.000Z `model_family_contract_red`; cause_status: `known`; cause: The new v1.8.6 contract tests correctly failed because the four model families were not yet admitted and model_options was not in the model.genesis step vocabulary.; resolution: `resolved`; lesson: For a new model family, lock the family-owned option vocabulary and model_params projection before exposing Agent admission.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `model-family-contract-before-admission`: occurrences=1; cause_status: `known`; root cause: The new v1.8.6 contract tests correctly failed because the four model families were not yet admitted and model_options was not in the model.genesis step vocabulary.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `model-family-contract-before-admission`: line experience occurrence(s)=1

## Future guidance

- For a new model family, lock the family-owned option vocabulary and model_params projection before exposing Agent admission.

## Event index

- #1: `4acb0418-e887-4f33-ac81-193940e684fb` | 2026-08-03T11:03:44.045Z | STATE_CHANGE/line_started | incident=`ddbbd924-be14-4660-ba75-bfcbecda7bdd` | lesson_key=`frozen-context-before-start` | event_sha256=`37f836c586ac50192fb3bea6bbb459d6abc32ef233aa6c311569b53377ad205f`
- #2: `916473c6-d28b-424d-baee-e04f46c874f3` | 2026-08-03T11:14:18.367Z | STATE_CHANGE/context_rescope_required | incident=`ceea60e7-371e-45db-9b61-b7de8c354541` | lesson_key=`context-pack-rescope` | event_sha256=`e7b879fec2b99bc87a62a80003cacc3f1884e904181d84676ec05c4575a2a597`
- #3: `14628979-7de9-4245-b4e0-361680a98e56` | 2026-08-03T11:14:18.370Z | STATE_CHANGE/context_rescoped | incident=`3ed28bdb-bab2-4769-92e4-8463e8e8ee51` | lesson_key=`context-pack-rescope` | event_sha256=`302e6dbbce902dd2779b901e067e6f6b919f7a6e71ddbd7ed3085d2837ba3318`
- #4: `2f4169a6-6dbe-4d9a-8a0d-9bc0b8a8e8b1` | 2026-08-03T11:14:39.000Z | FAILURE/model_family_contract_red | incident=`c63a4c58-f31c-43f5-9ae6-0ef0c0e48c43` | lesson_key=`model-family-contract-before-admission` | event_sha256=`a3456f6eae47bac67cf7e5811562d56730a86f6076ed9b31e61498055db4d43d`
