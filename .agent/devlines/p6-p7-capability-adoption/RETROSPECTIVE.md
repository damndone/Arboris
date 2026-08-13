# Retrospective — p6-p7-capability-adoption

## Goal

# P6/P7 Capability Adoption Objective  At baseline \`ebba33f18037d3569f3d39dae8773b21a870e6e5\`, integrate every operation declared by the frozen P7 source into Arboris's existing typed Agent workflow seam. The current source audit is the truth: 62 unique IDs are declared across the live \`*_OPERATION_IDS\` collections, and the power-analysis contract additionally exposes three designs by four solve targets without an operation-ID collection. Make those 12 combinations explicit in the adoption contract and test them all.  One declaration must automatically supply the closed editable schema, OperationRegistry definition, workflow vocabulary, planning/inspect/route visibility, capability inventory identity, reachability path, typed input adapter, result validation, provenance, and generic workflow execution. Keep pack operations composable through \`operation.multi_step\` unless a separately verified top-level surface is enabled. Do not add an orchestrator branch per operation, do not hide missing adapters as exemptions, and do not silently discard a non-frame input.  Selectively adopt only the frozen P7 contract/runtime/test material; preserve P0/P1/P2, Agent foundations, frontend, survey mathematics, and shared-stage boundaries. Prove correctness with TDD red tests, behavior-changing mutation evidence, external numerical oracles, focused workflow execution, formal FMS verification, and the host full gate. Browser and real-person natural-language acceptance remain explicitly deferred to the final P7 phase.

## Final status

COMPLETED

## Metrics

- Failure frequency: 12/21 (57.1%; 57.1 per 100 events)
- Repeat rate: 0/12 (0.0%)
- Recurrence rate: 0/12 (0.0%)
- MTTR: median=0 ms (sample=11; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/3)

## All failures

- #4 2026-08-08T23:05:20.000Z `p7_pack_focused_wrong_cwd`; cause_status: `known`; cause: The first focused P7 pack command ran from backend/ even though test_manova_pack.py contains a cwd-relative protected-path assertion; the test reported FileNotFoundError for backend/workbench/agent/operations.py.; resolution: `resolved`; lesson: Run suites containing cwd-relative fixtures from the repository root, and treat a FileNotFoundError from the wrong cwd as environment evidence rather than a product failure.
- #5 2026-08-08T23:12:00.000Z `p7_registry_test_wrong_path`; cause_status: `known`; cause: The first registry red-test command used tests/test_p7_adoption_registry.py relative to backend/, but this worktree stores tests at the repository root.; resolution: `resolved`; lesson: Use the repository-root test path with the backend interpreter for this worktree, and distinguish a test-discovery error from a product red test.
- #9 2026-08-08T23:39:00.000Z `p7_adapter_fixture_red`; cause_status: `known`; cause: The first live-call guard exposed eight adapter boundary mismatches: MANOVA treated an omitted optional covariate binding as present; resampling used statistic instead of statistic_id; survival.log_rank received an inapplicable tau; synthetic-control rows and units were transposed; and VAR/IRF used an undeclared stability policy.; resolution: `resolved`; lesson: Derive request options from the frozen runtime signatures and keep optional fields absent rather than sending empty or inapplicable values.
- #10 2026-08-08T23:47:00.000Z `p7_result_contract_red`; cause_status: `known`; cause: The TDD assertion requiring generated workflow output references to come from the frozen family contract initially failed with AttributeError: 'P7FamilyDeclaration' object has no attribute 'result_contract'.; resolution: `resolved`; lesson: Never invent output schema identifiers; project the exact result-contract constant declared by the adopted pack.
- #11 2026-08-08T23:52:00.000Z `p7_workflow_integration_tdd_red`; cause_status: `known`; cause: The first compiled-workflow projection assertion failed with assert 0 == 1 because p7_analysis artifacts were persisted but not included in collect_post_estimation_results. A separate result-shape assertion incorrectly assumed every frozen envelope had result.status and failed with KeyError: 'status'.; resolution: `resolved`; lesson: An executable artifact must also be projected to the product surface, and tests must assert the declared envelope contract rather than an assumed common field.
- #12 2026-08-08T23:57:00.000Z `p7_power_workflow_fixture`; cause_status: `known`; cause: The all-64 compiled-workflow guard first used an empty DataFrame for frame-independent power operations; _source_project wrote an empty CSV and the runtime correctly raised pandas.errors.EmptyDataError: No columns to parse from file.; resolution: `resolved`; lesson: A frame-independent operation still needs a readable source artifact in the workflow harness; do not confuse no data dependency with an unreadable empty file.
- #13 2026-08-09T00:00:00.000Z `p7_nested_raw_request_red`; cause_status: `known`; cause: The security test initially accepted options.policy.callback because raw request keys were checked only at one nesting level; the real failure was Failed: DID NOT RAISE P7PackAdapterError.; resolution: `resolved`; lesson: Security vocabulary must be enforced recursively across typed policy objects, not only at the request envelope.
- #16 2026-08-09T01:20:00.000Z `p7_legacy_guard_red`; cause_status: `known`; cause: The P7 declaration expansion made the live capability projection and STEP_CONSUMES_INPUT_FRAME set larger, while two older tests still asserted the pre-P7 literal coverage sets.; resolution: `resolved`; lesson: When a declaration-driven capability set grows, update old guards to derive from the live registry or explicitly delegate coverage to the declaration-driven guard; never delete the guard or hide the new capabilities.

