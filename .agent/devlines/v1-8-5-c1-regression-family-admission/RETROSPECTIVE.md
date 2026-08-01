# Retrospective — v1-8-5-c1-regression-family-admission

## Goal

# v1.8.5 C1 — Regression Family Admission Objective  This is the bounded FMS objective for C1 of \`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md\`.  The parent design is the only version-scope authority.  ## Objective  Complete the remaining workflow admission of existing native regression families through the server-owned \`ModelFamilyContract\` registry: Logit, Probit, Poisson, Negative Binomial, IV/2SLS, and TWFE DID.  Preserve the already admitted OLS, Panel OLS, CS-DID, SA-DID, and DCDH contracts as regression evidence, not as new delivery.  ## Scope  - Each newly admitted family declares its input preflight, Genesis parameter   construction, expected artifacts, result shape, diagnostics boundary, and   published Notebook vocabulary in the same contract. - IV requires non-overlapping endogenous and instrument column lists; TWFE DID   requires panel identity, time, and one explicit treatment definition. - A workflow and Notebook proposal either execute the selected family as   declared or fail closed with an actionable message. They never fallback to   OLS, assume OLS confidence-interval artifacts for a non-OLS result, or   accept an inference option that the selected existing estimator does not   consume. - Existing numerical estimators and golden fixtures remain unchanged.  ## Explicit non-scope  - No new estimator, \`glm:*\` alias, manual-form redesign, RecipeContract,   time-series default, memory-default expansion, custom capability change, or   exercise-specific behavior.  ## Acceptance  Tests first fail and then pass for every new family’s valid path and refusal path, including non-binary Logit/Probit, non-count Poisson/Negative Binomial, incomplete/underidentified IV, and incomplete DID definitions.  Existing goldens, Panel FE/dummy-FE oracle, and prior DID workflow admission remain unchanged.

## Final status

COMPLETED

## Metrics

