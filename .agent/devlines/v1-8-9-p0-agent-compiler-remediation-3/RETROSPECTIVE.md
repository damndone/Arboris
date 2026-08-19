# Retrospective — v1-8-9-p0-agent-compiler-remediation-3

## Goal

# v1.8.9 P0 Agent Compiler Remediation 3 Objective  Close the remaining Agent Compiler authority and multi-worker gaps before integration admission. Scope/principal/session binding must be issued by a server-owned authority that a caller cannot construct or re-issue from JSON; the public Agent/Notebook compiler path must not accept the historical ServerCompilationRecordIssuer bypass; and identical semantic intents must converge across independent compiler/store instances, not only within one Python process. Discovery and direct typed-draft entry must share the same natural-language eligibility and scope authority checks.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-agent-compiler-remediation-3 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-agent-compiler  Required outcomes:  - caller-created or deserialized ScopeAuthorityResolver/binding cannot issue   arbitrary scope, principal, session or project authority; - Agent/Notebook public compilation accepts only a new compiler-issued,   server-bound plan; historical C0 issuer/compiled aliases cannot bypass the   manifest, authority, policy and evidence gates. If the locked C0 contract   itself must change, record that as a separate contract dependency rather   than silently editing it; - identical intents across independent stores/processes have one durable   reservation/result or a stable conflict, never two server identities; - discovery and direct typed draft compilation both enforce   natural_language_enabled and the same server scope selection; - reconstructed JSON bindings, references, aliases and legacy objects fail   closed before compilation or runtime-visible persistence.  Keep C0 contract files locked in this package-local line. Do not modify runtime cutover, central catalog, frontend, provider integration, or protected paths.

## Final status

COMPLETED

## Metrics

- Failure frequency: 7/11 (63.6%; 63.6 per 100 events)
- Repeat rate: 0/7 (0.0%)
- Recurrence rate: 0/7 (0.0%)
- MTTR: N/A (sample=0; unresolved=7)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T11:20:12.000Z `scope_authority_red`; cause_status: `known`; cause: The adversarial red test showed that a caller can construct a scope binding and resolver and thereby select arbitrary scope and principal identity.; resolution: `open`; lesson: Require a server-owned sealed authority provider and reject caller-created or reconstructed bindings.
- #3 2026-08-16T11:20:12.000Z `selection_gate_red`; cause_status: `known`; cause: The adversarial red test showed that typed and JSON drafts enter PlanCompiler without a server-issued discovery selection.; resolution: `open`; lesson: Bind the public Agent and Notebook compiler path to a server-issued selection before draft validation.
- #4 2026-08-16T11:20:12.000Z `discovery_scope_red`; cause_status: `known`; cause: The adversarial red test showed that discovery accepts a caller-selected project scope after only checking its text format.; resolution: `open`; lesson: Discovery must resolve scope and principal through the same server authority as compilation.
- #5 2026-08-16T11:20:12.000Z `multi_store_reservation_red`; cause_status: `known`; cause: The adversarial red test showed that independent CompilationStore instances can both reserve one semantic key.; resolution: `open`; lesson: Use a durable cross-store reservation or return a stable conflict before compilation side effects.
- #7 2026-08-16T12:00:00.000Z `scope_bootstrap_proof_red`; cause_status: `known`; cause: The adversarial red probe showed that the private snapshot bootstrap still accepts caller input without a server proof.; resolution: `open`; lesson: Every authority bootstrap path, including package-local host seams, must require the server-owned proof object.
- #8 2026-08-16T12:00:00.000Z `public_durable_store_red`; cause_status: `known`; cause: The adversarial red probe showed that a valid public compile can run with a pure in-memory CompilationStore.; resolution: `open`; lesson: Public compilation must fail closed unless its store has an admitted durable reservation root.

## All errors

- None recorded.

## All gaps

- #6 2026-08-16T11:21:30.000Z `legacy_c0_issuer_dependency`; cause_status: `external`; cause: The locked C0 planning contract still exposes a historical ServerCompilationRecordIssuer entry point that this package-local line is not allowed to edit.; resolution: `open`; lesson: Do not claim legacy authority is closed while the locked C0 issuer remains a reachable public entry point.

