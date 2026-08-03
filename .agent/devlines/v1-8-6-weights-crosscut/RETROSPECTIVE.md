# Retrospective — v1-8-6-weights-crosscut

## Goal

# v1.8.6 S3 Weights Cross-cut Objective  在 S0 contract 基础上，把 sampling/analysis/frequency 三种权重语义贯通 API、service、 workflow contract、OLS/预测协议和可选 UI 字段；不支持的模型族必须拒绝。  ## 必须完成  1. API 请求、service、stage、typed packet 均保留三种权重字段，不互相替代。 2. \`frequency_weight\` 与 \`analysis_weight\` 接入 OLS；\`sampling_weight\` 在分层/PSU 语义未    完整实现前 fail-closed。 3. strata/PSU 复用既有 cluster 通道；模型族通过 \`allows_weights\` 声明准入。 4. 预测路径继续保留正 frequency weight 的 sample_weight 语义，并从真实 API 可达。  ## 可证伪验收  - HTTP/API 真实 Run 传入 frequency weight 后，prediction/OLS packet 记录列名和 executed 状态，   且结果与不加权结果不同。 - 全 1 frequency weight 与不传权重逐位一致。 - 未声明权重的模型族返回稳定错误码且不写结果 artifact。 - sampling_weight 的拒绝路径和下一步说明可见；UI 不伪装为已支持。

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

- #1: `31114f32-b8e5-4773-bd6c-af507c4f0717` | 2026-08-03T09:59:41.602Z | STATE_CHANGE/line_started | incident=`377487d4-5834-4a1a-afef-d99555503047` | lesson_key=`frozen-context-before-start` | event_sha256=`a67cf72c894957bfa8cae49fe383c1ebe6d76e2b7f6f069184536e8548048655`
