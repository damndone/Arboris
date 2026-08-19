# Retrospective — v1-8-9-p0-legacy-resume-hardening

## Goal

# Workbench v1.8.9 P0 Legacy Route and Resume Hardening Objective  Remove the remaining executable authority bypasses and make resume trust the server-owned completion/admission/artifact bindings rather than only persisted plan fingerprints.  Required outcomes:  - historical executable Notebook confirmation paths use the same server   AgentNotebookCompilerV1 compile/confirm/execute boundary as the new cutover; - historical executable Agent proposal confirmation paths cannot call the old   orchestrator directly without a server compilation record and confirmation; - resume revalidates persisted artifact IDs, output bindings and lineage   against the server completion/admission registry before any dependent   callback or new artifact write; - persisted model branches are equal to the current compiled model step's   outcome, predictors, covariance and family declaration, not merely the same   artifact identity; - mismatches fail closed with typed errors and do not execute user code or   write new artifacts.  This line owns legacy Agent/Notebook route adapters and workflow resume/branch validation plus focused regression tests. It does not modify Report consumer code, model estimators, provider implementations, browser fixtures, or release sidecars. Historical response-shape compatibility must remain explicitly separated from the security/correctness gate.

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/9 (44.4%; 44.4 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=3)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-19T16:45:00.000Z `tdd_red_legacy_resume_authority`; cause_status: `known`; cause: The six new authority-boundary tests fail on the baseline: legacy routes still reach old execution authority, Resume accepts forged persisted metadata, and model branch declarations are not compared with the compiled model step.; resolution: `accepted`; lesson: Keep legacy execution routes fail-closed and verify persisted workflow truth before callback or dependent artifact work.
- #3 2026-08-19T17:08:00.000Z `focused_regression_after_authority_hardening`; cause_status: `known`; cause: The first post-implementation focused run exposed three regressions: aborted evidence sequencing changed and two resume fixtures used the persisted workflow_step_id field rather than the old step_id expectation.; resolution: `resolved`; lesson: Run the inherited focused resume suite after adding persisted admission evidence and preserve abort ordering while rebinding resumed rows to the server schema.
- #6 2026-08-19T17:20:00.000Z `independent_spec_review_red`; cause_status: `known`; cause: Independent Legacy/Resume review probes were red before the hardening implementation: historical Notebook v1.0 confirm reached the legacy service, Agent bindings could select proposal scope and bypass identity binding, revoked or aborted admissions still resumed, corrupt completion metadata was rehydrated before seal validation, and model.custom branches lacked a server branch declaration gate.; resolution: `accepted`; lesson: Run adversarial probes against every retained compatibility entry point before treating a focused green suite as a complete authority boundary.

## All errors

- None recorded.

## All gaps

- #8 2026-08-19T18:05:00.000Z `inherited_workflow_seam_fixture`; cause_status: `known`; cause: The broader inherited workflow seam suite has fixtures that omit active_head_run_id, so compile_workflow fails at the existing WORKFLOW_SCOPE_MISSING boundary before the seam assertions run; the current implementation diff does not modify that compiler scope contract.; resolution: `accepted`; lesson: Separate unchanged inherited fixture failures from the scoped authority gate, and do not weaken a server admission scope contract to satisfy stale setup data.

## All waste

- None recorded.

## Root causes and solutions

- `focused-regression-after-resume-hardening`: occurrences=1; cause_status: `known`; root cause: The first post-implementation focused run exposed three regressions: aborted evidence sequencing changed and two resume fixtures used the persisted workflow_step_id field rather than the old step_id expectation.; solution: `resolved`
- `independent-spec-review-red`: occurrences=1; cause_status: `known`; root cause: Independent Legacy/Resume review probes were red before the hardening implementation: historical Notebook v1.0 confirm reached the legacy service, Agent bindings could select proposal scope and bypass identity binding, revoked or aborted admissions still resumed, corrupt completion metadata was rehydrated before seal validation, and model.custom branches lacked a server branch declaration gate.; solution: `accepted`
- `inherited-seam-fixture-scope-gap`: occurrences=1; cause_status: `known`; root cause: The broader inherited workflow seam suite has fixtures that omit active_head_run_id, so compile_workflow fails at the existing WORKFLOW_SCOPE_MISSING boundary before the seam assertions run; the current implementation diff does not modify that compiler scope contract.; solution: `accepted`
- `legacy-resume-branch-authority-red-first`: occurrences=1; cause_status: `known`; root cause: The six new authority-boundary tests fail on the baseline: legacy routes still reach old execution authority, Resume accepts forged persisted metadata, and model branch declarations are not compared with the compiled model step.; solution: `accepted`

## Added tests

- `tests/test_notebook_materialization.py::test_legacy_confirmation_remains_legacy_without_a_materialized_lie`
- `tests/test_v189_legacy_route_authority.py; tests/test_v189_resume_authority.py; tests/test_v189_workflow_truth.py`
- `tests/test_v189_legacy_route_authority.py;tests/test_v189_resume_authority.py;tests/test_v189_workflow_truth.py`
- `tests/test_workflow_resume.py`
- `tests/test_workflow_seam.py`

