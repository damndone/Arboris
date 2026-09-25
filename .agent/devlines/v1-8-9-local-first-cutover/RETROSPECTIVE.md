# Retrospective — v1-8-9-local-first-cutover

## Goal

# v1.8.9 local-first authority, resume, and clean cutover  ## Objective  在现有 v1.8.9 hardening integration candidate 上完成本机 macOS/Darwin 的安全闭环：  1. 跨进程 Resume 使用服务端持久化状态，可在 backend 重启后继续，并绑定 project/session/plan/model branch。 2. authority 只由当前 backend 发行、持久化和校验；客户端与 LLM 只能提交意图，不能提交 authority、owner、host 或 evidence 身份。 3. bootstrap 生成并校验本机 server identity、host identity 和 evidence owner，使结果可以证明来自当前 Workbench backend，并绑定本机 project/session。 4. deterministic evaluator 在无 provider、无网络时提供可重复的 typed correctness baseline；Provider benchmark 只消费同一 compiler/evaluator seam，不把 deterministic 结果冒充真实 LLM 结果。 5. Agent、Notebook、Report UI 统一走 v1.8.9 compiler/cutover；旧状态不迁移，明确返回 \`UNSUPPORTED_VERSION\`；删除旧执行路径与隐式 raw-result fallback。 6. 使用 Codex 内置浏览器自动验收新路径；Linux、其他 Mac、云环境只记录 \`NOT VERIFIED\`，不阻塞本机完成。  ## Safety and extensibility constraints  - 不读取、打印或写入 provider secret；真实 provider 不是本机 correctness gate。 - 只允许 server-owned typed references、closed capability vocabulary 和 admission-gated persistence；拒绝客户端伪造的 authority/evidence/host 字段。 - 统计执行仍由 typed operation registry 和确定性 runtime 负责；LLM 只负责受约束的意图理解、解释和组合建议。 - 不迁移历史状态；旧 schema、旧 execution route、缺少新身份绑定的 receipt 均 fail closed。 - 不新增第二套 Agent/Notebook 语义引擎；统一 compiler 是唯一计划入口，Report 只读正式 evidence projection。 - 修改范围限于 backend contracts/runtime/http/evidence/services、frontend Agent/Notebook/Report cutover、对应测试、目标文件和验收记录。  ## Required verification  - focused backend contract/runtime/route tests；cross-process subprocess/restart probe；evidence tamper and identity-binding probes。 - deterministic evaluator fixed-seed repeatability and provider seam tests with \`provider_called=false\`. - frontend typecheck and cutover route tests。 - internal browser automated acceptance for Agent, Notebook, Report; record exact URLs, visible markers, and failures. - formal event verification and retrospective; clearly separate implemented/tested, browser-accepted, provider-backed, and release claims.  ## Known non-blocking gates  - Linux/Darwin variants other than this host: \`NOT VERIFIED\`. - Other macOS hosts and cloud deployment: \`NOT VERIFIED\`. - Real external LLM provider quality benchmark: \`NOT VERIFIED\` until a provider is deliberately configured. - Release merge/tag: not part of this implementation line.

## Final status

IMPLEMENTING

## Metrics

- Failure frequency: 5/9 (55.6%; 55.6 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=4)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-23T15:05:00.000Z `local_first_red_test`; cause_status: `known`; cause: The new local-first bootstrap test imports the planned version boundary and local authority seams before those seams exist.; resolution: `open`; lesson: Keep a focused red test for every authority and version boundary before implementation.

## All errors

- #2 2026-08-23T15:01:10.371Z `formal_start_parameter_error`; cause_status: `known`; cause: The first two formal start attempts were rejected before line creation: shell-split gate values and a non-normalized tag. The third attempt used normalized identifiers and created the line.; resolution: `resolved`; lesson: Normalize every formal CLI identifier before starting a line and keep gate values shell-safe.

## All gaps

