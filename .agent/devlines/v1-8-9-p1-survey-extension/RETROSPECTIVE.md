# Retrospective — v1-8-9-p1-survey-extension

## Goal

# Workbench v1.8.9 P1 Complex Survey Extension Objective  Extend the existing family-agnostic survey variance engine through real workflow estimation hooks for Logit, Probit, and Poisson. The implementation must use the declared sampling design and the same variance semantics as the existing OLS path, including Taylor/linearization or replicate weights, design degrees of freedom, lonely-PSU/subpopulation policy, design effect, effective sample size, and explicit replicate failure handling.  The capability registry and UI must not advertise a family as survey-capable unless the estimator path actually applies the survey variance result. Any unsupported family/design combination must be typed blocked or unavailable; never fall back to naive model-based standard errors while retaining survey labels.  This line is limited to survey design/estimation adapters and their tests. It does not add new model families, change central Agent/Notebook routing, call an external provider, or claim browser/full-gate/release evidence.  The exact estimation outputs must retain coefficient-level variance source, design df, confidence intervals, p-values, survey metadata, and artifact provenance so Agent/Notebook/Report consumers can distinguish survey results from ordinary model results.

## Final status

COMPLETED

## Metrics

- Failure frequency: 9/28 (32.1%; 32.1 per 100 events)
- Repeat rate: 0/9 (0.0%)
- Recurrence rate: 0/9 (0.0%)
- MTTR: median=0 ms (sample=5; unresolved=4)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/6 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-19T16:58:00.000Z `survey_glm_wiring_red`; cause_status: `known`; cause: The required RED run showed that Logit, Probit, and Poisson family workflows completed without entering the shared survey variance engine, and the unsupported FPC workflow completed instead of being blocked.; resolution: `resolved`; lesson: Instrument real family workflows before trusting capability declarations.
- #13 2026-08-19T17:23:50.000Z `reviewer_spec_compliance_red`; cause_status: `known`; cause: The reviewer-directed RED probes showed that auto count falls through to the OLS fallback instead of the weighted poisson_rate handler, the clean capability helper is absent while build_capabilities hits the central import cycle, and both direct report HTML assertions still encounter a missing report artifact.; resolution: `open`; lesson: Turn reviewer findings into output-level red probes before changing production wiring or acceptance scope.
- #18 2026-08-19T17:56:49.000Z `invalid_survey_inputs_red`; cause_status: `known`; cause: The new real-entry probes show that SurveyDesign accepts negative, non-finite, and all-zero sampling weights, the engine accepts a mutated all-zero weight frame, and Poisson exposure values can be treated as ordinary predictors or raise an untyped overflow instead of a stable typed failure.; resolution: `open`; lesson: Probe mutable real entry points and invalid family inputs before trusting downstream numerical failures or capability declarations.

## All errors

- #4 2026-08-19T16:58:20.000Z `formal_cli_probe_error`; cause_status: `known`; cause: An unsupported devline-control subcommand and an unavailable interpreter path were used during an early status probe before the formal CLI command surface was checked.; resolution: `resolved`; lesson: Use the worktree interpreter and inspect the formal CLI command surface before appending line evidence.
- #8 2026-08-19T16:59:10.000Z `formal_event_schema_probe`; cause_status: `known`; cause: The first core verification event source used preventability=not_applicable, which the formal event schema correctly rejected before append.; resolution: `resolved`; lesson: Validate formal event vocabulary before submitting gate evidence.
- #23 2026-08-19T18:08:03.000Z `formal_event_schema_probe`; cause_status: `known`; cause: The first append attempt supplied two SHA-256 digests in one evidence.sha256 field, and the formal CLI rejected the event before it entered the chain.; resolution: `resolved`; lesson: Submit one digest per formal evidence block and let the CLI validate the event before treating it as recorded.

## All gaps

