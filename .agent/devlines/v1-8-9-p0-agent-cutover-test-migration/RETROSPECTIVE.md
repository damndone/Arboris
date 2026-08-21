# Retrospective — v1-8-9-p0-agent-cutover-test-migration

## Goal

# Workbench v1.8.9 P0 Agent/Notebook cutover test migration  ## Objective  Migrate historical direct calls to the Agent/Notebook cutover HTTP route into an explicit server-owned test harness after the identity boundary is closed. Tests must prove that an absent Request fails closed before authority or repository access, while bound HTTP requests still compile and preserve server-side confirmation behavior. Do not reintroduce a caller-controlled identity or a process-global authority shortcut.  ## Required evidence  - RED for the stale direct-call fixture after the identity hardening; - GREEN for the migrated cutover, route identity, natural-language, and   runtime-bridge tests; - compileall, diff check, formal verification, and retrospective; - browser, real provider, supervisor, multi-worker, full-host, merge, tag,   and release remain separate \`NOT VERIFIED\` gates.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/4 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T04:53:43.537Z `cutover_direct_fixture_red`; cause_status: `known`; cause: Historical cutover and runtime-bridge tests directly invoked route functions without a Request and expected caller-shaped scope metadata to select a compiler.; resolution: `open`; lesson: Route tests must exercise a real Request with server-owned identity binding when testing successful compilation; direct calls are negative fail-closed probes only.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `cutover-tests-need-host-harness`: occurrences=1; cause_status: `known`; root cause: Historical cutover and runtime-bridge tests directly invoked route functions without a Request and expected caller-shaped scope metadata to select a compiler.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `cutover-tests-need-host-harness`: line experience occurrence(s)=1

## Future guidance

- Route tests must exercise a real Request with server-owned identity binding when testing successful compilation; direct calls are negative fail-closed probes only.

## Event index

- #1: `b14f7ba9-ac7a-4b68-959a-f2fab84eb4de` | 2026-08-21T04:53:24.133Z | STATE_CHANGE/line_started | incident=`3d771411-b64e-40a6-9560-522c92d1d464` | lesson_key=`frozen-context-before-start` | event_sha256=`55aaa9564816eb46f6880fea3215c00dfc39e7eef3e463148155ec4a1634bed0`
- #2: `9abcdef0-1234-4567-889a-bcdef0123456` | 2026-08-21T04:53:43.537Z | FAILURE/cutover_direct_fixture_red | incident=`abcdef01-2345-4678-89ab-cdef01234567` | lesson_key=`cutover-tests-need-host-harness` | event_sha256=`addec9d90a992ffc629e93cfaaa1cbcdfc5b1dce2d0ff856e6355507ff3795be`
- #3: `bcdef012-3456-4789-8abc-def012345678` | 2026-08-21T04:56:56.328Z | GATE/cutover_http_harness_focused_green | incident=`cdef0123-4567-489a-8bcd-ef0123456789` | lesson_key=`cutover-http-harness` | event_sha256=`0486a40b1c470d63abf2725f18ebe165ca35121b7de1f8fd0085e39bf7caf6c2`
- #4: `def01234-5678-49ab-8cde-f0123456789a` | 2026-08-21T04:57:19.986Z | STATE_CHANGE/cutover_test_migration_line_completed | incident=`ef012345-6789-4abc-8def-0123456789ab` | lesson_key=`cutover-test-line-boundary` | event_sha256=`936f366df9f4df502c84e8cc35b9e904dfe8493140daf8ad42c6705eaafb2b48`