- #7 2026-08-23T16:26:44.786Z `non_blocking_host_and_provider_boundaries`; cause_status: `known`; cause: This line deliberately verifies only the current Darwin host. Real external provider quality, Linux, other macOS hosts, cloud deployment, and release merge/tag remain outside the local acceptance boundary; the deterministic baseline also reports unavailable for capabilities without a local fixture.; resolution: `accepted`; lesson: Do not convert a local Darwin safety result or deterministic evaluator result into an external-host or real-provider claim.
- #8 2026-08-23T16:47:47.177Z `release_gate_legacy_consumer_boundary`; cause_status: `known`; cause: The release-wide full gate remains red. The first reproducible failure is the historical v1.8.6 Agent statistical-evidence test writing a bare statistical_tests/evidence.json without a server-owned evidence owner, receipt, or projection binding, then expecting it to be trusted.; resolution: `open`; lesson: A clean cutover must update legacy consumer tests to exercise the canonical server-owned evidence path; never restore a raw artifact fallback merely to make the old assertion pass.
- #9 2026-08-23T16:53:01.845Z `release_gate_v187_unowned_projection_assertions`; cause_status: `known`; cause: After migrating the first legacy raw-evidence assertion, the next five release-suite failures are v1.8.7 tests that call Agent result projection without a server-owned evidence owner and still expect legacy model-result and survey sections.; resolution: `open`; lesson: Do not make an unconfigured direct helper silently bootstrap or trust evidence; migrate historical consumer tests to the explicit host-owned fixture and keep unavailable states typed.

## All waste

- None recorded.

## Root causes and solutions

- `explicit-unverified-boundaries`: occurrences=1; cause_status: `known`; root cause: This line deliberately verifies only the current Darwin host. Real external provider quality, Linux, other macOS hosts, cloud deployment, and release merge/tag remain outside the local acceptance boundary; the deterministic baseline also reports unavailable for capabilities without a local fixture.; solution: `accepted`
- `migrate-legacy-consumer-tests-to-owned-evidence`: occurrences=1; cause_status: `known`; root cause: The release-wide full gate remains red. The first reproducible failure is the historical v1.8.6 Agent statistical-evidence test writing a bare statistical_tests/evidence.json without a server-owned evidence owner, receipt, or projection binding, then expecting it to be trusted.; solution: `open`
- `migrate-v187-consumers-to-explicit-owner`: occurrences=1; cause_status: `known`; root cause: After migrating the first legacy raw-evidence assertion, the next five release-suite failures are v1.8.7 tests that call Agent result projection without a server-owned evidence owner and still expect legacy model-result and survey sections.; solution: `open`
- `normalized-fms-tag-before-start`: occurrences=1; cause_status: `known`; root cause: The first two formal start attempts were rejected before line creation: shell-split gate values and a non-normalized tag. The third attempt used normalized identifiers and created the line.; solution: `resolved`
- `red-test-before-local-authority`: occurrences=1; cause_status: `known`; root cause: The new local-first bootstrap test imports the planned version boundary and local authority seams before those seams exist.; solution: `open`

## Added tests

- `tests/test_v189_local_first_bootstrap.py`

## New rules

- `explicit-unverified-boundaries`: line experience occurrence(s)=1
- `migrate-legacy-consumer-tests-to-owned-evidence`: line experience occurrence(s)=1
- `migrate-v187-consumers-to-explicit-owner`: line experience occurrence(s)=1
- `normalized-fms-tag-before-start`: line experience occurrence(s)=1
- `red-test-before-local-authority`: line experience occurrence(s)=1

## Future guidance

- A clean cutover must update legacy consumer tests to exercise the canonical server-owned evidence path; never restore a raw artifact fallback merely to make the old assertion pass.
- Browser acceptance must verify user-visible trust boundaries after a real backend restart, not only component tests or HTTP status codes.
- Do not convert a local Darwin safety result or deterministic evaluator result into an external-host or real-provider claim.
- Do not make an unconfigured direct helper silently bootstrap or trust evidence; migrate historical consumer tests to the explicit host-owned fixture and keep unavailable states typed.
- Keep a focused red test for every authority and version boundary before implementation.
- Normalize every formal CLI identifier before starting a line and keep gate values shell-safe.

## Event index

