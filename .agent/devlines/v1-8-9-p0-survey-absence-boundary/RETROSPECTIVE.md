# Retrospective — v1-8-9-p0-survey-absence-boundary

## Goal

# Workbench v1.8.9 P0 survey-absence boundary objective  ## Objective  Close the workflow correctness regression at exact baseline \`7756709aa9c34084ccfe1e2e9060af4c5a9423f9\`: an ordinary run that does not declare a survey subpopulation is currently forwarded as the empty string and rejected by the typed Survey adapter as \`SURVEY_SUBPOP_INVALID\`.  The fix must preserve the distinction between an omitted optional declaration (\`None\`, meaning no subpopulation) and an explicitly invalid declaration (including an empty string supplied through a typed programmatic boundary, which remains fail-closed).  ## Required behavior  - HTTP \`/runs\` and \`/runs/batch\` use \`None\` for an omitted survey subpopulation. - \`_submit_run\` and \`_bg_run\` preserve \`None\` as absence and do not invent an   empty expression. - Explicit invalid typed values still reach the Survey adapter and fail closed. - Existing declared Survey wiring, falsey-value rejection, FPC/design limits,   and report evidence boundaries remain unchanged. - Add a regression probe at the HTTP-to-dispatch boundary and run the focused   Survey wiring plus affected workflow truth tests.  ## Scope  Allowed product/test/document paths:  - \`backend/workbench/http/runs_routes.py\` - \`backend/workbench/services/run_service.py\` - \`tests/test_survey_design_wiring_v187.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-survey-absence-boundary-objective.md\` - \`docs/superpowers/plans/2026-08-20-survey-absence-boundary.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-survey-absence-boundary-handoff.md\`  Protected paths include the Survey statistical engine, central Agent/Notebook/ Report cutover, other worktrees, release/merge/tag/push machinery, and all historical formal records.  ## Baseline, dependencies, and gates  - Exact baseline: \`7756709aa9c34084ccfe1e2e9060af4c5a9423f9\`. - Dependency: \`v1-8-9-p0-report-compose-closure\` (read-only historical evidence). - Required checks: TDD RED before production edits, focused Survey wiring and   workflow truth tests, compileall, \`git diff --check\`, formal verify, and a   formal retrospective. - Known gates remain \`NOT VERIFIED\`: central candidate acceptance, browser,   external provider/oracle, host, full gate, release readiness, merge, tag,   and push.  ## Completion target  The line may close only when the omitted HTTP declaration is proven to reach the runtime as \`None\`, explicit invalid declarations remain rejected, the focused suite is green, and the exact handoff is frozen before the final formal state event.

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

- #1: `b47e120a-874a-49c8-a2a3-1fda05d515d2` | 2026-08-20T08:13:21.380Z | STATE_CHANGE/line_started | incident=`99ff64a2-324d-46a8-a061-c2da3b67c841` | lesson_key=`frozen-context-before-start` | event_sha256=`29d2b88ef577f22316180cae74c05929a67b4fc8abc2f7cf109543b4ea9064a3`
