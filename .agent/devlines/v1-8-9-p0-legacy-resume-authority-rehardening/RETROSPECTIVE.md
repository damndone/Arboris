# Retrospective — v1-8-9-p0-legacy-resume-authority-rehardening

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Authority Re-hardening Objective  Close the independent-review findings that remain after \`9cfa05ecf71efcb4e16678519780ab0ca9ff28e1\`: a legacy Agent confirmation must be bound to the route-owned persisted proposal and server-issued confirmation at creation time, and Resume must validate every persisted model branch directly before any callback or write.  Required outcomes:  - legacy confirmation reads exact proposal id, revision, fingerprint,   semantic plan hash, actor, session, and project from server-owned proposal,   compilation, and confirmation state; caller-supplied identity is never the   authority and no \`proposal:compilation-record\` fallback exists; - receipt type, receipt serialization/tamper integrity, proposal identity,   semantic hash, scope, and one-time replay state are validated before   \`_cutover_authority\`, compiler record lookup, compiler recording, or   execution; a first-claim mismatch leaves the claim store untouched; - same-proposal success is one-time and cross-scope, replay, serialized, and   tampered receipts fail closed; - \`validate_resumed_step_state()\` itself traverses every persisted model branch   and checks outcome, predictors, covariance, and family declaration against   the current compiled model step, including a terminal model step with no   downstream consumer; invalid state fails before callback or persistence; - compatibility response shapes remain separate from the authority gate.  This line owns only the legacy Agent cutover boundary, the Resume validation boundary, and their focused compiler/route/resume regression probes. It does not modify Report, data, classification, survey, provider, browser, or release paths.  ## Boundary  - Affected paths: \`backend/workbench/http/agent_routes.py\`,   \`backend/workbench/agent/orchestrator.py\`,   \`backend/workbench/agent/workflow_runtime.py\`,   \`tests/test_v189_legacy_route_authority.py\`,   \`tests/test_v189_agent_notebook_cutover.py\`,   \`tests/test_v189_resume_authority.py\` - Allowed paths: the affected paths above and this objective file - Protected paths: \`backend/workbench/http/runs_routes.py\`,   \`backend/workbench/report_view_model.py\`, \`frontend/src/report\`,   \`backend/workbench/engine/stages/estimation.py\`,   \`backend/workbench/providers\`, all Report/data/classification/survey paths,   and unrelated central Agent/workflow paths - Baseline: \`9cfa05ecf71efcb4e16678519780ab0ca9ff28e1\` - Dependencies: \`v1-8-9-p0-legacy-proposal-binding-remediation\`,   \`v1-8-9-p0-legacy-resume-hardening\`,   \`v1-8-9-p0-agent-compiler-core\`, \`v1-8-9-contract-lock\` - Tests: focused legacy route/proposal/compiler/resume/workflow suites,   RED-to-GREEN first-claim and terminal-model probes,   \`PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests\`,   \`git diff --check\`, formal verify, and formal retrospective generation - Known gates: browser/provider/full gate/release remain \`NOT VERIFIED\`;   no dependency installation and no push/PR/merge/tag/release

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/5 (40.0%; 40.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T00:30:00.000Z `legacy_resume_authority_red`; cause_status: `known`; cause: The RED probes observed caller-controlled or synthetic proposal identity, legacy execution reaching authority and record before receipt validation, and terminal model resume skipping persisted branch validation.; resolution: `accepted`; lesson: Bind proposal identity at server-side proposal and compile creation, validate typed receipts and all persisted model branches before any authority or write, and prove first-claim fail-closed behavior with spies.

## All errors

- #3 2026-08-20T00:40:00.000Z `receipt_precedence_iteration`; cause_status: `known`; cause: The first route GREEN iteration exposed two ordering mismatches: semantic-hint rejection was classified as an untyped receipt error, and a previously claimed receipt was checked after proposal identity.; resolution: `resolved`; lesson: Preserve replay precedence after typed receipt retrieval while classifying every malformed or mismatched receipt as a binding failure unless the receipt authority type itself is absent.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `legacy-resume-authority-red-before-green`: occurrences=1; cause_status: `known`; root cause: The RED probes observed caller-controlled or synthetic proposal identity, legacy execution reaching authority and record before receipt validation, and terminal model resume skipping persisted branch validation.; solution: `accepted`
- `route-receipt-validation-precedence`: occurrences=1; cause_status: `known`; root cause: The first route GREEN iteration exposed two ordering mismatches: semantic-hint rejection was classified as an untyped receipt error, and a previously claimed receipt was checked after proposal identity.; solution: `resolved`

## Added tests

- `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_agent_notebook_cutover.py::test_compiler_confirmation_uses_a_server_proposal_identity_not_record_id tests/test_v189_agent_notebook_cutover.py::test_compiler_confirmation_rejects_caller_supplied_proposal_identity tests/test_v189_legacy_route_authority.py::test_first_legacy_claim_uses_server_receipt_proposal_identity_before_execute tests/test_v189_resume_authority.py::test_resume_validates_terminal_model_branches_before_any_callback_or_write -q (4 failed)`
- `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_route_authority.py -q (2 failed before correction)`
- `focused pytest suite: 341 passed, 53 warnings; compileall backend/workbench tests: passed; git diff --check: passed`

## New rules

- `legacy-resume-authority-red-before-green`: line experience occurrence(s)=1
- `route-receipt-validation-precedence`: line experience occurrence(s)=1

## Future guidance

- Bind proposal identity at server-side proposal and compile creation, validate typed receipts and all persisted model branches before any authority or write, and prove first-claim fail-closed behavior with spies.
- Preserve replay precedence after typed receipt retrieval while classifying every malformed or mismatched receipt as a binding failure unless the receipt authority type itself is absent.

## Event index

- #1: `4b360374-a7a7-4018-a32c-7b5129766922` | 2026-08-20T00:19:06.610Z | STATE_CHANGE/line_started | incident=`2944e122-25aa-4551-ad83-7e30b21d13e6` | lesson_key=`frozen-context-before-start` | event_sha256=`a7baa516d80d8e963390ed1015fff5b1efd667dc18ba737d542a24a9d1890ed1`
- #2: `b5c6d7e8-f901-4234-8567-890abcdef012` | 2026-08-20T00:30:00.000Z | FAILURE/legacy_resume_authority_red | incident=`c6d7e8f9-0123-4567-890a-bcdef0123456` | lesson_key=`legacy-resume-authority-red-before-green` | event_sha256=`0c12aa3b291a3c809e01aa3d867ea716d51c4868a77a02f05403f5b0088cec2b`
- #3: `d7e8f901-2345-4678-9abc-def012345678` | 2026-08-20T00:40:00.000Z | ERROR/receipt_precedence_iteration | incident=`e8f90123-4567-489a-bcde-f0123456789a` | lesson_key=`route-receipt-validation-precedence` | event_sha256=`c369c63fcc6b7462447e9efd04a0ac4c456527b994ded8008190ad78ba20c85c`
- #4: `f9012345-6789-4abc-def0-123456789abc` | 2026-08-20T00:41:00.000Z | GATE/focused_legacy_resume_green | incident=`01234567-89ab-4cde-f012-3456789abcde` | lesson_key=`focused-legacy-resume-green-boundary` | event_sha256=`ad81a400c2ae5baf52a4d95b207eadddd3987a557051e99cff8a1d63b018d8fe`
- #5: `12345678-9abc-4def-0123-456789abcdef` | 2026-08-20T00:45:00.000Z | STATE_CHANGE/line_completed | incident=`23456789-abcd-4ef0-1234-56789abcdef0` | lesson_key=`close-formal-line-on-current-evidence` | event_sha256=`511195e47e20fce4f22e4f4db62a192937ffa12c132c2a5f221c81e5f56bfe55`
