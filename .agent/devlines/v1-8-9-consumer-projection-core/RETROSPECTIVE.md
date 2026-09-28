# Retrospective — v1-8-9-consumer-projection-core

## Goal

# v1.8.9 Consumer Projection Core Objective  ## Objective  Implement a bounded, schema-versioned projection layer for Results, Agent, Notebook, Report and UI. The only statistical source is a server-persisted \`EvidenceEnvelopeV1\` binding. Projection code may select, redact, order and render persisted facts, but must never recompute estimates, infer missing values, invoke a model/statistical routine, or promote an availability or validation state.  Every consumer projection must retain the same artifact, envelope and fact identity. Missing, unsupported, incomplete or restricted facts remain \`UNAVAILABLE\`, \`DEGRADED\` or \`BLOCKED\`. Remote/provider egress is bounded, sensitivity-aware and receipt-backed; unknown sensitivity and unknown schema, renderer or policy fail closed.  ## Exact baseline and upstream authority  - Worktree: \`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-wave-a\` - Branch: \`workbench-v1.8.9-wave-a\` - Baseline SHA: \`c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749\` - Contract Lock C0 handoff: \`docs/superpowers/handoff/2026-08-15-v1.8.9-contract-lock-handoff.md\` - C0 catalog digest: \`cac54a40f62620b84d288416ee09d5b04814f4dbcb2c8ee3a4595522e3e0da40\` - Evidence envelope contract digest: \`a3aa7ac15779077042ef3f0e15ada0df6e1aefc555723c1617f5876d98a22835\` - Evidence persistence contract digest: \`44105bfc2fdada97a92c136bf29e4e2762e4098bbc5207fa47eb27509d0023f2\` - Context egress contract digest: \`892d6f672a9de9fae50dfe2c029a97e00dc24fede045df6ca9cf35e3c6b10817\`  The three P0 C1 implementation handoffs named by the implementation plan are not present in this worktree at the baseline. This line therefore consumes only their locked public contract seam and must not recreate their private implementation. Real C1 integration remains a separate acceptance boundary.  ## In-scope paths  - \`backend/workbench/evidence/consumer_adapters.py\` - \`backend/workbench/evidence/coverage.py\` - \`backend/workbench/services/results_service.py\` - \`backend/workbench/agent/context_tools.py\` - \`backend/workbench/agent/notebook/evidence.py\` - \`backend/workbench/report_view_model.py\` - \`backend/workbench/providers/builtin/consumer_projection.json\` - \`frontend/src/report/FamilyEvidence.tsx\` - \`frontend/src/report/FamilyEvidence.test.tsx\` - \`frontend/src/report/reportEvidence.ts\` - \`frontend/src/notebook/evidenceContracts.ts\` - \`tests/test_v189_consumer_projection.py\` - \`tests/test_v189_consumer_coverage.py\` - this objective, Work Order and completion handoff  ## Protected boundaries  Do not modify workflow runtime, planning compiler, central capability or workflow adapter registries, Notebook planner, ReportView, sectionRegistry mounts, the completed P1 data-consumer files, statistical implementations, provider execution, or any release/integration artifact outside this line. Do not add an LLM inference path, generic raw-dict fallback, client fact admission, zero/empty fallback, or raw-row remote egress.  ## Required evidence  - TDD red-first tests for persisted read admission, identity/value parity,   fact-level status/provenance preservation, sensitivity redaction, egress   receipts, bounded budgets, extension discovery and declaration-derived   coverage. - Focused backend projection and coverage suites. - Focused \`FamilyEvidence\` frontend tests and frontend typecheck. - \`git diff --check\`, formal event verification and CLI-generated retrospective. - Handoff must separate implementation, focused tests, formal process evidence,   and \`NOT VERIFIED\` C1 integration, browser, production mount, provider,   full-gate and release evidence.

## Final status

COMPLETED

## Metrics

