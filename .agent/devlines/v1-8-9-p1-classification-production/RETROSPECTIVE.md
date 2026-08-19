# Retrospective — v1-8-9-p1-classification-production

## Goal

# Workbench v1.8.9 P1 Classification Production Objective  Close the production classification path on top of the frozen v1.8.9 classification contracts. The path must consume the declared task/split/ availability/weight specifications instead of silently forcing IID raw-frame execution; use fold-local preprocessing; keep model selection, calibration, thresholding, and the final holdout separated; and emit one evidence shape that the server-indexed Report consumer can safely read.  The completion adapters are Logistic Regression and Random Forest. This line does not add model families, change the central Agent/Notebook router, or call an external provider. Unsupported categorical/missing/weight/split cases must return typed blocked or unavailable outcomes rather than silently degrading.  Required outcomes:  - task-declared IID/group/temporal/panel profiles are either executed with   their declared row/entity/time invariants or rejected explicitly; - preprocessing is fit only on the relevant training rows and its receipt is   bound to the split and artifact identity; - weights are either honored end-to-end or typed blocked before fitting; - calibration and threshold policy are represented honestly, with no claim of   calibrated evidence when only descriptive bins exist; - holdout release remains sealed and one-time; - classification evidence is internally consistent (\`validated\` only when the   packet is complete, otherwise \`degraded\`/\`unavailable\`) and matches the   typed frontend consumer shape.  The central cutover, browser acceptance, external provider benchmark, host full gate, merge, tag, and release remain separate gates.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/22 (22.7%; 22.7 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=3)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-19T16:45:53.000Z `tdd_red_task_split_profile`; cause_status: `known`; cause: The production classification entrypoint still fixed every task to the iid_stratified split profile.; resolution: `accepted`; lesson: Make the typed task split profile drive the executable manifest before any model fit.
- #3 2026-08-19T16:50:23.000Z `tdd_red_production_contracts`; cause_status: `known`; cause: The additive entrypoint rejects declared weights, has no preprocessing seam, and coerces numeric strings through the helper-only path.; resolution: `accepted`; lesson: Expose only typed production seams and fail closed before any helper-only fitting can run.

## All errors

- #4 2026-08-19T17:00:00.000Z `production_protocol_patch_error`; cause_status: `known`; cause: The first production-path patch left a metadata local uninitialized and then introduced an indentation error while adding weighted threshold inputs.; resolution: `accepted`; lesson: Run compileall immediately after surgical protocol edits and keep branch-local evidence green before adding the next contract.
- #16 2026-08-19T18:20:00.000Z `c0_test_path_probe_error`; cause_status: `known`; cause: The first C0 verification command used guessed test paths that do not exist in this repository.; resolution: `resolved`; lesson: Resolve repository-owned contract test paths before claiming C0 verification evidence.
- #17 2026-08-19T18:21:00.000Z `classification_catalog_bind_scope_error`; cause_status: `known`; cause: Binding the complete builtin provider catalog with only the classification contribution correctly failed because unrelated provider contributions were absent from this package-local runtime.; resolution: `resolved`; lesson: Keep the package-local runtime join typed and explicit, and leave host bootstrap composition as a separate integration boundary.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `compile-after-protocol-edit`: occurrences=1; cause_status: `known`; root cause: The first production-path patch left a metadata local uninitialized and then introduced an indentation error while adding weighted threshold inputs.; solution: `accepted`
- `production-contracts-red`: occurrences=1; cause_status: `known`; root cause: The additive entrypoint rejects declared weights, has no preprocessing seam, and coerces numeric strings through the helper-only path.; solution: `accepted`
- `task-split-profile-red`: occurrences=1; cause_status: `known`; root cause: The production classification entrypoint still fixed every task to the iid_stratified split profile.; solution: `accepted`
- `typed-classification-catalog-projection`: occurrences=1; cause_status: `known`; root cause: Binding the complete builtin provider catalog with only the classification contribution correctly failed because unrelated provider contributions were absent from this package-local runtime.; solution: `resolved`
- `verify-real-c0-test-paths`: occurrences=1; cause_status: `known`; root cause: The first C0 verification command used guessed test paths that do not exist in this repository.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `compile-after-protocol-edit`: line experience occurrence(s)=1
- `production-contracts-red`: line experience occurrence(s)=1
- `task-split-profile-red`: line experience occurrence(s)=1
- `typed-classification-catalog-projection`: line experience occurrence(s)=1
- `verify-real-c0-test-paths`: line experience occurrence(s)=1

## Future guidance

- Exercise each authority, split, policy, and evidence boundary before implementing its smallest green path.
- Expose only typed production seams and fail closed before any helper-only fitting can run.
- Keep each reviewer blocker as a behavior-level RED probe and implement the missing production boundary instead of weakening the assertion.
- Keep the package-local runtime join typed and explicit, and leave host bootstrap composition as a separate integration boundary.
- Make the typed task split profile drive the executable manifest before any model fit.
- Resolve repository-owned contract test paths before claiming C0 verification evidence.
- Run compileall immediately after surgical protocol edits and keep branch-local evidence green before adding the next contract.