- Failure frequency: 8/18 (44.4%; 44.4 per 100 events)
- Repeat rate: 0/8 (0.0%)
- Recurrence rate: 0/8 (0.0%)
- MTTR: median=1553500 ms (sample=8; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-01T13:07:30.000Z `tdd_red_missing_regression_contracts`; cause_status: `known`; cause: The workflow registry admits only OLS, Panel OLS, and the prior DID families, so the remaining existing native regression families have no typed workflow contract.; resolution: `open`; lesson: Add a family-owned contract before exposing an existing estimator to the typed workflow.
- #4 2026-08-01T13:16:54.000Z `tdd_red_logit_preflight_absent`; cause_status: `known`; cause: The workflow creates and executes a Genesis Draft before checking that a declared Logit outcome contains only binary 0/1 values.; resolution: `open`; lesson: Family-owned input semantics must be checked before Draft creation so invalid workflows do not create misleading lineage.
- #5 2026-08-01T13:19:09.000Z `tdd_red_family_column_lists_stringified`; cause_status: `known`; cause: The workflow runtime treats every family context field as a scalar string, so IV list-valued column declarations are stringified when building exploration context.; resolution: `open`; lesson: A model-family contract must distinguish source-column fields from scalar metadata and preserve list-valued columns elementwise.
- #6 2026-08-01T13:21:20.000Z `tdd_red_iv_source_column_omitted`; cause_status: `known`; cause: The model.genesis source-column extractor enumerates legacy timing fields and omits family-declared IV endogeneity and instrument columns.; resolution: `open`; lesson: Source-schema validation must derive all family input columns from the shared model-family contract.
- #7 2026-08-01T13:23:00.000Z `tdd_red_notebook_iv_family_validation_missing`; cause_status: `known`; cause: Notebook proposal validation checks only scalar required family fields and does not delegate the complete synthesized spec to the IV contract.; resolution: `open`; lesson: Notebook validation must call the same family contract used by compiled workflows, after verifying every declared source column against evidence.
- #8 2026-08-01T13:24:26.000Z `tdd_red_notebook_materialization_iv_fields_rejected`; cause_status: `known`; cause: Dataset Genesis materialization owns an OLS-shaped hardcoded parameter allowlist and infers native-family handling from covariance support.; resolution: `open`; lesson: Materialization must derive admitted family fields and native parameter construction from the shared family contract, not from OLS compatibility heuristics.
- #9 2026-08-01T13:31:49.000Z `tdd_red_family_field_silently_ignored`; cause_status: `known`; cause: Generic model.genesis vocabulary accepts all family-specific fields, while family validation only rejects a partial handwritten forbidden list.; resolution: `open`; lesson: Every family-specific field has one owning ModelFamilyContract; all other families must fail closed.

## All errors

- #2 2026-08-01T13:06:24.000Z `start_tag_not_normalized`; cause_status: `known`; cause: The initial formal start used the display release tag v1.8.5, but FMS tags must be normalized identifiers.; resolution: `resolved`; lesson: Use a normalized FMS tag rather than a dotted display version when starting a development line.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `family-column-fields-preserve-elementwise`: occurrences=1; cause_status: `known`; root cause: The workflow runtime treats every family context field as a scalar string, so IV list-valued column declarations are stringified when building exploration context.; solution: `open`
- `family-contract-drives-source-schema-validation`: occurrences=1; cause_status: `known`; root cause: The model.genesis source-column extractor enumerates legacy timing fields and omits family-declared IV endogeneity and instrument columns.; solution: `open`
- `family-input-validation-before-genesis`: occurrences=1; cause_status: `known`; root cause: The workflow creates and executes a Genesis Draft before checking that a declared Logit outcome contains only binary 0/1 values.; solution: `open`
- `materialization-uses-family-contract-not-ols-heuristic`: occurrences=1; cause_status: `known`; root cause: Dataset Genesis materialization owns an OLS-shaped hardcoded parameter allowlist and infers native-family handling from covariance support.; solution: `open`
- `model-family-field-ownership-fail-closed`: occurrences=1; cause_status: `known`; root cause: Generic model.genesis vocabulary accepts all family-specific fields, while family validation only rejects a partial handwritten forbidden list.; solution: `open`
- `normalized-fms-tag-before-start`: occurrences=1; cause_status: `known`; root cause: The initial formal start used the display release tag v1.8.5, but FMS tags must be normalized identifiers.; solution: `resolved`
- `notebook-delegates-to-shared-family-contract`: occurrences=1; cause_status: `known`; root cause: Notebook proposal validation checks only scalar required family fields and does not delegate the complete synthesized spec to the IV contract.; solution: `open`
- `regression-family-contract-before-admission`: occurrences=1; cause_status: `known`; root cause: The workflow registry admits only OLS, Panel OLS, and the prior DID families, so the remaining existing native regression families have no typed workflow contract.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `family-column-fields-preserve-elementwise`: line experience occurrence(s)=1
- `family-contract-drives-source-schema-validation`: line experience occurrence(s)=1
- `family-input-validation-before-genesis`: line experience occurrence(s)=1
- `materialization-uses-family-contract-not-ols-heuristic`: line experience occurrence(s)=1
- `model-family-field-ownership-fail-closed`: line experience occurrence(s)=1
- `normalized-fms-tag-before-start`: line experience occurrence(s)=1
- `notebook-delegates-to-shared-family-contract`: line experience occurrence(s)=1
- `regression-family-contract-before-admission`: line experience occurrence(s)=1

## Future guidance

- A model-family contract must distinguish source-column fields from scalar metadata and preserve list-valued columns elementwise.
- Add a family-owned contract before exposing an existing estimator to the typed workflow.
- Add an explicit family contract before publishing an existing estimator to the typed workflow.
- Every family-specific field has one owning ModelFamilyContract; all other families must fail closed.
- Fail closed on fields owned by a different ModelFamilyContract.
- Family input semantics belong before Draft creation, not in a later fit failure.
- Family-owned input semantics must be checked before Draft creation so invalid workflows do not create misleading lineage.
- Materialization must derive admitted family fields and native parameter construction from the shared family contract, not from OLS compatibility heuristics.
- Materialization must use family contracts, never infer native behavior from covariance support.
- Notebook validation delegates to the shared family contract after evidence column checks.
- Notebook validation must call the same family contract used by compiled workflows, after verifying every declared source column against evidence.
- Separate column fields from scalar family metadata in the shared contract.
- Source-schema validation must derive all family input columns from the shared model-family contract.
- Use a normalized FMS tag rather than a dotted display version when starting a development line.
- Use the family contract for source-schema validation rather than enumerating legacy fields.

## Event index

- #1: `3320e00b-1b0b-4f17-9f01-502acea4a882` | 2026-08-01T13:06:01.473Z | STATE_CHANGE/line_started | incident=`152e85d7-de3d-458a-8158-03cc05f1cd79` | lesson_key=`frozen-context-before-start` | event_sha256=`fb80aebff9702182922d303db96394010474f03778cb3401e86386cf15e38b7a`
- #2: `bbd5c017-d2a1-475e-a999-3225b8773a36` | 2026-08-01T13:06:24.000Z | ERROR/start_tag_not_normalized | incident=`fa23889f-1eae-46d9-b808-80bb1a7bf998` | lesson_key=`normalized-fms-tag-before-start` | event_sha256=`91ac4129d4606582efb9e955ae5074482721059c5744a4fe881f92502fc50bd5`
- #3: `733f1256-f3bc-4a69-b1d6-51ac29b52f84` | 2026-08-01T13:07:30.000Z | FAILURE/tdd_red_missing_regression_contracts | incident=`3c837193-317f-4a92-b4df-1740e1058d02` | lesson_key=`regression-family-contract-before-admission` | event_sha256=`756f28dbcc7ca53b2a404f440f5e214afdd711dff2ac0e6c1f2ad003932c8771`
- #4: `6a539414-b25c-4511-aefc-699c5d93e58e` | 2026-08-01T13:16:54.000Z | FAILURE/tdd_red_logit_preflight_absent | incident=`e9fe76bf-a28c-4982-bfe3-b9483ca8909e` | lesson_key=`family-input-validation-before-genesis` | event_sha256=`5bfbd8a662b843bc27cc811fe5259220fcdbda1d37e4f43967d3cbbd58db9409`
- #5: `fc2dbd1c-4555-4a33-982c-1c4b0e882a91` | 2026-08-01T13:19:09.000Z | FAILURE/tdd_red_family_column_lists_stringified | incident=`1468d885-a64a-4f06-a718-6500a8e27e9a` | lesson_key=`family-column-fields-preserve-elementwise` | event_sha256=`43d399b01cb312dfb68e8db954e69f758b5d5af0b051f381ea6837bcd6cc5fd1`
- #6: `dcac2bd0-66e9-47f4-aed9-728d23886155` | 2026-08-01T13:21:20.000Z | FAILURE/tdd_red_iv_source_column_omitted | incident=`53e60cb1-1e41-4771-a768-4c49c91a0af6` | lesson_key=`family-contract-drives-source-schema-validation` | event_sha256=`96c792222946835b4ebf0ae1e59876994e78afc5b196a170d7c2f6851358ef78`
- #7: `5d93b72f-7a5c-4474-9389-01f86f143ab8` | 2026-08-01T13:23:00.000Z | FAILURE/tdd_red_notebook_iv_family_validation_missing | incident=`6d345521-d0ae-40d4-b8e5-4c51e00cf944` | lesson_key=`notebook-delegates-to-shared-family-contract` | event_sha256=`4284e50fc744f55efa8ac6e2cf91928f71ebfe6df2a40e7aa58be7984f34385f`
- #8: `ce36d49b-ab89-4540-906e-99a55740221a` | 2026-08-01T13:24:26.000Z | FAILURE/tdd_red_notebook_materialization_iv_fields_rejected | incident=`a6ccbb37-2fcd-4b7f-90b4-882ff1cf218c` | lesson_key=`materialization-uses-family-contract-not-ols-heuristic` | event_sha256=`ffe9c8140c1588a5f1cd162b9fe48312970d45fbaff8a0ae24889fc5d51ce99c`
- #9: `8efa980f-dbcc-4995-a0fd-cd8ddac9092f` | 2026-08-01T13:31:49.000Z | FAILURE/tdd_red_family_field_silently_ignored | incident=`3f3b491e-2179-4111-a00b-f983a25eb67f` | lesson_key=`model-family-field-ownership-fail-closed` | event_sha256=`fe12808d356a471aa7ed6eaaee1a1e8db77b32ca8d3bd03a84e9fa7c628a50dc`
- #10: `6caac304-01a4-45e7-a019-09176df4d8a4` | 2026-08-01T13:48:00.000Z | REVIEW/c1_regression_contract_registry_resolved | incident=`3c837193-317f-4a92-b4df-1740e1058d02` | lesson_key=`regression-family-contract-before-admission` | event_sha256=`907ff14d689d30f7a2f0f5bd1f376802c030f036e23e3460a73feb8bd0b8eb0a`
- #11: `6c229a21-ba81-4c87-a84d-82c7ee92c5cc` | 2026-08-01T13:48:01.000Z | REVIEW/c1_logit_preflight_resolved | incident=`e9fe76bf-a28c-4982-bfe3-b9483ca8909e` | lesson_key=`family-input-validation-before-genesis` | event_sha256=`255119c0276af3023aafed26330f2064a652b6d80d6e3bf2ec874759d63bf0b2`
- #12: `68bc01a5-6a91-4cda-8cf5-cdeef9241ee4` | 2026-08-01T13:48:02.000Z | REVIEW/c1_family_column_context_resolved | incident=`1468d885-a64a-4f06-a718-6500a8e27e9a` | lesson_key=`family-column-fields-preserve-elementwise` | event_sha256=`d408b7c83790220272cdeb1d04941d0642199f767c9dff597d7bce3a5c994c2b`
- #13: `10e39d44-f8f6-4fb0-b269-f1d4d83d3066` | 2026-08-01T13:48:03.000Z | REVIEW/c1_iv_source_schema_resolved | incident=`53e60cb1-1e41-4771-a768-4c49c91a0af6` | lesson_key=`family-contract-drives-source-schema-validation` | event_sha256=`1a7c16d3d45eaf4392b2d5499f123cf3c7564b01b4cbded2513b0ac1244b32ca`
- #14: `0c9be275-9b59-4e17-9e68-3aae38755d57` | 2026-08-01T13:48:04.000Z | REVIEW/c1_notebook_iv_family_validation_resolved | incident=`6d345521-d0ae-40d4-b8e5-4c51e00cf944` | lesson_key=`notebook-delegates-to-shared-family-contract` | event_sha256=`99c4a5dc4c68d7f8dd8b2e5b538fd56b159bd534ad29e1fae6bf33ec6017a29a`
- #15: `8770ef75-ea89-4796-8f98-4d937b45a5a2` | 2026-08-01T13:48:05.000Z | REVIEW/c1_notebook_materialization_iv_resolved | incident=`a6ccbb37-2fcd-4b7f-90b4-882ff1cf218c` | lesson_key=`materialization-uses-family-contract-not-ols-heuristic` | event_sha256=`48c47c743ef9d3af8a868f4237a757c69ca23f145c96676968930172090f4806`
- #16: `e7e42dc9-1faa-46b8-8736-2d83f8b1d21e` | 2026-08-01T13:48:06.000Z | REVIEW/c1_family_field_ownership_resolved | incident=`3f3b491e-2179-4111-a00b-f983a25eb67f` | lesson_key=`model-family-field-ownership-fail-closed` | event_sha256=`f4fed8fbdf6dd4b9e443b4538d4bed2977b5d83d7e9e044e8f6ebcf950a38251`
- #17: `c6c9bf05-b120-4e2d-a24f-5ec8ad5d68d5` | 2026-08-01T13:48:07.000Z | GATE/c1_regression_family_targeted_gate | incident=`5b58c32b-5cb8-4f27-a4f7-218201a5bd7b` | lesson_key=`c1-focused-gate-separate-from-host-containment` | event_sha256=`6467063b35a9a61c3905c941123ce9180441b6e882c5edb10722868f200773b5`
- #18: `1b852881-9173-4e54-af0c-5e9742351e57` | 2026-08-01T13:48:08.000Z | STATE_CHANGE/c1_regression_family_admission_completed | incident=`d9e0a369-d567-4976-af26-94fe3b3682e9` | lesson_key=`close-c1-regression-family-admission-at-verified-boundary` | event_sha256=`f6619e7e33389ffafd291180f2451c80dbb06bcd08b253cb39ce25dd351feb5b`