- Failure frequency: 10/16 (62.5%; 62.5 per 100 events)
- Repeat rate: 0/10 (0.0%)
- Recurrence rate: 0/10 (0.0%)
- MTTR: median=0 ms (sample=5; unresolved=5)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #6 2026-08-16T06:20:55.000Z `projection_contract_tdd_red`; cause_status: `known`; cause: The first focused TDD run collected the newly added projection tests before the owned consumer_adapters and coverage modules existed, so the expected imports failed with ModuleNotFoundError.; resolution: `accepted`; lesson: Run the focused contract tests before implementation and preserve the red result as evidence of the test-first boundary.
- #8 2026-08-16T06:22:10.000Z `projection_source_order_mismatch`; cause_status: `known`; cause: The first implementation sorted persisted NumericFactV1 values by fact_id for every consumer, while the cross-consumer contract requires the source envelope identity and ordering to remain unchanged.; resolution: `open`; lesson: A projection ordering declaration must not silently reorder a persisted envelope when same-source identity includes sequence; preserve the envelope sequence in the minimal port slice.
- #9 2026-08-16T06:25:31.000Z `typed_frontend_projection_tdd_red`; cause_status: `known`; cause: The newly added frontend contract test supplied a typed evidence projection while FamilyEvidence still had only the legacy family-model branch, so React rendered no typed projection element.; resolution: `accepted`; lesson: Add typed consumer UI contributions behind an explicit prop and keep legacy report behavior unchanged.

## All errors

- #2 2026-08-16T06:15:24.000Z `inspection_missing_interpreter`; cause_status: `known`; cause: A read-only fixture inspection invoked the unavailable python command instead of the repository interpreter.; resolution: `resolved`; lesson: Use the repository interpreter from the frozen Context Pack for every fixture and gate command.
- #3 2026-08-16T06:15:29.000Z `locale_sensitive_hash_command`; cause_status: `external`; cause: The first read-only hash command failed in the shell locale setup before producing a digest.; resolution: `resolved`; lesson: Set the supported LC_ALL and LANG values before repository verification commands.
- #5 2026-08-16T06:18:05.000Z `formal_event_timestamp_validation`; cause_status: `known`; cause: The first append attempt used a UTC RFC3339 timestamp without millisecond precision and was rejected by the formal event validator.; resolution: `resolved`; lesson: Use millisecond-precision UTC RFC3339 timestamps for every formal event source.
- #7 2026-08-16T06:20:55.000Z `formal_event_preventability_validation`; cause_status: `known`; cause: The first append attempt for the TDD red event used an unsupported preventability value and was rejected by the formal event validator.; resolution: `resolved`; lesson: Use only the formal preventability vocabulary already present in the line event stream.
- #10 2026-08-16T06:28:25.000Z `typed_frontend_api_compatibility`; cause_status: `known`; cause: The first reportEvidence contribution replaced an existing shared module instead of preserving its groupFacts, capability-manifest, and display-label exports used by legacy report consumers.; resolution: `resolved`; lesson: When an owned module already has public consumers, extend its API additively and preserve every existing export.

## All gaps

- #4 2026-08-16T06:18:05.000Z `p0_c1_handoff_missing`; cause_status: `known`; cause: The implementation plan declares v1-8-9-p0-workflow-truth-core, v1-8-9-p0-evidence-core, and v1-8-9-p0-agent-compiler-core dependencies, but their formal handoffs and retrospectives are absent at baseline c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749.; resolution: `open`; lesson: When C1 producers are absent, keep consumer projections port-based and fail closed; never reimplement dependency internals.
- #11 2026-08-16T06:28:25.000Z `frontend_typecheck_existing_source_missing`; cause_status: `known`; cause: The focused frontend typecheck still fails because an existing untracked ClassificationEvidence.test.tsx imports missing ClassificationEvidence.tsx; that source is outside this line's owned paths and is not present at baseline.; resolution: `open`; lesson: Keep unrelated missing consumer sources as an explicit known gate and do not expand an owned-path scope to repair them.

## All waste

- None recorded.

## Root causes and solutions

