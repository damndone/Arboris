# Retrospective — v1-8-9-p1-classification-production

## Goal

# Workbench v1.8.9 P1 Classification Production Objective  Close the production classification path on top of the frozen v1.8.9 classification contracts. The path must consume the declared task/split/ availability/weight specifications instead of silently forcing IID raw-frame execution; use fold-local preprocessing; keep model selection, calibration, thresholding, and the final holdout separated; and emit one evidence shape that the server-indexed Report consumer can safely read.  The completion adapters are Logistic Regression and Random Forest. This line does not add model families, change the central Agent/Notebook router, or call an external provider. Unsupported categorical/missing/weight/split cases must return typed blocked or unavailable outcomes rather than silently degrading.  Required outcomes:  - task-declared IID/group/temporal/panel profiles are either executed with   their declared row/entity/time invariants or rejected explicitly; - preprocessing is fit only on the relevant training rows and its receipt is   bound to the split and artifact identity; - weights are either honored end-to-end or typed blocked before fitting; - calibration and threshold policy are represented honestly, with no claim of   calibrated evidence when only descriptive bins exist; - holdout release remains sealed and one-time; - classification evidence is internally consistent (\`validated\` only when the   packet is complete, otherwise \`degraded\`/\`unavailable\`) and matches the   typed frontend consumer shape.  The central cutover, browser acceptance, external provider benchmark, host full gate, merge, tag, and release remain separate gates.

## Final status

COMPLETED_WITH_KNOWN_GATES

## Metrics

- Failure frequency: 11/53 (20.8%; 20.8 per 100 events)
- Repeat rate: 0/11 (0.0%)
- Recurrence rate: 0/11 (0.0%)
- MTTR: median=0 ms (sample=6; unresolved=4)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/10 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-19T16:45:53.000Z `tdd_red_task_split_profile`; cause_status: `known`; cause: The production classification entrypoint still fixed every task to the iid_stratified split profile.; resolution: `accepted`; lesson: Make the typed task split profile drive the executable manifest before any model fit.
- #3 2026-08-19T16:50:23.000Z `tdd_red_production_contracts`; cause_status: `known`; cause: The additive entrypoint rejects declared weights, has no preprocessing seam, and coerces numeric strings through the helper-only path.; resolution: `accepted`; lesson: Expose only typed production seams and fail closed before any helper-only fitting can run.

## All errors

