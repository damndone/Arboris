# Retrospective — v1-8-6-consumer-entries

## Goal

# v1.8.6 Consumer Entries Objective  在已验证的 v1.8.6 模型族提交 \`b2c8018\` 上，补齐统计消费链路的两个用户入口边界：  1. 普通 \`Run\` UI 能配置四个 v1.8.6 模型族的 \`model_options\`，并将其送入现有 API； 2. 用户可通过 POST \`/runs\` 的声明字段提供变量/值标签，标签持久化并贯通 Table 1、报告、    XLSX 与图形轴；未声明时继续使用列名 fallback，并显式记录 fallback 来源。  不改变既有估计器数值、统计检验算法、FeatureRecipe 语义或发布状态。  ## 可证伪验收  - 普通 Run UI 选择 ordinal/multinomial/survival/quantile 时显示对应配置，提交的   \`FormData\` 含 \`model_options\`；生存模型缺 event 列在服务端结构化拒绝。 - \`/runs\` 接收严格 JSON \`labels\`，错误结构拒绝；成功运行的 \`run_inputs\`、Table 1、   HTML/XLSX 报告和至少一张图形的轴/标题读取同一声明标签。 - 未声明标签的报告仍可生成，且 \`label_source=column_name_fallback\`。 - 既有前端 API/Run/报告/回归测试、编译和 \`git diff --check\` 通过；Formal FMS verify 通过。  ## 边界  - 不解析 Stata/R 外部标签文件；本线只交付显式 JSON 声明。 - 不把标签用于模型列名、Graph identity 或数值计算。 - 不 push、PR、merge、tag 或发布。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 1/6 (16.7%; 16.7 per 100 events)
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

- #6 2026-08-03T11:37:48.000Z `consumer_entry_contract_red`; cause_status: `known`; cause: The new labels acceptance tests correctly failed because run_workflow had no labels transport, reports did not expose label source/value mappings, and figure axes did not yet use declared labels.; resolution: `resolved`; lesson: For labels, test the same declaration through transport, report/table export, and visualization metadata before claiming user reachability.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `labels-consumer-boundary-before-claim`: occurrences=1; cause_status: `known`; root cause: The new labels acceptance tests correctly failed because run_workflow had no labels transport, reports did not expose label source/value mappings, and figure axes did not yet use declared labels.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `labels-consumer-boundary-before-claim`: line experience occurrence(s)=1

## Future guidance

- For labels, test the same declaration through transport, report/table export, and visualization metadata before claiming user reachability.

## Event index

- #1: `2a695580-e41a-4368-8936-13d7433bf0aa` | 2026-08-03T11:28:27.642Z | STATE_CHANGE/line_started | incident=`c047e391-adb9-4580-896a-f371e36803d3` | lesson_key=`frozen-context-before-start` | event_sha256=`19c7c0fbc2164bb38a03f80302ac57feafe1cd29ab11dc78a83e9fa88de04308`
- #2: `f834330b-a3ca-4358-986d-c2396694d849` | 2026-08-03T11:32:30.660Z | STATE_CHANGE/context_rescope_required | incident=`6e991f25-ec42-4242-a02f-5baa2d69a509` | lesson_key=`context-pack-rescope` | event_sha256=`22fd287250ea24dd59d1862ea97c3794bef12d60e1daec6935ec7fcb0da7df82`
- #3: `7feca425-e06a-466d-9dae-8019e9b5ecba` | 2026-08-03T11:32:30.662Z | STATE_CHANGE/context_rescoped | incident=`f552dcc8-c5ee-44b5-90c2-c6653a68ec87` | lesson_key=`context-pack-rescope` | event_sha256=`d71f7070125b30212da8da7a28070b580684e65923607702ca518aaeacfc827d`
- #4: `33ec884f-8b31-4e11-90b7-71e7c40a8545` | 2026-08-03T11:34:11.770Z | STATE_CHANGE/context_rescope_required | incident=`393083f3-a49c-4ff7-8fba-f5c8432b3973` | lesson_key=`context-pack-rescope` | event_sha256=`6b3d3ca531817690635a56a3dd31d6f45146942f77fcf06f32dada3cc1d4816f`
- #5: `febbea38-44ef-4508-b52b-6175f7aa9f15` | 2026-08-03T11:34:11.773Z | STATE_CHANGE/context_rescoped | incident=`ff3fe456-d9c0-47cf-a913-5dff75a21b87` | lesson_key=`context-pack-rescope` | event_sha256=`27afa8a925f210111e0f5786b98417704191a8e96c1b2c06d8a9d596d8eab625`
- #6: `0c38a2bd-70c2-45ed-8d82-87f35acbca7d` | 2026-08-03T11:37:48.000Z | FAILURE/consumer_entry_contract_red | incident=`7bbf5591-5fa1-4f7b-a7cb-64b14a2c4d75` | lesson_key=`labels-consumer-boundary-before-claim` | event_sha256=`9f1dbdc4e8bb326e5a39f3450ab84107effe73f6820082d7166051619fb29682`
