# Retrospective — v1-8-arma-garch-runtime

## Goal

# v1.8 ARMA–GARCH Runtime Objective  ## Objective  Implement and verify the approved generic \`time_series.arma_garch\` Model Pack for one confirmed time column and one numeric value column. Deliver bounded automatic and manual ARMA/ARCH/GARCH workflows, strict sequential versus joint semantics, one-step rolling validation, traceable artifacts, Graph/run lifecycle, UI, Agent proposals, Compare, synthetic known-truth acceptance, and conditional VIX regression acceptance.  ## Scope boundary  Use \`statsmodels\` for ARMA and public \`arch\` APIs for ARCH/GARCH. Do not add a custom likelihood or optimizer, joint MA–GARCH, multivariate/exogenous/seasonal models, automatic interpolation/filling/aggregation, multi-step forecasts, or automatic VaR claims. Source datasets remain immutable and user confirmation is required for transform and time semantics.  The full approved requirements are in the user attachment and the execution checklist is \`docs/superpowers/plans/2026-07-20-v1.8-arma-garch-volatility-workbench-implementation-plan.md\`.  ## Acceptance evidence  Focused TDD suites, deterministic synthetic known-truth tests, immutable-source and no-leakage proofs, Pack/Graph/Artifact/Agent/Compare/UI integration tests, visible UI smoke, quick and full repository gates, and explicit VIX skip evidence when no real repository VIX input exists.

## Final status

STARTED

## Metrics

- Failure frequency: 6/25 (24.0%; 24.0 per 100 events)
- Repeat rate: 0/6 (0.0%)
- Recurrence rate: 0/6 (0.0%)
- MTTR: median=0 ms (sample=6; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/9 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/4)

## All failures

- None recorded.

## All errors

- #19 2026-07-21T22:26:00.000Z `nested_patch_execution_drift`; cause_status: `known`; cause: Agent precheck promised a key-wise nested model_options patch, but execution replaced the complete ARMA section and silently dropped the unpatched p order.; resolution: `resolved`; lesson: Typed patch precheck and execution must share one recursive merge primitive, with a guard proving unpatched sibling keys survive.
- #20 2026-07-21T22:27:00.000Z `project_forest_write_fingerprint_drift`; cause_status: `known`; cause: The project-wide canvas included an unrelated run sharing the same content-addressed model node, while backend mutation validation correctly fingerprinted only the selected rerun family.; resolution: `resolved`; lesson: Project-wide read projections may retain cross-family sharing for display and Compare, but mutation freshness inputs must be reduced to the backend's rerun-family boundary.
- #21 2026-07-21T22:28:00.000Z `persisted_compare_artifact_omission`; cause_status: `known`; cause: The persisted Compare reader omitted ts.train_validation_split, so it fell back to a contract-bound split hash and falsely reported different sample membership for identical frozen rows.; resolution: `resolved`; lesson: Persisted comparison tests must load the real artifact envelopes from disk; direct builder fixtures cannot prove the public reader includes every integrity input.

## All gaps

- #18 2026-07-21T22:25:00.000Z `known_truth_missing_policy`; cause_status: `known`; cause: The VIX known-truth path treated blank observations as an unstructured parse failure even though the approved contract permits an explicitly confirmed complete-case policy.; resolution: `resolved`; lesson: Known-truth fixtures must exercise each declared missing-value policy through the public run path and preserve a structured tombstone when the blocking policy is selected.
- #23 2026-07-21T22:30:00.000Z `time_series_report_fact_omission`; cause_status: `known`; cause: The report fact table only harvested generic scalar node fields and omitted the time-series analysis contract and data audit needed to cite transform, missing-row policy, estimation semantics, and sample counts.; resolution: `resolved`; lesson: A model-specific report must assert its essential semantic facts from real public artifacts before a provider can generate narrative text.
- #25 2026-07-21T22:55:22.000Z `table_structured_chart_visibility`; cause_status: `known`; cause: The generic Table view classified only legacy artifact_type=figure PNGs as charts, while the ARMA-GARCH pack registers its 17 structured chart payloads as time_series_json for client-side SVG rendering.; resolution: `resolved`; lesson: Every artifact consumer must be tested against the model pack's registered artifact types; structured client-rendered charts cannot be discovered by filtering only for legacy figure binaries.

## All waste

