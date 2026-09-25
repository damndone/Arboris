# Retrospective — v1-8-9-p0-model-auto-source-variant

## Goal

# v1.8.9 P0 model.auto source variant  ## Objective  Make the declaration-derived \`model.auto\` workflow contract accept its typed generic capability request when the compiler has added the standard \`source\` binding. The source binding is a cross-operation workflow field, not a second model.auto variant. Selector and generic-capability variants must remain exclusive, typed and fail closed for unknown fields.  ## Scope  - Update the model.auto contract/variant admission in   \`backend/workbench/agent/workflow_contracts.py\`. - Add focused contract coverage for selector, generic capability, and source   binding behavior in the new test file. - Preserve declaration-derived dispatch and unknown-field rejection.  ## Non-goals  - Do not change model estimation, family selection, or post-estimation logic. - Do not remove source dependencies from compiled workflows. - Do not add a second capability list or a model.auto-specific runtime bypass. - Do not modify workflow seam migration tests, providers, browser or release   gates.  ## Acceptance  - Generic \`model.auto\` with compiler-added \`source\` resolves its trusted   dispatcher. - Selector and generic variants remain distinct. - Unknown fields still fail closed. - Focused contract tests and \`git diff --check\` pass.

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

- #1: `5c69a26b-3d82-4216-979a-3f03f4c8e187` | 2026-08-21T10:33:16.505Z | STATE_CHANGE/line_started | incident=`498f46c6-62d6-440f-b56e-f4d9f61f7d78` | lesson_key=`frozen-context-before-start` | event_sha256=`3dfeb8f05c1fc888f11b8be88a1bb3ec15df4022692548d7f996ff740143cbaf`
- #2: `2d7f6a11-1e6c-4d58-9d11-6b2f7e9a4c30` | 2026-08-21T10:37:59.994Z | GATE/model_auto_source_variant_focused_gate | incident=`8c1f4b72-5a0e-4d93-b6f8-2e7a1c9d405b` | lesson_key=`model-auto-source-variant-focused-green` | event_sha256=`76fdbed2d4b62f8c0c25f6b5dd015fc6b25fa974d28c0728ba174a80db0f103f`
- #3: `9b4e2c71-6f0a-4d83-a5c9-1e7b3f8d2046` | 2026-08-21T10:38:29.837Z | STATE_CHANGE/line_completed | incident=`4e8a1c73-5b0d-4f92-a6c1-7e3b9d205148` | lesson_key=`close-line-after-evidence-agrees` | event_sha256=`ba5d2698cf5446a088e60f3dda7a7118dea0f62a0620d90df563a96435881c37`
