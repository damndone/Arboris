# Retrospective — integration-v1-7-3

## Goal

Assemble one evidence-bound v1.7.3 Integration candidate without treating control-plane, lane-local, browser, performance, or containment evidence as interchangeable.

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 4/29 (13.8%; 13.8 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=4; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/1)

## All failures

- #9 2026-07-20T02:10:00.000Z `c1_lmm_dispatch_bypassed_c2_boundary`; cause_status: `known`; cause: Registering the LMM pack made ordinary shared submission paths executable even though no real C2 OS containment capability had been admitted.; resolution: `resolved`; lesson: Shared dispatch and synchronous workflow now reject LMM before any upload, run, or snapshot is materialized; C1 input/result contracts and C2 runtime permission are separate capabilities, so executable model declarations must not imply containment permission.

## All errors

- #12 2026-07-20T02:41:00.000Z `test_helper_shadowed_declared_model_owner`; cause_status: `known`; cause: WO-A tests inserted a manual LMM handler while the production declaration loader owned the same model type, making results depend on suite order.; resolution: `resolved`; lesson: Tests exercising a declared pack must use the same declared owner as production; do not shadow a registered model handler in a fixture because loader conflict checks are intentional safety controls.

## All gaps

- #3 2026-07-20T01:15:00.000Z `runtime_contract_assembly_drift`; cause_status: `known`; cause: Reviewed WO components were present but did not share the runtime declarations and fixed-reader API contract.; resolution: `resolved`; lesson: An accepted lane requires an exact assembled runtime contract test, not only isolated lane tests.
- #6 2026-07-20T01:37:28.000Z `genesis_lmm_options_missing`; cause_status: `known`; cause: The Genesis wizard did not render or persist LMM model options even though the run form supported them.; resolution: `resolved`; lesson: Integration acceptance must exercise each user entry point, including Genesis, rather than infer coverage from the shared run form.

## All waste

- #23 2026-07-20T06:16:00.000Z `fms_parallel_promotion_index_race`; cause_status: `known`; cause: Retrospective generation and global promotion were started concurrently; promotion read the line before its formal state was visible.; resolution: `resolved`; lesson: Control operations that update and read the same FMS state must be serialized: append, regenerate retrospective, verify, then promote.

## Root causes and solutions

- `c1-c2-execution-boundary`: occurrences=1; cause_status: `known`; root cause: Registering the LMM pack made ordinary shared submission paths executable even though no real C2 OS containment capability had been admitted.; solution: `resolved`
- `declared-owner-no-test-shadowing`: occurrences=1; cause_status: `known`; root cause: WO-A tests inserted a manual LMM handler while the production declaration loader owned the same model type, making results depend on suite order.; solution: `resolved`
- `entrypoint-contract-coverage`: occurrences=1; cause_status: `known`; root cause: The Genesis wizard did not render or persist LMM model options even though the run form supported them.; solution: `resolved`
- `runtime-contract-assembly`: occurrences=1; cause_status: `known`; root cause: Reviewed WO components were present but did not share the runtime declarations and fixed-reader API contract.; solution: `resolved`
- `serialize-fms-control-operations`: occurrences=1; cause_status: `known`; root cause: Retrospective generation and global promotion were started concurrently; promotion read the line before its formal state was visible.; solution: `resolved`

## Added tests

- `frontend/src/lineage/drafts/GenesisWizard.test.tsx`
- `tests/agent/test_repeated_measures_recipe.py`
- `tests/test_lmm_extension_seams.py`

## New rules

- `c1-c2-execution-boundary`: line experience occurrence(s)=1
- `declared-owner-no-test-shadowing`: line experience occurrence(s)=1
- `entrypoint-contract-coverage`: line experience occurrence(s)=1
- `runtime-contract-assembly`: line experience occurrence(s)=1
- `serialize-fms-control-operations`: line experience occurrence(s)=1

## Future guidance

- An accepted lane requires an exact assembled runtime contract test, not only isolated lane tests.
- Control operations that update and read the same FMS state must be serialized: append, regenerate retrospective, verify, then promote.
- Integration acceptance must exercise each user entry point, including Genesis, rather than infer coverage from the shared run form.
- Shared dispatch and synchronous workflow now reject LMM before any upload, run, or snapshot is materialized; C1 input/result contracts and C2 runtime permission are separate capabilities, so executable model declarations must not imply containment permission.
- Tests exercising a declared pack must use the same declared owner as production; do not shadow a registered model handler in a fixture because loader conflict checks are intentional safety controls.

