# Retrospective — v1-8-9-agent-notebook-cutover

## Goal

# v1.8.9 Agent / Notebook Cutover Objective  ## Objective  把 Agent 与 Notebook 的自然语言入口接入同一个服务端能力目录、编译器、 确认边界、执行准入和结果证据链。自然语言只能提出受约束的 \`AnalysisIntentV1\`，不能直接生成 operation、provider、contract、事实或 执行权限。两条入口必须使用同一套语义计划和安全边界，只在交互与持久化 投影上保持差异。  目标链路为：  \`自然语言 -> 澄清 -> typed intent -> server compilation record -> PlanDiff/preview -> confirmation -> ExecutionAdmission -> execution -> immutable EvidenceEnvelope -> typed consumer projections\`。  ## Baseline and upstream authority  - Worktree: \`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-wave-a\` - Branch: \`workbench-v1.8.9-wave-a\` - Exact baseline: \`c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749\` - Plan lock: \`f3836408cf15c3e7380823e5c1b303b4467c7aec\` - C0 catalog digest recorded by Contract Lock: \`cac54a40f62620b84d288416ee09d5b04814f4dbcb2c8ee3a4595522e3e0da40\` - Evidence envelope contract digest: \`a3aa7ac15779077042ef3f0e15ada0df6e1aefc555723c1617f5876d98a22835\` - Evidence persistence contract digest: \`44105bfc2fdada97a92c136bf29e4e2762e4098bbc5207fa47eb27509d0023f2\` - Planning/execution-admission contract digest: \`8459bbfbf01400f3411245d5d1945ae36a300a55c3a096efbb74ea3705ab349a\` - Context-egress contract digest: \`892d6f672a9de9fae50dfe2c029a97e00dc24fede045df6ca9cf35e3c6b10817\`  The Data Consumer, Classification ML, Consumer Projection and provider-catalog integration lines are present as package-local contributions in this dirty integration worktree. The three historical P0 C1 implementation handoffs named by the program are not materialized here; this line must consume only their locked public seams and must keep any C1/runtime claim explicitly separate.  ## Required outcome  1. Provider declarations, frozen contract refs, runtime contributions and UI    renderers form one deterministic, fail-closed catalog. JSON may contain only    opaque executor IDs; actual callables are server-composed and registered. 2. Agent and Notebook submit the same typed intent to one public compiler and    receive either typed clarifications or a persisted \`CompilationRecordV1\`. 3. Execution accepts only a server-bound record ID and a server-issued,    actor/session/project-bound confirmation. Client-shaped compiled objects,    stale records, cross-session replay, changed data/provider/contract digests,    unknown effects and unsafe egress are rejected before side effects. 4. Completion cannot precede immutable evidence persistence. Result consumers    and Report/UI render only persisted typed projections; they do not calculate    or fabricate facts. 5. Data Consumer operations and Classification ML operations are exposed by    declaration-derived discovery. No central family/prefix/model switch is    added for these or future providers. 6. Notebook recipes persist intent, contract/provider refs, compilation record,    diff, confirmation, operation/artifact/evidence refs and rerun prerequisites;    editing or changing the bound snapshot invalidates old authority.  ## Safety and AI-native boundary  - LLMs/agents may normalize language, propose clarifying questions and explain   persisted results, but server-owned schemas and registries decide capability,   contracts, permissions, sensitivity, resource/effect and evidence. - Missing target, structure/time/entity, availability, positive class, metric,   decision cost, sensitivity or resource choice is a typed clarification or   block; no hidden default is invented. - Prompt injection, unsupported operations, conflicting constraints, raw provider   clients, direct module imports, arbitrary code strings and prompt-requested   egress bypasses are negative-path tests, not fallback behavior. - Remote context is receipt-backed, sensitivity-bounded and budgeted. Unknown   sensitivity/schema/renderer/policy is blocked. - Read-only preview may be prepared automatically only when declared safe;   execution always observes the declared confirmation/effect policy.  ## Acceptance boundary  The line must provide focused backend/frontend tests, typecheck, compileall, diff check, formal event verification and a generated retrospective. Shadow planning must classify exact matches, justified changes, typed clarifications and regressions with zero silent capability loss, authority broadening or consumer fact divergence.  Browser-visible acceptance, external provider calls, host full gate, release, merge, push and tag remain separate evidence and must be reported as \`NOT VERIFIED\` unless independently run.