- #6 2026-07-20T22:47:44.000Z `unbounded_readonly_scout`; cause_status: `known`; cause: Two read-only integration scouts were given broad cross-layer discovery scopes and did not return a bounded handoff after repeated time-box reminders.; resolution: `resolved`; lesson: Read-only scouts must have one seam, an explicit evidence cap, and a short stop condition; use the existing architecture scout result instead of repeating broad discovery.
- #7 2026-07-20T23:21:28.000Z `unresponsive_refix_worker`; cause_status: `known`; cause: The first bounded refix worker stopped responding after receiving concrete review findings and three time-boxed waits.; resolution: `resolved`; lesson: Refix assignments need a small test-bound patch scope and an explicit stop condition; replace an unresponsive worker without repeating the implementation locally.
- #12 2026-07-20T23:47:09.000Z `unverified_test_handoff`; cause_status: `known`; cause: The independent known-truth author produced useful fixtures and tests but exceeded the time box and returned without running its required focused test.; resolution: `resolved`; lesson: A test-author line must stop after writing the bounded suite and run its one required command before adding secondary failure cases.
- #22 2026-07-21T22:29:00.000Z `synthetic_fixture_false_green`; cause_status: `known`; cause: A hand-built Compare fixture supplied the frozen split directly, so builder tests passed while the real persisted reader omitted it and forced a second browser create-inspect-delete-create cycle.; resolution: `resolved`; lesson: For cross-layer acceptance, derive fixtures from actual persisted responses and assert the public reader output before testing the pure builder.

## Root causes and solutions

- `assert-model-essential-facts-before-provider-report`: occurrences=1; cause_status: `known`; root cause: The report fact table only harvested generic scalar node fields and omitted the time-series analysis contract and data audit needed to cite transform, missing-row policy, estimation semantics, and sample counts.; solution: `resolved`
- `derive-cross-layer-fixtures-from-persisted-responses`: occurrences=1; cause_status: `known`; root cause: A hand-built Compare fixture supplied the frozen split directly, so builder tests passed while the real persisted reader omitted it and forced a second browser create-inspect-delete-create cycle.; solution: `resolved`
- `exercise-known-truth-missing-policy-through-public-run`: occurrences=1; cause_status: `known`; root cause: The VIX known-truth path treated blank observations as an unstructured parse failure even though the approved contract permits an explicitly confirmed complete-case policy.; solution: `resolved`
- `render-structured-charts-by-registered-artifact-identity`: occurrences=1; cause_status: `known`; root cause: The generic Table view classified only legacy artifact_type=figure PNGs as charts, while the ARMA-GARCH pack registers its 17 structured chart payloads as time_series_json for client-side SVG rendering.; solution: `resolved`
- `separate-project-read-identity-from-family-write-fingerprint`: occurrences=1; cause_status: `known`; root cause: The project-wide canvas included an unrelated run sharing the same content-addressed model node, while backend mutation validation correctly fingerprinted only the selected rerun family.; solution: `resolved`
- `share-nested-patch-merge-between-precheck-and-execution`: occurrences=1; cause_status: `known`; root cause: Agent precheck promised a key-wise nested model_options patch, but execution replaced the complete ARMA section and silently dropped the unpatched p order.; solution: `resolved`
- `test-compare-through-persisted-artifact-reader`: occurrences=1; cause_status: `known`; root cause: The persisted Compare reader omitted ts.train_validation_split, so it fell back to a contract-bound split hash and falsely reported different sample membership for identical frozen rows.; solution: `resolved`
- `timebox-known-truth-author-before-secondary-cases`: occurrences=1; cause_status: `known`; root cause: The independent known-truth author produced useful fixtures and tests but exceeded the time box and returned without running its required focused test.; solution: `resolved`
- `timebox-readonly-architecture-scouts`: occurrences=1; cause_status: `known`; root cause: Two read-only integration scouts were given broad cross-layer discovery scopes and did not return a bounded handoff after repeated time-box reminders.; solution: `resolved`
- `timebox-unresponsive-refix-worker`: occurrences=1; cause_status: `known`; root cause: The first bounded refix worker stopped responding after receiving concrete review findings and three time-boxed waits.; solution: `resolved`

## Added tests

- `backend/workbench/analysis_loop/time_series_compare.py`
- `backend/workbench/model_options.py`
- `scripts/gate.sh`
- `tests/agent/test_arma_garch_agent_compare.py`
- `tests/contracts/test_arma_garch_contracts.py and tests/models/arma_garch`
- `tests/models/arma_garch/test_arma.py`
- `tests/models/arma_garch/test_estimation.py`
- `tests/models/arma_garch/test_forecast.py`
- `tests/models/arma_garch/test_known_truth.py`
- `tests/models/arma_garch/test_pack_runtime.py`
- `tests/models/arma_garch/test_statistics.py`

## New rules