## All errors

- #2 2026-08-08T22:59:28.000Z `context_pack_path_lookup`; cause_status: `known`; cause: The first read command used the legacy uppercase CONTEXT_PACK.md name; this formal line emits the current lowercase context-pack.md filename.; resolution: `resolved`; lesson: Use the formal CLI's actual lowercase context-pack.md output and verify the path before interpreting a missing file as a missing context pack.
- #3 2026-08-08T23:00:51.000Z `formal_cli_authoring`; cause_status: `known`; cause: The first formal-line start used unquoted option values, then a normalized tag; subsequent append attempts used an external event path and incomplete event schema before the accepted event was authored.; resolution: `resolved`; lesson: Query and satisfy the formal CLI schema before invoking it; quote multi-word values, use normalized tags, keep event evidence repository-relative, and validate every required event field locally.

## All gaps

- #6 2026-08-08T23:16:00.000Z `p7_resampling_dependency_scope`; cause_status: `known`; cause: Importing the copied resampling pack failed because its frozen runtime imports workbench.engine.replicate_combine, which was not in the initial P6 affected-path scope.; resolution: `open`; lesson: Audit transitive imports of every frozen pack before freezing formal affected paths; when a real dependency is required, rescope through the formal CLI rather than bypassing the allowlist.
- #17 2026-08-09T01:35:00.000Z `host_nested_sandbox_not_permitted`; cause_status: `known`; cause: The macOS host rejected sandbox-exec sandbox_apply with Operation not permitted, so code-execution and sandbox tests could not exercise their intended host boundary.; resolution: `not_applicable`; lesson: Keep host-device sandbox failures visible and separately classified; never weaken safety code or convert an unavailable containment boundary into a green product claim.

## All waste

- #14 2026-08-09T00:02:00.000Z `p7_noop_mutation_rejected`; cause_status: `known`; cause: A provenance mutation changed the file hash but initially targeted an earlier post-estimation branch with the same source-sha expression; the P7 integration test stayed green, proving the mutation changed bytes but not the asserted behavior.; resolution: `resolved`; lesson: Mutation evidence requires a behavioral red state, not merely a changed file hash; inspect the targeted execution path when a mutation remains green.
- #15 2026-08-09T00:08:00.000Z `p7_pack_glob_collected_baseline_test`; cause_status: `known`; cause: A broad test_*pack.py glob included the pre-existing test_engine_pack.py, whose standalone collection fails with the same StatisticalTestsStage circular-import error on clean P3 and P4 baselines; the command was not a P7 product failure.; resolution: `resolved`; lesson: Use an explicit focused file list when a repository contains known collection-order-sensitive legacy tests, and compare suspicious failures against a clean baseline before changing code.
- #19 2026-08-09T01:50:00.000Z `p7_wrong_test_selector`; cause_status: `known`; cause: A targeted pytest command named test_every_registered_p7_operation_records_the_dataset_it_actually_read, but the live test is named test_every_registered_p7_operation_completes_through_compiled_workflow.; resolution: `resolved`; lesson: Query the live test definitions before constructing a focused selector so a test-discovery error cannot be mistaken for a product red state.

