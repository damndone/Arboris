# Retrospective — v1-8-9-p1-classification-production-remediation-8

## Goal

# Workbench v1.8.9 P1 Classification Production Remediation 8 Objective  Close the remaining independent-spec-review blocker from baseline \`caca840088ea449e1066a84d705c6284ae8f4070\`: the real ReportWorkspace artifacts-list path must fail closed with one typed unavailable/error contract when \`artifacts_index.json\` is missing or malformed, and the production classification regression assertions around lines 1047 and 1177 must enforce the exact invariant/code instead of accepting multiple alternatives.  The remediation is limited to the server repository/list route seam, the frontend ReportWorkspace classification/report seam, and focused tests. It must preserve all existing classification production, generic artifact integrity, Agent/Notebook, and central router behavior. No central Agent or Notebook router changes, provider calls, browser work, or release operations are in scope.  Required outcomes:  - \`backend/workbench/repository/run_repository.py\` and   \`backend/workbench/http/runs_routes.py\` return a stable typed   unavailable/error code for a missing or malformed \`artifacts_index.json\` at   the actual artifacts-list entrypoint; no raw \`JSONDecodeError\` or equivalent   exception crosses the HTTP boundary. - \`frontend/src/report/ReportWorkspaceContext.tsx\` consumes the typed list   outcome and keeps Report unavailable; it never treats a missing index as an   empty successful \`groups\` result and never continues with an untyped error. - The focused negative probes reproduce both failures before the fix and pass   after the fix through the real repository/route/ReportWorkspace seams. - The assertions near lines 1047 and 1177 in   \`tests/test_v189_classification_production.py\` use exact invariant/code   values, with RED probes proving the old permissive assertions would have   allowed an invalid result.  The central Agent/Notebook router, browser acceptance, provider benchmark, host full gate, merge, tag, release, and root-main synchronization remain \`NOT VERIFIED\` and outside this remediation line.

## Final status

COMPLETED_WITH_KNOWN_GATES

## Metrics

