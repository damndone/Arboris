# Retrospective — v1-8-3-cf4-notebook-option-consumer

## Goal

# v1.8.3 CF4 Notebook Option consumer wiring  将已通过 Capability Factory admission 的 \`CapabilityResolutionBinding\` 接入 NotebookService 的 Option proposal 生成：由服务端持有的 binding catalog 按 Agent 提供的 capability id 解析 binding，生成 notebook-option/v1.2，并持久化 binding digest；未注册的原生能力继续使用既有 v1.0/v1.1 路径。  本切片只实现 proposal/revision 的受信绑定，不开放 Notebook 执行、确认执行、 materialization 新能力、HTTP/Graph/Run 接线，也不允许 Agent 提供或伪造 binding。 绑定缺失、失效、身份不一致、推荐决策缺失或执行模式非 \`materialize_only\` 时 必须 fail closed，并保持 batch 原子性与 replay 语义。  完成标准：  - catalog 是服务端拥有的唯一 binding lookup，不从 Agent payload 恢复 authority； - 已注册 binding 生成 v1.2，包含稳定 binding digest，且 \`execution_allowed\` 为 false； - 原生 Option、旧 v1.0/v1.1 读取和现有 replay 行为不回归； - 失效/伪造/缺失/冲突输入有稳定拒绝测试； - targeted notebook、capability、命名 gate 与 devline verify 通过。

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/9 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=780000 ms (sample=2; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-07-26T18:10:00.000Z `tdd_red_before_notebook_consumer`; cause_status: `known`; cause: The service consumer test imports the not-yet-created server-owned capability binding catalog.; resolution: `open`; lesson: Write the trusted consumer boundary test before adding the service integration.
- #4 2026-07-26T18:12:00.000Z `test_fixture_used_unpublished_artifact`; cause_status: `known`; cause: The first consumer test used an artifact id that is not in the published Notebook vocabulary.; resolution: `resolved`; lesson: Consumer tests must use the same published artifact vocabulary enforced by NotebookService.

## All errors

- #2 2026-07-26T18:10:30.000Z `event_append_schema_rejected`; cause_status: `known`; cause: The first attempt to append the TDD red event used an unsupported resolution_status field.; resolution: `mitigated`; lesson: Use the formal event schema and treat CLI validation errors as process evidence.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `formal-event-schema-validation`: occurrences=1; cause_status: `known`; root cause: The first attempt to append the TDD red event used an unsupported resolution_status field.; solution: `mitigated`
- `published-artifact-vocabulary-in-consumer-tests`: occurrences=1; cause_status: `known`; root cause: The first consumer test used an artifact id that is not in the published Notebook vocabulary.; solution: `resolved`
- `tdd-red-before-notebook-consumer`: occurrences=1; cause_status: `known`; root cause: The service consumer test imports the not-yet-created server-owned capability binding catalog.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `formal-event-schema-validation`: line experience occurrence(s)=1
- `published-artifact-vocabulary-in-consumer-tests`: line experience occurrence(s)=1
- `tdd-red-before-notebook-consumer`: line experience occurrence(s)=1

## Future guidance

- Close the TDD red incident after the production boundary and its regression test both pass.
- Consumer tests must use the same published artifact vocabulary enforced by NotebookService.
- Review versioned consumer bindings against later revalidation and authority drift, while preserving the explicit distinction between materialize-only and confirm-and-execute.
- Use the formal event schema and treat CLI validation errors as process evidence.
- Write the trusted consumer boundary test before adding the service integration.

## Event index

- #1: `82eca716-b114-4b5d-b7c1-130dfa8f1039` | 2026-07-26T18:06:27.517Z | STATE_CHANGE/line_started | incident=`e8ee23f8-3cb0-4f2d-b900-4308a12242c5` | lesson_key=`frozen-context-before-start` | event_sha256=`9d05bdb3229041b481a0b2ff1b724251f2cc1608111d729b167f35c1c6119e20`
- #2: `f1b2c3d4-1111-4111-8111-111111111111` | 2026-07-26T18:10:30.000Z | ERROR/event_append_schema_rejected | incident=`f1b2c3d4-2222-4222-8222-222222222222` | lesson_key=`formal-event-schema-validation` | event_sha256=`023b9d63ee46dbdc3de55e716fbe123f6c1431bbfec29492e6199fd840f9752b`
- #3: `f1b2c3d4-3333-4333-8333-333333333333` | 2026-07-26T18:10:00.000Z | FAILURE/tdd_red_before_notebook_consumer | incident=`f1b2c3d4-4444-4444-8444-444444444444` | lesson_key=`tdd-red-before-notebook-consumer` | event_sha256=`ec86fab24ee8b9131ec0bf95b0130cd3c52b0a84b469ec7a00436a75bfcf3c13`
- #4: `f1b2c3d4-5555-4555-8555-555555555555` | 2026-07-26T18:12:00.000Z | FAILURE/test_fixture_used_unpublished_artifact | incident=`f1b2c3d4-6666-4666-8666-666666666666` | lesson_key=`published-artifact-vocabulary-in-consumer-tests` | event_sha256=`af305bbdf975b1a346a15acae97993c49d40de22ef2edc59777800870721f9b4`
- #5: `f1b2c3d4-7777-4777-8777-777777777777` | 2026-07-26T18:20:00.000Z | REVIEW/notebook_consumer_security_review | incident=`f1b2c3d4-8888-4888-8888-888888888888` | lesson_key=`notebook-binding-review-and-scope` | event_sha256=`8b0ac8e8fa84d68b092e376baa1505ce2ae0ba1736d4a54d7dfa7c3598099483`
- #6: `f1b2c3d4-9999-4999-8999-999999999999` | 2026-07-26T18:28:00.000Z | GATE/notebook_consumer_targeted_regression_gate | incident=`f1b2c3d4-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`notebook-consumer-targeted-gate` | event_sha256=`cde97c6f7ecdbdba877f6ac6470c1d681e80c9026a935321e67b8ef363c01d07`
- #7: `f1b2c3d4-bbbb-4bbb-8bbb-bbbbbbbbbbbb` | 2026-07-26T18:29:00.000Z | GATE/quick_gate_host_containment_unavailable | incident=`f1b2c3d4-cccc-4ccc-8ccc-cccccccccccc` | lesson_key=`native-containment-host-capability` | event_sha256=`55f429b32f3c18d23937aa69469a8f26700d08e7ecad0b5f1a100cc7354c258c`
- #8: `f1b2c3d4-dddd-4ddd-8ddd-dddddddddddd` | 2026-07-26T18:35:00.000Z | STATE_CHANGE/line_completed | incident=`f1b2c3d4-eeee-4eee-8eee-eeeeeeeeeeee` | lesson_key=`notebook-consumer-boundary-complete` | event_sha256=`702e22f7c9f7ec707fd2e89238ecfb1ce27bad6c8f400905b62808074ec56306`
- #9: `f1b2c3d4-ffff-4fff-8fff-ffffffffffff` | 2026-07-26T18:36:00.000Z | REVIEW/tdd_red_resolved | incident=`f1b2c3d4-4444-4444-8444-444444444444` | lesson_key=`tdd-red-before-notebook-consumer` | event_sha256=`296c0e6340773c59678e7a60242753bd5dd3b791e3d111b31551fb28e3b61268`