## Root causes and solutions

- `behavior-changing-mutation-only`: occurrences=1; cause_status: `known`; root cause: A provenance mutation changed the file hash but initially targeted an earlier post-estimation branch with the same source-sha expression; the P7 integration test stayed green, proving the mutation changed bytes but not the asserted behavior.; solution: `resolved`
- `focused-regression-file-list`: occurrences=1; cause_status: `known`; root cause: A broad test_*pack.py glob included the pre-existing test_engine_pack.py, whose standalone collection fails with the same StatisticalTestsStage circular-import error on clean P3 and P4 baselines; the command was not a P7 product failure.; solution: `resolved`
- `focused-suite-root-cwd`: occurrences=1; cause_status: `known`; root cause: The first focused P7 pack command ran from backend/ even though test_manova_pack.py contains a cwd-relative protected-path assertion; the test reported FileNotFoundError for backend/workbench/agent/operations.py.; solution: `resolved`
- `formal-cli-schema-before-invocation`: occurrences=1; cause_status: `known`; root cause: The first formal-line start used unquoted option values, then a normalized tag; subsequent append attempts used an external event path and incomplete event schema before the accepted event was authored.; solution: `resolved`
- `formal-context-pack-path`: occurrences=1; cause_status: `known`; root cause: The first read command used the legacy uppercase CONTEXT_PACK.md name; this formal line emits the current lowercase context-pack.md filename.; solution: `resolved`
- `host-sandbox-gate-classification`: occurrences=1; cause_status: `known`; root cause: The macOS host rejected sandbox-exec sandbox_apply with Operation not permitted, so code-execution and sandbox tests could not exercise their intended host boundary.; solution: `not_applicable`
- `live-test-name-before-selection`: occurrences=1; cause_status: `known`; root cause: A targeted pytest command named test_every_registered_p7_operation_records_the_dataset_it_actually_read, but the live test is named test_every_registered_p7_operation_completes_through_compiled_workflow.; solution: `resolved`
- `p7-adapter-request-boundary`: occurrences=1; cause_status: `known`; root cause: The first live-call guard exposed eight adapter boundary mismatches: MANOVA treated an omitted optional covariate binding as present; resampling used statistic instead of statistic_id; survival.log_rank received an inapplicable tau; synthetic-control rows and units were transposed; and VAR/IRF used an undeclared stability policy.; solution: `resolved`
- `p7-frame-independent-fixture`: occurrences=1; cause_status: `known`; root cause: The all-64 compiled-workflow guard first used an empty DataFrame for frame-independent power operations; _source_project wrote an empty CSV and the runtime correctly raised pandas.errors.EmptyDataError: No columns to parse from file.; solution: `resolved`
- `p7-live-registry-guard`: occurrences=1; cause_status: `known`; root cause: The P7 declaration expansion made the live capability projection and STEP_CONSUMES_INPUT_FRAME set larger, while two older tests still asserted the pre-P7 literal coverage sets.; solution: `resolved`
- `p7-recursive-request-safety`: occurrences=1; cause_status: `known`; root cause: The security test initially accepted options.policy.callback because raw request keys were checked only at one nesting level; the real failure was Failed: DID NOT RAISE P7PackAdapterError.; solution: `resolved`
- `p7-result-contract-source`: occurrences=1; cause_status: `known`; root cause: The TDD assertion requiring generated workflow output references to come from the frozen family contract initially failed with AttributeError: 'P7FamilyDeclaration' object has no attribute 'result_contract'.; solution: `resolved`
- `p7-result-projection-and-envelope`: occurrences=1; cause_status: `known`; root cause: The first compiled-workflow projection assertion failed with assert 0 == 1 because p7_analysis artifacts were persisted but not included in collect_post_estimation_results. A separate result-shape assertion incorrectly assumed every frozen envelope had result.status and failed with KeyError: 'status'.; solution: `resolved`
- `p7-transitive-dependency-scope`: occurrences=1; cause_status: `known`; root cause: Importing the copied resampling pack failed because its frozen runtime imports workbench.engine.replicate_combine, which was not in the initial P6 affected-path scope.; solution: `open`
- `registry-test-root-path`: occurrences=1; cause_status: `known`; root cause: The first registry red-test command used tests/test_p7_adoption_registry.py relative to backend/, but this worktree stores tests at the repository root.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `behavior-changing-mutation-only`: line experience occurrence(s)=1
- `focused-regression-file-list`: line experience occurrence(s)=1
- `focused-suite-root-cwd`: line experience occurrence(s)=1
- `formal-cli-schema-before-invocation`: line experience occurrence(s)=1
- `formal-context-pack-path`: line experience occurrence(s)=1
- `host-sandbox-gate-classification`: line experience occurrence(s)=1
- `live-test-name-before-selection`: line experience occurrence(s)=1
- `p7-adapter-request-boundary`: line experience occurrence(s)=1
- `p7-frame-independent-fixture`: line experience occurrence(s)=1
- `p7-live-registry-guard`: line experience occurrence(s)=1
- `p7-recursive-request-safety`: line experience occurrence(s)=1
- `p7-result-contract-source`: line experience occurrence(s)=1
- `p7-result-projection-and-envelope`: line experience occurrence(s)=1
- `p7-transitive-dependency-scope`: line experience occurrence(s)=1
- `registry-test-root-path`: line experience occurrence(s)=1

