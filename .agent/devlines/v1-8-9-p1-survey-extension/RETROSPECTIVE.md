# Retrospective — v1-8-9-p1-survey-extension

## Goal

# Workbench v1.8.9 P1 Complex Survey Extension Objective  Extend the existing family-agnostic survey variance engine through real workflow estimation hooks for Logit, Probit, and Poisson. The implementation must use the declared sampling design and the same variance semantics as the existing OLS path, including Taylor/linearization or replicate weights, design degrees of freedom, lonely-PSU/subpopulation policy, design effect, effective sample size, and explicit replicate failure handling.  The capability registry and UI must not advertise a family as survey-capable unless the estimator path actually applies the survey variance result. Any unsupported family/design combination must be typed blocked or unavailable; never fall back to naive model-based standard errors while retaining survey labels.  This line is limited to survey design/estimation adapters and their tests. It does not add new model families, change central Agent/Notebook routing, call an external provider, or claim browser/full-gate/release evidence.  The exact estimation outputs must retain coefficient-level variance source, design df, confidence intervals, p-values, survey metadata, and artifact provenance so Agent/Notebook/Report consumers can distinguish survey results from ordinary model results.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/10 (50.0%; 50.0 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-19T16:58:00.000Z `survey_glm_wiring_red`; cause_status: `known`; cause: The required RED run showed that Logit, Probit, and Poisson family workflows completed without entering the shared survey variance engine, and the unsupported FPC workflow completed instead of being blocked.; resolution: `resolved`; lesson: Instrument real family workflows before trusting capability declarations.

## All errors

- #4 2026-08-19T16:58:20.000Z `formal_cli_probe_error`; cause_status: `known`; cause: An unsupported devline-control subcommand and an unavailable interpreter path were used during an early status probe before the formal CLI command surface was checked.; resolution: `resolved`; lesson: Use the worktree interpreter and inspect the formal CLI command surface before appending line evidence.
- #8 2026-08-19T16:59:10.000Z `formal_event_schema_probe`; cause_status: `known`; cause: The first core verification event source used preventability=not_applicable, which the formal event schema correctly rejected before append.; resolution: `resolved`; lesson: Validate formal event vocabulary before submitting gate evidence.

## All gaps

- #5 2026-08-19T16:58:30.000Z `report_admission_receipt_boundary`; cause_status: `known`; cause: The existing survey report visibility tests reach run completion, but HTML report rendering is refused by the protected report helper because this direct test workflow has no admitted server receipt.; resolution: `accepted`; lesson: Keep package-local survey evidence separate from the protected admission-receipt and browser acceptance boundary.
- #6 2026-08-19T16:58:40.000Z `capability_bootstrap_import_boundary`; cause_status: `known`; cause: A clean-process direct build_capabilities probe failed in the pre-existing StatisticalTestsStage and orchestrator circular import before reaching the survey capability projection; the scoped capability composition tests pass through their established harness.; resolution: `accepted`; lesson: Report capability projection tests with their actual bootstrap context and keep unrelated import-cycle gates out of the survey implementation scope.

## All waste

- None recorded.

## Root causes and solutions

- `instrument-real-survey-workflows`: occurrences=1; cause_status: `known`; root cause: The required RED run showed that Logit, Probit, and Poisson family workflows completed without entering the shared survey variance engine, and the unsupported FPC workflow completed instead of being blocked.; solution: `resolved`
- `separate-capability-bootstrap-gate`: occurrences=1; cause_status: `known`; root cause: A clean-process direct build_capabilities probe failed in the pre-existing StatisticalTestsStage and orchestrator circular import before reaching the survey capability projection; the scoped capability composition tests pass through their established harness.; solution: `accepted`
- `separate-report-receipt-gate`: occurrences=1; cause_status: `known`; root cause: The existing survey report visibility tests reach run completion, but HTML report rendering is refused by the protected report helper because this direct test workflow has no admitted server receipt.; solution: `accepted`
- `validate-event-vocabulary`: occurrences=1; cause_status: `known`; root cause: The first core verification event source used preventability=not_applicable, which the formal event schema correctly rejected before append.; solution: `resolved`
- `verify-formal-cli-surface`: occurrences=1; cause_status: `known`; root cause: An unsupported devline-control subcommand and an unavailable interpreter path were used during an early status probe before the formal CLI command surface was checked.; solution: `resolved`

## Added tests

- `tests/test_survey_glm_family_wiring_v189.py`
- `tests/test_survey_report_visibility_v187.py`

## New rules

- `instrument-real-survey-workflows`: line experience occurrence(s)=1
- `separate-capability-bootstrap-gate`: line experience occurrence(s)=1
- `separate-report-receipt-gate`: line experience occurrence(s)=1
- `validate-event-vocabulary`: line experience occurrence(s)=1
- `verify-formal-cli-surface`: line experience occurrence(s)=1

## Future guidance

