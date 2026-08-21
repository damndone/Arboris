# Retrospective — v1-8-9-p0-report-legacy-contract-migration

## Goal

# v1.8.9 P0 — migrate legacy report tests to the fail-closed contract  Migrate broad legacy tests that assume an unbound local run automatically writes and serves \`reports/report.html\`. The v1.8.9 contract requires a server-owned Report evidence capability; without deployment-owned host admission, the correct result is typed unavailable/blocked evidence with model artifacts retained.  Keep dedicated owner-admitted Report tests as the positive path. Do not weaken production evidence admission, invent a test-only owner in production code, or change numerical/report claims to read raw model files.  Acceptance: the owned legacy tests assert the current typed unavailable behavior where no C0 owner is injected, while preserving non-report model/diagnostic assertions. The scoped suite, compile/diff checks, and formal verification pass. Browser, real Provider, external host resolver, and release gates remain explicit known gates.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/8 (37.5%; 37.5 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/1)

## All failures

- #2 2026-08-21T06:48:06.242Z `scoped_suite_red`; cause_status: `known`; cause: The hardening candidate's owned legacy tests still assume an unbound local run writes and serves reports/report.html, while the current v1.8.9 contract requires server-owned Report evidence admission.; resolution: `open`; lesson: Lock the fail-closed Report boundary in legacy tests before migrating presentation-only expectations; retain model outputs, diagnostics, categorical interpretation, and typed unavailable evidence.
- #5 2026-08-21T06:55:11.177Z `migration_probe_mismatch`; cause_status: `known`; cause: The first replacement for the legacy report missing-on-disk test targeted a non-Report diagnostic artifact; the current route returned an untyped 500 for that path, so the replacement did not preserve the intended Report boundary.; resolution: `resolved`; lesson: When migrating a legacy Report file-integrity test, keep the probe on the ownerless Report artifact boundary and assert typed non-registration rather than introducing a new non-Report route expectation.

## All errors

- #4 2026-08-21T06:48:52.742Z `invalid_event_probe`; cause_status: `known`; cause: The first attempt to append the read-only formal probe event used an incident_id with an invalid UUID shape and was rejected before changing the event log.; resolution: `accepted`; lesson: Validate formal event identifiers before append and use devline_control.py verify --line for line integrity checks.

## All gaps

- None recorded.

## All waste

- #3 2026-08-21T06:48:38.441Z `unsupported_status_probe`; cause_status: `known`; cause: A read-only status probe used an unsupported devline_control.py status subcommand; the formal CLI exposes verify instead.; resolution: `accepted`; lesson: Use devline_control.py verify --line for formal line status and integrity checks.

## Root causes and solutions

- `formal-event-validation`: occurrences=1; cause_status: `known`; root cause: The first attempt to append the read-only formal probe event used an incident_id with an invalid UUID shape and was rejected before changing the event log.; solution: `accepted`
- `formal-verify-command`: occurrences=1; cause_status: `known`; root cause: A read-only status probe used an unsupported devline_control.py status subcommand; the formal CLI exposes verify instead.; solution: `accepted`
- `report-download-no-owner`: occurrences=1; cause_status: `known`; root cause: The first replacement for the legacy report missing-on-disk test targeted a non-Report diagnostic artifact; the current route returned an untyped 500 for that path, so the replacement did not preserve the intended Report boundary.; solution: `resolved`
- `report-fail-closed-contract`: occurrences=1; cause_status: `known`; root cause: The hardening candidate's owned legacy tests still assume an unbound local run writes and serves reports/report.html, while the current v1.8.9 contract requires server-owned Report evidence admission.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `formal-event-validation`: line experience occurrence(s)=1
- `formal-verify-command`: line experience occurrence(s)=1
- `report-download-no-owner`: line experience occurrence(s)=1
- `report-fail-closed-contract`: line experience occurrence(s)=1

## Future guidance

