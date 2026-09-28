# Retrospective — v1-8-9-agent-notebook-runtime-bridge

## Goal

# Workbench v1.8.9 Agent / Notebook Runtime Bridge Objective  ## Objective  把 Wave C 的安全共享编译器接到正式的应用启动配置和 Notebook 自然语言入口， 并让 ReportWorkspaceContext 自动消费已持久化的分类证据。Agent 与 Notebook 仍然 共享同一个 \`AnalysisIntentV1 -> CompilationRecordV1 -> confirmation -> admission -> trusted provider -> evidence\` 链路；本线不创建假 provider、不绕过旧执行内核、 不把客户端文本或路径变成执行权限。  ## Required outcome  1. 应用启动可以显式注册 server-owned \`AgentNotebookCompilerV1\`，HTTP 只按精确的    project/session scope 查找；未绑定时继续返回明确的 503，不隐式回退到旧路径。 2. runtime composition helper 只能把服务端传入的真实    \`ProviderRuntimeContributionV1\` 加入可信 registry；缺失、重复、合同不一致或    没有 evidence committer 时 fail closed。不得从 manifest 导入 callable，也不得    用 fixture/no-op 冒充生产能力。 3. Notebook 有一个薄的自然语言 compile adapter，校验 Notebook scope 后委托共享    compiler；它不维护第二套 capability 表、不直接调用 provider、不接受客户端确认    对象。确认和执行继续使用 server-retained receipt。 4. ReportWorkspaceContext 自动从已索引、hash 校验的分类 artifact 读取 typed    \`workbench.prediction.classification-evidence\` packet；缺失、损坏或未知 schema    只显示 \`UNAVAILABLE\`，不计算、不 dump raw JSON。 5. 旧 Notebook route、受保护 workflow runtime 和已有 provider/模型代码保持不变；    本线只增加 bridge，不宣称全历史 runtime 已迁移。  ## Safety boundary  - 自然语言只能触发 typed intent normalization；未知字段、prompt injection、未知   sensitivity、跨 scope record、stale snapshot 和伪造 confirmation 都拒绝。 - 默认进程不凭空获得数据执行能力。只有 deployment/bootstrap 明确注入真实 provider   contributions 后，相关 scope 才可执行；否则保留 503/typed unavailable。 - Report 只读已持久化 evidence；前端永远不从 artifact 标题猜测 packet，也不在浏览器   端重算统计量。  ## Acceptance boundary  需通过本线后端定向测试、既有 cutover/Notebook 回归、前端定向测试、typecheck、 compileall、diff check 和 formal devline verify。浏览器、外部 provider、host full gate、merge、push、tag、release 仍分别记为 \`NOT VERIFIED\`，除非实际执行。

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/18 (11.1%; 11.1 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T07:34:00.000Z `runtime_bridge_tdd_red`; cause_status: `known`; cause: The new runtime bridge tests were collected before the owned composition helper existed, so the expected missing-module RED was observed.; resolution: `resolved`; lesson: Keep the runtime composition contract tests ahead of the implementation and preserve the collection RED as test-first evidence.
- #13 2026-08-16T08:00:20.000Z `classification_index_fixture_red`; cause_status: `known`; cause: The first classification consumer regression run exposed that the additive classification entrypoint had no artifacts_index.json in its isolated fixture, so the new registration boundary failed closed before producing a consumable packet.; resolution: `resolved`; lesson: Evidence-consuming tests must create the same admitted artifacts_index boundary as a real run; missing persistence state is a typed failure, not an implicit initialization opportunity.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `classification-consumer-fixture-must-model-index-boundary`: occurrences=1; cause_status: `known`; root cause: The first classification consumer regression run exposed that the additive classification entrypoint had no artifacts_index.json in its isolated fixture, so the new registration boundary failed closed before producing a consumable packet.; solution: `resolved`
- `runtime-bridge-tdd-red-first`: occurrences=1; cause_status: `known`; root cause: The new runtime bridge tests were collected before the owned composition helper existed, so the expected missing-module RED was observed.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `classification-consumer-fixture-must-model-index-boundary`: line experience occurrence(s)=1
- `runtime-bridge-tdd-red-first`: line experience occurrence(s)=1

## Future guidance

- Close security review findings with executable scope-bound contracts and consumer-side verification, while recording compatibility seams and unverified deployment boundaries separately from implementation evidence.
- Evidence-consuming tests must create the same admitted artifacts_index boundary as a real run; missing persistence state is a typed failure, not an implicit initialization opportunity.
- Keep the runtime composition contract tests ahead of the implementation and preserve the collection RED as test-first evidence.
- Treat independent review findings as implementation work before claiming the bridge acceptance boundary; identity, artifact integrity, availability state, and authority storage must fail closed.

## Event index

- #1: `a08ef3f7-0a2d-44bd-892c-d161a9870c86` | 2026-08-16T07:33:15.444Z | STATE_CHANGE/line_started | incident=`e230fd67-61bf-49ea-aabb-d7c2a6901c5d` | lesson_key=`frozen-context-before-start` | event_sha256=`817306e0a247ab56f130f59f0efb4c0ff4223c4ec9cd0eccfc42de87ce8aa830`
- #2: `c2f3a4b5-6789-4cde-9012-3456789abcde` | 2026-08-16T07:34:00.000Z | FAILURE/runtime_bridge_tdd_red | incident=`d3e4f5a6-b7c8-49d0-e1f2-3456789abcde` | lesson_key=`runtime-bridge-tdd-red-first` | event_sha256=`0a5bb06956db872d2301ee833d80520d78cd540ef5e16c6e92ae1587f4972a52`
- #3: `e4f5a6b7-c8d9-4012-3456-789abcdef012` | 2026-08-16T07:41:02.000Z | GATE/runtime_bridge_focused_gate | incident=`f5a6b7c8-d9e0-4123-4567-89abcdef0123` | lesson_key=`runtime-bridge-focused-gate` | event_sha256=`736eca35319e757153a6072ad2e7a6edba91057e21252522152149feb5903e3e`
- #4: `b70d2afe-3beb-41d7-8103-296a983c4dc2` | 2026-08-16T07:49:30.733Z | STATE_CHANGE/context_rescope_required | incident=`4f5cb63d-da54-40d6-acff-8cdf922e78cc` | lesson_key=`context-pack-rescope` | event_sha256=`cbf3f39fe66b51f60fb47f34d7da862646fa854e867ce434eed739fc39de8795`
- #5: `8736dd78-c500-4916-9965-df8c2fcf3f05` | 2026-08-16T07:49:30.737Z | STATE_CHANGE/context_rescoped | incident=`19b99937-dbf0-46b3-b7e6-7a4679591c3e` | lesson_key=`context-pack-rescope` | event_sha256=`e8c41d552e078eefbc3ae64ee5bb8188cdb6966b1e881476c5f252991209240c`
- #6: `e155c3ab-80c8-4086-90df-1465d21b5842` | 2026-08-16T07:49:56.823Z | STATE_CHANGE/context_rescope_required | incident=`90f36add-817f-4edc-a5d9-c96acb75a612` | lesson_key=`context-pack-rescope` | event_sha256=`c4d1c546a5b62c2aa1f74abd7d12855b67f790b055535f590ed416f6eb5c4545`
- #7: `0cf674aa-dbb0-4831-b07c-0f41f5c5d510` | 2026-08-16T07:49:56.829Z | STATE_CHANGE/context_rescoped | incident=`5aacb642-9b08-476d-bcea-26181a1959cb` | lesson_key=`context-pack-rescope` | event_sha256=`38a4ffeb239fda2805f358e03f7b1c466b530cd967d295d589d92586532bfb44`
- #8: `9f7b7d2d-3c3f-4b6e-b9ea-27d5e0f3d4af` | 2026-08-16T08:00:00.000Z | REVIEW/runtime_bridge_security_review | incident=`d7bb7c54-6f38-4a0d-95fc-21b9ce84e9d2` | lesson_key=`runtime-bridge-review-findings-must-close-before-acceptance` | event_sha256=`eb64898448b46df4cdff4d7c8357ecc545e0bffeeafb3efbf0546749b87ddae3`
- #9: `ebc4d326-54d7-4ea9-ac47-b161a6d0a895` | 2026-08-16T07:55:36.721Z | STATE_CHANGE/context_rescope_required | incident=`881db017-1464-4aae-94e8-4e4543bba487` | lesson_key=`context-pack-rescope` | event_sha256=`39e364b231c8eea8ab5adf3e81dadcb7a488d5f5efeb89db44233492831ec342`
- #10: `6190a08e-6497-484a-8a42-7038b2972c34` | 2026-08-16T07:55:36.729Z | STATE_CHANGE/context_rescoped | incident=`cd70684c-5170-4394-8fd0-0e784050f182` | lesson_key=`context-pack-rescope` | event_sha256=`4722b15fddea25fac658d3e98fe53c633179de954286a65f9ccab0968b36a2fc`
- #11: `a875612d-1411-4bdf-ab0c-ce9512fc03ff` | 2026-08-16T07:57:20.727Z | STATE_CHANGE/context_rescope_required | incident=`c71fff93-ff69-437b-bb91-5c586d02c197` | lesson_key=`context-pack-rescope` | event_sha256=`c886ded1ef8777f396613d592cede28b9116615bf3b9e415cd46680ac0a11d21`
- #12: `0ed77de6-8969-4ddf-8358-11adedbf4db4` | 2026-08-16T07:57:20.735Z | STATE_CHANGE/context_rescoped | incident=`bbc1f62a-06eb-4b03-a695-40bd5162a6b9` | lesson_key=`context-pack-rescope` | event_sha256=`b5891b81f30231567bde3310fc0a6a2d82ca578cfc90cc7ec26cd98c03f31d45`
- #13: `f0cf62a0-481c-4be2-9d57-7f25859e9f7a` | 2026-08-16T08:00:20.000Z | FAILURE/classification_index_fixture_red | incident=`1ef3f91e-4b27-4d36-ae9a-8e1b8b6b3c2d` | lesson_key=`classification-consumer-fixture-must-model-index-boundary` | event_sha256=`b47c402eb291c19e807386739fcec4646130d3f0af4e6c29ba3f45047c163d23`
- #14: `ceb01cfe-1027-43a1-bb26-cf67cc792066` | 2026-08-16T08:12:23.376Z | STATE_CHANGE/context_rescope_required | incident=`1525b1f9-dde2-46a9-97cc-93b5f907920f` | lesson_key=`context-pack-rescope` | event_sha256=`23b65f591bdaa833ba9d81e3fb2378cef7f785ad1120d1ed4776927ea0ba338e`
- #15: `c3ed3a2c-1db8-4008-bcc1-4eac0f6a4269` | 2026-08-16T08:12:23.388Z | STATE_CHANGE/context_rescoped | incident=`e8cc9a98-83c8-415d-8927-3217bec07dcb` | lesson_key=`context-pack-rescope` | event_sha256=`3891bcbda83b55e950d2f54fab033ace91fba801fdd194fbefcaf4ac2ca3aadd`
- #16: `5a3ca8a8-1d4c-4557-8c7d-79eeb1d3a2f5` | 2026-08-16T08:26:00.000Z | GATE/full_backend_host_containment_gate | incident=`6d7c8e9f-a0b1-42c3-d4e5-f60718293a4b` | lesson_key=`full-backend-host-sandbox-gate-separate` | event_sha256=`294399066c78df8cd5054dddb40695b2485586e9817f1f749be39285b0ad7071`
- #17: `b5f4d9a8-7c62-4e31-9f08-2d6a5b4c3e17` | 2026-08-16T08:30:00.000Z | REVIEW/runtime_bridge_security_review_closeout | incident=`c6e5d4f3-a2b1-4987-0f6e-5d4c3b2a1908` | lesson_key=`runtime-bridge-review-closeout-preserves-boundaries` | event_sha256=`e0f17ed871c266986b2665bc0a48c0bcf82c0a0559ce80ceb8c09cc79879bef2`
- #18: `d7c6b5a4-9382-4f10-8e2d-6c5b4a392817` | 2026-08-16T08:31:00.000Z | STATE_CHANGE/line_completed | incident=`e8d7c6b5-a493-4f20-9e1d-7c6b5a493827` | lesson_key=`close-scoped-line-with-explicit-boundaries` | event_sha256=`5688cb057f72e4b4e3592d4bcf81f04426beb63d2e46f6e770bd77ece8b31ec9`
