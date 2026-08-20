# Retrospective — v1-8-9-p0-survey-absence-boundary

## Goal

# Workbench v1.8.9 P0 survey-absence boundary objective  ## Objective  Close the workflow correctness regression at exact baseline \`7756709aa9c34084ccfe1e2e9060af4c5a9423f9\`: an ordinary run that does not declare a survey subpopulation is currently forwarded as the empty string and rejected by the typed Survey adapter as \`SURVEY_SUBPOP_INVALID\`.  The fix must preserve the distinction between an omitted optional declaration (\`None\`, meaning no subpopulation) and an explicitly invalid declaration (including an empty string supplied through a typed programmatic boundary, which remains fail-closed).  ## Required behavior  - HTTP \`/runs\` and \`/runs/batch\` use \`None\` for an omitted survey subpopulation. - \`_submit_run\` and \`_bg_run\` preserve \`None\` as absence and do not invent an   empty expression. - Explicit invalid typed values still reach the Survey adapter and fail closed. - Existing declared Survey wiring, falsey-value rejection, FPC/design limits,   and report evidence boundaries remain unchanged. - Add a regression probe at the HTTP-to-dispatch boundary and run the focused   Survey wiring plus affected workflow truth tests.  ## Scope  Allowed product/test/document paths:  - \`backend/workbench/http/runs_routes.py\` - \`backend/workbench/services/run_service.py\` - \`tests/test_survey_design_wiring_v187.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-survey-absence-boundary-objective.md\` - \`docs/superpowers/plans/2026-08-20-survey-absence-boundary.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-survey-absence-boundary-handoff.md\`  Protected paths include the Survey statistical engine, central Agent/Notebook/ Report cutover, other worktrees, release/merge/tag/push machinery, and all historical formal records.  ## Baseline, dependencies, and gates  - Exact baseline: \`7756709aa9c34084ccfe1e2e9060af4c5a9423f9\`. - Dependency: \`v1-8-9-p0-report-compose-closure\` (read-only historical evidence). - Required checks: TDD RED before production edits, focused Survey wiring and   workflow truth tests, compileall, \`git diff --check\`, formal verify, and a   formal retrospective. - Known gates remain \`NOT VERIFIED\`: central candidate acceptance, browser,   external provider/oracle, host, full gate, release readiness, merge, tag,   and push.  ## Completion target  The line may close only when the omitted HTTP declaration is proven to reach the runtime as \`None\`, explicit invalid declarations remain rejected, the focused suite is green, and the exact handoff is frozen before the final formal state event.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=421391 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T08:15:06.150Z `survey_optional_absence_tdd_red`; cause_status: `known`; cause: The new HTTP regression probe shows that an omitted survey subpopulation is forwarded as an empty string, so ordinary runs cannot distinguish absence from an invalid declared expression.; resolution: `open`; lesson: Optional typed declarations must preserve omission separately from explicitly invalid values at every transport boundary.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `survey-optional-absence-boundary`: occurrences=1; cause_status: `known`; root cause: The new HTTP regression probe shows that an omitted survey subpopulation is forwarded as an empty string, so ordinary runs cannot distinguish absence from an invalid declared expression.; solution: `open`

## Added tests

- `tests/test_survey_design_wiring_v187.py`

## New rules

- `survey-optional-absence-boundary`: line experience occurrence(s)=1

## Future guidance

- Optional typed declarations must preserve omission separately from explicitly invalid values at every transport boundary.

## Event index

- #1: `b47e120a-874a-49c8-a2a3-1fda05d515d2` | 2026-08-20T08:13:21.380Z | STATE_CHANGE/line_started | incident=`99ff64a2-324d-46a8-a061-c2da3b67c841` | lesson_key=`frozen-context-before-start` | event_sha256=`29d2b88ef577f22316180cae74c05929a67b4fc8abc2f7cf109543b4ea9064a3`
- #2: `1c9d5e72-4a8b-46f0-9d13-7e2c5b8a1046` | 2026-08-20T08:15:06.150Z | FAILURE/survey_optional_absence_tdd_red | incident=`7f4b2c19-8e63-4a5d-9c71-2b0f6d8e3a14` | lesson_key=`survey-optional-absence-boundary` | event_sha256=`ed08eab9db6dfddd0b4e3b41ed631c217fedc144bdab62a6a76f5819d4e86997`
- #3: `2e7a4c91-6b35-48d0-a2f7-9c1e5b6d8034` | 2026-08-20T08:19:21.966Z | GATE/survey_optional_absence_green | incident=`4a8e2c71-5d93-46b0-9f18-7c2e6a4d0b35` | lesson_key=`survey-optional-absence-green` | event_sha256=`cf8a07fb530b0108761bab182a6f6df79c7efc943381ecf6144077bdf29cc65d`
- #4: `5b1e7c94-2d68-4a30-9f75-6c3e8b1a204d` | 2026-08-20T08:21:26.557Z | STATE_CHANGE/survey_absence_boundary_completed | incident=`8c4a1e73-5b92-46d0-9f27-3e6a8b1c5d40` | lesson_key=`survey-absence-boundary-closeout` | event_sha256=`a4e0c8cc63b1be3f826c7680985b289fc0ffab23a38d6d7ccd722de0a1ddb027`
- #5: `6c2a8e51-4d97-40b3-9f76-1e5a7c2d804b` | 2026-08-20T08:22:07.541Z | GATE/survey_optional_absence_red_resolved | incident=`7f4b2c19-8e63-4a5d-9c71-2b0f6d8e3a14` | lesson_key=`survey-optional-absence-red-resolved` | event_sha256=`79f8b5287326c5aa92d32eb5cbed0135791b5e3ab7deb781a4244cb3fdde35ad`