- Lock the fail-closed Report boundary in legacy tests before migrating presentation-only expectations; retain model outputs, diagnostics, categorical interpretation, and typed unavailable evidence.
- Review legacy Report migrations for authority preservation, not only green assertions.
- Use devline_control.py verify --line for formal line status and integrity checks.
- Validate formal event identifiers before append and use devline_control.py verify --line for line integrity checks.
- When migrating a legacy Report file-integrity test, keep the probe on the ownerless Report artifact boundary and assert typed non-registration rather than introducing a new non-Report route expectation.

## Event index

- #1: `fa6ee31c-b291-4af0-9905-37b3640982ea` | 2026-08-21T06:31:53.233Z | STATE_CHANGE/line_started | incident=`60a1fe94-2a3c-47fd-98db-1d5b947a9c40` | lesson_key=`frozen-context-before-start` | event_sha256=`876f25dbcdd2870cd5a70bca6c76d5a0dcf44f073af0c524aaedb1afc22e6d8a`
- #2: `f2d6c0bf-1f55-4d3a-8f57-665e8d56d5f0` | 2026-08-21T06:48:06.242Z | FAILURE/scoped_suite_red | incident=`5e24e196-74a0-42a6-b93d-66a33d339f44` | lesson_key=`report-fail-closed-contract` | event_sha256=`a3c4f1b6721a60c959d07dc3794f8c54c3581dda96463c94af01631631777e21`
- #3: `f91cc1a6-9ff8-46f6-8ff8-42fa0a3a8ba3` | 2026-08-21T06:48:38.441Z | WASTE/unsupported_status_probe | incident=`c89f20aa-29d9-4a09-a1f6-a29fcf1bdb56` | lesson_key=`formal-verify-command` | event_sha256=`b71da226fb0b34153bfdd2b5b87931bf4c614a7ba8cd7dca90eda2059b6d1895`
- #4: `d1e0f2dd-4510-4d23-9491-e71147571b8e` | 2026-08-21T06:48:52.742Z | ERROR/invalid_event_probe | incident=`d7d77f2e-6ff6-4c4e-9e67-d955cf5a1bc1` | lesson_key=`formal-event-validation` | event_sha256=`aeef33ec028f0296b53e6a623453d6542bd47486f17ee7603fb15109af2389d8`
- #5: `bd3b6ba8-7629-48cf-aed2-f50f62d64f1a` | 2026-08-21T06:55:11.177Z | FAILURE/migration_probe_mismatch | incident=`d17d0af8-2f63-4db5-8a62-3fef7c7f8b01` | lesson_key=`report-download-no-owner` | event_sha256=`22a3fee3f7605b0486e937ae57625235f7c189876bfb8d822962fd5b52428794`
- #6: `0e4d1971-886b-448c-9cab-3bd5a7dcb7c8` | 2026-08-21T06:57:50.333Z | REVIEW/owned_scope_review | incident=`8bf3bde3-5c21-4c70-bdb8-2bc4a2c48879` | lesson_key=`owned-report-migration-review` | event_sha256=`71c9457cb1aaf02111f8508210d4ddeea875f73849499a7d4e894ccf369f2149`
- #7: `f7ef97f1-ea5e-41fb-9f7f-d8a9ff8f35f0` | 2026-08-21T06:58:14.048Z | GATE/scoped_verification | incident=`feaf7ed6-94c2-4f28-8d31-c6f3a784a32b` | lesson_key=`scoped-report-verification` | event_sha256=`ab484098bfa12a74f2d4ff0f2b9fbca1206bebbbe743ed81c3297dabefe660de`
- #8: `0c8e22af-a818-4e88-8b8c-c47c07a7ae4f` | 2026-08-21T06:58:51.006Z | STATE_CHANGE/line_completed | incident=`c0f0e3f2-7d1a-4a4f-88a8-0cc0c0c6bd8d` | lesson_key=`report-line-closeout` | event_sha256=`06253a67f76e7bcd928b7b74b3a28307a57b20de601ac961d75fb48d062baf4c`