- `assert-model-essential-facts-before-provider-report`: line experience occurrence(s)=1
- `derive-cross-layer-fixtures-from-persisted-responses`: line experience occurrence(s)=1
- `exercise-known-truth-missing-policy-through-public-run`: line experience occurrence(s)=1
- `render-structured-charts-by-registered-artifact-identity`: line experience occurrence(s)=1
- `separate-project-read-identity-from-family-write-fingerprint`: line experience occurrence(s)=1
- `share-nested-patch-merge-between-precheck-and-execution`: line experience occurrence(s)=1
- `test-compare-through-persisted-artifact-reader`: line experience occurrence(s)=1
- `timebox-known-truth-author-before-secondary-cases`: line experience occurrence(s)=1
- `timebox-readonly-architecture-scouts`: line experience occurrence(s)=1
- `timebox-unresponsive-refix-worker`: line experience occurrence(s)=1

## Future guidance

- A model-specific report must assert its essential semantic facts from real public artifacts before a provider can generate narrative text.
- A test-author line must stop after writing the bounded suite and run its one required command before adding secondary failure cases.
- A volatility candidate is valid evidence only when final estimation preserves its holdback, strategy, aligned sample mask, stationarity gate, and complete mean-model binding.
- Every artifact consumer must be tested against the model pack's registered artifact types; structured client-rendered charts cannot be discovered by filtering only for legacy figure binaries.
- For cross-layer acceptance, derive fixtures from actual persisted responses and assert the public reader output before testing the pure builder.
- Forecast comparison is trustworthy only when distribution identity, common successful origins, and scale-specific point semantics are explicit and tested.
- Known-truth fixtures must exercise each declared missing-value policy through the public run path and preserve a structured tombstone when the blocking policy is selected.
- Known-truth gates must challenge diagnostic precedence and invalid-parameter interpretation, while statistical recovery assertions use fixed seeds and finite-sample neighborhoods.
- Persisted comparison tests must load the real artifact envelopes from disk; direct builder fixtures cannot prove the public reader includes every integrity input.
- Project-wide read projections may retain cross-family sharing for display and Compare, but mutation freshness inputs must be reduced to the backend's rerun-family boundary.
- Read-only scouts must have one seam, an explicit evidence cap, and a short stop condition; use the existing architecture scout result instead of repeating broad discovery.
- Refix assignments need a small test-bound patch scope and an explicit stop condition; replace an unresponsive worker without repeating the implementation locally.
- Runtime acceptance needs late-failure fault injection, a complete artifact inventory, stage-owned chart lineage, and an explicit tuning-versus-evaluation sample role before the slice can pass.
- Statistical candidate gates need adversarial boundary probes for configuration caps, serialization, scale invariance, and immutable evidence before acceptance.
- Typed patch precheck and execution must share one recursive merge primitive, with a guard proving unpatched sibling keys survive.

## Event index