## New rules

- `focused-regression-after-resume-hardening`: line experience occurrence(s)=1
- `independent-spec-review-red`: line experience occurrence(s)=1
- `inherited-seam-fixture-scope-gap`: line experience occurrence(s)=1
- `legacy-resume-branch-authority-red-first`: line experience occurrence(s)=1

## Future guidance

- Keep legacy execution routes fail-closed and verify persisted workflow truth before callback or dependent artifact work.
- Run adversarial probes against every retained compatibility entry point before treating a focused green suite as a complete authority boundary.
- Run the inherited focused resume suite after adding persisted admission evidence and preserve abort ordering while rebinding resumed rows to the server schema.
- Separate unchanged inherited fixture failures from the scoped authority gate, and do not weaken a server admission scope contract to satisfy stale setup data.
- When the security contract removes a legacy execution authority, retain the typed refusal and report stale inherited expectations separately instead of restoring the bypass.

## Event index

- #1: `67572805-c70d-4101-96ef-d37366cb19a2` | 2026-08-19T16:34:43.796Z | STATE_CHANGE/line_started | incident=`159c397a-666a-419d-b6f6-c97c5a5cddfd` | lesson_key=`frozen-context-before-start` | event_sha256=`e3dfabc485fb45f3558398953289e6796549ee333407fb607a5642a70d3de681`
- #2: `b18b0b7d-2f70-4bd0-8a51-75f5de4d2026` | 2026-08-19T16:45:00.000Z | FAILURE/tdd_red_legacy_resume_authority | incident=`f98a69e1-2e2a-4f44-8d31-fb1f9b6e48d1` | lesson_key=`legacy-resume-branch-authority-red-first` | event_sha256=`5b80f9f88bf298871f50316f7cff84f597634e7a51a27225b35a4f9a84ca5cf9`
- #3: `d0a1b2c3-4d5e-4678-9abc-def012345678` | 2026-08-19T17:08:00.000Z | FAILURE/focused_regression_after_authority_hardening | incident=`e1a2b3c4-d5e6-4789-abcd-ef0123456789` | lesson_key=`focused-regression-after-resume-hardening` | event_sha256=`e2a3e2cfa6d81ccafa2de83736f60feea46917ca144231ec6a7deef75169d166`
- #4: `f2b3c4d5-e6f7-4890-ab12-cd3456789012` | 2026-08-19T17:10:00.000Z | GATE/focused_verification_passed | incident=`a3b4c5d6-e7f8-4901-ab23-cd4567890123` | lesson_key=`focused-authority-gate-before-handoff` | event_sha256=`afdc0ddfbc34ecd88c67b50772d4f385474316a4faf6cde06b768a70e2df790e`
- #5: `c4d5e6f7-8901-4a23-bcde-f56789012345` | 2026-08-19T17:11:00.000Z | STATE_CHANGE/line_completed | incident=`d5e6f789-0123-4abc-def5-678901234567` | lesson_key=`package-local-closeout-keeps-external-gates-separate` | event_sha256=`f6bfdb31f11f633c9b07d827cab874c7264fa3f2f378da950317c5bb8795ca1e`
- #6: `e6f78901-234a-4bcd-ef56-789012345678` | 2026-08-19T17:20:00.000Z | FAILURE/independent_spec_review_red | incident=`f7890123-456a-4bcd-ef78-901234567890` | lesson_key=`independent-spec-review-red` | event_sha256=`26470bda14ae6456215dbc7eb9816becc12e68f3ec88d4b3c87a311a289af181`
- #7: `a0123456-789b-4cde-f012-345678901234` | 2026-08-19T17:35:00.000Z | REVIEW/inherited_legacy_expectation | incident=`b1234567-89ac-4def-0123-456789012345` | lesson_key=`legacy-expectation-conflicts-with-fail-closed` | event_sha256=`b93a203f63f2b923c658b1672b4d4d414fa5071cb450de21fcb2af6b6e24730a`
- #8: `c2345678-9abd-4ef0-1234-567890123456` | 2026-08-19T18:05:00.000Z | GAP/inherited_workflow_seam_fixture | incident=`d3456789-abcd-4f01-2345-678901234567` | lesson_key=`inherited-seam-fixture-scope-gap` | event_sha256=`192c020260d53608234a6c1fb6021de5901acde7035ae85c5a824a08a650bedb`
- #9: `d456789a-bcde-4f12-3456-789012345678` | 2026-08-19T18:20:00.000Z | GATE/post_review_hardening_closeout | incident=`e56789ab-cdef-4012-3456-789012345678` | lesson_key=`legacy-resume-post-review-closeout` | event_sha256=`72248703fc179a4b90896d720469ee4e7c2464a8d7c9b2f701f5181c622c4e06`