- #4 2026-08-19T17:00:00.000Z `production_protocol_patch_error`; cause_status: `known`; cause: The first production-path patch left a metadata local uninitialized and then introduced an indentation error while adding weighted threshold inputs.; resolution: `accepted`; lesson: Run compileall immediately after surgical protocol edits and keep branch-local evidence green before adding the next contract.
- #16 2026-08-19T18:20:00.000Z `c0_test_path_probe_error`; cause_status: `known`; cause: The first C0 verification command used guessed test paths that do not exist in this repository.; resolution: `resolved`; lesson: Resolve repository-owned contract test paths before claiming C0 verification evidence.
- #17 2026-08-19T18:21:00.000Z `classification_catalog_bind_scope_error`; cause_status: `known`; cause: Binding the complete builtin provider catalog with only the classification contribution correctly failed because unrelated provider contributions were absent from this package-local runtime.; resolution: `resolved`; lesson: Keep the package-local runtime join typed and explicit, and leave host bootstrap composition as a separate integration boundary.
- #29 2026-08-19T18:30:30.000Z `formal_cli_surface_misread`; cause_status: `known`; cause: The first attempt used nonexistent formal control subcommands append-event and status instead of the existing append interface.; resolution: `resolved`; lesson: Check the formal CLI help before appending line evidence and never bypass the control surface with direct .agent edits.
- #31 2026-08-19T19:20:00.000Z `formal_retrospective_stale`; cause_status: `known`; cause: Formal verification correctly rejected the pre-existing generated retrospective because the new RED, CLI correction, and GREEN gate events had been appended afterward.; resolution: `open`; lesson: Regenerate the formal retrospective immediately after appending material events and before treating formal verification as current.
- #34 2026-08-19T20:12:00.000Z `classification_reportview_fixture_missing_family`; cause_status: `known`; cause: The stricter frontend classification family validator exposed a pre-existing ReportView v1.8.9 test fixture without family_evidence.classification.; resolution: `resolved`; lesson: Keep every consumer fixture aligned with the complete typed family evidence contract.
- #38 2026-08-19T15:56:10.000Z `formal_append_event_path_error`; cause_status: `known`; cause: The formal append command rejected an external temporary event path because event files must be repository-relative.; resolution: `resolved`; lesson: Use the formal CLI with a repository-relative temporary event file and never edit .agent records directly.
- #40 2026-08-19T16:08:30.000Z `verification_frontend_wrong_workdir`; cause_status: `known`; cause: The initial npm frontend focused and typecheck commands were launched from the worktree root, which has no package.json; the actual package root is the allowlisted frontend directory.; resolution: `resolved`; lesson: Resolve the package root before running frontend verification commands in a multi-package worktree.
- #47 2026-08-19T21:30:30.000Z `classification_fourth_remediation_formal_append_error`; cause_status: `known`; cause: The first formal append attempt omitted the required event_id field and was rejected before changing the formal log.; resolution: `resolved`; lesson: Check the append event schema before invoking the formal CLI and preserve the CLI as the only formal write path.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `classification-fourth-remediation-cli-error`: occurrences=1; cause_status: `known`; root cause: The first formal append attempt omitted the required event_id field and was rejected before changing the formal log.; solution: `resolved`
- `compile-after-protocol-edit`: occurrences=1; cause_status: `known`; root cause: The first production-path patch left a metadata local uninitialized and then introduced an indentation error while adding weighted threshold inputs.; solution: `accepted`
- `formal-append-repo-relative-event-file`: occurrences=1; cause_status: `known`; root cause: The formal append command rejected an external temporary event path because event files must be repository-relative.; solution: `resolved`
- `formal-cli-surface-check`: occurrences=1; cause_status: `known`; root cause: The first attempt used nonexistent formal control subcommands append-event and status instead of the existing append interface.; solution: `resolved`
- `formal-retrospective-regeneration`: occurrences=1; cause_status: `known`; root cause: Formal verification correctly rejected the pre-existing generated retrospective because the new RED, CLI correction, and GREEN gate events had been appended afterward.; solution: `open`
- `frontend-verification-package-root`: occurrences=1; cause_status: `known`; root cause: The initial npm frontend focused and typecheck commands were launched from the worktree root, which has no package.json; the actual package root is the allowlisted frontend directory.; solution: `resolved`
- `production-contracts-red`: occurrences=1; cause_status: `known`; root cause: The additive entrypoint rejects declared weights, has no preprocessing seam, and coerces numeric strings through the helper-only path.; solution: `accepted`
- `task-split-profile-red`: occurrences=1; cause_status: `known`; root cause: The production classification entrypoint still fixed every task to the iid_stratified split profile.; solution: `accepted`
- `typed-classification-catalog-projection`: occurrences=1; cause_status: `known`; root cause: Binding the complete builtin provider catalog with only the classification contribution correctly failed because unrelated provider contributions were absent from this package-local runtime.; solution: `resolved`
- `typed-family-fixtures`: occurrences=1; cause_status: `known`; root cause: The stricter frontend classification family validator exposed a pre-existing ReportView v1.8.9 test fixture without family_evidence.classification.; solution: `resolved`
- `verify-real-c0-test-paths`: occurrences=1; cause_status: `known`; root cause: The first C0 verification command used guessed test paths that do not exist in this repository.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `classification-fourth-remediation-cli-error`: line experience occurrence(s)=1
- `compile-after-protocol-edit`: line experience occurrence(s)=1
- `formal-append-repo-relative-event-file`: line experience occurrence(s)=1
- `formal-cli-surface-check`: line experience occurrence(s)=1
- `formal-retrospective-regeneration`: line experience occurrence(s)=1
- `frontend-verification-package-root`: line experience occurrence(s)=1
- `production-contracts-red`: line experience occurrence(s)=1
- `task-split-profile-red`: line experience occurrence(s)=1
- `typed-classification-catalog-projection`: line experience occurrence(s)=1
- `typed-family-fixtures`: line experience occurrence(s)=1
- `verify-real-c0-test-paths`: line experience occurrence(s)=1