- #5 2026-08-19T16:58:30.000Z `report_admission_receipt_boundary`; cause_status: `known`; cause: The existing survey report visibility tests reach run completion, but HTML report rendering is refused by the protected report helper because this direct test workflow has no admitted server receipt.; resolution: `accepted`; lesson: Keep package-local survey evidence separate from the protected admission-receipt and browser acceptance boundary.
- #6 2026-08-19T16:58:40.000Z `capability_bootstrap_import_boundary`; cause_status: `known`; cause: A clean-process direct build_capabilities probe failed in the pre-existing StatisticalTestsStage and orchestrator circular import before reaching the survey capability projection; the scoped capability composition tests pass through their established harness.; resolution: `accepted`; lesson: Report capability projection tests with their actual bootstrap context and keep unrelated import-cycle gates out of the survey implementation scope.
- #27 2026-08-19T18:10:52.000Z `external_acceptance_boundaries_not_verified`; cause_status: `known`; cause: The survey package gate does not establish Report HTML/admitted-receipt content, a raw clean-process build_capabilities bootstrap, an R oracle rerun, browser acceptance, provider evidence, or the full release gate.; resolution: `accepted`; lesson: Keep package-local survey verification separate from Report admission, browser, provider, external-oracle, full-gate, and release claims.

## All waste

- None recorded.

## Root causes and solutions

- `explicit-external-boundaries`: occurrences=1; cause_status: `known`; root cause: The survey package gate does not establish Report HTML/admitted-receipt content, a raw clean-process build_capabilities bootstrap, an R oracle rerun, browser acceptance, provider evidence, or the full release gate.; solution: `accepted`
- `formal-evidence-single-digest`: occurrences=1; cause_status: `known`; root cause: The first append attempt supplied two SHA-256 digests in one evidence.sha256 field, and the formal CLI rejected the event before it entered the chain.; solution: `resolved`
- `instrument-real-survey-workflows`: occurrences=1; cause_status: `known`; root cause: The required RED run showed that Logit, Probit, and Poisson family workflows completed without entering the shared survey variance engine, and the unsupported FPC workflow completed instead of being blocked.; solution: `resolved`
- `real-entry-invalid-input-red`: occurrences=1; cause_status: `known`; root cause: The new real-entry probes show that SurveyDesign accepts negative, non-finite, and all-zero sampling weights, the engine accepts a mutated all-zero weight frame, and Poisson exposure values can be treated as ordinary predictors or raise an untyped overflow instead of a stable typed failure.; solution: `open`
- `reviewer-spec-red-probes`: occurrences=1; cause_status: `known`; root cause: The reviewer-directed RED probes showed that auto count falls through to the OLS fallback instead of the weighted poisson_rate handler, the clean capability helper is absent while build_capabilities hits the central import cycle, and both direct report HTML assertions still encounter a missing report artifact.; solution: `open`
- `separate-capability-bootstrap-gate`: occurrences=1; cause_status: `known`; root cause: A clean-process direct build_capabilities probe failed in the pre-existing StatisticalTestsStage and orchestrator circular import before reaching the survey capability projection; the scoped capability composition tests pass through their established harness.; solution: `accepted`
- `separate-report-receipt-gate`: occurrences=1; cause_status: `known`; root cause: The existing survey report visibility tests reach run completion, but HTML report rendering is refused by the protected report helper because this direct test workflow has no admitted server receipt.; solution: `accepted`
- `validate-event-vocabulary`: occurrences=1; cause_status: `known`; root cause: The first core verification event source used preventability=not_applicable, which the formal event schema correctly rejected before append.; solution: `resolved`
- `verify-formal-cli-surface`: occurrences=1; cause_status: `known`; root cause: An unsupported devline-control subcommand and an unavailable interpreter path were used during an early status probe before the formal CLI command surface was checked.; solution: `resolved`

## Added tests

- `tests/test_survey_design_engine_v187.py`
- `tests/test_survey_glm_family_wiring_v189.py`
- `tests/test_survey_report_visibility_v187.py`

## New rules

- `explicit-external-boundaries`: line experience occurrence(s)=1
- `formal-evidence-single-digest`: line experience occurrence(s)=1
- `instrument-real-survey-workflows`: line experience occurrence(s)=1
- `real-entry-invalid-input-red`: line experience occurrence(s)=1
- `reviewer-spec-red-probes`: line experience occurrence(s)=1
- `separate-capability-bootstrap-gate`: line experience occurrence(s)=1
- `separate-report-receipt-gate`: line experience occurrence(s)=1
- `validate-event-vocabulary`: line experience occurrence(s)=1
- `verify-formal-cli-surface`: line experience occurrence(s)=1

## Future guidance

