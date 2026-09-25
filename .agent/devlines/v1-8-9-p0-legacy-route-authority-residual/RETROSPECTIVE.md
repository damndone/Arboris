# Retrospective — v1-8-9-p0-legacy-route-authority-residual

## Goal

# Workbench v1.8.9 P0 Legacy Route Authority Residuals  ## Objective  Migrate the remaining legacy Agent route tests to the current server-owned identity and proposal-integrity contract. Tests that exercise proposal integrity must reach that check through an explicitly admitted host identity; tests that intentionally omit host authority must assert the typed identity failure at that earlier boundary. Do not weaken production admission order.  ## Scope  - \`tests/test_v189_legacy_resume_remediation3.py\` - \`tests/test_v189_legacy_route_authority.py\`  ## Acceptance  - Focused tests pass with the intended assertion boundary. - Tampered, incomplete, cross-scope, replayed and mismatched proposals remain   fail-closed before compiler record/execute calls. - No default host identity, caller-selected authority, or production change is   introduced.  ## Boundary  - Affected paths: the two test files above - Allowed paths: the two test files above - Protected paths: all production Agent/Notebook route and authority code - Dependencies: current v1.8.9 server-owned identity contract - Tests: \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_v189_legacy_resume_remediation3.py tests/test_v189_legacy_route_authority.py\` - Known gates: full backend, browser, production host/provider, and release gates remain separate

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/6 (50.0%; 50.0 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T09:52:44.946Z `scoped_baseline_red`; cause_status: `known`; cause: The current server-owned identity gate runs before the legacy proposal-integrity assertions in ten focused tests.; resolution: `open`; lesson: Provide a legal server-owned host identity for proposal-integrity tests and assert the typed identity boundary for missing-authority tests.

## All errors

- #3 2026-08-21T09:53:02.368Z `formal_cli_import_path`; cause_status: `known`; cause: The formal control CLI imported the linked v1.8.6 backend module instead of the current worktree backend.; resolution: `resolved`; lesson: Invoke the formal CLI with the current worktree PYTHONPATH when linked worktrees share a virtual environment.
- #4 2026-08-21T09:57:51.699Z `formal_event_contract_iteration`; cause_status: `known`; cause: The first GREEN gate event used a preventability value outside the formal event schema.; resolution: `resolved`; lesson: Validate formal event enum values before submitting material gate evidence.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `formal-cli-current-worktree-import`: occurrences=1; cause_status: `known`; root cause: The formal control CLI imported the linked v1.8.6 backend module instead of the current worktree backend.; solution: `resolved`
- `formal-event-enum-validation`: occurrences=1; cause_status: `known`; root cause: The first GREEN gate event used a preventability value outside the formal event schema.; solution: `resolved`
- `legacy-identity-gate-before-proposal-integrity`: occurrences=1; cause_status: `known`; root cause: The current server-owned identity gate runs before the legacy proposal-integrity assertions in ten focused tests.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `formal-cli-current-worktree-import`: line experience occurrence(s)=1
- `formal-event-enum-validation`: line experience occurrence(s)=1
- `legacy-identity-gate-before-proposal-integrity`: line experience occurrence(s)=1

## Future guidance

- Invoke the formal CLI with the current worktree PYTHONPATH when linked worktrees share a virtual environment.
- Provide a legal server-owned host identity for proposal-integrity tests and assert the typed identity boundary for missing-authority tests.
- Validate formal event enum values before submitting material gate evidence.

## Event index

- #1: `44752ad2-e14b-4f75-8652-7f2382d2ca8e` | 2026-08-21T09:48:01.796Z | STATE_CHANGE/line_started | incident=`f0fafe69-da77-42e9-8fd0-0d1be88058ea` | lesson_key=`frozen-context-before-start` | event_sha256=`8884819618c9c632dfbcec5f4aa946e6e4b24e68d34bae1962676fe076616430`
- #2: `d6e4f39b-7a11-4b5d-9e20-3c6f8a1b2d47` | 2026-08-21T09:52:44.946Z | FAILURE/scoped_baseline_red | incident=`04b9e7c2-5d13-46a8-9f20-7c3e1b6d8a54` | lesson_key=`legacy-identity-gate-before-proposal-integrity` | event_sha256=`4d2d706caaf293493326c4b58c7c3609db4cd81ea82c9cf35bcfa19843e35950`
- #3: `e7f4a2c9-6b18-4d53-8a20-1f7c3b9e5d62` | 2026-08-21T09:53:02.368Z | ERROR/formal_cli_import_path | incident=`15c8e4f7-2a69-4b30-9d81-6e3f7a5c2b14` | lesson_key=`formal-cli-current-worktree-import` | event_sha256=`2999938dca510868303515a25574df5c3eb5c39e4a2b8133ac2bd0c80302a952`
- #4: `a1e7c4f9-2b63-4d80-9a15-6c3e8f7b5d24` | 2026-08-21T09:57:51.699Z | ERROR/formal_event_contract_iteration | incident=`37e8a5c1-2d94-46bf-9a70-5e3c8f1b6d24` | lesson_key=`formal-event-enum-validation` | event_sha256=`5c20d2e439701fa2531068ac71df84714b90b447f8e390d4fc900f1b0768d6ad`
- #5: `b2f8d5a0-3c74-4e91-8a26-7d4f9b1c6e35` | 2026-08-21T09:58:07.940Z | GATE/scoped_legacy_route_green | incident=`48f9b6d2-3e05-47ca-8b61-6f4d9a2c7e35` | lesson_key=`scoped-legacy-route-green-boundary` | event_sha256=`15c30de1f09cfbe3176612434ef56c0f65dfbaffb1ca3710d73cc02c759f4c3b`
- #6: `c3a9e6f2-4b75-4d80-9a16-7e5c2b8f1d43` | 2026-08-21T09:59:24.128Z | STATE_CHANGE/line_completed | incident=`59e8c7a3-1f64-4b90-8d25-6c3a9e7f2b14` | lesson_key=`scoped-legacy-route-line-complete` | event_sha256=`face1bd8db0d1179bf92fa738435726f9e31bef4b6aba9f60a08c93ac3c65f83`
