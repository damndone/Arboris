# Retrospective — v1-8-6-graph-persistence

## Goal

# v1.8.6 Graph Identity Persistence Objective  把 predictive-research 的分层 SampleSpec identity 投影到 Graph 节点，并让 GraphStore 读回后仍保留 \`node_hash\`。旧 graph.json 没有该字段时必须继续可读， 以保持 v1.8.5 运行的兼容性；新 prediction run 的 dataset/split/model/evaluation 链必须可从 Graph 节点取到非空稳定身份。  ## 可证伪验收  - GraphRecorder 写入的 node_hash 经 GraphStore 写入/读回保持不变。 - 没有 node_hash 的旧 JSON 仍读回为 \`None\`，不改变旧节点的其他字段。 - predictive-research Graph chain 的每个节点都有非空稳定 node_hash。 - 相关回归测试与既有 GraphStore/GraphRecorder 测试通过。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 1/6 (16.7%; 16.7 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=120000 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-03T09:56:30.000Z `tdd_red_graph_node_hash_roundtrip`; cause_status: `known`; cause: At the graph-persistence line baseline, GraphRecorder accepts node_hash but GraphStore._node_from_json drops it, so the required persisted identity roundtrip is red.; resolution: `open`; lesson: Run the line-specific acceptance command at the frozen baseline and record the actual persistence failure before editing the serializer boundary.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `graph-persistence-red-before-serializer-change`: occurrences=1; cause_status: `known`; root cause: At the graph-persistence line baseline, GraphRecorder accepts node_hash but GraphStore._node_from_json drops it, so the required persisted identity roundtrip is red.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `graph-persistence-red-before-serializer-change`: line experience occurrence(s)=1

## Future guidance

- Run the line-specific acceptance command at the frozen baseline and record the actual persistence failure before editing the serializer boundary.

## Event index

- #1: `c5f3330d-8b7a-4134-8560-03d04a01e421` | 2026-08-03T09:55:29.247Z | STATE_CHANGE/line_started | incident=`1ef58966-8d0f-4992-93ed-9e094b2ba507` | lesson_key=`frozen-context-before-start` | event_sha256=`8d3668ae05318c4111786185edd0efbce01d6d9904c6c6f1d9d09507c8aba9ce`
- #2: `12345678-9abc-4def-0123-456789abcdef` | 2026-08-03T09:56:30.000Z | FAILURE/tdd_red_graph_node_hash_roundtrip | incident=`23456789-abcd-4ef0-1234-56789abcdef0` | lesson_key=`graph-persistence-red-before-serializer-change` | event_sha256=`1195237d3b337fbd465ddf3ef4b1e6e0c24f74253a462aef74b718ecb2f42df4`
- #3: `23456789-abcd-4ef0-1234-56789abcdef0` | 2026-08-03T09:58:30.000Z | GATE/tdd_green_graph_persistence | incident=`23456789-abcd-4ef0-1234-56789abcdef0` | lesson_key=`graph-identity-persistence-green-boundary` | event_sha256=`f15cf78c0fcaff982c958e5bba96a14e6d676f01425aa79dabe23986b676729a`
- #4: `e3f4a5b6-c7d8-4901-2345-abcdef012361` | 2026-08-03T15:21:08.000Z | GATE/identity_graph_gate_passed | incident=`f4a5b6c7-d8e9-4012-3456-abcdef012362` | lesson_key=`identity-graph-gate-evidence` | event_sha256=`a526464a6a7a7a534388267dd0dcbee9420d5242f3c1ec2eb31a0492bfdba005`
- #5: `521dcf3c-ca77-474f-ac7f-b71a3624dbdf` | 2026-08-03T15:49:28.846Z | STATE_CHANGE/context_rescope_required | incident=`a915c5d4-2499-441d-a9d2-bc715edf6a3d` | lesson_key=`context-pack-rescope` | event_sha256=`4a7c30f8a8e7aa8eee414ca418c58ab5f82c61fc944b41f0dee569c6fca262d8`
- #6: `2705865b-1282-4835-9801-a1b16f4f57f7` | 2026-08-03T15:49:28.850Z | STATE_CHANGE/context_rescoped | incident=`7a14c5db-399d-4343-850b-3eba453658e3` | lesson_key=`context-pack-rescope` | event_sha256=`6acf903ff4f622aa5e6542d7235eb58e246b5a16dbf296ab7013644d85868dc7`