- #1: `ededbe1f-5b49-4f43-bff1-99dcdd8bfc0d` | 2026-07-20T21:41:41.926Z | STATE_CHANGE/line_started | incident=`a65edf25-62cd-4386-b91f-e66fdae1b7ef` | lesson_key=`frozen-context-before-start` | event_sha256=`1616ac187e075f392cb932abbf0fc42bc46886c4bfe41c831153b19059ea4c22`
- #2: `ffa50f83-b2d3-4063-97a3-d3fe9c213159` | 2026-07-20T21:43:41.992Z | GATE/implementation_plan_review | incident=`e537354a-664b-44f3-b975-f1047a1e54e4` | lesson_key=`review-plan-for-false-completion` | event_sha256=`4a8dcd9b45765eaa51dd505bac6e213cec6e156d34e569ca31299b5a38d907c5`
- #3: `fdc43a33-4b4f-43ce-9182-d8568bddf6df` | 2026-07-20T22:12:32.835Z | GATE/slice1_accepted | incident=`7fb1cd02-d444-428e-a356-12574279e016` | lesson_key=`freeze-input-before-estimation` | event_sha256=`230ce9fc06317c1b695ddfbd55976ea9b1468610155a6de5f31e4f729b5c2d00`
- #4: `afa48a99-b3b5-40cf-91df-f74845bcde5c` | 2026-07-20T22:39:04.000Z | REVIEW/statistical_boundary_review | incident=`968018aa-cfcd-4e70-bbdb-45536a6ff275` | lesson_key=`adversarial-statistical-boundary-probes` | event_sha256=`39087770c11490bf9c702a777e24eef1218e0cb03a0a2c5f838bf114732363fc`
- #5: `105f75a6-49be-487e-9d0a-9b4a604680c6` | 2026-07-20T22:39:04.000Z | GATE/slice2a_accepted | incident=`bb341197-e95f-4594-906d-11d0383342da` | lesson_key=`accept-mean-model-after-boundary-review` | event_sha256=`fd8023163db06f033d25086c501c4b59fead6b1a274e0c7b6091c56d8b6ea089`
- #6: `eb32bfa4-5981-4f40-bfcc-99d315dfa2e6` | 2026-07-20T22:47:44.000Z | WASTE/unbounded_readonly_scout | incident=`564f2c26-5088-4baa-808f-41f0f5c69b5b` | lesson_key=`timebox-readonly-architecture-scouts` | event_sha256=`ea314d9ce098da28818b6c627c31dfdb0f1a6b440673eb318f73a1912bd7ee1e`
- #7: `a7e91c84-ca00-445a-825e-2c517fd02df1` | 2026-07-20T23:21:28.000Z | WASTE/unresponsive_refix_worker | incident=`6b522547-507f-4b54-82ed-3718a6daf34e` | lesson_key=`timebox-unresponsive-refix-worker` | event_sha256=`24f8b802960caf985411701319007dc5de52ab323ac501873e388e86c90c4960`
- #8: `3aebe778-b57e-402a-a3de-241ebd6f1e45` | 2026-07-20T23:21:28.000Z | REVIEW/volatility_estimation_review | incident=`a1ecdf48-96e6-483f-bad6-39bb51d9867e` | lesson_key=`bind-volatility-final-fit-to-candidate` | event_sha256=`6251162135745b004e114fbacbe367218f8438ba78ab6f1f6c809226e02bfbfc`
- #9: `1c00f1de-0ab2-496e-856b-265eb67876ce` | 2026-07-20T23:22:18.000Z | GATE/slice2b_accepted | incident=`9739ef39-a789-4953-8eeb-a462f15485ee` | lesson_key=`accept-volatility-after-full-binding-review` | event_sha256=`d37ab52f1c6b7ff210ff7ad785927e3ab90a99bac3a4e4504479195dea80fee7`
- #10: `b7728246-4162-43e1-8555-e305e0825f4d` | 2026-07-20T23:36:19.000Z | REVIEW/rolling_forecast_review | incident=`0e33a0dd-5b56-4bed-b3c9-e63226478a3a` | lesson_key=`compare-forecasts-on-common-frozen-origins` | event_sha256=`25ca09287863dff6bd4a910c32e5c15477a8e2fa127fb22ef5ce4fd0afac0522`
- #11: `d6be3c2f-b7aa-4d1b-b690-97cc3b9c6546` | 2026-07-20T23:36:19.000Z | GATE/slice2c_accepted | incident=`98ca602a-a8ef-4514-8436-8fa097de8dcb` | lesson_key=`accept-rolling-after-common-origin-review` | event_sha256=`2cfd5ad7e8634c7c69f78d8318db2d553e5a583977ec199cd29b771dd900a862`
- #12: `d0708224-620c-48d1-9af7-95c13c325aba` | 2026-07-20T23:47:09.000Z | WASTE/unverified_test_handoff | incident=`9133ec1e-b0fb-4061-82de-058c0efcc3da` | lesson_key=`timebox-known-truth-author-before-secondary-cases` | event_sha256=`2b0f113a0609831e38db8d3002f226c8a33957ef788fd5aaf8aaa1dbb50c44ff`
- #13: `9c7f288a-5e9a-487c-9513-e6e153c079c2` | 2026-07-20T23:47:09.000Z | REVIEW/known_truth_review | incident=`6af838a6-6a8e-4a93-bbef-23372b003ee8` | lesson_key=`known-truth-tests-diagnostic-precedence-and-invalid-parameters` | event_sha256=`c890b9fca6d3277201361339c375ce45201a9c1665f8caa3f76b8c55afad67de`
- #14: `ddacaa68-3657-4ed7-9e1d-8ba074930d36` | 2026-07-20T23:47:09.000Z | GATE/statistical_core_accepted | incident=`b31b2740-91f9-4342-b51a-9adedea9c552` | lesson_key=`accept-statistical-core-after-independent-known-truth` | event_sha256=`dcb3187b940e3d503ace330b72c664f1044f97549a590443bcdd80a4f2f0dcb8`
- #15: `3aaf5f90-24cf-4946-b1dd-ad4d1b616ff1` | 2026-07-21T00:33:50.000Z | REVIEW/runtime_integration_review | incident=`b423f1ac-7a19-4f1b-9edf-2c7841d3d7f8` | lesson_key=`bind-terminal-truth-and-evaluation-role` | event_sha256=`a2d19c46d412bf489b4ed80d7b76921ce87fcdb0371cc802ddbba60737d3ae4a`
- #16: `0d2a149c-6b03-41fd-81e4-786ec86581c1` | 2026-07-21T00:37:37.000Z | GATE/slice4_workbench_agent_compare_accepted | incident=`d08c0ddb-15e9-4531-be1e-7454d11a8870` | lesson_key=`test-real-ui-agent-compare-seams` | event_sha256=`dcf4a954b362f97692217f66865bdff3bde17d971df5e008b0c472be923b7952`
- #17: `cbbe24b0-339d-4f89-937d-0e1c5b359ec5` | 2026-07-21T01:05:48.000Z | GATE/runtime_integration_reaccepted | incident=`b423f1ac-7a19-4f1b-9edf-2c7841d3d7f8` | lesson_key=`bind-terminal-truth-and-evaluation-role` | event_sha256=`d58e770b724c9f4ea1b760a1bf5a123072726f8c295f2bdd401f8db86c955195`
- #18: `56f22730-c972-4ead-9000-2d221948de4d` | 2026-07-21T22:25:00.000Z | GAP/known_truth_missing_policy | incident=`f2883cee-3b76-4f19-af1c-d373061b68b5` | lesson_key=`exercise-known-truth-missing-policy-through-public-run` | event_sha256=`a04cca0149a0deb721856c8f12690bf3d81a099b6e0c544b2ae25bfdba5688e8`
- #19: `9d5895ac-b220-44d9-b499-e8540048eea0` | 2026-07-21T22:26:00.000Z | ERROR/nested_patch_execution_drift | incident=`d4cc64ad-c3e0-4dbd-bf6e-d729703ae460` | lesson_key=`share-nested-patch-merge-between-precheck-and-execution` | event_sha256=`1ca6312e47e9c7296a5c3e8bb6d8d4d8f1fee4a52696f15936729630920bc755`
- #20: `ae60fe94-7452-40bc-836f-a8ed0a1014d8` | 2026-07-21T22:27:00.000Z | ERROR/project_forest_write_fingerprint_drift | incident=`3c024606-963a-4a95-ae7b-c145c2b98c74` | lesson_key=`separate-project-read-identity-from-family-write-fingerprint` | event_sha256=`6f4985270b2d01ccaf7dd2a5d794eb738c6c0b267124a154d0f777c2a851f460`
- #21: `ba85f910-e9bf-4017-9ec4-35f4c3879b4a` | 2026-07-21T22:28:00.000Z | ERROR/persisted_compare_artifact_omission | incident=`7cdaf1c9-4be1-46ab-96a7-584d4146568d` | lesson_key=`test-compare-through-persisted-artifact-reader` | event_sha256=`a60cc73853d45a917fa3da3ec2cee1c3b6cf21d0dc93768b20229097fb3d7d73`
- #22: `340a7808-2be5-42fb-b88c-03477adba11b` | 2026-07-21T22:29:00.000Z | WASTE/synthetic_fixture_false_green | incident=`7cdaf1c9-4be1-46ab-96a7-584d4146568d` | lesson_key=`derive-cross-layer-fixtures-from-persisted-responses` | event_sha256=`fae88d033f6d218bd0997b356b5c391705a48c90cfc93771e58e9037e100c681`
- #23: `b32aff3e-544c-401a-9ce5-79097fe245f5` | 2026-07-21T22:30:00.000Z | GAP/time_series_report_fact_omission | incident=`73cf8f1a-3a3b-4395-87d2-36b249453ace` | lesson_key=`assert-model-essential-facts-before-provider-report` | event_sha256=`146eef8977d641e5cb42b98335b0cb3c96dea5933935652b2dba1e0e1b775dff`
- #24: `73930a15-1bbb-4a37-a46e-d4725e2bc8eb` | 2026-07-21T22:48:00.000Z | GATE/vix_browser_debug_full_gate | incident=`8a7ac846-386c-436d-b4f9-a5484a79ef20` | lesson_key=`close-browser-debug-with-fresh-nonoverlapping-full-gate` | event_sha256=`45f69cf62dfcd305c863cdce336687a074341f07c8ee2b2570ccaecd5b0afc6c`
- #25: `8c61d5f8-6870-4c87-ba3c-b192893522dd` | 2026-07-21T22:55:22.000Z | GAP/table_structured_chart_visibility | incident=`7acf7462-b8c2-4062-846c-35f3fe3a3844` | lesson_key=`render-structured-charts-by-registered-artifact-identity` | event_sha256=`882a743aecd2243cb44199e6411347af8fd58ee77fd43a8309d140eeccf77181`