## Future guidance

- A declaration-driven adapter entry must validate both the typed input mode and the operation identity before delegating to its family validator.
- A frame-independent operation still needs a readable source artifact in the workflow harness; do not confuse no data dependency with an unreadable empty file.
- An executable artifact must also be projected to the product surface, and tests must assert the declared envelope contract rather than an assumed common field.
- Audit transitive imports of every frozen pack before freezing formal affected paths; when a real dependency is required, rescope through the formal CLI rather than bypassing the allowlist.
- Derive request options from the frozen runtime signatures and keep optional fields absent rather than sending empty or inapplicable values.
- Keep host-device sandbox failures visible and separately classified; never weaken safety code or convert an unavailable containment boundary into a green product claim.
- Mutation evidence requires a behavioral red state, not merely a changed file hash; inspect the targeted execution path when a mutation remains green.
- Never invent output schema identifiers; project the exact result-contract constant declared by the adopted pack.
- Query and satisfy the formal CLI schema before invoking it; quote multi-word values, use normalized tags, keep event evidence repository-relative, and validate every required event field locally.
- Query the live test definitions before constructing a focused selector so a test-discovery error cannot be mistaken for a product red state.
- Run suites containing cwd-relative fixtures from the repository root, and treat a FileNotFoundError from the wrong cwd as environment evidence rather than a product failure.
- Security vocabulary must be enforced recursively across typed policy objects, not only at the request envelope.
- Use an explicit focused file list when a repository contains known collection-order-sensitive legacy tests, and compare suspicious failures against a clean baseline before changing code.
- Use the formal CLI's actual lowercase context-pack.md output and verify the path before interpreting a missing file as a missing context pack.
- Use the repository-root test path with the backend interpreter for this worktree, and distinguish a test-discovery error from a product red test.
- When a declaration-driven capability set grows, update old guards to derive from the live registry or explicitly delegate coverage to the declaration-driven guard; never delete the guard or hide the new capabilities.

## Event index