## All waste

- None recorded.

## Root causes and solutions

- `compiler-bootstrap-proof`: occurrences=1; cause_status: `known`; root cause: The adversarial red probe showed that the private snapshot bootstrap still accepts caller input without a server proof.; solution: `open`
- `compiler-durable-reservation`: occurrences=1; cause_status: `known`; root cause: The adversarial red test showed that independent CompilationStore instances can both reserve one semantic key.; solution: `open`
- `compiler-public-durable-store`: occurrences=1; cause_status: `known`; root cause: The adversarial red probe showed that a valid public compile can run with a pure in-memory CompilationStore.; solution: `open`
- `compiler-sealed-scope-authority`: occurrences=1; cause_status: `known`; root cause: The adversarial red test showed that a caller can construct a scope binding and resolver and thereby select arbitrary scope and principal identity.; solution: `open`
- `compiler-selection-admission`: occurrences=1; cause_status: `known`; root cause: The adversarial red test showed that typed and JSON drafts enter PlanCompiler without a server-issued discovery selection.; solution: `open`
- `discovery-server-scope-binding`: occurrences=1; cause_status: `known`; root cause: The adversarial red test showed that discovery accepts a caller-selected project scope after only checking its text format.; solution: `open`
- `legacy-c0-issuer-dependency`: occurrences=1; cause_status: `external`; root cause: The locked C0 planning contract still exposes a historical ServerCompilationRecordIssuer entry point that this package-local line is not allowed to edit.; solution: `open`

## Added tests

- `tests/test_v189_agent_compiler.py`
- `tests/test_v189_agent_compiler.py::test_direct_typed_or_json_draft_requires_server_discovery_selection`
- `tests/test_v189_agent_compiler.py::test_discovery_scope_cannot_be_selected_by_caller_string`
- `tests/test_v189_agent_compiler.py::test_independent_compilation_stores_do_not_both_reserve_same_key`
- `tests/test_v189_agent_compiler.py::test_public_compiler_requires_durable_reservation_store`
- `tests/test_v189_agent_compiler.py::test_scope_authority_resolver_is_not_caller_constructible_or_reissuable`

## New rules

- `compiler-bootstrap-proof`: line experience occurrence(s)=1
- `compiler-durable-reservation`: line experience occurrence(s)=1
- `compiler-public-durable-store`: line experience occurrence(s)=1
- `compiler-sealed-scope-authority`: line experience occurrence(s)=1
- `compiler-selection-admission`: line experience occurrence(s)=1
- `discovery-server-scope-binding`: line experience occurrence(s)=1
- `legacy-c0-issuer-dependency`: line experience occurrence(s)=1

## Future guidance

- Bind the public Agent and Notebook compiler path to a server-issued selection before draft validation.
- Discovery must resolve scope and principal through the same server authority as compilation.
- Do not claim legacy authority is closed while the locked C0 issuer remains a reachable public entry point.
- Every authority bootstrap path, including package-local host seams, must require the server-owned proof object.
- Public compilation must fail closed unless its store has an admitted durable reservation root.
- Record package-local green evidence separately from integration and contract-cutover evidence.
- Require a server-owned sealed authority provider and reject caller-created or reconstructed bindings.
- Use a durable cross-store reservation or return a stable conflict before compilation side effects.

## Event index

