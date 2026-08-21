# Retrospective — v1-8-9-p0-statistical-stage-import-cycle

## Goal

# Workbench v1.8.9 P0 statistical stage import-cycle and ARMA gate  Remove the production import cycle that prevents the ARMA-GARCH pack runtime from importing \`StatisticalTestsStage\`, then migrate the adjacent ARMA public workflow assertion to the current server-owned Report/evidence boundary. Keep the statistical algorithms, typed evidence contracts, and fail-closed Report authority unchanged.  Required outcomes:  - \`StatisticalTestsStage\` imports without a partially initialized orchestrator   package; - the ARMA pack runtime focused tests pass; - an unbound Report writer remains unavailable rather than silently generating   \`report.html\`; - no raw result or caller-owned Report authority fallback is restored; - the scoped test, compileall, and diff checks pass.

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

- #2 2026-08-21T05:50:56.047Z `statistical_stage_import_cycle_red`; cause_status: `known`; cause: The ARMA pack runtime focused suite reproduces a circular import: statistical_tests imports orchestrator._errors while orchestrator.__init__ imports StatisticalTestsStage before the class is defined.; resolution: `open`; lesson: Stage modules must not import their parent package during package initialization; public tests must assert the server-owned Report/evidence boundary rather than raw HTML fallback.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `statistical-stage-import-cycle-red`: occurrences=1; cause_status: `known`; root cause: The ARMA pack runtime focused suite reproduces a circular import: statistical_tests imports orchestrator._errors while orchestrator.__init__ imports StatisticalTestsStage before the class is defined.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `statistical-stage-import-cycle-red`: line experience occurrence(s)=1

## Future guidance

- Stage modules must not import their parent package during package initialization; public tests must assert the server-owned Report/evidence boundary rather than raw HTML fallback.

## Event index

- #1: `cad9a006-0eca-47e1-8db8-d9e789482ca6` | 2026-08-21T05:47:06.195Z | STATE_CHANGE/line_started | incident=`dfb8b56a-3846-41dd-911a-3b303d71d4e5` | lesson_key=`frozen-context-before-start` | event_sha256=`ceb2b580065eaaf008fd7a9b7f9a2a0efff12d395bef5733d9732af4979964c2`
- #2: `0a8b7c6d-5e4f-4321-9abc-def012345678` | 2026-08-21T05:50:56.047Z | FAILURE/statistical_stage_import_cycle_red | incident=`12345678-90ab-cdef-1234-567890abcdef` | lesson_key=`statistical-stage-import-cycle-red` | event_sha256=`9ef37fda03c56b3a6fce6ad9d1f12f97965360b9f2635db8b57b2b30ef7478cb`
- #3: `23456789-abcd-4ef0-9123-456789abcdef` | 2026-08-21T05:52:32.144Z | GATE/statistical_stage_import_cycle_green | incident=`abcdef01-2345-6789-abcd-ef0123456789` | lesson_key=`statistical-stage-import-cycle-gate` | event_sha256=`02a300c5194f5f2624d02049c9a68e03cf89ce939fd5b393162957a75470f39d`
- #4: `3456789a-bcde-4f01-9234-56789abcdef0` | 2026-08-21T05:52:50.796Z | STATE_CHANGE/statistical_stage_import_cycle_completed | incident=`456789ab-cdef-4012-9345-6789abcdef01` | lesson_key=`formal-terminal-state` | event_sha256=`d80090edf2bf3a325fa60cb35149ec3e1cad6e8623a961dd647c95b8fa316aea`