- `c1-handoff-missing`: occurrences=1; cause_status: `known`; root cause: The implementation plan declares v1-8-9-p0-workflow-truth-core, v1-8-9-p0-evidence-core, and v1-8-9-p0-agent-compiler-core dependencies, but their formal handoffs and retrospectives are absent at baseline c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749.; solution: `open`
- `formal-event-timestamp-precision`: occurrences=1; cause_status: `known`; root cause: The first append attempt used a UTC RFC3339 timestamp without millisecond precision and was rejected by the formal event validator.; solution: `resolved`
- `formal-event-vocabulary`: occurrences=1; cause_status: `known`; root cause: The first append attempt for the TDD red event used an unsupported preventability value and was rejected by the formal event validator.; solution: `resolved`
- `frontend-typecheck-owned-scope-gap`: occurrences=1; cause_status: `known`; root cause: The focused frontend typecheck still fails because an existing untracked ClassificationEvidence.test.tsx imports missing ClassificationEvidence.tsx; that source is outside this line's owned paths and is not present at baseline.; solution: `open`
- `preserve-existing-frontend-exports`: occurrences=1; cause_status: `known`; root cause: The first reportEvidence contribution replaced an existing shared module instead of preserving its groupFacts, capability-manifest, and display-label exports used by legacy report consumers.; solution: `resolved`
- `preserve-persisted-fact-order`: occurrences=1; cause_status: `known`; root cause: The first implementation sorted persisted NumericFactV1 values by fact_id for every consumer, while the cross-consumer contract requires the source envelope identity and ordering to remain unchanged.; solution: `open`
- `projection-contract-tdd-red`: occurrences=1; cause_status: `known`; root cause: The first focused TDD run collected the newly added projection tests before the owned consumer_adapters and coverage modules existed, so the expected imports failed with ModuleNotFoundError.; solution: `accepted`
- `repository-interpreter-path`: occurrences=1; cause_status: `known`; root cause: A read-only fixture inspection invoked the unavailable python command instead of the repository interpreter.; solution: `resolved`
- `supported-locale-before-verification`: occurrences=1; cause_status: `external`; root cause: The first read-only hash command failed in the shell locale setup before producing a digest.; solution: `resolved`
- `typed-ui-contribution-tdd-red`: occurrences=1; cause_status: `known`; root cause: The newly added frontend contract test supplied a typed evidence projection while FamilyEvidence still had only the legacy family-model branch, so React rendered no typed projection element.; solution: `accepted`

## Added tests

- `frontend/src/report/ClassificationEvidence.test.tsx`
- `frontend/src/report/FamilyEvidence.test.tsx`
- `frontend/src/report/reportEvidence.ts`
- `tests/test_v189_consumer_projection.py`
- `tests/test_v189_consumer_projection.py tests/test_v189_consumer_coverage.py frontend/src/report/FamilyEvidence.test.tsx`
- `tests/test_v189_consumer_projection.py::test_cross_consumer_projection_preserves_identity_values_and_status_axes`

## New rules

- `c1-handoff-missing`: line experience occurrence(s)=1
- `formal-event-timestamp-precision`: line experience occurrence(s)=1
- `formal-event-vocabulary`: line experience occurrence(s)=1
- `frontend-typecheck-owned-scope-gap`: line experience occurrence(s)=1
- `preserve-existing-frontend-exports`: line experience occurrence(s)=1
- `preserve-persisted-fact-order`: line experience occurrence(s)=1
- `projection-contract-tdd-red`: line experience occurrence(s)=1
- `repository-interpreter-path`: line experience occurrence(s)=1
- `supported-locale-before-verification`: line experience occurrence(s)=1
- `typed-ui-contribution-tdd-red`: line experience occurrence(s)=1

## Future guidance