- #1: `e6ec3871-16de-482f-957e-03b0256e3b4a` | 2026-08-08T22:58:50.772Z | STATE_CHANGE/line_started | incident=`c0c4490d-a98b-46eb-bc5b-51c7e804fbd2` | lesson_key=`frozen-context-before-start` | event_sha256=`6bda93cd3b384f6394452b69b586a7e1cfa6647d22b2a1feae1ea26efefb7f6f`
- #2: `b98d2d9f-71bb-4d86-9a94-c557d4f7a8d1` | 2026-08-08T22:59:28.000Z | ERROR/context_pack_path_lookup | incident=`7f8d82c8-63a1-4be6-b4dd-ea1bc5d8ef51` | lesson_key=`formal-context-pack-path` | event_sha256=`048a023528fac9630914ce94f4a607532aa835594ba288de66107612c646b81f`
- #3: `4e11fd2e-4ad7-4ef1-b31a-6bc62dcde15e` | 2026-08-08T23:00:51.000Z | ERROR/formal_cli_authoring | incident=`d22664c6-8e36-42ea-a4be-5b6e7c26752b` | lesson_key=`formal-cli-schema-before-invocation` | event_sha256=`5a04be239f2a6c0fd48a034ab08d4fc3b7b0ecfee8da59972b992d7c5db5cfcb`
- #4: `a6a7d3b0-5f2c-4ae5-a6a7-cfdca9e9f127` | 2026-08-08T23:05:20.000Z | FAILURE/p7_pack_focused_wrong_cwd | incident=`b7d9d8d6-98b1-47ac-a8da-9e6bdb94e7fb` | lesson_key=`focused-suite-root-cwd` | event_sha256=`0fa5aab6809008fe84f0ef283058b24a953cf56ce55c248db3fdc445875bf72c`
- #5: `f0a1c3d4-5e6f-4789-8abc-def012345678` | 2026-08-08T23:12:00.000Z | FAILURE/p7_registry_test_wrong_path | incident=`12345678-90ab-4cde-8f01-234567890abc` | lesson_key=`registry-test-root-path` | event_sha256=`77082351164aba0384935a90834543b492ca249fdae35794ed99b000a4271ae4`
- #6: `23456789-0abc-4def-8123-456789abcdef` | 2026-08-08T23:16:00.000Z | GAP/p7_resampling_dependency_scope | incident=`34567890-abcd-4ef0-9234-56789abcdef0` | lesson_key=`p7-transitive-dependency-scope` | event_sha256=`446bd5cde119021c8338bcc10cfce310b5fe9d7a0bf21d63efd53931ddb4fa95`
- #7: `980aed29-a974-49e2-9915-c78f9a59f567` | 2026-08-08T23:14:03.440Z | STATE_CHANGE/context_rescope_required | incident=`b1e6e4ad-30b7-4a7e-91a7-cd84c9100cce` | lesson_key=`context-pack-rescope` | event_sha256=`96a9595ca2046dc3543b5769553a0fe5ee501d7eeceeab293c28c5cea0f20c4a`
- #8: `2130dfc5-9e4a-4978-ba54-559a5662e6d3` | 2026-08-08T23:14:03.445Z | STATE_CHANGE/context_rescoped | incident=`c6de1829-7338-4dbc-add6-7a7b00027d52` | lesson_key=`context-pack-rescope` | event_sha256=`7a1ebe4e82ffd3862153693d2c58f865c6c1966c3892d3ffca40827f76e40289`
- #9: `8d6b8f4a-2bb2-4e6d-8f0a-1a26d0c91a11` | 2026-08-08T23:39:00.000Z | FAILURE/p7_adapter_fixture_red | incident=`6c46f2b3-0a0a-44aa-ae8f-2d9a7c51a101` | lesson_key=`p7-adapter-request-boundary` | event_sha256=`fd53d2f759be825568287ce17ddfdb15ae25c0b21516a96a94c968a684e45de5`
- #10: `a4f0a3f7-7d42-4b21-9b89-84d5ed6db102` | 2026-08-08T23:47:00.000Z | FAILURE/p7_result_contract_red | incident=`c8c3d4a1-2a2d-4b6a-8cb0-7c71c7d8a202` | lesson_key=`p7-result-contract-source` | event_sha256=`87d4a30373213ec6ca9357cbb789f489f5e8feddd3a23e83c3aeac70e25b5420`
- #11: `e2e1ac80-f2ac-4b95-b8a4-9ebcb16f5303` | 2026-08-08T23:52:00.000Z | FAILURE/p7_workflow_integration_tdd_red | incident=`dce7de9b-9c06-470f-bbe6-71fd704b4303` | lesson_key=`p7-result-projection-and-envelope` | event_sha256=`648d919eb2d95bc554e7bbe537a6bd4ea427af8e264f1d20cb4ff82db2ba8ae7`
- #12: `f5de1db5-89e1-4a0d-a32c-33c0ae5b8404` | 2026-08-08T23:57:00.000Z | FAILURE/p7_power_workflow_fixture | incident=`f2f61d6d-4a9e-4d10-953d-5b6c8f5a4405` | lesson_key=`p7-frame-independent-fixture` | event_sha256=`8e31a679624f12e6884dcc291cd3740fcb8318a6241db6f49ec9280ae7e9038d`
- #13: `1d0463f2-2f4e-43e5-8df6-2ea4e4d0c506` | 2026-08-09T00:00:00.000Z | FAILURE/p7_nested_raw_request_red | incident=`4f3e2e1b-7f88-4d95-8d86-9c10bd4e4506` | lesson_key=`p7-recursive-request-safety` | event_sha256=`bb7a18487f0ac15f131129b2e0dc25368996af9d1928ef6a50f1ce348ca282d0`
- #14: `7f7fb27a-9c1e-4d31-a2de-5c8b9e0d9707` | 2026-08-09T00:02:00.000Z | WASTE/p7_noop_mutation_rejected | incident=`2c6a1e88-7091-4c18-a485-8c7d0a019008` | lesson_key=`behavior-changing-mutation-only` | event_sha256=`2436c557657c0dbb392f0e8d8d6a82f34da0f4e05976505e53bbfbcbda62f035`
- #15: `56a8d4f1-1f2d-4a9a-b4e0-86b7a2a30109` | 2026-08-09T00:08:00.000Z | WASTE/p7_pack_glob_collected_baseline_test | incident=`be2b8f6c-3d3c-41af-93a4-1d2f6a7b0210` | lesson_key=`focused-regression-file-list` | event_sha256=`828aedf118a6eb43b11643b5d9a7d26d58c8ceaa5dc705ef05e8d1fa85ad7a0d`
- #16: `b5a1d3f8-923f-4c46-91e2-4a5d7bb6f201` | 2026-08-09T01:20:00.000Z | FAILURE/p7_legacy_guard_red | incident=`c4d2e6a9-7f13-4b80-9a5e-2d6f8c1b3047` | lesson_key=`p7-live-registry-guard` | event_sha256=`7989c391a28c82f85a63c1560cf6a66c0f0f6167ee931e3468daf6b099b6c10b`
- #17: `d7e4f1a2-6b93-4c08-8e15-9a2f7d6c5048` | 2026-08-09T01:35:00.000Z | GAP/host_nested_sandbox_not_permitted | incident=`e8f2a6c1-5d79-4b03-9c24-7a1e6f8d2053` | lesson_key=`host-sandbox-gate-classification` | event_sha256=`44b7249c096e93a20d30e13e3fc7804700b4bbe7a3eaff5a4fc4f601e4e76d0e`
- #18: `f1c8a5d2-7e04-4b96-9a31-6d2f8c7e5049` | 2026-08-09T01:45:00.000Z | REVIEW/p7_registry_identity_gap | incident=`a2d9f6b3-8c17-4e05-9b64-1f7a3d5e2086` | lesson_key=`p7-registry-operation-identity` | event_sha256=`263082364faffca311e81e86483aaf901aabf62fb4e3fe3516e84e394394fb3d`
- #19: `a4e9c2f7-1d63-4b08-95a2-7e6c3f1d5048` | 2026-08-09T01:50:00.000Z | WASTE/p7_wrong_test_selector | incident=`b5f1d8a3-6c27-4e09-9a74-2d8f5c1e3069` | lesson_key=`live-test-name-before-selection` | event_sha256=`0b2bb963b98ef94f5e83b6d883febdc317a7331571187f6fa6b458e4aa3b3a2a`
- #20: `c6f3a9d1-8e24-4b07-95f2-1a7d6c4e3085` | 2026-08-09T02:05:00.000Z | STATE_CHANGE/p7_local_adoption_completed | incident=`d7a4e1f9-2c63-4b08-8d15-6f9a3e7c2041` | lesson_key=`p7-local-adoption-boundary` | event_sha256=`26cea5815ea69ef5e91ae45ae9d0436016ee0aff63d8d936d5be27578ce010f0`
- #21: `7c91a2b3-d4e5-4678-9abc-def012345678` | 2026-08-13T09:45:01.000Z | GATE/p7_resampling_dependency_resolved | incident=`34567890-abcd-4ef0-9234-56789abcdef0` | lesson_key=`p7-transitive-dependency-scope` | event_sha256=`7cc4d41be8a54ac296a04d987742daf28fe19eca5eff46e9fb0d62f1276c8cdc`