## Final status

COMPLETED

## Metrics

- Failure frequency: 6/16 (37.5%; 37.5 per 100 events)
- Repeat rate: 0/6 (0.0%)
- Recurrence rate: 0/6 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=5)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-16T07:03:40.000Z `cutover_contract_tests_tdd_red`; cause_status: `known`; cause: The new Wave C contract tests were collected before the owned cutover facades, lifecycle store and Notebook recipe adapter existed.; resolution: `accepted`; lesson: Keep the shared Agent/Notebook authority tests ahead of the central implementation and preserve collection RED as test-first evidence.
- #12 2026-08-16T07:31:00.000Z `frontend_registry_contract_regression`; cause_status: `known`; cause: Full frontend regression found three existing sectionRegistry assertions still expected the pre-Wave-C list and order after the declaration-derived dataConsumerEvidence entry was added.; resolution: `open`; lesson: When a canonical registry grows, update its existing identity/order contract in the same scoped change and rerun the complete frontend suite.

## All errors

- #2 2026-08-16T07:02:05.353Z `baseline_registry_probe_import`; cause_status: `known`; cause: The initial baseline registry probe imported a notebook capability helper from the wrong module; the current code does not export that symbol there.; resolution: `resolved`; lesson: Probe the actual public Agent and Notebook registry exports before treating a baseline snapshot as evidence.
- #5 2026-08-16T07:15:00.000Z `cutover_admission_effect_mismatch`; cause_status: `known`; cause: The first successful execution-path test reached the existing ExecutionAdmissionGateV1, which compared its admission-effect vocabulary directly with the planning-effect vocabulary; read_only and read are semantically equivalent but represented by different frozen enums.; resolution: `open`; lesson: Test the semantic bridge between planning and admission effect vocabularies before claiming a server-confirmed execution path.
- #10 2026-08-16T07:22:00.000Z `cutover_test_baseline_replaced`; cause_status: `known`; cause: Parallel audit found that the Wave C test files replaced rather than extended the pre-existing Agent operation lifecycle and Notebook planning suites: 666 and 4319 lines were removed relative to the exact devline baseline.; resolution: `open`; lesson: Wave-specific contract tests must extend existing suites; never replace the historical lifecycle or Notebook coverage when adding a cutover seam.

## All gaps

- #11 2026-08-16T07:28:00.000Z `cutover_legacy_runtime_bypass`; cause_status: `known`; cause: Read-only inventory shows protected workflow_runtime.py still invokes operation.execute_with_context directly, while the existing /notebooks routes retain the legacy NotebookPlanningAgent/NotebookService lifecycle. The new AgentNotebookCompilerV1 route is an explicit shared seam but is not yet the unique global runtime choke point.; resolution: `open`; lesson: A new safe facade is not a global choke point until every historical runtime caller is inventoried and migrated or explicitly blocked.

## All waste

- None recorded.

## Root causes and solutions

- `baseline-registry-probe-public-api`: occurrences=1; cause_status: `known`; root cause: The initial baseline registry probe imported a notebook capability helper from the wrong module; the current code does not export that symbol there.; solution: `resolved`
- `cutover-admission-effect-vocabulary-bridge`: occurrences=1; cause_status: `known`; root cause: The first successful execution-path test reached the existing ExecutionAdmissionGateV1, which compared its admission-effect vocabulary directly with the planning-effect vocabulary; read_only and read are semantically equivalent but represented by different frozen enums.; solution: `open`
- `cutover-contract-tests-red-first`: occurrences=1; cause_status: `known`; root cause: The new Wave C contract tests were collected before the owned cutover facades, lifecycle store and Notebook recipe adapter existed.; solution: `accepted`
- `cutover-legacy-runtime-admission-boundary`: occurrences=1; cause_status: `known`; root cause: Read-only inventory shows protected workflow_runtime.py still invokes operation.execute_with_context directly, while the existing /notebooks routes retain the legacy NotebookPlanningAgent/NotebookService lifecycle. The new AgentNotebookCompilerV1 route is an explicit shared seam but is not yet the unique global runtime choke point.; solution: `open`
- `cutover-tests-append-only-baseline`: occurrences=1; cause_status: `known`; root cause: Parallel audit found that the Wave C test files replaced rather than extended the pre-existing Agent operation lifecycle and Notebook planning suites: 666 and 4319 lines were removed relative to the exact devline baseline.; solution: `open`
- `registry-contract-test-update`: occurrences=1; cause_status: `known`; root cause: Full frontend regression found three existing sectionRegistry assertions still expected the pre-Wave-C list and order after the declaration-derived dataConsumerEvidence entry was added.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `baseline-registry-probe-public-api`: line experience occurrence(s)=1
- `cutover-admission-effect-vocabulary-bridge`: line experience occurrence(s)=1
- `cutover-contract-tests-red-first`: line experience occurrence(s)=1
- `cutover-legacy-runtime-admission-boundary`: line experience occurrence(s)=1
- `cutover-tests-append-only-baseline`: line experience occurrence(s)=1
- `registry-contract-test-update`: line experience occurrence(s)=1

