# Retrospective — v1-8-9-p0-report-legacy-html-migration

## Goal

# Workbench v1.8.9 P0 Report Legacy Contract Migration  Migrate remaining legacy tests that treat an unbound local HTML file as an authoritative Report result. Preserve the v1.8.9 fail-closed rule: an unbound run may expose typed diagnostics and unavailable evidence, but must not expose citable Report facts or raw fallback HTML.  Scope: tests/models/arma_garch/test_deliverables.py, tests/test_cs_did_wiring.py, tests/test_debug_audit.py.  Acceptance: focused tests pass; assertions use typed evidence/diagnostic contracts; server-owner-admitted Report tests remain authoritative; no production Report weakening.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/9 (11.1%; 11.1 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=573092 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T07:14:03.655Z `tdd_red_legacy_report_html`; cause_status: `known`; cause: The scoped tests still treated unbound reports/report.html as an authoritative Report even though the completed run now fails closed and emits typed report-unavailable diagnostics.; resolution: `open`; lesson: Migrate unbound Report assertions to typed diagnostic and unavailable-evidence contracts before reading any HTML.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `typed-report-unavailable-before-html`: occurrences=1; cause_status: `known`; root cause: The scoped tests still treated unbound reports/report.html as an authoritative Report even though the completed run now fails closed and emits typed report-unavailable diagnostics.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `typed-report-unavailable-before-html`: line experience occurrence(s)=1

## Future guidance

- Migrate unbound Report assertions to typed diagnostic and unavailable-evidence contracts before reading any HTML.
- Owner-bound Report fixtures must use the canonical project/runs/run topology so helper-derived project identity exercises the real authority boundary.
- Resolve a recorded RED incident through an explicit follow-up event tied to the same incident identity and verified commit.
- Use typed diagnostics and owner-bound evidence projections as the only Report facts boundary; presentation HTML is never an unbound authority.

## Event index

- #1: `a46ba07b-2b15-4762-9d90-105b8e22e064` | 2026-08-21T07:06:47.459Z | STATE_CHANGE/line_started | incident=`3bcda712-7256-47ec-9d20-da6bb97455e9` | lesson_key=`frozen-context-before-start` | event_sha256=`894af9c7177c51af5887b4ed0cf34ce3e1c033e00857c6a33bc985adcd4fe862`
- #2: `c2a3f4b5-6c7d-4890-ab12-cd34ef567890` | 2026-08-21T07:14:03.655Z | FAILURE/tdd_red_legacy_report_html | incident=`d3e4f5a6-b718-49ca-8d2e-3f4051627384` | lesson_key=`typed-report-unavailable-before-html` | event_sha256=`05c6073411f76b87cb329147e00910115d7abf07a9da5849718af6433b499e5b`
- #3: `e4f5a6b7-c829-4adb-9e3f-405162738495` | 2026-08-21T07:17:26.147Z | REVIEW/typed_unavailable_contract_migration | incident=`f5a6b7c8-d930-4bec-af40-5162738495a6` | lesson_key=`unbound-report-is-unavailable` | event_sha256=`e2d4c64db11ef7068227fb2e6599114a7083811a64d9eadbdf1c9638ade79234`
- #4: `f6a7b8c9-e041-4cfd-b051-62738495a6b7` | 2026-08-21T07:17:45.864Z | GATE/scoped_report_legacy_migration_tests | incident=`a7b8c9d0-e152-4dfe-c162-738495a6b7c8` | lesson_key=`scoped-gate-separates-owner-boundary` | event_sha256=`85c73d5a1a12df6841e0088ff97e850f09357096b92b718cac9666c88d0c3b28`
- #5: `b8c9d0e1-f263-4e0f-d374-8495a6b7c8d9` | 2026-08-21T07:18:00.974Z | GATE/compile_and_diff_check | incident=`c9d0e1f2-a374-4f10-e485-95a6b7c8d9e0` | lesson_key=`compile-diff-before-formal-closeout` | event_sha256=`98ab0dddbb4f8522bc2957f9a8b5b8566d4b763212b30fa98e31dd2481d37506`
- #6: `d0e1f2a3-b485-4c96-d7e8-9f0a1b2c3d4e` | 2026-08-21T07:21:02.364Z | REVIEW/owner_fixture_canonical_run_root | incident=`e1f2a3b4-c596-4d07-e8f9-0a1b2c3d4e5f` | lesson_key=`owner-fixture-uses-canonical-run-root` | event_sha256=`057978a8e1d0527527ef27b30c8220226c941bd87af78e7e5de29f7da4253e38`
- #7: `f1a2b3c4-d506-4e78-f9a0-b1c2d3e4f506` | 2026-08-21T07:22:04.037Z | GATE/post_commit_scoped_verification | incident=`a2b3c4d5-e617-4f89-a0b1-c2d3e4f50617` | lesson_key=`post-commit-scoped-verification` | event_sha256=`3103104eb8b0c8a4fee2223f6db4ea129625c3a3986ecf7376f688facba09adc`
- #8: `b3c4d5e6-f708-4a91-b2c3-d4e5f6071829` | 2026-08-21T07:22:30.633Z | STATE_CHANGE/report_legacy_html_migration_completed | incident=`c4d5e6f7-a819-4b2c-c3d4-e5f60718293a` | lesson_key=`close-after-typed-report-gate` | event_sha256=`b05074ee650a76ce34a8e7ba55609fced2620ff2b9fc77659a12b6ca97a0b371`
- #9: `d5e6f708-a91b-4c23-d4e5-f60718293a4b` | 2026-08-21T07:23:36.747Z | REVIEW/tdd_red_legacy_report_html_resolved | incident=`d3e4f5a6-b718-49ca-8d2e-3f4051627384` | lesson_key=`typed-report-unavailable-before-html` | event_sha256=`dbaf62c08360a9bba015c9a0f5e0dbb7e6eb4d7442713c57768043bbf4415de1`
