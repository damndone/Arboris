# Retrospective — v1-8-3-cf4-notebook-provider-injection

## Goal

# v1.8.3 CF4 Notebook provider injection  将已完成的服务器拥有 \`CapabilityBindingCatalog\` 接入 Notebook 的 HTTP 服务入口。 路由从应用级、受信注入点取得 catalog，并把它传给每个按项目创建的 \`NotebookService\`， 使已登记且仍有效的 capability 可沿既有 proposal 生命周期生成 \`NotebookOptionRevision@1.2\`；未配置 catalog 时保留原生 v1.0/v1.1 路径。  本切片不创建或持久化 authority，不允许 HTTP/Agent 注册、替换或伪造 binding，不开放 \`confirm_and_execute\`、自动执行、网络 fetch 或新的执行面。注入值必须是服务端拥有的 \`CapabilityBindingCatalog\`；错误配置 fail closed。覆盖 HTTP 路由真实请求、旧路径兼容、 跨请求使用同一受信 catalog，以及注入状态不影响其他项目。  完成标准：  - 生产 Notebook 路由具备明确的 server-owned catalog injection seam； - 注册 capability 经 HTTP proposal 生成 v1.2 并保留 binding digest； - 未配置 catalog 的现有路由行为不回归； - 不合规注入不会降级为普通能力或改变执行授权； - targeted notebook、capability、命名 gate 与正式 devline verify 通过。

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/8 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=1320000 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-07-26T22:20:00.000Z `tdd_red_before_provider_injection`; cause_status: `known`; cause: The HTTP seam test imported the not-yet-created server-owned catalog configuration function.; resolution: `open`; lesson: Write the real HTTP consumer test before adding the application-level authority injection seam.

## All errors

- #4 2026-07-26T22:41:00.000Z `rescope_allowlist_rejected`; cause_status: `known`; cause: The first attempt to formally rescope the line for planner projection was rejected because the current CLI disallows a direct backend/workbench/app.py allowlist path as too broad.; resolution: `mitigated`; lesson: When a frozen scope cannot be safely expanded through the formal CLI, close the bounded slice and start the next line from its exact commit rather than editing FMS records manually.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `formal-rescope-boundary`: occurrences=1; cause_status: `known`; root cause: The first attempt to formally rescope the line for planner projection was rejected because the current CLI disallows a direct backend/workbench/app.py allowlist path as too broad.; solution: `mitigated`
- `tdd-red-before-provider-injection`: occurrences=1; cause_status: `known`; root cause: The HTTP seam test imported the not-yet-created server-owned catalog configuration function.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `formal-rescope-boundary`: line experience occurrence(s)=1
- `tdd-red-before-provider-injection`: line experience occurrence(s)=1

## Future guidance

- HTTP consumer tests must use the existing context fingerprint and published artifact vocabulary before attributing failures to the provider seam.
- Keep server injection, planner projection, artifact vocabulary, and execution admission as separate verifiable seams.
- When a frozen scope cannot be safely expanded through the formal CLI, close the bounded slice and start the next line from its exact commit rather than editing FMS records manually.
- Write the real HTTP consumer test before adding the application-level authority injection seam.

## Event index

- #1: `98384f07-f146-426d-a510-2dbf7de2a2fe` | 2026-07-26T22:17:25.268Z | STATE_CHANGE/line_started | incident=`75d2e2fc-c8c3-4b5d-bec8-98c4cbe6d7ef` | lesson_key=`frozen-context-before-start` | event_sha256=`b27b2198fcaa9ed07081ecaf7b9f329f0e48d3b1db95ae69aebe4eede8c357a0`
- #2: `6f4d9e65-8a46-4c53-a1bb-49fa5c2e03a1` | 2026-07-26T22:20:00.000Z | FAILURE/tdd_red_before_provider_injection | incident=`7d35b4fe-fcc4-48d8-bf11-95b5b168a4e0` | lesson_key=`tdd-red-before-provider-injection` | event_sha256=`0f8cd5184a90d54d6fe454bab5963e135144c278b98a65e9d2ade8c98e1b9759`
- #3: `e86a0c4f-7d0f-4bb5-91e1-3b8b0a5ef9d0` | 2026-07-26T22:40:00.000Z | REVIEW/planner_projection_boundary_found | incident=`0a66f202-e7a6-4ca0-8b86-5d9a0b68d9a2` | lesson_key=`planner-projection-needs-server-declaration` | event_sha256=`8a6c334bcd535a13f5d5898a2f9b76ce7e8e186cbec670948d1db9ba731b43f2`
- #4: `5e0f2c5a-5fd2-47ba-b5c8-1e7d0a2c6b11` | 2026-07-26T22:41:00.000Z | ERROR/rescope_allowlist_rejected | incident=`7bd4f5c2-70fb-4b2a-9b74-3a4d5e6f7081` | lesson_key=`formal-rescope-boundary` | event_sha256=`88237c90b26be6ddeea703dc4cbca8200bb87ba077bdfb1518004aa146cd478f`
- #5: `b4156b8e-5cf4-4f9c-8f65-7d24f3a0c812` | 2026-07-26T22:42:00.000Z | REVIEW/tdd_red_resolved | incident=`7d35b4fe-fcc4-48d8-bf11-95b5b168a4e0` | lesson_key=`tdd-red-before-provider-injection` | event_sha256=`205bd691ecf91252802bffadbe9d0eff3634a4cd4f203876f4bcd2e62adf6bb7`
- #6: `7c2d9e0a-4f61-4b2a-8d35-c0e7f1a9b246` | 2026-07-26T22:43:00.000Z | GATE/notebook_provider_injection_targeted_gate | incident=`2b6d5f1a-8e47-4c39-a0d2-6f9b3e5c7d81` | lesson_key=`provider-injection-targeted-gate` | event_sha256=`f5761d47994bc2375ce7644ac88b8a54d6c50dfb40a3070bdc11c98e24fb45c7`
- #7: `9a4f6c2e-1d73-4b58-8e0a-5f2c7d9b3461` | 2026-07-26T22:44:00.000Z | GATE/quick_gate_host_containment_unavailable | incident=`4e7b2c9f-6a15-4d38-b0e2-8f5c1a7d9346` | lesson_key=`native-containment-host-capability` | event_sha256=`379f94063306ac43c430d8c2e1e45a0f21f685966d9b974d8ae810ad4ecf818c`
- #8: `c5e8a1d7-3f60-4b29-9c72-5a0e6d8f4132` | 2026-07-26T22:45:00.000Z | STATE_CHANGE/provider_injection_completed | incident=`6f1b4d8e-2a97-4c53-b0e6-9d7f5a1c8342` | lesson_key=`provider-injection-boundary-complete` | event_sha256=`5e26b76571918f8679337eb0ad85c1589608ccd0a8447e5eb7a80fbb7ebd8c87`