## Future guidance

- A new safe facade is not a global choke point until every historical runtime caller is inventoried and migrated or explicitly blocked.
- Freeze identity and count snapshots before changing an Agent/Notebook catalog or authority seam.
- Keep the shared Agent/Notebook authority tests ahead of the central implementation and preserve collection RED as test-first evidence.
- Probe the actual public Agent and Notebook registry exports before treating a baseline snapshot as evidence.
- Test the semantic bridge between planning and admission effect vocabularies before claiming a server-confirmed execution path.
- Wave-specific contract tests must extend existing suites; never replace the historical lifecycle or Notebook coverage when adding a cutover seam.
- When a canonical registry grows, update its existing identity/order contract in the same scoped change and rerun the complete frontend suite.

## Event index

- #1: `ea9f9c9a-d3f5-4b08-a8f7-d1347f05ccaa` | 2026-08-16T07:00:31.710Z | STATE_CHANGE/line_started | incident=`7211d657-2492-4111-b91d-22ce7c69a45e` | lesson_key=`frozen-context-before-start` | event_sha256=`660286b9be35f96894d767503f59cba85b5d5c2734621b0b8ddc2c0dd19cd4bc`
- #2: `2c3d4e5f-6071-489a-b2c3-d4e5f6071829` | 2026-08-16T07:02:05.353Z | ERROR/baseline_registry_probe_import | incident=`3d4e5f60-7182-49ab-c3d4-e5f60718293a` | lesson_key=`baseline-registry-probe-public-api` | event_sha256=`96d6d39adf9eef3df483775465ecceee2171508b9b5a1b97578a51d9091377b0`
- #3: `4e5f6071-8293-4a5b-c6d7-e8f9012345ab` | 2026-08-16T07:02:33.000Z | REVIEW/cutover_baseline_registry_snapshot | incident=`5f607182-93a4-4b6c-d7e8-f9012345abcd` | lesson_key=`cutover-baseline-registry-snapshot` | event_sha256=`b48846c732581960d3917bb3c21e7019f9b88a6ea3e8de6416967a49c2c2a59c`
- #4: `60718293-a4b5-4c6d-e7f8-9012345abcde` | 2026-08-16T07:03:40.000Z | FAILURE/cutover_contract_tests_tdd_red | incident=`718293a4-b5c6-4d7e-f809-12345abcdef0` | lesson_key=`cutover-contract-tests-red-first` | event_sha256=`de71d08127ec628749ee8234ec5ba4ae8afb6f86e7ebeace4b6f604fd67d19d1`
- #5: `8193a4b5-c6d7-4e8f-9012-345abcdef012` | 2026-08-16T07:15:00.000Z | ERROR/cutover_admission_effect_mismatch | incident=`92a4b5c6-d7e8-4f90-a123-45abcdef0123` | lesson_key=`cutover-admission-effect-vocabulary-bridge` | event_sha256=`cd1808d25a2997ab7e189363a77b5897a7ce169fe0d5d9ecec068d0400fff562`
- #6: `98236dc2-344e-4b0b-8ea2-73c8cae6f198` | 2026-08-16T07:16:16.924Z | STATE_CHANGE/context_rescope_required | incident=`eda16c8c-5cdf-4dbe-9ea3-cb274ba90b50` | lesson_key=`context-pack-rescope` | event_sha256=`59f1921e5a28344513dd1c4d0a7c8d35a577d8c654334a4cacaad45511102a87`
- #7: `df234154-7f62-4f62-aac9-ee9bb90f6963` | 2026-08-16T07:16:16.929Z | STATE_CHANGE/context_rescoped | incident=`41a52721-2fa3-40f5-9349-ac593def8101` | lesson_key=`context-pack-rescope` | event_sha256=`fe618ffa33942bef457656b6001ea6b5695705f19e3a7f73ffd327d7f751c8f7`
- #8: `dd289f2b-caaf-4d9e-a976-072070c23d42` | 2026-08-16T07:16:30.121Z | STATE_CHANGE/context_rescope_required | incident=`88c29ca8-8112-4390-a459-0e165554e24f` | lesson_key=`context-pack-rescope` | event_sha256=`fc262b4698d09a5779d30f806bd99ba71b0323eaa1b8e4c5586bfecf5b22c77b`
- #9: `f156f57f-afb7-482f-b03e-02624ee84e79` | 2026-08-16T07:16:30.128Z | STATE_CHANGE/context_rescoped | incident=`998922f2-dafd-4af8-bdb6-47dc1e3d8a8b` | lesson_key=`context-pack-rescope` | event_sha256=`16130f4d5a8081872408f4b477eba937ddca1c24c7ff3286662dfc56ce65872e`
- #10: `a4b5c6d7-e8f9-4012-3456-789abcdef012` | 2026-08-16T07:22:00.000Z | ERROR/cutover_test_baseline_replaced | incident=`b5c6d7e8-f901-4234-5678-9abcdef01234` | lesson_key=`cutover-tests-append-only-baseline` | event_sha256=`345852d462cadfe6e521fbc4af0c89446a95c29ff252e4c2663aa949af785f55`
- #11: `b6c7d8e9-f012-4345-6789-abcdef012345` | 2026-08-16T07:28:00.000Z | GAP/cutover_legacy_runtime_bypass | incident=`c7d8e9f0-1234-4567-89ab-cdef01234567` | lesson_key=`cutover-legacy-runtime-admission-boundary` | event_sha256=`358ebd5c86c26eb265dde2f6eacd85ae75e847907852613a1ae49bef13deea13`
- #12: `c8d9e0f1-2345-4678-9abc-def012345678` | 2026-08-16T07:31:00.000Z | FAILURE/frontend_registry_contract_regression | incident=`d9e0f123-4567-489a-bcde-f0123456789a` | lesson_key=`registry-contract-test-update` | event_sha256=`a54e6dbe637adc54670e1b576e052dd82938e6cd91a05acef403f7f8004f9d41`
- #13: `c8a83077-5bb2-41a7-9984-764b33b5a36a` | 2026-08-16T07:25:55.333Z | STATE_CHANGE/context_rescope_required | incident=`3a04190a-3158-48a0-aac2-1b316d8977a4` | lesson_key=`context-pack-rescope` | event_sha256=`d371bcefb37ef657624d59d4a340852ac7f396bdcef3099b813dfb5bc588e411`
- #14: `9805c90a-5529-498c-8cc6-8fd8d171a346` | 2026-08-16T07:25:55.343Z | STATE_CHANGE/context_rescoped | incident=`732a3701-db13-4a90-8d28-fab2d415e371` | lesson_key=`context-pack-rescope` | event_sha256=`d1f7b147170b91fb407da130f606e4195d0a10316e0ce2b6c1d1db43dc377d98`
- #15: `d0e1f234-5678-49ab-cdef-0123456789ab` | 2026-08-16T07:35:00.000Z | GATE/cutover_lane_local_gate | incident=`e1f23456-789a-4bcd-ef01-23456789abcd` | lesson_key=`cutover-lane-local-gate-boundary` | event_sha256=`045bee20091302a26f51329c9cd5ae4e20af03df8cc60b209981754f1cd86e7b`
- #16: `e1f23456-789a-4bcd-ef01-23456789abcd` | 2026-08-16T07:38:00.000Z | STATE_CHANGE/agent_notebook_cutover_slice_completed | incident=`f2345678-9abc-4def-0123-456789abcdef` | lesson_key=`bounded-agent-notebook-cutover-close` | event_sha256=`4d43a6890af7ac3b8503b55e16791851f8567e2c730368a7a5cc0e9f4c0c69ea`