- A projection ordering declaration must not silently reorder a persisted envelope when same-source identity includes sequence; preserve the envelope sequence in the minimal port slice.
- Add typed consumer UI contributions behind an explicit prop and keep legacy report behavior unchanged.
- Keep unrelated missing consumer sources as an explicit known gate and do not expand an owned-path scope to repair them.
- Review the persisted sequence boundary explicitly whenever a projection declares an ordering policy.
- Run the focused contract tests before implementation and preserve the red result as evidence of the test-first boundary.
- Set the supported LC_ALL and LANG values before repository verification commands.
- Use millisecond-precision UTC RFC3339 timestamps for every formal event source.
- Use only the formal preventability vocabulary already present in the line event stream.
- Use the repository interpreter from the frozen Context Pack for every fixture and gate command.
- When C1 producers are absent, keep consumer projections port-based and fail closed; never reimplement dependency internals.
- When an owned module already has public consumers, extend its API additively and preserve every existing export.

## Event index

- #1: `f95944a3-1d2a-420e-94d3-d5f8a84eb4ce` | 2026-08-16T06:12:44.075Z | STATE_CHANGE/line_started | incident=`8f7008e3-ee6e-4866-a58b-9f359daa7e44` | lesson_key=`frozen-context-before-start` | event_sha256=`cb7affffa1c5b2a4c6fd166544753c537704015a46e7a49972a9481fb27eb5ba`
- #2: `3f2a6e9c-1d7b-4a8e-9c20-5b6d7f8e9012` | 2026-08-16T06:15:24.000Z | ERROR/inspection_missing_interpreter | incident=`c9d3a4e5-f607-4891-a2b3-c4d5e6f70819` | lesson_key=`repository-interpreter-path` | event_sha256=`f3f479ba1ad7f8ae061d6cb26e52eae5d5c95fa30e616b174895609747d2e218`
- #3: `4a6e9c1d-7b3f-4a8e-9c20-5b6d7f8e9013` | 2026-08-16T06:15:29.000Z | ERROR/locale_sensitive_hash_command | incident=`d4e5f607-1829-4ab3-cdef-456789012346` | lesson_key=`supported-locale-before-verification` | event_sha256=`d75d7219826823bfa1f0d054932fbe976327665fddb9be2ee2324e1982b6d633`
- #4: `5b7f1a2c-3d4e-4f50-8a61-7b8c9d0e1f23` | 2026-08-16T06:18:05.000Z | GAP/p0_c1_handoff_missing | incident=`6c8d9e0f-1a2b-43c4-9d5e-6f708192a3b4` | lesson_key=`c1-handoff-missing` | event_sha256=`04e34a82625b1fe88e3d51bfbb9840a12fee3ad8b3d160b5357849f448897caf`
- #5: `7d9e0f1a-2b3c-45d6-8e7f-9012a3b4c5d6` | 2026-08-16T06:18:05.000Z | ERROR/formal_event_timestamp_validation | incident=`8e0f1a2b-3c4d-4567-9e80-1234a5b6c7d8` | lesson_key=`formal-event-timestamp-precision` | event_sha256=`a6dd13bc0c042f82425a0c06fa4b40d98499cef15a9fde143f52c027b85eb189`
- #6: `9f1a2b3c-4d5e-4678-9a0b-1c2d3e4f5061` | 2026-08-16T06:20:55.000Z | FAILURE/projection_contract_tdd_red | incident=`a2b3c4d5-e6f7-4890-a1b2-c3d4e5f60718` | lesson_key=`projection-contract-tdd-red` | event_sha256=`01737f6e726c0a7bbd4324c0525f378afd56ef6e82ee48881b7f8b6e5484c704`
- #7: `b3c4d5e6-f708-49a1-b2c3-d4e5f6071829` | 2026-08-16T06:20:55.000Z | ERROR/formal_event_preventability_validation | incident=`c4d5e6f7-0819-4a2b-3c4d-5e6f708192a3` | lesson_key=`formal-event-vocabulary` | event_sha256=`685278f03967f6b15313d2a653a7081c358bb523de81a5ef56bcf82011a207b6`
- #8: `d5e6f708-192a-4b3c-5d6e-7f8091a2b3c4` | 2026-08-16T06:22:10.000Z | FAILURE/projection_source_order_mismatch | incident=`e6f70819-2a3b-4c5d-6e7f-8091a2b3c4d5` | lesson_key=`preserve-persisted-fact-order` | event_sha256=`05460d50bd417e5ee5fd19f2625a188650f61d2373fc579b1e443ee0d6ff8c1a`
- #9: `f708192a-3b4c-4d5e-6f70-8192a3b4c5d6` | 2026-08-16T06:25:31.000Z | FAILURE/typed_frontend_projection_tdd_red | incident=`08192a3b-4c5d-6e7f-8091-a2b3c4d5e6f7` | lesson_key=`typed-ui-contribution-tdd-red` | event_sha256=`47df72f9a7f7f64bbae49e6d0484e35490b383c58f4a2b47dd82c26a97c0b0ea`
- #10: `192a3b4c-5d6e-4f70-8192-a3b4c5d6e7f8` | 2026-08-16T06:28:25.000Z | ERROR/typed_frontend_api_compatibility | incident=`2a3b4c5d-6e7f-4890-a1b2-c3d4e5f60718` | lesson_key=`preserve-existing-frontend-exports` | event_sha256=`f36ec471b168c0b60320547170c260cb7d0c5922753f70abc8c52469ba4866e8`
- #11: `3b4c5d6e-7f80-491a-2b3c-4d5e6f708192` | 2026-08-16T06:28:25.000Z | GAP/frontend_typecheck_existing_source_missing | incident=`4c5d6e7f-8091-4a2b-3c4d-5e6f708192a3` | lesson_key=`frontend-typecheck-owned-scope-gap` | event_sha256=`b654985802a6f811a20f746dccf8a5bafbc86b5f3c768ecc7ce1306a4178be08`
- #12: `4c5d6e7f-8091-4a2b-3c4d-5e6f708192a3` | 2026-08-16T06:29:51.000Z | REVIEW/persisted_source_order_review_passed | incident=`5d6e7f80-91a2-4b3c-4d5e-6f708192a3b4` | lesson_key=`source-order-review-passed` | event_sha256=`c4448e852661b32cc804b76cc47e4f90beb44b7078bac2c7a571c1624777c087`
- #13: `6e7f8091-a2b3-4c5d-6e7f-8091a2b3c4d5` | 2026-08-16T06:29:51.000Z | GATE/consumer_projection_focused_gate | incident=`7f8091a2-b3c4-4d5e-6f70-8192a3b4c5d6` | lesson_key=`focused-projection-gate-boundary` | event_sha256=`376a10364dd159c090d730ad19703c5ed82a760155538494ac5ce854066c404c`
- #14: `8091a2b3-c4d5-4e6f-7081-92a3b4c5d6e7` | 2026-08-16T06:31:45.000Z | GATE/formal_verify_and_diff_check | incident=`91a2b3c4-d5e6-4f70-8192-a3b4c5d6e7f8` | lesson_key=`formal-verify-before-close` | event_sha256=`86719be79de04c9e7c0b4d99e59804547b23df294b6e74ec4936417e5217ac88`
- #15: `a2b3c4d5-e6f7-4890-a1b2-c3d4e5f60718` | 2026-08-16T06:32:00.000Z | STATE_CHANGE/consumer_projection_slice_completed | incident=`b3c4d5e6-f708-49a1-b2c3-d4e5f6071829` | lesson_key=`bounded-consumer-line-close` | event_sha256=`3e40ff06f9e227f02ed1baf0edc8e61d5076b9d0e526031bda50467b78bdfbec`
- #16: `c4d5e6f7-0819-4a2b-3c4d-5e6f708192a3` | 2026-08-16T06:32:15.000Z | GATE/final_focused_verification | incident=`d5e6f708-192a-4b3c-5d6e-7f8091a2b3c4` | lesson_key=`final-focused-verification` | event_sha256=`1debcb949c02666582e755137525705108d214c97141314472448ac298262d92`
