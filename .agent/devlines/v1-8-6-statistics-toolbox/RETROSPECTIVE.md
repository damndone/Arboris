# Retrospective — v1-8-6-statistics-toolbox

## Goal

# v1.8.6 S2/S9/S10 Statistics Toolbox Objective  将独立统计工具接入正常 Run 的 evidence packet，并完成回归表、Table 1、变量/值标签的 用户消费端。  ## 必须完成  - \`anova_posthoc\`、Cohen's d、eta/omega squared、Levene/Bartlett/Shapiro 等由正常数据形状   触发并进入 \`workbench.statistics.evidence-packet\` v1。 - one-sample/paired/Wilcoxon 只有在存在显式参考均值/配对语义时触发；缺语义 fail-closed，   不能按列顺序猜配对。 - Table/Report/Agent 消费 assumptions、warnings、effect sizes、校正范围和 CI（适用时）。 - 多模型回归表、显著性标记、Table 1、变量/值标签贯通输出。  ## 可证伪验收  - 含多分类分组的普通真实 Run 的 statistical_tests artifact 出现 \`anova_posthoc\` 与   \`cohens_d\`；后端非自身引用数从 0 变为至少 1。 - 新 packet 可被 Table/Report/Agent 读到精确值；旧八类检验与 FDR/golden 不变。 - 标签从用户声明或支持的导入格式进入表格、报告和图形轴；不支持的导入标签能力明确降级。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 3/13 (23.1%; 23.1 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-03T10:32:00.000Z `tdd_red_statistics_user_loop`; cause_status: `known`; cause: The new red tests require a normal statistical loop to emit a schema-validated evidence family and a real Run artifact, but run_statistical_tests only returns the legacy families and the stage writes no evidence packet.; resolution: `open`; lesson: Statistics kernel tests are insufficient; the normal stage and a real Run artifact must be red before wiring the consumer path.
- #3 2026-08-03T10:31:33.000Z `statistics_empty_packet_contract`; cause_status: `known`; cause: The new advanced statistics evidence builder initially called the typed packet constructor for an empty result set, but the constructor correctly rejects empty packets.; resolution: `resolved`; lesson: Keep empty optional evidence families representable without weakening the non-empty typed packet contract.

## All errors

- None recorded.

## All gaps

- #6 2026-08-03T15:00:02.000Z `unowned_v186_statistics_http_test`; cause_status: `known`; cause: The ordinary-Run statistics API evidence test was added after the statistics Context Pack was frozen.; resolution: `open`; lesson: A statistics kernel feature needs a formally owned ordinary-Run HTTP acceptance test before it can count as user-reachable.

## All waste

- None recorded.

## Root causes and solutions

- `empty-optional-evidence-family`: occurrences=1; cause_status: `known`; root cause: The new advanced statistics evidence builder initially called the typed packet constructor for an empty result set, but the constructor correctly rejects empty packets.; solution: `resolved`
- `statistics-http-test-needs-formal-owner`: occurrences=1; cause_status: `known`; root cause: The ordinary-Run statistics API evidence test was added after the statistics Context Pack was frozen.; solution: `open`
- `statistics-red-must-cross-normal-run-boundary`: occurrences=1; cause_status: `known`; root cause: The new red tests require a normal statistical loop to emit a schema-validated evidence family and a real Run artifact, but run_statistical_tests only returns the legacy families and the stage writes no evidence packet.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `empty-optional-evidence-family`: line experience occurrence(s)=1
- `statistics-http-test-needs-formal-owner`: line experience occurrence(s)=1
- `statistics-red-must-cross-normal-run-boundary`: line experience occurrence(s)=1

## Future guidance

- A statistics kernel feature needs a formally owned ordinary-Run HTTP acceptance test before it can count as user-reachable.
- Keep empty optional evidence families representable without weakening the non-empty typed packet contract.
- Statistics kernel tests are insufficient; the normal stage and a real Run artifact must be red before wiring the consumer path.

## Event index

