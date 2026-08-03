# Retrospective — v1-8-6-graph-persistence

## Goal

# v1.8.6 Graph Identity Persistence Objective  把 predictive-research 的分层 SampleSpec identity 投影到 Graph 节点，并让 GraphStore 读回后仍保留 \`node_hash\`。旧 graph.json 没有该字段时必须继续可读， 以保持 v1.8.5 运行的兼容性；新 prediction run 的 dataset/split/model/evaluation 链必须可从 Graph 节点取到非空稳定身份。  ## 可证伪验收  - GraphRecorder 写入的 node_hash 经 GraphStore 写入/读回保持不变。 - 没有 node_hash 的旧 JSON 仍读回为 \`None\`，不改变旧节点的其他字段。 - predictive-research Graph chain 的每个节点都有非空稳定 node_hash。 - 相关回归测试与既有 GraphStore/GraphRecorder 测试通过。

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

- #1: `c5f3330d-8b7a-4134-8560-03d04a01e421` | 2026-08-03T09:55:29.247Z | STATE_CHANGE/line_started | incident=`1ef58966-8d0f-4992-93ed-9e094b2ba507` | lesson_key=`frozen-context-before-start` | event_sha256=`8d3668ae05318c4111786185edd0efbce01d6d9904c6c6f1d9d09507c8aba9ce`
