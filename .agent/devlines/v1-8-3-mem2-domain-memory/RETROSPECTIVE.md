# Retrospective — v1-8-3-mem2-domain-memory

## Goal

Implement MEM2 as a scoped, append-only cross-project domain-memory control plane. Define immutable bounded content revisions, redacted source-access bindings and validity, candidate and approval/current-grant records, independent default-off use/iteration preferences, and deterministic fail-closed retrieval. The package may emit local bounded trace contracts and an unmounted HTTP adapter, but must not modify the shared Context Compiler, Core Trace, application mounting, Notebook mounting, capability ranking/admission, authorization, dependency installation, code execution, or dispatch paths. Memory may provide only current-evidence-checked hints and must never become an authority source or execution trigger. Prove namespace isolation, CAS approval, stale/revoked/deleted/tainted-source exclusion, redaction, boundedness, idempotent append-only persistence, default-off semantics, and no exercise-specific naming.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/9 (22.2%; 22.2 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-07-27T10:00:00.000Z `tdd_red_before_domain_memory_contract`; cause_status: `known`; cause: The MEM2 contract tests failed during collection because the new domain memory contract modules do not exist yet.; resolution: `accepted`; lesson: Define immutable content, approval, validity, and candidate contracts before persistence or retrieval.
- #7 2026-07-27T11:00:00.000Z `frontend_typecheck_async_response_red`; cause_status: `known`; cause: The new domain-memory API adapter initially passed a Promise<Response> where the shared response reader requires Response.; resolution: `resolved`; lesson: Run the frontend typecheck directly after adding an API adapter and await every shared response reader input.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `domain-memory-contract-first`: occurrences=1; cause_status: `known`; root cause: The MEM2 contract tests failed during collection because the new domain memory contract modules do not exist yet.; solution: `accepted`
- `frontend-api-awaits-response`: occurrences=1; cause_status: `known`; root cause: The new domain-memory API adapter initially passed a Promise<Response> where the shared response reader requires Response.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `domain-memory-contract-first`: line experience occurrence(s)=1
- `frontend-api-awaits-response`: line experience occurrence(s)=1

## Future guidance

- Cross-project memory must be an explicitly scoped, revocable hint source whose approval and source access are rechecked on every retrieval.
- Define immutable content, approval, validity, and candidate contracts before persistence or retrieval.
- Run the frontend typecheck directly after adding an API adapter and await every shared response reader input.

## Event index

- #1: `7970a04b-dea6-47eb-95b9-2c17737f124f` | 2026-07-27T06:39:53.601Z | STATE_CHANGE/line_started | incident=`79e260be-cf93-48b7-b309-9bc00e0c825e` | lesson_key=`frozen-context-before-start` | event_sha256=`0e04120bf91e4da97b8c68cc37863dcd2940ecd67f33a35c1aa7ab79523227d1`
- #2: `1a4e38cc-02ca-4b13-952a-2f9a85dbe54a` | 2026-07-27T06:40:37.199Z | STATE_CHANGE/context_rescope_required | incident=`9dbdb2a1-466c-47b6-b61c-fd3cf270c9bc` | lesson_key=`context-pack-rescope` | event_sha256=`77c23f438aee217c10f01ef20d4f107743c8a4648825198685874b37a34cc4fa`
- #3: `121d9e53-7b37-4fa0-a4f2-801a38c5bc41` | 2026-07-27T06:40:37.203Z | STATE_CHANGE/context_rescoped | incident=`c0607098-0007-4a73-a1f0-af439ade226e` | lesson_key=`context-pack-rescope` | event_sha256=`aa8fb5e34cca7f1a243f1104e36d57dc0a6d498d5d84b7e02cc7ad322069081b`
- #4: `11111111-2222-4333-8444-555555555555` | 2026-07-27T10:00:00.000Z | FAILURE/tdd_red_before_domain_memory_contract | incident=`22222222-3333-4444-8555-666666666666` | lesson_key=`domain-memory-contract-first` | event_sha256=`74e02fd41feef122ef793aded6fc7c5c581a8946f0f524687f307bf423295ae4`
- #5: `33333333-4444-4555-8666-777777777777` | 2026-07-27T11:00:00.000Z | REVIEW/mem2_control_plane_security_review_accepted | incident=`44444444-5555-4666-8777-888888888888` | lesson_key=`domain-memory-retrieval-rechecks-authority` | event_sha256=`82a6f2f2d31ab3d029710d5caa77725d9ceb10fe62434d5f3dc37c817f12eef1`
- #6: `55555555-6666-4777-8888-999999999999` | 2026-07-27T11:00:00.000Z | GATE/mem2_targeted_gate | incident=`66666666-7777-4888-8999-000000000000` | lesson_key=`mem2-targeted-gate-not-integration` | event_sha256=`e1e26f83b785ae5b2a40895133b6d190bd8b6f9f6c9abe28362aff8721ea2a12`
- #7: `77777777-8888-4999-9000-111111111111` | 2026-07-27T11:00:00.000Z | FAILURE/frontend_typecheck_async_response_red | incident=`88888888-9999-4000-8111-222222222222` | lesson_key=`frontend-api-awaits-response` | event_sha256=`57c50ca25eb8db9cefcb517fba22ff327b010ecda029696332038d91f7d7ba75`
- #8: `99999999-0000-4111-8222-333333333333` | 2026-07-27T11:00:00.000Z | GATE/mem2_targeted_gate | incident=`00000000-1111-4222-8333-444444444444` | lesson_key=`mem2-targeted-gate-not-integration` | event_sha256=`e3bca75dc1101f925ca4b5d354f296576fcf56fbcd1af7e003426cd52818dfa3`
- #9: `11111111-aaaa-4bbb-8ccc-222222222222` | 2026-07-27T11:05:00.000Z | STATE_CHANGE/mem2_domain_memory_completed | incident=`22222222-bbbb-4ccc-8ddd-333333333333` | lesson_key=`close-mem2-before-shared-integration` | event_sha256=`6ab8be99ba7199221494834b74b082d238dadd4a31ed9332d3b5494a83187b59`
