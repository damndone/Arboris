# Retrospective — v1-8-9-p0-evidence-report-hardening

## Goal

# Workbench v1.8.9 P0 Evidence and Report Hardening Objective  Close the real consumer-boundary gaps between persisted workflow artifacts, EvidenceEnvelope/EvidenceCommitBinding, and the Report UI.  Required outcomes:  - an indexed post-estimation artifact without a committed canonical evidence   binding cannot create citable Report facts; it must render as   \`UNAVAILABLE\`/\`BLOCKED\` with a typed reason; - the actual ReportView path must receive and render the typed evidence   projection, including status, envelope digest, provenance and bounded facts; - no raw JSON fallback or recursive scalar extraction may bypass evidence   status, digest, or admission checks; - Agent, Notebook, and Report must preserve the same fact identity/value for a   committed envelope; - tests must prove both the accepted committed path and the rejected   uncommitted/tampered path.  This line owns the run/report evidence loading and Report consumer paths plus their tests. It does not modify Agent/Notebook routing, provider execution, model estimators, or release sidecars. Browser/provider/full-host-gate acceptance remains separate.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/10 (30.0%; 30.0 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/4 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #3 2026-08-19T17:01:00.000Z `preexisting_host_authority`; cause_status: `external`; cause: The existing post-estimation compatibility run failed before the Report route assertion because the protected Agent workflow host-authority resolver is not configured.; resolution: `accepted`; lesson: Keep Agent host-authority failures separate from the Report consumer gate and use an isolated route probe for this line.
- #4 2026-08-19T17:02:00.000Z `formal_event_validation_retry`; cause_status: `known`; cause: The first TDD red gate event draft used an unsupported preventability value and was rejected by the formal CLI before being corrected and appended.; resolution: `resolved`; lesson: Validate formal event enum values before invoking the append control.
- #5 2026-08-19T17:04:00.000Z `preexisting_api_admission`; cause_status: `external`; cause: The broader API compatibility suite could not materialize its completed-run report artifacts because the host-owned workflow admission receipt is unavailable.; resolution: `accepted`; lesson: Use focused route probes when the broader API fixture depends on an unavailable host admission receipt.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `separate-agent-host-authority-failure`: occurrences=1; cause_status: `external`; root cause: The existing post-estimation compatibility run failed before the Report route assertion because the protected Agent workflow host-authority resolver is not configured.; solution: `accepted`
- `separate-api-admission-failure`: occurrences=1; cause_status: `external`; root cause: The broader API compatibility suite could not materialize its completed-run report artifacts because the host-owned workflow admission receipt is unavailable.; solution: `accepted`
- `validate-formal-event-enums`: occurrences=1; cause_status: `known`; root cause: The first TDD red gate event draft used an unsupported preventability value and was rejected by the formal CLI before being corrected and appended.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `separate-agent-host-authority-failure`: line experience occurrence(s)=1
- `separate-api-admission-failure`: line experience occurrence(s)=1
- `validate-formal-event-enums`: line experience occurrence(s)=1

## Future guidance

- Keep Agent host-authority failures separate from the Report consumer gate and use an isolated route probe for this line.
- Use focused route probes when the broader API fixture depends on an unavailable host admission receipt.
- Validate formal event enum values before invoking the append control.

## Event index

- #1: `4d4470c0-5786-414e-bfa6-9ed9c056a9fe` | 2026-08-19T16:34:43.586Z | STATE_CHANGE/line_started | incident=`ad4126bd-d9c4-4939-9b43-f3c6c602b59b` | lesson_key=`frozen-context-before-start` | event_sha256=`54b27b5ba090210619b4dea7929898a22befe6d604842036a6fe60b10cd8dc0e`
- #2: `55d848f3-0ad1-4b28-8d3d-5e2be9e2915b` | 2026-08-19T16:52:00.000Z | GATE/tdd_red | incident=`9cd71950-19d3-4c36-93b3-0bde0c690d77` | lesson_key=`tdd-red-before-implementation` | event_sha256=`29dfa363d880bcbb42494351e2f7089f20aab358ec77f56c849874d1a069e83f`
- #3: `2f6e0f16-5eef-4e38-b5f4-2a3fcdad57bf` | 2026-08-19T17:01:00.000Z | ERROR/preexisting_host_authority | incident=`7ee2d830-5d8f-4ee4-87e1-4071e118c99f` | lesson_key=`separate-agent-host-authority-failure` | event_sha256=`ab706e1a59ec8ece6620bbfa617b0541fa867274aa228166e66e69f6b6f3f6e2`
- #4: `8e7c7d9e-8e20-4f74-b3a0-e1542e0e53a8` | 2026-08-19T17:02:00.000Z | ERROR/formal_event_validation_retry | incident=`c9458024-0c33-45ef-b6dc-0d27eefdd950` | lesson_key=`validate-formal-event-enums` | event_sha256=`c80e7538c063a898a129ba89420f4c7cf425267e6e8cfe132c710e397778f063`
- #5: `e4b00c49-19b3-4d24-aed7-5ce86ab7a613` | 2026-08-19T17:04:00.000Z | ERROR/preexisting_api_admission | incident=`6ecfce9d-0e70-4b95-90d9-9a2e65b82f20` | lesson_key=`separate-api-admission-failure` | event_sha256=`f42126c3dadf6ce8e6017a4a47b390990eb5a103799a262393a25ded51f819ff`
- #6: `c745b744-c195-45d7-bd43-6d66b20a8b19` | 2026-08-19T17:06:00.000Z | GATE/report_boundary_backend | incident=`e9c6cc2d-fc2f-4dba-9e23-d8f09d0e7bc3` | lesson_key=`backend-report-boundary-green` | event_sha256=`66d81f70ea968a3bbd2f8f6f18a7029857eeb81d64f531288fb0c0adc4b72d8c`
- #7: `6f3a4e68-660f-45da-b5ef-5aa9ec0e0f2a` | 2026-08-19T17:06:10.000Z | GATE/report_boundary_frontend | incident=`e0a994ef-6bb1-48d1-a61a-3f6fc25388df` | lesson_key=`frontend-report-boundary-green` | event_sha256=`3fc0e291acd313fe02100598ce45349a61ebef0916d2421764135adef46ef03f`
- #8: `f6d4cbd7-5ff4-4cc2-b7bf-9e1cf8de373a` | 2026-08-19T17:06:20.000Z | GATE/frontend_typecheck | incident=`4b5d45c6-480e-4c98-9825-3a7c22414a1c` | lesson_key=`frontend-typecheck-separate-browser` | event_sha256=`d61e6c5404936ebfbfeaba54860c271ab4f16fa545fbd2609b175b1792f3bece`
- #9: `d84e986a-2d3d-4011-a5e9-37dbd85ee968` | 2026-08-19T17:08:00.000Z | STATE_CHANGE/implementation_verified | incident=`d67651d8-b1e8-4135-ad5b-a43124b964c6` | lesson_key=`report-boundary-implementation-verified` | event_sha256=`87a348d11f05722166c7ff674115081126e88075e6fcfd9089df3d9c7307fdcf`
- #10: `9d8be3e7-82e6-44dc-8cf0-bbf1b6bc7b12` | 2026-08-19T17:12:00.000Z | STATE_CHANGE/line_completed | incident=`46d65aed-6cba-40d0-93da-4e753caef2b7` | lesson_key=`close-with-evidence-and-deferred-gates` | event_sha256=`b9fe97935143dd24c615fad0f946f9e608401b7a93993805d7a852caab424d80`