- Instrument real family workflows before trusting capability declarations.
- Keep input validation at the earliest executable family boundary and carry provenance through the same typed result projection used by ordinary coefficients.
- Keep internal aliases on one family contract and make package-local acceptance distinguish typed external unavailability from successful report rendering.
- Keep model-specific link and offset details inside the shared estimator adapter, not in a second variance workflow.
- Keep package-local survey evidence separate from the protected admission-receipt and browser acceptance boundary.
- Keep package-local survey verification separate from Report admission, browser, provider, external-oracle, full-gate, and release claims.
- Probe mutable real entry points and invalid family inputs before trusting downstream numerical failures or capability declarations.
- Report capability projection tests with their actual bootstrap context and keep unrelated import-cycle gates out of the survey implementation scope.
- Submit one digest per formal evidence block and let the CLI validate the event before treating it as recorded.
- Turn reviewer findings into output-level red probes before changing production wiring or acceptance scope.
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
- #11: `e420c0f9-b8b2-4137-9621-e1d2e2cd4d25` | 2026-08-19T17:21:27.904Z | STATE_CHANGE/context_rescope_required | incident=`af6c61e4-bd05-4e5f-8471-658507372d64` | lesson_key=`context-pack-rescope` | event_sha256=`6998f2dc3566475f03be7ffad60322c2f1ec3e3a6750a7864682bab50612d147`
- #12: `f393c24d-4d1f-4f51-89c7-0bb91688cb35` | 2026-08-19T17:21:27.911Z | STATE_CHANGE/context_rescoped | incident=`7b25ca97-6b96-4a0d-9e4a-6476e63fccef` | lesson_key=`context-pack-rescope` | event_sha256=`f2421459d7b3ac1c7c0304a38d7d08d608d6cfaf86ea099a1acc937d4513b719`
- #13: `2e6f3a91-4d72-4c08-9b15-7f0a6e2d4c83` | 2026-08-19T17:23:50.000Z | FAILURE/reviewer_spec_compliance_red | incident=`b7c4e2a1-6d93-4f08-9c25-7e1a3d5b9f62` | lesson_key=`reviewer-spec-red-probes` | event_sha256=`c88216ff33729dcdf6f46b5194f6ab8f4f8d57105db6c03ed80d982a6c2ae66d`
- #14: `4a8d2f61-9c37-4e05-b7a2-6f1c9d3e8b54` | 2026-08-19T17:30:06.000Z | REVIEW/reviewer_spec_compliance_resolved | incident=`b7c4e2a1-6d93-4f08-9c25-7e1a3d5b9f62` | lesson_key=`reviewer-spec-red-probes` | event_sha256=`ecabdac2cac2b3bf6766602cadf74b103d2a31d3fe880db798ec60edfb9efddc`
- #15: `6c1e8b4d-2f79-4a03-9d56-7b0c2e8f1a63` | 2026-08-19T17:30:30.000Z | GATE/survey_focused_verification_green | incident=`c2f7a9e1-4d63-8b05-6f2a-9e1c7d4b8f50` | lesson_key=`focused-gate-boundary` | event_sha256=`d4b67c37c90b376084215e05b2cbd3ef99b969084aa35409d7025f49fa19f707`
- #16: `8f3a1d6c-5b72-4e09-a8c1-7d2f6b4e9a50` | 2026-08-19T17:30:53.000Z | GATE/compile_and_diff_check_green | incident=`d5a2f8c1-7e49-4b06-9d3f-1a6c8e2b7f50` | lesson_key=`compile-and-diff-check` | event_sha256=`87b6760afc038e3a4bfba6e57622eb094fb107b4d6d5a42476d03e630319bd19`
- #17: `1b7e4c92-6d35-4a08-9f21-3c7b5e1d8a60` | 2026-08-19T17:31:20.000Z | STATE_CHANGE/line_completed | incident=`e6a1c7d9-4f20-8b35-6c2e-9d7a1f5b3c84` | lesson_key=`explicit-boundary-line-close` | event_sha256=`d7dc1a6283b0128c9606950defe6e2c03e98dcb64b1eff30b47841732c630703`
- #18: `7f4a2c91-5d83-4e07-b6f1-9a2c8d5e7031` | 2026-08-19T17:56:49.000Z | FAILURE/invalid_survey_inputs_red | incident=`c8e5a1d7-4b92-6f30-9e2c-7a5d1b8f3c64` | lesson_key=`real-entry-invalid-input-red` | event_sha256=`1d08f1eed69b4eba69981e6ae8417a80bf87027bb301350e663b4be55c2c6b7e`
- #19: `a1a381c2-23df-4553-af8a-02f5414ee93c` | 2026-08-19T17:59:15.261Z | STATE_CHANGE/context_rescope_required | incident=`c1f974fc-c9e4-4f6e-ab1f-2902ad632c3a` | lesson_key=`context-pack-rescope` | event_sha256=`2d518eb59f6b68e1151494b9aabbe90c3d1c766387dc22b81c94762396f892d8`
- #20: `7adf368b-1572-4683-bc46-cc1b88ad695e` | 2026-08-19T17:59:15.270Z | STATE_CHANGE/context_rescoped | incident=`5bfb7823-e2f0-4f26-bdd0-ab4653e532be` | lesson_key=`context-pack-rescope` | event_sha256=`2f87b814f9ad0867d9f2d31014e37cc22d15e32c28115ca3cc5a762669632e9a`
- #21: `c69bf552-44fc-440a-8c39-87c9ddf780a7` | 2026-08-19T18:01:50.603Z | STATE_CHANGE/context_rescope_required | incident=`ab8351ef-b346-4762-8472-841f94422524` | lesson_key=`context-pack-rescope` | event_sha256=`727f766eb9b1ef3b0583102026dce52a5259be79efa1e0435c6e145f9068c4c3`
- #22: `cf29f523-5d70-4671-a474-d7a9817ec753` | 2026-08-19T18:01:50.615Z | STATE_CHANGE/context_rescoped | incident=`bd01a116-506e-470b-9b65-f165b76e7dc1` | lesson_key=`context-pack-rescope` | event_sha256=`09a6094fc22b2faf5b9a0d9100691cb489698a583c4e90eb804a2596ac6b1212`
- #23: `8a3d7f1c-5b92-4e06-a8d4-2f7c1b9e5630` | 2026-08-19T18:08:03.000Z | ERROR/formal_event_schema_probe | incident=`d1e7a4c9-5b82-6f30-9e2d-7a1c8f4b5630` | lesson_key=`formal-evidence-single-digest` | event_sha256=`7ced7f6ce60a758171fa6ce39e310a0d56727f2570979b804f45f39eb2f8e6d3`
- #24: `9c2f6a1d-7e43-4b80-b5d9-1a6c8f2e7043` | 2026-08-19T18:09:54.000Z | REVIEW/survey_fail_closed_and_adapter_review_resolved | incident=`e4a7c1d9-5f20-8b36-2c7e-9a1d6f4b8053` | lesson_key=`survey-inputs-and-provenance-single-seam` | event_sha256=`4ad65989b5db3937cc33de8773b1aaa77b0ecb2a18448f9e4b1b907b8da12ad1`
- #25: `a5d8f2c1-7b64-4e90-9a3f-1c6d8e2b7045` | 2026-08-19T18:10:10.000Z | GATE/survey_expanded_focused_green | incident=`f1c7a4d9-5e20-8b36-2a7d-9c1e6f4b8053` | lesson_key=`expanded-survey-focused-gate` | event_sha256=`3a8b5c27b16aa42b4e4736d482e38f9407671072e76fb3be44263c24b9242ef4`
- #26: `b6e9a2d1-7c54-4f80-9a3e-1d6c8b2f7045` | 2026-08-19T18:10:36.000Z | GATE/compile_and_diff_check_green | incident=`c7a4d1e9-5f20-8b36-2c7e-9a1d6f4b8053` | lesson_key=`final-syntax-diff-gate` | event_sha256=`13300233eb801632a244c2e1710597dee4de99fe0f4511b3071e11fbe45aec4b`
- #27: `c7f1a4d9-5e20-8b36-2a7d-9c1e6f4b8053` | 2026-08-19T18:10:52.000Z | GAP/external_acceptance_boundaries_not_verified | incident=`d8a4c1e7-5f20-9b36-2c7e-1a6d8f4b9053` | lesson_key=`explicit-external-boundaries` | event_sha256=`925801f88a67b51d71987760e2d2b41be8ef67847c4f3f7469fd1bb94e1ad8ba`
- #28: `d8a4c1e7-5f20-9b36-2c7e-1a6d8f4b9053` | 2026-08-19T18:11:12.000Z | STATE_CHANGE/line_completed_after_repair_gate | incident=`e9b5d2f8-6c31-4a07-9e2d-7b5f1c8a6043` | lesson_key=`repair-line-close-with-boundaries` | event_sha256=`0c7225ad6113b8a5528e848aa4b04c18f37f3458d2ad6a3dbda3f28516a06668`