- #1: `c7f1e1cf-ecd1-4b84-9308-0876aee87023` | 2026-08-16T11:16:17.837Z | STATE_CHANGE/line_started | incident=`fe5a7527-9e61-4614-8fc0-4dbbc9579526` | lesson_key=`frozen-context-before-start` | event_sha256=`ecf328d8d2c5979b30698a167408e082d05233b1c82e218c321ec2dda0477174`
- #2: `0b1c2d3e-4f50-6789-abcd-000000000001` | 2026-08-16T11:20:12.000Z | FAILURE/scope_authority_red | incident=`0b1c2d3e-4f50-6789-abcd-000000000011` | lesson_key=`compiler-sealed-scope-authority` | event_sha256=`668782c9dca4a6ee7e1f12e16a323c52ef436bb8066c4f5d6b3de4d987c2ff77`
- #3: `0b1c2d3e-4f50-6789-abcd-000000000002` | 2026-08-16T11:20:12.000Z | FAILURE/selection_gate_red | incident=`0b1c2d3e-4f50-6789-abcd-000000000012` | lesson_key=`compiler-selection-admission` | event_sha256=`d0cb528ac899b472ce445bf1202d4abc336e16799c8b031c2df4a5b66a3fec07`
- #4: `0b1c2d3e-4f50-6789-abcd-000000000003` | 2026-08-16T11:20:12.000Z | FAILURE/discovery_scope_red | incident=`0b1c2d3e-4f50-6789-abcd-000000000013` | lesson_key=`discovery-server-scope-binding` | event_sha256=`1a68fbcb5ad7448de8722ee772004f6d22cdc5b3d7a70ba1247cc30976abbe14`
- #5: `0b1c2d3e-4f50-6789-abcd-000000000004` | 2026-08-16T11:20:12.000Z | FAILURE/multi_store_reservation_red | incident=`0b1c2d3e-4f50-6789-abcd-000000000014` | lesson_key=`compiler-durable-reservation` | event_sha256=`463616ddb11464d68460eba67e88f5f6ffdc355688544bbe02c1076c5caccd6f`
- #6: `0b1c2d3e-4f50-6789-abcd-000000000005` | 2026-08-16T11:21:30.000Z | GAP/legacy_c0_issuer_dependency | incident=`0b1c2d3e-4f50-6789-abcd-000000000015` | lesson_key=`legacy-c0-issuer-dependency` | event_sha256=`e94612720775d5cd6acec5c8dabf9fafe97e4214defa5a36c2145a21125c068f`
- #7: `0b1c2d3e-4f50-6789-abcd-000000000006` | 2026-08-16T12:00:00.000Z | FAILURE/scope_bootstrap_proof_red | incident=`0b1c2d3e-4f50-6789-abcd-000000000016` | lesson_key=`compiler-bootstrap-proof` | event_sha256=`b40ef14add0292b70cd80f929f9b9d832dd5d3a54650175913c3d1e4434b33f9`
- #8: `0b1c2d3e-4f50-6789-abcd-000000000007` | 2026-08-16T12:00:00.000Z | FAILURE/public_durable_store_red | incident=`0b1c2d3e-4f50-6789-abcd-000000000017` | lesson_key=`compiler-public-durable-store` | event_sha256=`3d91524f8e82dbcd6127732eb0ff2e56a6f9a70df1e5b5f68de51bb75728cb4d`
- #9: `0b1c2d3e-4f50-6789-abcd-000000000008` | 2026-08-16T12:10:00.000Z | REVIEW/remediation3_direct_probe_review | incident=`0b1c2d3e-4f50-6789-abcd-000000000018` | lesson_key=`compiler-package-vs-integration-evidence` | event_sha256=`42cc988a725d420bdc037fbc6e28dea2bfcb433eea54f26e7c29fedaadf7bba5`
- #10: `0b1c2d3e-4f50-6789-abcd-000000000009` | 2026-08-16T12:15:00.000Z | GATE/remediation3_focused_gate | incident=`0b1c2d3e-4f50-6789-abcd-000000000019` | lesson_key=`compiler-focused-gate-separate-from-host` | event_sha256=`76d53aecc9ecf5d91cd5bc17cbe5cfc200ed498135ab1e52609ed9fe74fc8081`
- #11: `0b1c2d3e-4f50-6789-abcd-000000000010` | 2026-08-16T12:20:00.000Z | STATE_CHANGE/remediation3_package_local_completed | incident=`0b1c2d3e-4f50-6789-abcd-000000000020` | lesson_key=`compiler-remediation-handoff-boundary` | event_sha256=`4c885684efee573e593e80f9a9b1d9545b58ef7738a9b610786d85ee67661415`
