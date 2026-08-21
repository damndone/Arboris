# Retrospective — v1-8-9-p0-notebook-materialization-retry-state

## Goal

# Workbench v1.8.9 P0 Notebook Materialization Retry State  ## Objective  When a typed Notebook option has a persisted Pipeline Draft, a failed execution returns the option to \`selected\` so the user can retry. Reusing the same server-owned materialization must restore the lifecycle to \`materialized\` before the next execution callback; otherwise a safe retry is incorrectly rejected even though the Draft and evidence are still valid.  ## Scope  - \`backend/workbench/agent/notebook/materialization.py\` - \`tests/test_notebook_trace_chain.py\`  ## Acceptance  - A selected option with an existing valid materialization can be retried and   transitions back to \`materialized\` exactly once per retry preparation. - The retry continues to use the existing Draft identity and binding; no new   Draft or unpinned source is created. - Trace evidence records the lifecycle transition and the subsequent   execution attempt. - Legacy options remain fail-closed and no execution/confirmation gate is   weakened. - Scoped tests, compile, diff check, formal verification, and retrospective   pass.

## Final status

COMPLETED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `146265ee-fc67-4b71-a625-1fc968fe3b5e` | 2026-08-21T08:43:23.846Z | STATE_CHANGE/line_started | incident=`28851b98-2f1e-46e9-bc97-7b9ea98cf541` | lesson_key=`frozen-context-before-start` | event_sha256=`415f8e99a974bb45d50d898e505554651d4149d8f32b9537cfee7c9b9a3ceab2`
- #2: `33333333-3333-4333-8333-333333333331` | 2026-08-21T08:47:30.089Z | GATE/materialization_retry_green | incident=`33333333-3333-4333-8333-333333333332` | lesson_key=`notebook-materialization-retry` | event_sha256=`401d310a9ba050a549208a36ee838b93783069bbc903ed1fafd91f6f55d892be`
- #3: `33333333-3333-4333-8333-333333333333` | 2026-08-21T08:47:30.215Z | STATE_CHANGE/line_completed | incident=`33333333-3333-4333-8333-333333333334` | lesson_key=`formal-closeout` | event_sha256=`39550a9546d702b28bdb8b7f66649e1368967cde40c85a4093cb6b772cd72010`