## Future guidance

- Check the append event schema before invoking the formal CLI and preserve the CLI as the only formal write path.
- Check the formal CLI help before appending line evidence and never bypass the control surface with direct .agent edits.
- Exercise each authority, split, policy, and evidence boundary before implementing its smallest green path.
- Expose only typed production seams and fail closed before any helper-only fitting can run.
- Keep adversarial behavior-level probes ahead of implementation and require server-owned identity, metadata, and evidence joins at every production consumer boundary.
- Keep authority, typed family identity, and persisted support evidence as behavior-level RED probes before production repair.
- Keep consumer fixtures at the same typed identity boundary as production packets; do not weaken the validator to accommodate stale tests.
- Keep each reviewer blocker as a behavior-level RED probe and implement the missing production boundary instead of weakening the assertion.
- Keep every consumer fixture aligned with the complete typed family evidence contract.
- Keep foreign-copy, memory-bypass, raw-frontend, Notebook, tamper, stale, and status probes ahead of implementation and require one server-indexed wrapper at every consumer boundary.
- Keep public consumer APIs capability-only and bind every consumed classification field to a server-owned persisted receipt before trusting outer artifact or index digests.
- Keep the package-local runtime join typed and explicit, and leave host bootstrap composition as a separate integration boundary.
- Keep the server-indexed wrapper as the only production consumer boundary and retain Notebook as a first-class persisted projection.
- Keep the shared server-owned wrapper as the only classification consumer input and bind every rendered field to its receipt.
- Make the typed task split profile drive the executable manifest before any model fit.
- Regenerate the formal retrospective immediately after appending material events and before treating formal verification as current.
- Resolve repository-owned contract test paths before claiming C0 verification evidence.
- Resolve the package root before running frontend verification commands in a multi-package worktree.
- Run compileall immediately after surgical protocol edits and keep branch-local evidence green before adding the next contract.
- Treat server-owned persisted artifact reload as a separate boundary from a green runtime return; every consumer must validate the same fold receipt contract and status/identity joins.
- Use the formal CLI with a repository-relative temporary event file and never edit .agent records directly.

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
- #23: `82566738-51ae-44f4-8d7f-eff629fe33c7` | 2026-08-19T18:21:42.757Z | STATE_CHANGE/context_rescope_required | incident=`f3b7db84-83ea-455a-8ac5-1a970fd7ddbc` | lesson_key=`context-pack-rescope` | event_sha256=`d76e2c95ef3dfabba8715153a2b34a7b082e09b065cc7c3800742a31062811e1`
- #24: `9453bc52-19e1-4263-850e-91fa71baced7` | 2026-08-19T18:21:42.768Z | STATE_CHANGE/context_rescoped | incident=`836d8f7b-4d27-4542-84c9-d8006a898197` | lesson_key=`context-pack-rescope` | event_sha256=`be06613ccfe41c6e7f72a421d84c42ace0750b36dc5377b8bed19349a34fa415`
- #25: `d4b6c2ef-4d1e-4c9f-8d61-2a19bb4c7e80` | 2026-08-19T18:23:06.000Z | REVIEW/workspace_context_typed_fixture_red | incident=`4f2d8e76-1fbb-4a77-9c88-11a8efbb0ce5` | lesson_key=`workspace-context-typed-fixture-red` | event_sha256=`f4004bb7873d5242ab89babd2b57ff0ed3eddce9ac3f7cf33b36162600f3a179`
- #26: `e7a1c3d2-7b54-4f8e-9a60-6c1d2e5f8b93` | 2026-08-19T18:23:30.000Z | GATE/workspace_context_typed_fixture_green | incident=`5e4a1d7c-91f0-4b2e-8d36-0af3c9b7e2a1` | lesson_key=`workspace-context-typed-fixture-green` | event_sha256=`dbc215358f9a1e9980892cc66f2aefe6bb913c7037be34be774289113b557fe5`
- #27: `f8c2a7d1-5e49-4b63-91f0-2d7e8a4c6b35` | 2026-08-19T18:24:00.000Z | STATE_CHANGE/workspace_context_fixture_scope_complete | incident=`6a3d1f8b-2e74-4c90-a5b1-7f0d9e2c4a68` | lesson_key=`workspace-context-fixture-scope-complete` | event_sha256=`a3fcb031aa3383cc99d196f27716a676a2327026adae6cec6d9a63cdb450a951`
- #28: `a1f4c9e2-7b63-4d18-9a05-2c8e6f1b4d70` | 2026-08-19T18:30:00.000Z | REVIEW/classification_production_adversarial_red | incident=`b7e2d9f4-1a63-4c80-95f7-2d6e8a1b0c43` | lesson_key=`classification-production-adversarial-red` | event_sha256=`6ded5d242765a69d773f9e4ece3e3400096588b4e1b787bcf3cb9ad10d21ee3a`
- #29: `c8d1e6f3-4a70-49b2-85e1-3f6c9d0a2b74` | 2026-08-19T18:30:30.000Z | ERROR/formal_cli_surface_misread | incident=`d9f2a7b4-6c81-40e5-93f0-1a8d6b2c4e75` | lesson_key=`formal-cli-surface-check` | event_sha256=`067bdb21bab2ab7cf1c941bd69957e0c014787db94b5c1a6afacb11c1e629010`
- #30: `e4b9c2d7-61f0-4a83-95ce-2b7d8f1a6c40` | 2026-08-19T19:19:00.000Z | GATE/classification_production_remediation_green | incident=`f5a8c3e1-7d20-4b96-8f34-1c6e9a2d5b70` | lesson_key=`classification-production-remediation-green` | event_sha256=`9a4396f7d9ea927b1315e922f221db161ecb7cd78d3e360ac092329552aa9211`
- #31: `b6e1d4f8-2a70-49c3-85fd-1c7b9e0a4d52` | 2026-08-19T19:20:00.000Z | ERROR/formal_retrospective_stale | incident=`c7f2a9e4-1b63-40d5-8f27-6a0e3c9b5d81` | lesson_key=`formal-retrospective-regeneration` | event_sha256=`47e98312dba2b4653ff0443f2ad0c3e66daca0718ef46076b2786a27d1ce27cd`
- #32: `d2f7a4c9-6e10-4b83-95a1-3c8d0f2e7b64` | 2026-08-19T19:22:00.000Z | GATE/formal_retrospective_current | incident=`e3a8c5f1-7d20-4b96-9f34-1c6e0a2d5b87` | lesson_key=`formal-retrospective-current` | event_sha256=`046e420ec5fde02ca98192cbb7635bd27b07a2d1bb9046937e0412d48607420a`
- #33: `f3d8b2a1-1c4e-4a6f-9b7d-2e8f0c5a6b11` | 2026-08-19T20:05:00.000Z | REVIEW/classification_production_second_round_red | incident=`c4e9a7b2-5d1f-4c8e-9a63-f0b7d2e5c811` | lesson_key=`classification-second-round-red` | event_sha256=`0ce6c06117dffc8e7316ef3f781dce085c9c08fb1b29722396156b27bb4dcea5`
- #34: `a7c1e4f9-2b6d-4a8e-9c03-f5d7b1e2a644` | 2026-08-19T20:12:00.000Z | ERROR/classification_reportview_fixture_missing_family | incident=`d9f2a7b4-6c81-40e5-93f0-1a8d6b2c4e75` | lesson_key=`typed-family-fixtures` | event_sha256=`631204a20f73bf297bb091a621de6266cdb15e8db979b155ba1a0ac9929c65ae`
- #35: `b8e2f5a1-6c3d-4f79-9a02-d7e1c5b8f644` | 2026-08-19T20:16:00.000Z | GATE/classification_production_second_round_focused_green | incident=`e1a7c4d9-2f6b-48e0-9c53-b7d1a5f8e244` | lesson_key=`classification-second-round-green` | event_sha256=`072a912946ae162ed1b7a3570c90563dc43abeaa66b68361132879af19b6e518`
- #36: `c9f4a7d2-6e1b-48f0-9a53-b7d5c2e8f144` | 2026-08-19T20:22:00.000Z | GATE/classification_production_final_verification | incident=`f2a8c5e1-7d39-4b60-9c24-d6f1a7e5b842` | lesson_key=`final-focused-verification` | event_sha256=`45d68ea71de36ce228a5797ca5f92d8a1b5af6d8eaf03d072629c10cec4f3f8a`
- #37: `5a1e7c3d-9b42-4f68-8d20-6c3b7e1a5f94` | 2026-08-19T15:55:44.000Z | REVIEW/classification_production_persistence_third_round_red | incident=`1f6b3d8a-2c57-4e90-b731-9d5a0c6f2e84` | lesson_key=`classification-persistence-third-round-red` | event_sha256=`f1fc184772ebce7602982b8461546a3af8314a5e21daecb3b239d3034084d00a`
- #38: `3c8f1d2a-7b64-4e90-a531-6d2f8b9c0e17` | 2026-08-19T15:56:10.000Z | ERROR/formal_append_event_path_error | incident=`8d2f6a1c-4b79-45e0-9c31-7a5d2e8f6b04` | lesson_key=`formal-append-repo-relative-event-file` | event_sha256=`4b4946f74042a53e73fc9d996a42f3437b68e11d9a3c34108f32f64a644f99ee`
- #39: `7b2e5d9a-4c61-48f0-a3d7-1e9b6c2f5a84` | 2026-08-19T16:06:30.000Z | GATE/classification_production_persistence_third_round_green | incident=`6f1c8a3d-5b72-4e90-9d24-7a0e3c6b1f58` | lesson_key=`classification-production-persistence-third-round-green` | event_sha256=`23ddebc8d7ba0186829d27a95db8b853c522e041f23699af37cb0b33681befbb`
- #40: `9d4f2b7c-6a18-4e50-b3d9-1c7a8f2e5b64` | 2026-08-19T16:08:30.000Z | ERROR/verification_frontend_wrong_workdir | incident=`4a8e1c6f-2b73-49d0-a5e1-7c3b9f6d2a80` | lesson_key=`frontend-verification-package-root` | event_sha256=`9972d32427d56e059b395ccce0877e0aa2ec72472239212e320d926be657531f`
- #41: `17d179c5-9951-4c6d-b817-9dbe5a10d031` | 2026-08-19T20:26:53.068Z | STATE_CHANGE/context_rescope_required | incident=`caf3788e-cdcf-44d9-9b81-c3b72ed442af` | lesson_key=`context-pack-rescope` | event_sha256=`2ee656d38edad877e52576ea86228a6db6c5d183b0c782cd005e67933f941752`
- #42: `938163fc-f7e6-488c-ad50-66c1303bf5f5` | 2026-08-19T20:26:53.087Z | STATE_CHANGE/context_rescoped | incident=`dd4e3231-0202-400d-b8a4-89d894aa134c` | lesson_key=`context-pack-rescope` | event_sha256=`3b73d5454a73aafcdf7e5ad6f502bcdc284c3f1b85c65e5eb9fb0a1144fffe3d`
- #43: `a4c9e2f7-1b6d-48a3-9f05-c7d2e8b4a619` | 2026-08-19T16:27:57.000Z | REVIEW/classification_reviewer_blockers_red | incident=`9e3a4c8b-6d2f-41a7-9c5e-0b8d2f6a4e19` | lesson_key=`classification-reviewer-blockers-red` | event_sha256=`c7394e50708ebfcfa27299e2be878f42b260c4350b95180cdee450ab81ac166a`
- #44: `c1d8e7f6-a5b4-4c3d-9e2f-1a0b9c8d7e6f` | 2026-08-19T20:58:00.000Z | GATE/quick_gate_backend_full_fallback_failed | incident=`e2f1a0b9-c8d7-4e6f-a5b4-3c2d1e0f9a8b` | lesson_key=`classification-host-gate-boundary` | event_sha256=`959911cc09687e16829b102206c2a16e3f3713ea8a43ac6831bec581aac511d6`
- #45: `d4e3f2a1-b0c9-48d7-6e5f-4a3b2c1d0e9f` | 2026-08-19T21:05:00.000Z | REVIEW/classification_reviewer_blockers_green | incident=`f5e4d3c2-b1a0-49f8-7e6d-5c4b3a2d1e0f` | lesson_key=`classification-reviewer-blockers-green` | event_sha256=`d36a494dbbc57d16ddd2b02aff249668d4c65e5cc3c28b7b5ce32052feaef1c8`
- #46: `4f6a8c1e-2d3b-49a7-8c5e-0f1d2a3b4c5e` | 2026-08-19T21:30:00.000Z | REVIEW/classification_fourth_remediation_red | incident=`4f6a8c1e-2d3b-49a7-8c5e-0f1d2a3b4c5d` | lesson_key=`classification-fourth-remediation-red` | event_sha256=`f2d28c1f50713c24643a7e7aaa765ebe2a3db80d357c03a4fe5f5fff278f94ad`
- #47: `4f6a8c1e-2d3b-49a7-8c5e-0f1d2a3b4c5f` | 2026-08-19T21:30:30.000Z | ERROR/classification_fourth_remediation_formal_append_error | incident=`4f6a8c1e-2d3b-49a7-8c5e-0f1d2a3b4c60` | lesson_key=`classification-fourth-remediation-cli-error` | event_sha256=`5407beb5ebd4c7d4186151dfdcf9adf5b510425e13d585c9fb006d814eb1f831`
- #48: `4f6a8c1e-2d3b-49a7-8c5e-0f1d2a3b4c61` | 2026-08-19T21:45:00.000Z | GATE/classification_fourth_remediation_green | incident=`4f6a8c1e-2d3b-49a7-8c5e-0f1d2a3b4c62` | lesson_key=`classification-fourth-remediation-green` | event_sha256=`4f083b1c21f04a9019aa2845d746996afc6248c2ecff9a82d9b5526b3564cb4e`
- #49: `044f40e2-b0fc-4270-bb52-14ce39c0aabd` | 2026-08-19T21:31:32.985Z | STATE_CHANGE/context_rescope_required | incident=`08139993-3cd7-401f-ad22-242dc7f7b2a8` | lesson_key=`context-pack-rescope` | event_sha256=`24760a387c443d1175ea5dcf4881a61b6e9b304216e431111f0bdcf0bdecda05`
- #50: `3592d200-b4e0-4955-a44b-d7dd46d762b7` | 2026-08-19T21:31:33.006Z | STATE_CHANGE/context_rescoped | incident=`a91b5328-6563-4ade-a0fe-e89e3f500b68` | lesson_key=`context-pack-rescope` | event_sha256=`856433fa43ebdb5ed0e4c143bd82bcd5d443a08cd27a5546044408133fc740cc`
- #51: `6f5a4c3b-2d1e-49f8-8a7b-6c5d4e3f2a10` | 2026-08-19T21:34:00.000Z | REVIEW/classification_fifth_remediation_red | incident=`6f5a4c3b-2d1e-49f8-8a7b-6c5d4e3f2a11` | lesson_key=`classification-fifth-remediation-red` | event_sha256=`274f5e9b07f9a385776ec67843e7315c4391d992519a18f240897c43c6a16ad1`
- #52: `6f5a4c3b-2d1e-49f8-8a7b-6c5d4e3f2a12` | 2026-08-19T21:48:00.000Z | GATE/classification_fifth_remediation_green | incident=`6f5a4c3b-2d1e-49f8-8a7b-6c5d4e3f2a13` | lesson_key=`classification-fifth-remediation-green` | event_sha256=`2c45558a1ef383b39b5acf6ebfa6953ad572fa9133d21778c0fbe0b20fa5205a`
- #53: `6f5a4c3b-2d1e-49f8-8a7b-6c5d4e3f2a14` | 2026-08-19T21:49:00.000Z | STATE_CHANGE/classification_fifth_remediation_complete | incident=`6f5a4c3b-2d1e-49f8-8a7b-6c5d4e3f2a15` | lesson_key=`classification-fifth-remediation-terminal` | event_sha256=`3ffd33c878b7925f0aab11e279a4212e84cfea2c4ff0a35f0098998a958113ce`