- #1: `3f8e6fe8-6fac-4397-ac21-8f0652499c4e` | 2026-08-03T10:17:35.668Z | STATE_CHANGE/line_started | incident=`73549ab1-4640-4b93-abc6-d66800a38ed8` | lesson_key=`frozen-context-before-start` | event_sha256=`ae2a61bfc8249c13b5858f2d71deafb624dc1b32b0cc3eae3e5560f07788baaf`
- #2: `e6b8d0f2-4a73-5c91-1e27-3f9b5d7a0c84` | 2026-08-03T10:32:00.000Z | FAILURE/tdd_red_statistics_user_loop | incident=`f7c9e1a3-5b84-6d02-2f38-4a0c6e8b1d95` | lesson_key=`statistics-red-must-cross-normal-run-boundary` | event_sha256=`955a1cc9bf00ba6e9a265a7c5a8a1dd23b15c589ec1ffa3fade0c1005d363169`
- #3: `a8d5b9e1-1f0e-4e1e-9b35-30a3f3cd7f01` | 2026-08-03T10:31:33.000Z | FAILURE/statistics_empty_packet_contract | incident=`d2730b0e-6e83-4c56-9fa2-6ab6f16c86f1` | lesson_key=`empty-optional-evidence-family` | event_sha256=`49587e7b3d774c9483e8da5b0711f769213e6141a809251aa5ed7ff1f42e924a`
- #4: `066957c3-f787-4ce1-8eb7-feaeb2cee008` | 2026-08-03T13:18:41.026Z | STATE_CHANGE/context_rescope_required | incident=`aaf73b5e-0a01-41ef-bc3c-80d6ea039983` | lesson_key=`context-pack-rescope` | event_sha256=`5ab5bae2112ade06ae313bdc7298b955ed018e073dfc4d582593454636b2cca8`
- #5: `372be64b-2106-473f-94e6-b2eef7be78a2` | 2026-08-03T13:18:41.033Z | STATE_CHANGE/context_rescoped | incident=`410019ac-139f-4242-bc87-13d8f5ff96af` | lesson_key=`context-pack-rescope` | event_sha256=`9b2c3767ef7cef8051fb54e7598b8b0d6c221231455ef3a20e491441ade78de3`
- #6: `f5a6b7c8-d9e0-4123-4567-89abcdef0123` | 2026-08-03T15:00:02.000Z | GAP/unowned_v186_statistics_http_test | incident=`a6b7c8d9-e0f1-4234-5678-9abcdef01234` | lesson_key=`statistics-http-test-needs-formal-owner` | event_sha256=`23face3cee5abbd41ee861797c374432c980e4d63163a172ba13dc5fef22c985`
- #7: `a7ea40c9-5038-47a2-b550-ac599797f35c` | 2026-08-03T15:04:26.166Z | STATE_CHANGE/context_rescope_required | incident=`bb2c3727-91c5-4ddd-a7aa-759f57b50691` | lesson_key=`context-pack-rescope` | event_sha256=`46d27e34113629593b5cc515373c35d57663dfb5025a0b5c0c7e3b472cd3abc9`
- #8: `59cc9e0f-4994-4600-bd15-d1e7b4292e82` | 2026-08-03T15:04:26.173Z | STATE_CHANGE/context_rescoped | incident=`32480ed5-fe84-4bcd-a716-4c771080fd2d` | lesson_key=`context-pack-rescope` | event_sha256=`2d3cc8db5622040e27ea607f1615c3ae5c40c1aa010160b079491033e0b1fc95`
- #9: `e31b2f42-dbf5-4f58-bf37-add8feeda5dc` | 2026-08-03T15:05:55.422Z | STATE_CHANGE/context_rescope_required | incident=`18e57f8a-982a-4c9a-abfb-1ffa95b0a04f` | lesson_key=`context-pack-rescope` | event_sha256=`7719aa10a468cabb22c51ca082b70b97ecab20fc89997f940bd524bc4a683e9f`
- #10: `dcdec905-81ff-448a-bed2-f3660a9330f6` | 2026-08-03T15:05:55.430Z | STATE_CHANGE/context_rescoped | incident=`d271df9b-3f13-4868-b05c-8dac4bc77b15` | lesson_key=`context-pack-rescope` | event_sha256=`e7d9840d28f88cdd24c7c145601d2d818faa8d3ab04f6df5de94763210a6865d`
- #11: `c5d6e7f8-a9b0-4123-4567-abcdef012353` | 2026-08-03T15:21:04.000Z | GATE/statistics_http_gate_passed | incident=`d6e7f8a9-b0c1-4234-5678-abcdef012354` | lesson_key=`statistics-http-gate-evidence` | event_sha256=`f4d1575feda6024ea4b80a2f2cadb357736dc843ec7aa4cce3942ea890ec1e24`
- #12: `18baabf4-d04e-4da8-9104-df0b642eafad` | 2026-08-03T15:49:29.883Z | STATE_CHANGE/context_rescope_required | incident=`d815864c-7514-4d15-946c-c417bd43daeb` | lesson_key=`context-pack-rescope` | event_sha256=`9c38b6ebe434514637ee0045dce32c949bd7d626fe361d96136e7462cf1364ba`
- #13: `b09f29e9-5730-4072-8664-3eb024b09daf` | 2026-08-03T15:49:29.891Z | STATE_CHANGE/context_rescoped | incident=`3ebb09d5-0da3-4209-87d1-a1acd4d1f558` | lesson_key=`context-pack-rescope` | event_sha256=`a5f3eeaf7dbaaa59dbaff25ba118258c87dd990707c395e0153f4b44b1d74843`