## Event index

- #1: `3f4aa530-821c-4584-97c6-99265ae00432` | 2026-08-19T16:35:25.954Z | STATE_CHANGE/line_started | incident=`9d7384b9-584a-4bc7-8667-368e4bda6295` | lesson_key=`frozen-context-before-start` | event_sha256=`e9b030083b1fcf8c956311785644b2be80098ff007f09081431a95e6f2ebf90c`
- #2: `4f3aa530-821c-4584-97c6-99265ae00432` | 2026-08-19T16:45:53.000Z | FAILURE/tdd_red_task_split_profile | incident=`9d7384b9-584a-4bc7-8667-368e4bda6295` | lesson_key=`task-split-profile-red` | event_sha256=`a634efbfac5f168f83f35c3ebd2c70f35023a5f89dfc9c349f01144b7e9c6318`
- #3: `5f4aa530-821c-4584-97c6-99265ae00433` | 2026-08-19T16:50:23.000Z | FAILURE/tdd_red_production_contracts | incident=`ad7384b9-584a-4bc7-8667-368e4bda6296` | lesson_key=`production-contracts-red` | event_sha256=`e6558838fe0be65e77472c8c4a057257dfe60e0cdc4b603614ba958494e9d80f`
- #4: `6f4aa530-821c-4584-97c6-99265ae00434` | 2026-08-19T17:00:00.000Z | ERROR/production_protocol_patch_error | incident=`bd7384b9-584a-4bc7-8667-368e4bda6296` | lesson_key=`compile-after-protocol-edit` | event_sha256=`4987a6218dc492128ac657a9ff1bf7274a74335d2e9b2340d096cdab46ff09ee`
- #5: `7f4aa530-821c-4584-97c6-99265ae00434` | 2026-08-19T18:00:00.000Z | REVIEW/tdd_red_classification_production_review_blockers | incident=`cd7384b9-584a-4bc7-8667-368e4bda6295` | lesson_key=`classification-production-review-red-probes` | event_sha256=`bcebac2de2155b37a795600186c37fec21dbb49d766e2dfe537b6bbc5bf17062`
- #6: `91f007e9-594d-4ebd-8719-ac4cd7cf0456` | 2026-08-19T17:48:38.902Z | STATE_CHANGE/context_rescope_required | incident=`317e0b4f-4304-425d-aa64-caf09be7ba9f` | lesson_key=`context-pack-rescope` | event_sha256=`42421ff066aae5323be95cc4d9c13e0613e2d4ad800d7706c0d7dd086ef6c090`
- #7: `2ff2f4e2-eca4-4510-86aa-bd972d9f60aa` | 2026-08-19T17:48:38.906Z | STATE_CHANGE/context_rescoped | incident=`b8a8a8d8-0dd1-4040-9e63-cc4aa08b9fb7` | lesson_key=`context-pack-rescope` | event_sha256=`f086378f1b4b3eeae0888cd7b31f541993a0932afee09903ebb0da51a1d3db36`
- #8: `d3f0148f-a3f2-4555-adda-550a868b1780` | 2026-08-19T17:48:39.021Z | STATE_CHANGE/context_rescope_required | incident=`d4a38f17-eb69-4496-b88b-99d1a59018fc` | lesson_key=`context-pack-rescope` | event_sha256=`6a21592315b4bff7174fb71fe963ff7d7ad86fb1d1b1d76610016e9b960a4c76`
- #9: `7218f982-09b6-4f7e-9ea3-d792cdc2e958` | 2026-08-19T17:48:39.026Z | STATE_CHANGE/context_rescoped | incident=`d66333c5-1f4d-4821-8176-4f4bc9c1f469` | lesson_key=`context-pack-rescope` | event_sha256=`7b21272f966b1368940c24286c546bc59aec778b6349ca7a6e2db633ed76a96d`
- #10: `1601a801-95c9-4c66-98ba-03b170c2d83a` | 2026-08-19T17:48:39.144Z | STATE_CHANGE/context_rescope_required | incident=`a4785ddd-b69f-4ab1-b350-2284b8dc5a40` | lesson_key=`context-pack-rescope` | event_sha256=`733e40535863949db68ab0e08ee4dc504aded40aae474dcfaf5bb9348a004162`
- #11: `8ed03ad5-0f18-4867-96f2-0c3426432b4a` | 2026-08-19T17:48:39.149Z | STATE_CHANGE/context_rescoped | incident=`721385c3-31e1-4d35-bce0-dd49dfa371ba` | lesson_key=`context-pack-rescope` | event_sha256=`5b4cc8696fcf730fc8035431b7c9904d8065da8e9d579b9fdf06b2c05781adb2`
- #12: `5fcabfeb-c5d5-4e72-adfb-e3d2952c75e6` | 2026-08-19T17:48:39.265Z | STATE_CHANGE/context_rescope_required | incident=`9f94c71a-27a7-4b77-94f2-14189fd768ed` | lesson_key=`context-pack-rescope` | event_sha256=`ebe157c9fdf7c155b5117f21219933d571c57766b6798f57e8c8506b553eca8c`
- #13: `521af9df-0b96-4e0d-b17a-3eacb9b015e5` | 2026-08-19T17:48:39.271Z | STATE_CHANGE/context_rescoped | incident=`7b42b536-fb65-4664-83c0-2b31eac6ad46` | lesson_key=`context-pack-rescope` | event_sha256=`2cb674bb40f23e5e128b2db731d35a22ee6dc5fc44d31d0ba01a5f55bf560be6`
- #14: `c48518a3-9c7f-4277-b06e-942922181f7d` | 2026-08-19T17:48:39.387Z | STATE_CHANGE/context_rescope_required | incident=`6d7e1934-6d15-40f4-b2fe-d453fdfb5285` | lesson_key=`context-pack-rescope` | event_sha256=`6db8cdf57a3dd55af8c07f9440213e27d4bea2374c46ef5e565a12fe2f14496e`
- #15: `5c16839b-7fce-4d82-b18c-fee59206dca7` | 2026-08-19T17:48:39.394Z | STATE_CHANGE/context_rescoped | incident=`df79436a-bf82-46b3-bd26-e0fdd16d103b` | lesson_key=`context-pack-rescope` | event_sha256=`906be779c48beae0ed61ededca0acf76a847e00d56cdb1f51964a3a57e142603`
- #16: `8a3c41de-8d03-4c9d-9370-1a5a1c70d6f7` | 2026-08-19T18:20:00.000Z | ERROR/c0_test_path_probe_error | incident=`5b4d6c19-90a8-4e15-86a5-0df45d2f6f9a` | lesson_key=`verify-real-c0-test-paths` | event_sha256=`b058fac97a6fa839739240d36adca79cc941342c867dd71bf3f2a89ca14b2315`
- #17: `9b4d52ef-9e14-40d0-a2d8-6e48f5d72a1e` | 2026-08-19T18:21:00.000Z | ERROR/classification_catalog_bind_scope_error | incident=`7c1fd4d1-6d0b-4b9a-a83e-0e2e6cb16f0b` | lesson_key=`typed-classification-catalog-projection` | event_sha256=`aa5a12bf6070eeef18f58aaa88bf72813b889b9b67cd8cfa9d9f00a5b8629550`
- #18: `0a1ae295-53c7-485a-b1a5-d1a02fadefaf` | 2026-08-19T18:13:12.865Z | STATE_CHANGE/context_rescope_required | incident=`811c3c3f-b6f2-4492-80b9-11998c1a92ac` | lesson_key=`context-pack-rescope` | event_sha256=`ec20b5e8dd9e75040d2d8ea13ba50807e52ec008d7e7099e37ba66322727bedf`
- #19: `52e8b1b3-1bb0-43f1-9da8-04c115c1e225` | 2026-08-19T18:13:12.875Z | STATE_CHANGE/context_rescoped | incident=`6f5fa724-1c4c-46d8-ae57-3682c054136d` | lesson_key=`context-pack-rescope` | event_sha256=`eead48ed614bbb532add545029b7e618d8fe6d192359dc2202b16c722b4ea23e`
- #20: `ab6e58d7-3f2a-44d0-a742-0bcdf1d69b1c` | 2026-08-19T18:14:28.000Z | REVIEW/classification_production_red_probes | incident=`3d8f45b1-30a4-49c6-99f0-7d1ea09d13c4` | lesson_key=`classification-production-review-red` | event_sha256=`92d80e39cbb939eb886c1c65b0cc425de9daa6773cbbdf564dfa727c5a511df1`
- #21: `bd2f8a9e-2ca0-46a6-9b7b-f8bdf4d7e591` | 2026-08-19T18:15:50.000Z | GATE/classification_production_local_verification_green | incident=`0e7bcf4f-6eb8-4b31-9a40-711789c8a630` | lesson_key=`classification-production-local-gate` | event_sha256=`b51e54637a207d48b052588422c3f3ae2e632dc372829196c5326945153bab21`
- #22: `c1e4a6b3-6d7f-4c88-8c7c-7f51a4f8e213` | 2026-08-19T18:16:30.000Z | STATE_CHANGE/classification_production_scope_complete | incident=`1a5f2f2c-fb9c-4d0e-83e0-62af0e63d02a` | lesson_key=`classification-production-scope-complete` | event_sha256=`b485b1a4324e804f72f9b0a5e581111dd6e06038edb75d3baac65d06e7b6214e`
