# Retrospective — v1-8-9-p0-workflow-model-dependency-selection

## Goal

# v1.8.9 P0 workflow model-dependency selection  ## Objective  Make post-estimation dependency resolution select the completed model branch from a workflow step that also has a separately declared dataset source. A non-model source dependency must not be interpreted as a malformed model producer, while malformed or ambiguous model bindings must still fail closed.  ## Scope  - Update the workflow runtime dependency selector only where needed to skip   unrelated data dependencies and validate the selected model dependency. - Add focused regression coverage for a model post-estimation step whose   dependency list contains both a model producer and a source dataset step. - Preserve server-owned admission, typed model-branch evidence, lineage and   fail-closed behavior.  ## Non-goals  - Do not remove source dependencies from compiled workflows. - Do not revive raw payload or caller-provided model branch authority. - Do not change estimator formulas, covariance semantics, model families, or   provider configuration. - Do not modify browser, provider, release or unrelated workflow seam tests.  ## Acceptance  - The focused regression passes with the canonical model branch binding. - A malformed selected model binding still fails closed. - A workflow with a model dependency plus a non-model source dependency reaches   the intended post-estimation operation. - \`git diff --check\` and formal Context Pack verification pass.

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

- #1: `5cde11a2-b309-4e7e-b88b-817a8fdfe6d2` | 2026-08-21T10:28:49.198Z | STATE_CHANGE/line_started | incident=`61cd2756-6dcc-4aa9-8adc-e5dd2ba83323` | lesson_key=`frozen-context-before-start` | event_sha256=`01af72564c7b97cba33aa4cbf68f4295eb1f7fc98ba26fe73cde1647400c8a32`
- #2: `c6e2a8f4-1b7d-49d0-835c-2a6f7d1b9e4c` | 2026-08-21T10:31:57.596Z | GATE/model_dependency_selection_focused_gate | incident=`d7b3f9a1-6e2c-4a80-b5d1-9c7e3f2a6b84` | lesson_key=`mixed-dependency-model-selection` | event_sha256=`eb4390d600e93dda7a07391407426cea31e53d241f61395b8072410b71a53a8a`
- #3: `a7c3e9f1-6b2d-4a80-b5c1-9d7e3f2a6b84` | 2026-08-21T10:32:16.124Z | STATE_CHANGE/line_completed | incident=`b8d4f0a2-7c1e-49b5-836d-2f6a7c1e9b4d` | lesson_key=`scoped-model-dependency-closeout` | event_sha256=`9ed40455efffd29aa9875f88b4680425126ffca8414b5ba40b74e8b83fdd898b`
