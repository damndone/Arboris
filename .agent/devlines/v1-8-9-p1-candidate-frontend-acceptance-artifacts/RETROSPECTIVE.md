# Retrospective — v1-8-9-p1-candidate-frontend-acceptance-artifacts

## Goal

# Workbench v1.8.9 candidate frontend acceptance artifacts objective  Restore the four typed frontend acceptance tests required by the immutable v1.8.9 foundation runner. These tests are acceptance fixtures, not a second frontend runtime: they must exercise the existing Lineage data-operation, Notebook planning, Report evidence, and evaluation-status contracts already present in the candidate.  Required outcomes:  - the four runner-declared paths exist in the candidate; - each test uses the current public component/contract surface; - Lineage proves preview-before-confirm and source identity binding; - Notebook proves plan-only state does not expose an executable confirmation; - Report proves typed evidence renders and unknown raw payloads become   unavailable without leaking their contents; - evaluation status proves incomplete evidence is rejected rather than   synthesized; - the exact four-file Vitest command passes and \`git diff --check\` passes.  This line does not change product behavior, acceptance runner policy, provider authority, statistical estimators, browser automation, or release state.

## Final status

STARTED

## Metrics

- Failure frequency: 2/4 (50.0%; 50.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: N/A (sample=0; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T05:19:24.436Z `frontend_preflight_red`; cause_status: `known`; cause: The runner-declared frontend acceptance artifacts are missing from the candidate.; resolution: `open`; lesson: Restore every runner-declared frontend acceptance artifact before claiming the candidate frontend gate.
- #3 2026-08-21T05:20:20.411Z `frontend_acceptance_artifacts_missing`; cause_status: `known`; cause: The candidate-bound foundation runner declares four frontend acceptance paths, but the current candidate does not contain those files.; resolution: `open`; lesson: Candidate acceptance artifacts must be present in the exact candidate being evaluated; a test in another worktree is not candidate evidence.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `candidate-frontend-artifact-presence`: occurrences=1; cause_status: `known`; root cause: The candidate-bound foundation runner declares four frontend acceptance paths, but the current candidate does not contain those files.; solution: `open`
- `frontend-acceptance-artifact-missing`: occurrences=1; cause_status: `known`; root cause: The runner-declared frontend acceptance artifacts are missing from the candidate.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `candidate-frontend-artifact-presence`: line experience occurrence(s)=1
- `frontend-acceptance-artifact-missing`: line experience occurrence(s)=1

## Future guidance

- Candidate acceptance artifacts must be present in the exact candidate being evaluated; a test in another worktree is not candidate evidence.
- Restore every runner-declared frontend acceptance artifact before claiming the candidate frontend gate.

## Event index

- #1: `dd2dce63-f26c-48ba-ae8c-64e70a6419e5` | 2026-08-21T05:15:50.213Z | STATE_CHANGE/line_started | incident=`d052a1f8-dec3-42a1-8b07-a25a55f4834f` | lesson_key=`frozen-context-before-start` | event_sha256=`073c7caaccf2cc669853823927ee00b99772f47b7ba8515c6a50a6bc2d45cd62`
- #2: `7f3d9e7c-8b6b-4c7d-9d0d-5a87f6b3f1c2` | 2026-08-21T05:19:24.436Z | FAILURE/frontend_preflight_red | incident=`2d1e6f8a-0c2b-4a17-9c35-6e8f4b1a7d20` | lesson_key=`frontend-acceptance-artifact-missing` | event_sha256=`70d2c5faa613b7e8b555255a28eb874a3edd7fa7d12cc0093f3a5ea2f6c0ebe1`
- #3: `4c7d2e1f-9a8b-43c5-b6d7-0e1f2a3b4c5d` | 2026-08-21T05:20:20.411Z | FAILURE/frontend_acceptance_artifacts_missing | incident=`5e6f7a8b-9c0d-41e2-f3a4-b5c6d7e8f901` | lesson_key=`candidate-frontend-artifact-presence` | event_sha256=`af34dd45e869cbb3352cd3baa381e7f4b1258f5b622b5ff8a088de65da4b1d6f`
- #4: `b8e3c7a1-5d29-4f6b-9c02-71a4e8d6f3b0` | 2026-08-21T05:27:22.710Z | GATE/frontend_acceptance_artifacts_green | incident=`c4f8a2d6-0b17-4e93-8c5a-1d7f6b2e9a04` | lesson_key=`candidate-frontend-acceptance-artifacts-green` | event_sha256=`a90ef8501c9cf873eea856816720606f7e88b82e1f2ccb42782cbe3486991edb`