- Failure frequency: 4/10 (40.0%; 40.0 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-19T23:52:00.000Z `classification_remediation_eight_red`; cause_status: `known`; cause: The real artifacts-list route returned 200 with empty groups when artifacts_index.json was missing and leaked JSONDecodeError for malformed JSON; the production tests also accepted multiple incompatible contract codes.; resolution: `accepted`; lesson: Probe the actual repository, route, and frontend list seams before implementation and assert one exact code for each invariant.

## All errors

- #3 2026-08-19T23:52:10.000Z `classification_remediation_eight_formal_timestamp_error`; cause_status: `known`; cause: The first RED event append used a UTC timestamp without the required millisecond precision and the formal CLI rejected it before changing the event stream.; resolution: `resolved`; lesson: Validate formal event timestamps against the CLI schema before append.
- #7 2026-08-19T23:56:00.000Z `classification_remediation_eight_frontend_message_compatibility`; cause_status: `known`; cause: The first typed frontend error message changed the established figure-inventory wording, causing one existing ReportView assertion to fail even though the new typed code was preserved.; resolution: `resolved`; lesson: Preserve established user-facing error wording while adding the typed server code to the same message.
- #8 2026-08-19T23:56:10.000Z `classification_remediation_eight_api_fixture_boundary`; cause_status: `known`; cause: The broader API artifact selector included two asynchronous completed-run fixture assertions that failed because the generated report artifact was absent; direct artifacts_index schema probes passed and the failure was outside the remediation path.; resolution: `accepted`; lesson: Separate route-contract probes from asynchronous host fixture assumptions before interpreting a related-suite failure as a remediation regression.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `classification-remediation-eight-api-fixture-boundary`: occurrences=1; cause_status: `known`; root cause: The broader API artifact selector included two asynchronous completed-run fixture assertions that failed because the generated report artifact was absent; direct artifacts_index schema probes passed and the failure was outside the remediation path.; solution: `accepted`
- `classification-remediation-eight-formal-timestamp-error`: occurrences=1; cause_status: `known`; root cause: The first RED event append used a UTC timestamp without the required millisecond precision and the formal CLI rejected it before changing the event stream.; solution: `resolved`
- `classification-remediation-eight-frontend-message-compatibility`: occurrences=1; cause_status: `known`; root cause: The first typed frontend error message changed the established figure-inventory wording, causing one existing ReportView assertion to fail even though the new typed code was preserved.; solution: `resolved`
- `classification-remediation-eight-red`: occurrences=1; cause_status: `known`; root cause: The real artifacts-list route returned 200 with empty groups when artifacts_index.json was missing and leaked JSONDecodeError for malformed JSON; the production tests also accepted multiple incompatible contract codes.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `classification-remediation-eight-api-fixture-boundary`: line experience occurrence(s)=1
- `classification-remediation-eight-formal-timestamp-error`: line experience occurrence(s)=1
- `classification-remediation-eight-frontend-message-compatibility`: line experience occurrence(s)=1
- `classification-remediation-eight-red`: line experience occurrence(s)=1

## Future guidance

- Preserve established user-facing error wording while adding the typed server code to the same message.
- Preserve server-owned list error codes at the ReportWorkspace seam and gate report continuation on the same typed inventory failure.
- Probe the actual repository, route, and frontend list seams before implementation and assert one exact code for each invariant.
- Separate route-contract probes from asynchronous host fixture assumptions before interpreting a related-suite failure as a remediation regression.
- Validate formal event timestamps against the CLI schema before append.

## Event index

- #1: `df8fc073-f28d-47ac-8f46-3fc227779235` | 2026-08-19T23:45:36.926Z | STATE_CHANGE/line_started | incident=`ba25c548-cfff-4335-b7cd-cdcd2e4ddaf6` | lesson_key=`frozen-context-before-start` | event_sha256=`41a2f6bfd681872828f23d80f74fb41c807cf3a66c423b1d19ebbbbb8e17894d`
- #2: `6a7b8c9d-0e1f-4234-a567-89abcdef0123` | 2026-08-19T23:52:00.000Z | FAILURE/classification_remediation_eight_red | incident=`7b8c9d0e-1f2a-4345-b678-9abcdef01234` | lesson_key=`classification-remediation-eight-red` | event_sha256=`56f6a03da40cedbb18a43fe1c8dd0112e980730c7c9d52f88b381e5505445e17`
- #3: `8c9d0e1f-2a3b-4456-c789-abcdef012345` | 2026-08-19T23:52:10.000Z | ERROR/classification_remediation_eight_formal_timestamp_error | incident=`9d0e1f2a-3b4c-4567-89ab-cdef01234567` | lesson_key=`classification-remediation-eight-formal-timestamp-error` | event_sha256=`79204e607a36163ecd1203047f4ee6c132ca56ffb75446b8e5ed0b3a747b2ec1`
- #4: `30aa7c8d-f321-4dc8-8fa6-2469249b1811` | 2026-08-19T23:51:10.176Z | STATE_CHANGE/context_rescope_required | incident=`1b07e2b6-8194-4bf7-9dd5-d2692b2d2242` | lesson_key=`context-pack-rescope` | event_sha256=`0df164e5ae9757eed9ea4549fafbd382fd9928db736131cbbeec76ef0dfe512f`
- #5: `df4d2b36-3d5d-42b1-85fb-eec9d6839b3f` | 2026-08-19T23:51:10.181Z | STATE_CHANGE/context_rescoped | incident=`ac132b88-e55d-47cf-bb8f-2d1f1d74b4f5` | lesson_key=`context-pack-rescope` | event_sha256=`a943cfff3aaa4041c46fae45da3420e8c9688282e0f8d81d9a197171293e0c63`
- #6: `0e1f2a3b-4c5d-4678-9abc-def012345678` | 2026-08-19T23:54:00.000Z | REVIEW/classification_remediation_eight_frontend_red | incident=`1f2a3b4c-5d6e-4789-abcd-ef0123456789` | lesson_key=`classification-remediation-eight-frontend-red` | event_sha256=`9ae5448ec53a135f8ad646f2946011f7c8f0c114655a3f0edffa8f4334332da9`
- #7: `2a3b4c5d-6e7f-4890-abcd-ef0123456789` | 2026-08-19T23:56:00.000Z | ERROR/classification_remediation_eight_frontend_message_compatibility | incident=`3b4c5d6e-7f80-4901-bcde-f0123456789a` | lesson_key=`classification-remediation-eight-frontend-message-compatibility` | event_sha256=`1b928e1ee0d7eff124cbea1aa73c3c6a1c1068056c53a45ae953319f039454c7`
- #8: `4c5d6e7f-8091-4a2b-cdef-0123456789ab` | 2026-08-19T23:56:10.000Z | ERROR/classification_remediation_eight_api_fixture_boundary | incident=`5d6e7f80-912a-4b3c-def0-123456789abc` | lesson_key=`classification-remediation-eight-api-fixture-boundary` | event_sha256=`92cfc62f4f9de561311ef94bc45599ffc363acebd15044d4ca7c541828795cd4`
- #9: `6e7f8091-2a3b-4c5d-ef01-23456789abcd` | 2026-08-19T23:58:00.000Z | GATE/classification_remediation_eight_green | incident=`7f80912a-3b4c-4d5e-f012-3456789abcde` | lesson_key=`classification-remediation-eight-green` | event_sha256=`0164136ce6155eb890a96abd628327ccb89ffffbfd204f4f5f89f35bc5cc0bf1`
- #10: `80912a3b-4c5d-4e6f-0123-456789abcdef` | 2026-08-19T23:59:00.000Z | STATE_CHANGE/classification_remediation_eight_terminal | incident=`91a3b4c5-d6e7-4890-ab12-3456789abcde` | lesson_key=`classification-remediation-eight-terminal` | event_sha256=`e6cd7eae93b264e1571236d8888137351d155bdcd8a864b23056765fc3c77995`