## Event index

- #1: `80f5b484-9cf1-44a9-ba63-f702f35d21ae` | 2026-07-19T23:45:32.637Z | STATE_CHANGE/line_started | incident=`61ae4667-5df3-46ba-923d-8eb65d968fc9` | lesson_key=`frozen-context-before-start` | event_sha256=`8b757686961a35740e27acead87895198d4f8de84f28e0a165d1b7e11fa4e297`
- #2: `10000000-0000-4000-8000-000000000005` | 2026-07-19T19:20:00.000Z | STATE_CHANGE/formal_control_plane_checkpoint | incident=`20000000-0000-4000-8000-000000000005` | lesson_key=`integration-candidate-not-assembled` | event_sha256=`1ec782b7fc333e2397fcc1e330de943a0de3c88b7b7372f0b36e55d3acb611c9`
- #3: `43b2f64c-0f59-4e8c-91f1-8dbe3533d1e1` | 2026-07-20T01:15:00.000Z | GAP/runtime_contract_assembly_drift | incident=`6ce72c72-0b70-4f89-9749-e6a6e95c1c6e` | lesson_key=`runtime-contract-assembly` | event_sha256=`928007e28fc3f5f991c1b86196490352774cca0c0e43f9c56a00f23a220ec29f`
- #4: `7f3e8087-80a7-468d-9cb0-443a6efe6111` | 2026-07-20T01:37:24.759Z | STATE_CHANGE/context_rescope_required | incident=`1c28ddb3-178c-4ff8-b888-e754762a9460` | lesson_key=`context-pack-rescope` | event_sha256=`37288f797482a809eb5c8742199ab7c6f66663586bb6c3c5a850ca1041acaefc`
- #5: `a362fd45-0cbe-4e16-851f-d647c1eedaa3` | 2026-07-20T01:37:24.762Z | STATE_CHANGE/context_rescoped | incident=`b57e69c5-b197-4ce2-9961-886e0f4988a9` | lesson_key=`context-pack-rescope` | event_sha256=`b1b9f58b2801f992e7aa95c33319bf814ff1c751739d78660a36b491651adae8`
- #6: `5d33c8d3-d5c5-4e6e-986d-743927f7f8d9` | 2026-07-20T01:37:28.000Z | GAP/genesis_lmm_options_missing | incident=`475a99d2-0c73-432e-9f1e-cfda3bb7f735` | lesson_key=`entrypoint-contract-coverage` | event_sha256=`c779aaa53bc5139d1185c68977334ba443b8392ecfbe5422359d24428a822b6d`
- #7: `a27bcc9b-73b0-47fb-806d-1b3baf5335cc` | 2026-07-20T01:56:56.652Z | STATE_CHANGE/context_rescope_required | incident=`71bf4cc4-2b5d-4b9f-b32b-05aab57d910d` | lesson_key=`context-pack-rescope` | event_sha256=`736dfb1b70a726590e1dbe32d139b37546c903b5ab530781502a3fbac298bb0c`
- #8: `d0b5e89c-693c-4d91-be80-4dd2feaa5c76` | 2026-07-20T01:56:56.657Z | STATE_CHANGE/context_rescoped | incident=`04e00b9a-f2b0-4a0e-b23e-c05c08e34762` | lesson_key=`context-pack-rescope` | event_sha256=`dbb0aafdb9d859111f7dfaa0e672230e16842b175a9581c5e96c50080688642f`
- #9: `cf5c50d1-c2f1-4617-9016-0a32c9f0c2e1` | 2026-07-20T02:10:00.000Z | FAILURE/c1_lmm_dispatch_bypassed_c2_boundary | incident=`b7427631-1145-4e3c-9c09-2a7d4be07f4a` | lesson_key=`c1-c2-execution-boundary` | event_sha256=`1759c8a6bf1129160cf14ad3fabe16ffe31453f3fe967c117c39c7959da58eb4`
- #10: `2f198f8a-0f8c-4099-ac0a-3a5ac103ff2b` | 2026-07-20T02:18:39.623Z | STATE_CHANGE/context_rescope_required | incident=`44b055ae-bc6e-433c-8237-5df1e5b3777d` | lesson_key=`context-pack-rescope` | event_sha256=`ca79e00c51523713339c8e88e61f2cffbc86225c6c0d88accefba5021e5248d6`
- #11: `805fb68b-79e1-4a65-9fd7-0dd0753806e4` | 2026-07-20T02:18:39.629Z | STATE_CHANGE/context_rescoped | incident=`77a30480-098e-45ce-9dc9-6888f4774d43` | lesson_key=`context-pack-rescope` | event_sha256=`203f5ee474c2fb5d24cfe48bc41a5b9d7a4dcefe64ebd1d1859ee98e3c21b18d`
- #12: `8d31da52-57b9-44a3-a8ec-e6a9fa3c73ce` | 2026-07-20T02:41:00.000Z | ERROR/test_helper_shadowed_declared_model_owner | incident=`daa7d3a5-4b47-4aa1-9a7e-a6b583e354d5` | lesson_key=`declared-owner-no-test-shadowing` | event_sha256=`6b1d94d36965c8176e8d8df97cc6f9f79811201f2ae92f9f4c8d92df562f2e32`
- #13: `74b407f1-911f-4813-ae2b-026d83594fc6` | 2026-07-20T03:05:00.000Z | STATE_CHANGE/local_development_acceptance_c2_deferred | incident=`33bf1e06-364e-4d2d-b258-6ebf1e056e4a` | lesson_key=`c2-deferral-is-not-security-pass` | event_sha256=`f1346d06fea673d7d5598817be73d12e50f4d0ee9217b0555dbafe83d67f30de`
- #14: `f95421b9-2f58-4acd-bf22-82417bdee77d` | 2026-07-20T05:38:45.118Z | STATE_CHANGE/context_rescope_required | incident=`05f286fb-0741-4bf1-ac34-bba6cd8da88a` | lesson_key=`context-pack-rescope` | event_sha256=`a16ecea0fb2364f629a8c194b93113652eff5e6c29df237ad1b7832b0e9b0f15`
- #15: `fa1b21ff-ada0-460a-a1da-fbb83920f02b` | 2026-07-20T05:38:45.126Z | STATE_CHANGE/context_rescoped | incident=`acabeed5-26af-43a2-880b-7a628f962039` | lesson_key=`context-pack-rescope` | event_sha256=`428e6ca107f7ca018e8108243e5a5a40441152b393f54aafd24927b8af0227bd`
- #16: `8faf39cb-3928-4317-b828-d31dccd54f0e` | 2026-07-20T05:39:00.145Z | STATE_CHANGE/context_rescope_required | incident=`2029d399-2438-4499-bb5d-f526f591f328` | lesson_key=`context-pack-rescope` | event_sha256=`c619cb94029d4ba0b3c6251ef85570b0ceae6e88aafb2bd098943249879f8f2e`
- #17: `462a373e-4049-4831-bb33-29d351afbaf8` | 2026-07-20T05:39:00.155Z | STATE_CHANGE/context_rescoped | incident=`dd7b182f-b6a3-46df-ae4a-67ec72245c27` | lesson_key=`context-pack-rescope` | event_sha256=`f666c9f3bdd01a7a877e51834f8c0c1760e32b26061217519316b0a5ebb99f3e`
- #18: `b9750298-46f8-4f7f-bc02-06c587eea6a4` | 2026-07-20T05:43:29.877Z | STATE_CHANGE/context_rescope_required | incident=`683de24a-a6c5-42be-aece-8780d187d6eb` | lesson_key=`context-pack-rescope` | event_sha256=`5c24941c508b2c301aa670efd4b3b5c27a909298946e31808d31bef7d88925ec`
- #19: `0b259956-79e2-4ac6-b0ed-54cb79c85ecf` | 2026-07-20T05:43:29.888Z | STATE_CHANGE/context_rescoped | incident=`75112ba1-459f-468e-930a-6853b37c866c` | lesson_key=`context-pack-rescope` | event_sha256=`9ea88fcbde6f8549c19af9c91553551842da41cb8426fd850de8698115f1bfb6`
- #20: `f4aee30f-7c2b-432d-a7bc-3b62a27d0b28` | 2026-07-20T05:48:12.613Z | STATE_CHANGE/context_rescope_required | incident=`88f1f907-7d49-41ed-9ffd-f5116e2e46fb` | lesson_key=`context-pack-rescope` | event_sha256=`651cf7052067105206bd9dcc30aa71e80e68356aeb035a7b5c5773e90d5339d5`
- #21: `210c96a9-31f3-48e9-8041-39e097fecd34` | 2026-07-20T05:48:12.625Z | STATE_CHANGE/context_rescoped | incident=`c83b40be-cef6-4d9e-a396-090587fcef55` | lesson_key=`context-pack-rescope` | event_sha256=`e0afe25a64d8e4a0f7186290efd602af0ee4878cd388331a2d73fcaa62e2eac9`
- #22: `dd3d0f5e-677a-44c5-8289-9eaf968ab6c2` | 2026-07-20T06:14:00.000Z | GATE/local_integration_gate_passed | incident=`b71e60c4-2ddb-40e7-bbdb-d388d30ef933` | lesson_key=`browser-plus-full-gate-local-acceptance` | event_sha256=`40043c7fbcbc92018da2cc93d700b46a960e79cc895c3ce50ab858986c653398`
- #23: `3ccaa49b-aa22-496e-ba08-e3ee12f2d545` | 2026-07-20T06:16:00.000Z | WASTE/fms_parallel_promotion_index_race | incident=`c5464228-6445-4f47-ab19-c1642af5d747` | lesson_key=`serialize-fms-control-operations` | event_sha256=`1865e060131d0c637717d9ca5244ef0d2a136f2958262cb524f090e3b8acd3f9`
- #24: `218fc918-d983-42c5-b1d2-a13ff29d8c5c` | 2026-07-20T07:46:44.876Z | STATE_CHANGE/context_rescope_required | incident=`5e86517f-085f-4728-b193-eb9c34e811a8` | lesson_key=`context-pack-rescope` | event_sha256=`032f69245ef3eacd13bb4e3ff12ffac768fae6b2a0fcbb83f090a44d9d1d291f`
- #25: `409af46a-1323-4bef-a0a2-345e275f94d8` | 2026-07-20T07:46:44.889Z | STATE_CHANGE/context_rescoped | incident=`ac2d0c0b-01d6-4d90-a1dc-8e82f80cedff` | lesson_key=`context-pack-rescope` | event_sha256=`ffbb8c352797b747b3577bbad99a670dc68bb1fb4e0b97a8c7ba5cf2a73780da`
- #26: `72225fe5-fd99-4232-8d6a-2e85ce7c2e43` | 2026-07-20T08:00:46.000Z | GATE/precommit_full_local_gate_passed | incident=`7daea5fe-ffbb-4be4-8ec0-ec4ba208511f` | lesson_key=`precommit-full-gate-and-clean-diff` | event_sha256=`c8d30311c08faedfc6fedbd68afcaa7bace6593cde7020153a61e28dea1b2ec2`
- #27: `f49af146-c542-49c0-95ec-726818f7d60c` | 2026-07-20T08:02:52.712Z | STATE_CHANGE/context_rescope_required | incident=`4d5eddba-1c84-42e9-97e3-f9e3e50aa893` | lesson_key=`context-pack-rescope` | event_sha256=`d61c2bf0df4fc35597ed85b98e1e45b07cb8144159b0b1f5f53b62327b7b714f`
- #28: `7b812f62-c406-4ca4-bd1d-3d08406debca` | 2026-07-20T08:02:52.727Z | STATE_CHANGE/context_rescoped | incident=`21408edf-1745-48be-a211-94365ed41d54` | lesson_key=`context-pack-rescope` | event_sha256=`6189c0f4b18a41ddcd3dc54cd4ad6fd1ddf1b3cfb713168a6ad133bde1cd9587`
- #29: `264b965a-1e1a-4671-b8bc-6a087b4a3f57` | 2026-07-20T08:18:00.000Z | GATE/exact_commit_full_gate_passed | incident=`3a77f9cd-76be-47a5-8aa4-bd29c308c1ac` | lesson_key=`exact-commit-full-gate` | event_sha256=`9dcd8d1aadf784a0e16b0e89aff560cef18ed29079a9459eb5372cf604db75e2`
