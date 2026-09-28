# Retrospective — v1-8-9-p0-legacy-consumer-gate-migration

## Goal

# v1.8.9 P0 Legacy Consumer Gate Migration Objective  Migrate the remaining legacy consumer seams to the current typed, server-owned contracts using tests and fixtures only. Investigate every failure from the required focused gate and make the smallest test-only or fixture-only change that exercises the existing report, evidence, and proposal seams.  This line must not modify production code, restore raw model-result or unbound report fallbacks, reintroduce caller-owned executor/path behavior, or add an untyped proposal-store fallback. Existing unrelated dirty worktree changes are outside this line and must remain untouched.  ## Completion boundary  - All 22 focused failures are classified and either corrected in the owned   tests/goldens or recorded as an unresolved production-owner blocker. - The focused test command, backend compileall, and \`git diff --check\` have   fresh evidence. - Formal events, verification, retrospective, and handoff are produced through   \`scripts/devline_control.py\` and the handoff records exact limits. - No browser, provider, release, merge, or production-readiness claim is made   by this test/fixture migration line.

## Final status

STARTED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
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

- #1: `4e00a72c-9427-466e-9730-287dbb3b3eb4` | 2026-08-20T23:12:28.293Z | STATE_CHANGE/line_started | incident=`0637377e-756b-4fa4-979c-30e1a5c4cbaf` | lesson_key=`frozen-context-before-start` | event_sha256=`157d589b30772b00600eb93f65253e5c7e49205d982bd16ebb98a74af1f6a149`
