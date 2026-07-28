# Retrospective — v1-8-3-cf4-recommendation-authority-guard

## Goal

Close the P1 recommendation authority gap at the Notebook write seam. A capability-bound option may produce NotebookOptionRevision@1.2 only when its recommendation is RecommendationDecisionV11 and the service can validate that decision against a persisted server-owned FeasibilityDecision or ComparisonDecision. Legacy RecommendationDecision@1.0 must fail closed before any option, decision, Draft, or materialization write. Preserve the existing legacy path for unbound options. Add focused regression tests and update only the affected capability-bound expectations; do not synthesize a server decision from Agent claims and do not open execution.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/7 (42.9%; 42.9 per 100 events)
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

- #4 2026-07-27T10:10:00.000Z `tdd_red_legacy_decision_reached_bound_option`; cause_status: `known`; cause: The focused regression reached the write seam and showed that a legacy recommendation can still mint a capability-bound option instead of failing closed.; resolution: `accepted`; lesson: Exercise the authority boundary with an admitted capability and a legacy decision before changing the service.

## All errors

- #2 2026-07-27T10:06:00.000Z `recommendation_guard_fixture_import_error`; cause_status: `known`; cause: The new regression fixture imported helpers from the wrong existing test module and failed during collection.; resolution: `resolved`; lesson: Check the exact existing test fixture module before adding a cross-test regression import.
- #3 2026-07-27T10:08:00.000Z `recommendation_guard_fixture_scope_mismatch`; cause_status: `known`; cause: The regression fixture changed the project identity while reusing a binding scoped to the default project, so the test stopped at the earlier scope guard.; resolution: `resolved`; lesson: Keep test project identity aligned with the scope identity pinned by the server-owned binding.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `guard-fixture-import-path`: occurrences=1; cause_status: `known`; root cause: The new regression fixture imported helpers from the wrong existing test module and failed during collection.; solution: `resolved`
- `guard-fixture-scope-identity`: occurrences=1; cause_status: `known`; root cause: The regression fixture changed the project identity while reusing a binding scoped to the default project, so the test stopped at the earlier scope guard.; solution: `resolved`
- `legacy-recommendation-boundary-red`: occurrences=1; cause_status: `known`; root cause: The focused regression reached the write seam and showed that a legacy recommendation can still mint a capability-bound option instead of failing closed.; solution: `accepted`

## Added tests

- `tests/test_capability_recommendation_guard.py`
- `tests/test_capability_recommendation_guard.py;tests/test_notebook_capability_binding.py;tests/test_notebook_recommendation.py;tests/test_no_exercise_specific_naming.py`

## New rules

- `guard-fixture-import-path`: line experience occurrence(s)=1
- `guard-fixture-scope-identity`: line experience occurrence(s)=1
- `legacy-recommendation-boundary-red`: line experience occurrence(s)=1

## Future guidance

- Check the exact existing test fixture module before adding a cross-test regression import.
- Exercise the authority boundary with an admitted capability and a legacy decision before changing the service.
- Keep test project identity aligned with the scope identity pinned by the server-owned binding.
- Reject legacy authority at the narrowest write seam before it can create a bound option or any durable record.

## Event index

- #1: `dab2aac0-706f-4a31-b71c-2744c2a6e4ec` | 2026-07-27T06:02:23.571Z | STATE_CHANGE/line_started | incident=`227c91df-4f1e-4fcb-aa97-d84a2ba51c57` | lesson_key=`frozen-context-before-start` | event_sha256=`ff68ce80eac2088362e1049942b30cef23df61b81b8049b09f4b7553ccbfd36e`
- #2: `ef012345-6789-4abc-def0-123456789abc` | 2026-07-27T10:06:00.000Z | ERROR/recommendation_guard_fixture_import_error | incident=`ef012345-6789-4abc-def0-123456789abd` | lesson_key=`guard-fixture-import-path` | event_sha256=`bfed0825f92b9f38762ec4ba21c4052f67b14fa4c742e362fbab3c7840af77cc`
- #3: `f0123456-789a-4bcd-ef01-23456789abcd` | 2026-07-27T10:08:00.000Z | ERROR/recommendation_guard_fixture_scope_mismatch | incident=`f0123456-789a-4bcd-ef01-23456789abce` | lesson_key=`guard-fixture-scope-identity` | event_sha256=`87a8da2a36a8cddff31f80030124334283b8b4e71a1002ad6e5964660f02e3a5`
- #4: `01234567-89ab-4cde-f012-3456789abcde` | 2026-07-27T10:10:00.000Z | FAILURE/tdd_red_legacy_decision_reached_bound_option | incident=`01234567-89ab-4cde-f012-3456789abcdf` | lesson_key=`legacy-recommendation-boundary-red` | event_sha256=`86273aa284cb3e19a3e0fa0b1bda85c8fe7f1d2e2770dc3de36863c37e25b6fb`
- #5: `12345678-9abc-4def-0123-456789abcdef` | 2026-07-27T10:16:00.000Z | REVIEW/recommendation_authority_guard_review_accepted | incident=`12345678-9abc-4def-0123-456789abcdf0` | lesson_key=`bound-option-requires-v11-authority` | event_sha256=`12d189920a88cacd2fa9ac8fdddfcf0f4fe4a2007a7f72ca96256fb2d410562e`
- #6: `23456789-abcd-4ef0-1234-56789abcdef0` | 2026-07-27T10:18:00.000Z | GATE/recommendation_authority_guard_targeted_gate | incident=`23456789-abcd-4ef0-1234-56789abcdef1` | lesson_key=`guard-before-producer-upgrade` | event_sha256=`925ae584412e816894dc58a276613fd91257b8ce7e8d6f607653d22a10da5ce2`
- #7: `3456789a-bcde-4f01-2345-6789abcdef01` | 2026-07-27T10:19:00.000Z | STATE_CHANGE/recommendation_authority_guard_completed | incident=`3456789a-bcde-4f01-2345-6789abcdef02` | lesson_key=`close-recommendation-bypass-first` | event_sha256=`59cdb7d9e7077687dce5fe8086ec9f54dba518c9b18b94816329fceacab82c80`
