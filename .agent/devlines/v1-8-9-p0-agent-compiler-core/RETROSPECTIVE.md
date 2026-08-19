# Retrospective — v1-8-9-p0-agent-compiler-core

## Goal

# v1.8.9 P0 Agent Compiler Objective  Build a registry-derived capability manifest, two-stage discovery, typed Agent Plan IR, PortType compatibility, FailureEnvelope and a server-owned compiler. The provider contract may emit only DraftAgentPlan. Build server compilation, CompilationRecord persistence and shadow-equivalence core without modifying orchestrator, operations, Notebook, routes, workflow runtime or central registries. Preserve current authorities until the explicit cutover line.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Branch: workbench-v1.8.9-p0-agent-compiler Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-agent-compiler Formal line: v1-8-9-p0-agent-compiler-core  Required outcomes: - Natural-language/provider output is strict untrusted draft IR, never authority or executable code. - Bounded registry-derived discovery exposes no arbitrary tool/model/provider. - Server compilation validates ports, scope, capability, safety and failure contracts, then persists an immutable CompilationRecord. - Shadow equivalence and adversarial tests prove current authority is not bypassed.  Boundaries: no workflow runtime/contracts, operations, orchestrator, Notebook, routes, data operations, predictive research, frontend, provider execution, dynamic imports or cutover. Formal state is managed only by scripts/devline_control.py.

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/8 (50.0%; 50.0 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=3)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T09:50:20.000Z `focused_red_collection`; cause_status: `known`; cause: Focused tests were written before the implementation modules and initially failed at collection.; resolution: `resolved`; lesson: Keep a confirmed RED run before adding the minimal implementation.

## All errors

- #3 2026-08-16T09:51:00.000Z `protected_contract_test_denominator`; cause_status: `external`; cause: The protected contract-lock parametrized test assumes one builtin provider, while the required agent.compiler declaration adds a second provider.; resolution: `accepted`; lesson: Treat fixed registry denominators as an explicit integration boundary when adding a declaration-only provider.
- #5 2026-08-16T09:52:30.000Z `ruff_unavailable`; cause_status: `external`; cause: The repository virtualenv does not provide the ruff module for the requested static check.; resolution: `accepted`; lesson: Record unavailable quality tooling separately from completed executable verification.

## All gaps

- #7 2026-08-16T09:54:00.000Z `runtime_acceptance_not_in_scope`; cause_status: `known`; cause: This line intentionally stops at the shadow-equivalence compiler core and does not perform runtime route cutover, provider execution, browser acceptance, or release integration.; resolution: `accepted`; lesson: Keep shadow-core evidence separate from runtime cutover and release acceptance.

## All waste

- None recorded.

## Root causes and solutions

- `protected-provider-denominator-boundary`: occurrences=1; cause_status: `external`; root cause: The protected contract-lock parametrized test assumes one builtin provider, while the required agent.compiler declaration adds a second provider.; solution: `accepted`
- `quality-tool-not-verified`: occurrences=1; cause_status: `external`; root cause: The repository virtualenv does not provide the ruff module for the requested static check.; solution: `accepted`
- `shadow-core-not-runtime-acceptance`: occurrences=1; cause_status: `known`; root cause: This line intentionally stops at the shadow-equivalence compiler core and does not perform runtime route cutover, provider execution, browser acceptance, or release integration.; solution: `accepted`
- `tdd-red-before-implementation`: occurrences=1; cause_status: `known`; root cause: Focused tests were written before the implementation modules and initially failed at collection.; solution: `resolved`

## Added tests

- `tests/contracts/test_v189_contract_lock.py`
- `tests/test_v189_agent_compiler.py`

## New rules

- `protected-provider-denominator-boundary`: line experience occurrence(s)=1
- `quality-tool-not-verified`: line experience occurrence(s)=1
- `shadow-core-not-runtime-acceptance`: line experience occurrence(s)=1
- `tdd-red-before-implementation`: line experience occurrence(s)=1

## Future guidance

- Keep a confirmed RED run before adding the minimal implementation.
- Keep authority provenance, bounded inputs, and runtime acceptance boundaries explicit in the handoff.
- Keep shadow-core evidence separate from runtime cutover and release acceptance.
- Record unavailable quality tooling separately from completed executable verification.
- Treat fixed registry denominators as an explicit integration boundary when adding a declaration-only provider.

## Event index

- #1: `54f2cd30-a796-4472-a8d1-c05b25261996` | 2026-08-16T09:28:53.752Z | STATE_CHANGE/line_started | incident=`9b3d1ce0-fc76-4031-93e2-dc54750dcde6` | lesson_key=`frozen-context-before-start` | event_sha256=`7918dd907dcc559d7433534938373e1e9755e5ee183dc4458aeba45c067388bf`
- #2: `0b024102-b13f-4a45-8caf-8d8f874f658e` | 2026-08-16T09:50:20.000Z | FAILURE/focused_red_collection | incident=`6882111b-7df0-4b6e-8c4e-5ec31b068c51` | lesson_key=`tdd-red-before-implementation` | event_sha256=`5c2b236d4510ea4151fc0866f13e48978c3aa899a48634de0f7e95b659fbe47b`
- #3: `f08675d7-5aee-4b78-a2d4-51eba98eca3b` | 2026-08-16T09:51:00.000Z | ERROR/protected_contract_test_denominator | incident=`4d028059-c75f-48be-bb09-29e259e0a1ca` | lesson_key=`protected-provider-denominator-boundary` | event_sha256=`3a0fcfc725b350f804c182956ded374855ff427db4d715457d73745bba9007a1`
- #4: `c8e7fdbd-0482-4839-bc0e-5889728df49b` | 2026-08-16T09:52:00.000Z | REVIEW/specification_self_audit | incident=`82c91c4f-64e6-4bf1-b29c-32015b14a06e` | lesson_key=`authority-boundary-self-audit` | event_sha256=`26148302ee573f4899d16b49b75553e13f8acc727e14ae178f2382438de41001`
- #5: `2869b77b-fac8-456c-bbd3-eef45459a920` | 2026-08-16T09:52:30.000Z | ERROR/ruff_unavailable | incident=`cb78bdc6-4cf4-4066-8f75-bef7c3183bba` | lesson_key=`quality-tool-not-verified` | event_sha256=`8cc82ef604887e4c4723c11cc0d53b6ac72369144b0f61c57cee15d02609a0d6`
- #6: `f2f6b239-2b45-473e-bb21-39972851fccf` | 2026-08-16T09:53:00.000Z | GATE/focused_tests_passed | incident=`dc8ca33f-037c-4dcd-a80c-6a05df52c462` | lesson_key=`focused-p0-gate` | event_sha256=`5e70f341c4c395788258bdf89e81ea523e38c0bf3cbe573a893a1e02d3028fcb`
- #7: `a1c452c1-9ffb-4030-8135-236107bca669` | 2026-08-16T09:54:00.000Z | GAP/runtime_acceptance_not_in_scope | incident=`a095e524-9677-486e-bd14-5b605aef39e5` | lesson_key=`shadow-core-not-runtime-acceptance` | event_sha256=`bdf64f145b589bf0cf6a3abd151816b8a7a465e48154dde7b9a1d6f024db3d93`
- #8: `a095e524-9677-486e-bd14-5b605aef39e5` | 2026-08-16T09:55:00.000Z | STATE_CHANGE/line_completed | incident=`c8e7fdbd-0482-4839-bc0e-5889728df49b` | lesson_key=`scoped-core-closeout` | event_sha256=`82173f4d4dcb98d8e5c3df220c6bb2d2d32569597a2d11fb4aac463ea5bd6c5a`
