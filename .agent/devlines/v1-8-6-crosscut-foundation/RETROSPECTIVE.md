# Retrospective — v1-8-6-crosscut-foundation

## Goal

# v1.8.6 S0 Cross-cutting Expansion Objective  基于已完成的 predictive-research foundation，先完成可追加的估计器注册面、模型族契约声明、 SampleSpec identity 接线和 legacy prediction 显式化。不得改变既有无权重模型数值。  ## 必须完成  1. 把 \`CORE_PACK\` 的注册与 handler/model-params 构造解耦；新增模型族只追加注册项。 2. 为 \`ModelFamilyContract\` 增加 \`allows_weights\` 与 \`supported_split_kinds\`，未声明能力    在拟合前 fail-closed。 3. 把 \`SampleSpecV1.content_hash()\` 接入 run identity、Graph identity 和缓存失效判定；    FeatureRecipe 结果 identity 不包含 SplitPlan，Evaluation/Prediction identity 必须包含。 4. 旧 \`run_prediction_model\` 明确标为历史重放 helper，显式声明 shuffle/cross-validation    语义，不再成为新 run 的隐式入口。  ## 可证伪验收  - 既有 golden 23 逐位 0-drift。 - 新模型族只需追加 registry entry 的结构测试通过。 - 未声明权重/split 的模型族稳定拒绝且不产生结果 artifact。 - 同一 SampleSpec 重复 identity 相同；改变 SplitPlan 参数产生新的评估 identity；改变无关   字段不会错误失效上游变换缓存。 - 旧 helper 的历史重放测试通过，新 run 路径没有调用它。

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

- #1: `16ab850c-cbb4-46e1-a792-f5dab3461de5` | 2026-08-03T09:39:14.231Z | STATE_CHANGE/line_started | incident=`70375217-7841-4718-9216-3583ff381868` | lesson_key=`frozen-context-before-start` | event_sha256=`a6399d4e8a90643dcb3b2c80b998e46c5c3ff48c91e86d6042712bd81b0c64a4`