- Instrument real family workflows before trusting capability declarations.
- Keep model-specific link and offset details inside the shared estimator adapter, not in a second variance workflow.
- Keep package-local survey evidence separate from the protected admission-receipt and browser acceptance boundary.
- Report capability projection tests with their actual bootstrap context and keep unrelated import-cycle gates out of the survey implementation scope.
- Use the worktree interpreter and inspect the formal CLI command surface before appending line evidence.
- Validate formal event vocabulary before submitting gate evidence.

## Event index

- #1: `3fb0b117-2c74-41d0-bb0a-c5d05d9abeda` | 2026-08-19T16:35:26.403Z | STATE_CHANGE/line_started | incident=`ed0c69d8-27ae-4324-abe5-6eb868a02d71` | lesson_key=`frozen-context-before-start` | event_sha256=`ae7dd5a660580499bcba750502b403539cdfb045a7d124bbd395010883641338`
- #2: `2f3dcb4a-7a67-4f5b-9a5b-1b6f4c8e2d91` | 2026-08-19T16:58:00.000Z | FAILURE/survey_glm_wiring_red | incident=`af763810-5ed4-4db2-8a5e-0cb5a2b93c61` | lesson_key=`instrument-real-survey-workflows` | event_sha256=`641cc7bd5801cdd1f40a996bb8dccc5539d84d903f231debb26a131faf9c6f35`
- #3: `7c9b2f16-3e54-4a8f-9d12-6b7e5f0a4c83` | 2026-08-19T16:58:10.000Z | REVIEW/shared_adapter_link_decision | incident=`b2e8a4c7-1d96-4f30-8a5b-7c2d9e6f1048` | lesson_key=`shared-adapter-link-and-offset` | event_sha256=`bca7542f4aac8b81dc0460824e58808a8c07ba4089bfa702439ba232f9af715f`
- #4: `4a1d8e63-2f70-4c95-b8e4-3d6a9f1027cb` | 2026-08-19T16:58:20.000Z | ERROR/formal_cli_probe_error | incident=`d9c4e7a1-6b20-4f83-9a5d-2c7e1048b6f9` | lesson_key=`verify-formal-cli-surface` | event_sha256=`34b4bcfefe6aa3600915def075fa464c86924bc3fc2dd015c87b9af608365c60`
- #5: `8e2b6d41-9f70-4c53-a8d1-6b5e2037f94a` | 2026-08-19T16:58:30.000Z | GAP/report_admission_receipt_boundary | incident=`c6a1e8d4-2f79-4b53-9d0e-7c5a1048f632` | lesson_key=`separate-report-receipt-gate` | event_sha256=`f48a4793d529dd53846942ddde5e344aa81e4a49a58e4e980b0295cc24d4fb2d`
- #6: `5d9a2f70-4c63-8e11-b7a5-0d2e9461f8cb` | 2026-08-19T16:58:40.000Z | GAP/capability_bootstrap_import_boundary | incident=`a4e7c1d9-2f60-4b83-9d5a-7c1048e6f2b3` | lesson_key=`separate-capability-bootstrap-gate` | event_sha256=`0d984cf1fb9a3d597934821b8622a73b050ce82b1e113dfd49ce72b1e3654df2`
- #7: `9b4e1d72-6a80-4f35-c9b1-7e2d5083a6f4` | 2026-08-19T16:59:00.000Z | GATE/survey_core_verification_green | incident=`e1a7c4d9-2f80-4b63-9d5e-7c1048f6a2b1` | lesson_key=`green-core-survey-gate` | event_sha256=`6ffc9447e5ddd31b1498dad8318cfd50fae025895750a93c39938f76f7ffc9f7`
- #8: `6f2a8d41-5c70-4e93-b1d6-9a2048c7f3be` | 2026-08-19T16:59:10.000Z | ERROR/formal_event_schema_probe | incident=`c1e7a4d9-2f80-4b63-9d5a-6c1048f7a2b3` | lesson_key=`validate-event-vocabulary` | event_sha256=`b3acf13c9ec1dffd3123b233b1542f21d17edc90c086644bb28d967077540344`
- #9: `3e8a1d64-7c20-4f95-b6d1-9a5042c7f8be` | 2026-08-19T16:59:20.000Z | GATE/compile_and_diff_check_green | incident=`d4c7a1e9-2f80-4b63-9d5a-6c1048f7a2b3` | lesson_key=`compile-and-diff-gate` | event_sha256=`5c04e25c6ce6f662ec4e1979c7dcb0b6a73aaed62cf88f8b6cc6f8d14267cae8`
- #10: `1d7a4e92-6c30-4f85-b9e1-2a5078c3d6fb` | 2026-08-19T17:01:00.000Z | STATE_CHANGE/line_completed | incident=`e4a1c7d9-2f60-4b83-9d5a-6c1048f7a2b3` | lesson_key=`explicit-boundary-line-close` | event_sha256=`cc22ffc7fd8c26307534c6cc05cd4111df8778ab42917cc60cfe11190e0f2016`