- #1: `181dee01-0036-4671-969c-707883fa8723` | 2026-08-23T15:00:31.569Z | STATE_CHANGE/line_started | incident=`259babd4-7ac9-4b66-97c2-8b768384fa60` | lesson_key=`frozen-context-before-start` | event_sha256=`ae9a4985fa404165e37e330289f660fffe7e047e20ccafaeb683d0da80dff72c`
- #2: `0f7b1c2d-3e4f-4567-89ab-cdef01234567` | 2026-08-23T15:01:10.371Z | ERROR/formal_start_parameter_error | incident=`1f8c2d3e-4f5a-4678-9abc-def012345678` | lesson_key=`normalized-fms-tag-before-start` | event_sha256=`200a71c2c9f3d43f4b6ee52ab1f42a95b2317493e05c72c78ea9e81fb9517789`
- #3: `2a8c1e6f-5d72-4a90-9e11-1d3e8c4b7f20` | 2026-08-23T15:05:00.000Z | FAILURE/local_first_red_test | incident=`7e2d4b9a-6f31-4c85-b0ad-9c1e2f7a8d43` | lesson_key=`red-test-before-local-authority` | event_sha256=`1c75e376378b5cbf9290fc7ca20763667e75dd349b33715909c3906fc52e8406`
- #4: `7b5c4d3e-2f1a-4b6c-8d9e-0f1a2b3c4d5e` | 2026-08-23T16:25:43.225Z | STATE_CHANGE/local_authority_resume_cutover_implemented | incident=`6a5b4c3d-2e1f-4a6b-8c9d-0e1f2a3b4c5d` | lesson_key=`local-first-authority-before-execution` | event_sha256=`6b15d3012b851ff6696816c7d055b47f60e020da3a6e276c8a616f176d718da2`
- #5: `8c6d5e4f-3a2b-4c7d-9e0f-1a2b3c4d5e6f` | 2026-08-23T16:26:14.375Z | REVIEW/latest_browser_cutover_acceptance | incident=`7b6c5d4e-3a2f-4b7c-8d9e-0f1a2b3c4d5e` | lesson_key=`restart-then-browser-acceptance` | event_sha256=`3d6b3a36987b936aeb91b48468029776457ac4bfcc52b7700e7d69050582e558`
- #6: `9d7e6f5a-4b3c-4d8e-0f1a-2b3c4d5e6f7a` | 2026-08-23T16:26:31.114Z | GATE/local_first_focused_qa | incident=`8c7d6e5f-4a3b-4d9e-0f1a-2b3c4d5e6f7a` | lesson_key=`separate-focused-and-release-gates` | event_sha256=`693f0dc28692cd9588b1cbc822bcbaa661526976e12a0c6e9105d488ce6957db`
- #7: `0e8f7a6b-5c4d-4e9f-1a2b-3c4d5e6f7a8b` | 2026-08-23T16:26:44.786Z | GAP/non_blocking_host_and_provider_boundaries | incident=`9d8e7f6a-5b4c-4e0f-1a2b-3c4d5e6f7a8b` | lesson_key=`explicit-unverified-boundaries` | event_sha256=`73a5d876146fc4d158a461245f650ebe0f92d6e0af5d6e78ae2dce4d6d529546`
- #8: `1f9a8b7c-6d5e-4f3a-2b1c-0d9e8f7a6b5c` | 2026-08-23T16:47:47.177Z | GAP/release_gate_legacy_consumer_boundary | incident=`0a1b2c3d-4e5f-4678-9abc-def012345678` | lesson_key=`migrate-legacy-consumer-tests-to-owned-evidence` | event_sha256=`2a7ec42ac9b216de96e9a36f843a9f060d7c6da30afea5a5cd9461c0e52d73de`
- #9: `2a0b1c2d-3e4f-5678-9abc-def012345678` | 2026-08-23T16:53:01.845Z | GAP/release_gate_v187_unowned_projection_assertions | incident=`1b2c3d4e-5f6a-4789-0abc-def123456789` | lesson_key=`migrate-v187-consumers-to-explicit-owner` | event_sha256=`d6cf91394b96996e2e844d7d0992143c5d89c6ee594444035845af2783688d9d`
