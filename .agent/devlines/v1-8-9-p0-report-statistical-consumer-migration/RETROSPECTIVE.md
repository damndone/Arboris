# Retrospective — v1-8-9-p0-report-statistical-consumer-migration

## Goal

# Workbench v1.8.9 P0 Statistical Consumer Migration  ## Objective  Migrate remaining statistical tests that consume \`reports/report.html\` or assume legacy Report output to the typed diagnostic, model-result, label, and Report-unavailable contracts. Preserve the actual statistical assertions and ensure unsupported/unbound presentation remains fail-closed.  ## Scope  - \`tests/test_ols_weights_v186.py\` - \`tests/test_orchestrator_e2e.py\` - \`tests/test_p0_regression.py\`  ## Acceptance  - Focused tests pass without restoring unbound HTML authority. - Weighting, Poisson offset/fallback, model outputs, diagnostics, and lineage   remain asserted through durable typed evidence. - Any Report assertion uses typed unavailable evidence when the host owner is   absent. - Compile, diff check, formal verify, and retrospective pass.  ## Non-goals  Do not modify statistical estimators or weaken model result correctness merely to satisfy presentation-only assertions.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/7 (42.9%; 42.9 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-21T08:37:43.145Z `tdd_red_report_consumers`; cause_status: `known`; cause: The focused statistical consumer suite still read unbound reports/report.html and asserted legacy sampling and Poisson fallback behavior after the typed report and fail-closed survey contracts were active.; resolution: `resolved`; lesson: Migrate presentation consumers to durable typed evidence while preserving model, diagnostic, weighting, offset, fallback, trace, and lineage behavior.

## All errors

- #2 2026-08-21T08:36:34.524Z `formal_cli_target_worktree_import`; cause_status: `known`; cause: The first formal control invocation used the shared virtual environment without explicitly placing this worktree backend first, so the CLI imported a different worktree's development-control module.; resolution: `resolved`; lesson: Run formal control commands with the target worktree backend explicitly first when linked worktrees share a virtual environment.
- #3 2026-08-21T08:37:03.011Z `formal_event_source_unavailable`; cause_status: `known`; cause: The first append attempt placed the temporary event source in the shared workspace root rather than the target linked worktree, so the formal CLI rejected the repository-relative source as unavailable.; resolution: `resolved`; lesson: Provide repository-relative event source paths inside the target worktree to devline_control append.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `formal-cli-target-worktree-import`: occurrences=1; cause_status: `known`; root cause: The first formal control invocation used the shared virtual environment without explicitly placing this worktree backend first, so the CLI imported a different worktree's development-control module.; solution: `resolved`
- `formal-event-source-worktree-relative`: occurrences=1; cause_status: `known`; root cause: The first append attempt placed the temporary event source in the shared workspace root rather than the target linked worktree, so the formal CLI rejected the repository-relative source as unavailable.; solution: `resolved`
- `typed-report-consumer-boundary`: occurrences=1; cause_status: `known`; root cause: The focused statistical consumer suite still read unbound reports/report.html and asserted legacy sampling and Poisson fallback behavior after the typed report and fail-closed survey contracts were active.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `formal-cli-target-worktree-import`: line experience occurrence(s)=1
- `formal-event-source-worktree-relative`: line experience occurrence(s)=1
- `typed-report-consumer-boundary`: line experience occurrence(s)=1

## Future guidance

- Keep presentation consumers on durable typed evidence and leave unbound Report unavailable.
- Migrate presentation consumers to durable typed evidence while preserving model, diagnostic, weighting, offset, fallback, trace, and lineage behavior.
- Provide repository-relative event source paths inside the target worktree to devline_control append.
- Run formal control commands with the target worktree backend explicitly first when linked worktrees share a virtual environment.

## Event index

- #1: `59d24f9a-11a1-4d6b-9e6c-075eeccfcb5f` | 2026-08-21T08:24:12.749Z | STATE_CHANGE/line_started | incident=`12824e45-b29d-4860-afc2-fca4fb5ac4fa` | lesson_key=`frozen-context-before-start` | event_sha256=`ae030db954792f7902511c94e7b7faa49bb2949c27d4bc49887cc1b7d414e1b4`
- #2: `a6b7c8d9-e0f1-4234-8567-8a9b0c1d2e3f` | 2026-08-21T08:36:34.524Z | ERROR/formal_cli_target_worktree_import | incident=`b7c8d9e0-f1a2-4345-9678-9b0c1d2e3f4a` | lesson_key=`formal-cli-target-worktree-import` | event_sha256=`ce779b33d19c2a21ef9bc8677a75138c25359d0c6d5c29be8239f79fb336048f`
- #3: `e7f8a9b0-c1d2-4567-8e90-f1a2b3c4d5e6` | 2026-08-21T08:37:03.011Z | ERROR/formal_event_source_unavailable | incident=`f8a9b0c1-d2e3-4678-9f01-a2b3c4d5e6f7` | lesson_key=`formal-event-source-worktree-relative` | event_sha256=`91bf08d6ac41bf5a193f238b0d37e89992cea89b869ca527b8d6be8660c08dd8`
- #4: `c8d9e0f1-a2b3-4456-a789-0c1d2e3f4a5b` | 2026-08-21T08:37:43.145Z | FAILURE/tdd_red_report_consumers | incident=`d9e0f1a2-b3c4-4567-8a90-1d2e3f4a5b6c` | lesson_key=`typed-report-consumer-boundary` | event_sha256=`ac98bdef3bec9338b8ac90566fe02c8684bd66851cda59c02bfa2d1266037b5e`
- #5: `e0f1a2b3-c4d5-4678-9a01-2e3f4a5b6c7d` | 2026-08-21T08:41:09.538Z | REVIEW/typed_report_consumer_review | incident=`f1a2b3c4-d5e6-4789-a012-3f4a5b6c7d8e` | lesson_key=`typed-report-consumer-boundary` | event_sha256=`f7cf641428d7bf02436c85c571803b77f14c3e59b26bf5e9a0182cbcfebc7cfc`
- #6: `a2b3c4d5-e6f7-4890-a123-4b5c6d7e8f90` | 2026-08-21T08:42:14.707Z | GATE/report_statistical_consumer_green | incident=`b3c4d5e6-f789-4a01-b234-5c6d7e8f9012` | lesson_key=`typed-report-consumer-boundary` | event_sha256=`250624362aca04396109387c21169dc741bb840e48457c73a97e2bdfb8e4edef`
- #7: `c4d5e6f7-8901-4b23-c456-7d8e9f012345` | 2026-08-21T08:42:48.498Z | STATE_CHANGE/line_completed | incident=`d5e6f789-0123-4c45-d678-8e9f01234567` | lesson_key=`formal-closeout` | event_sha256=`b6d6e64f5c8c42f72d158172e017c63fcf673d558a776086fb91ae0bf964d1b4`
