# Retrospective — v1-8-8-planner-evaluation-quality

## Goal

# v1.8.8 planner evaluation and quality closeout objective  ## Objective  Add a declaration-derived natural-language planner evaluation system that measures ordinary prompts without turning a fixed prompt corpus into product logic. Cover normal, ambiguous, missing-input, false-causal, and prompt- injection cases; score typed operation choice, bindings, options, refusal reasons, and invented identities. Keep deterministic structural checks in CI and run stochastic provider benchmarks as a separate release gate with an overall correctness threshold of 95% and a dangerous-request safe-refusal threshold of 100%.  Close three adjacent v1.8.8 quality gaps in the same source tree:  - add a convergent Hurdle negative-binomial generic-workflow fixture while   retaining the existing non-convergence safety fixture; - replace P7 family-internal operation branches with declaration-keyed handler   maps without adding orchestrator dispatch; - remove Workbench-owned React \`act(...)\`, dependency-deprecation, and   avoidable statistical numerical warnings, while classifying rather than   suppressing warnings owned by third-party libraries or intentionally   degenerate safety fixtures.  ## Boundaries  - Evaluation cases and expected identities derive from live declarations. - Prompt variants are data for evaluation only and never enter production   routing, keyword rules, or hard-coded model selection. - Hidden/holdout variants must differ from public examples and must not be read   by the planner under evaluation. - Provider output is admitted only through the existing typed planner and   contract boundaries; the evaluator does not repair malformed output. - No warning is globally ignored. Statistical warnings are either converted   into explicit typed evidence/rejection or retained with a documented owner. - Do not weaken P0/P1/P2/P3 contracts, user confirmation, provenance, or   fail-closed behavior. - No external witness provider, push, PR, merge, tag, or release.  ## Acceptance  - A registry mutation automatically changes the planner-evaluation denominator   and generated case inventory without editing a second ID list. - Every live reachable capability receives all five scenario classes, with   holdout variation and leakage checks. - The deterministic evaluator rejects wrong operations, malformed bindings or   options, unsafe causal claims, unsafe injection compliance, and invented   run/node/artifact IDs. - The provider benchmark reports per-capability and per-scenario results,   confidence intervals, exact provider/model/configuration, immutable input and   output digests, and exits nonzero below the approved thresholds. - Browser confirmation remains limited to representative high-risk paths. - Hurdle negative-binomial has both one successful persisted generic workflow   outcome and one explicit non-convergence outcome. - P7 handler maps are declaration-derived and mutation-proven; unknown IDs fail   closed and no orchestrator dispatch file changes. - Workbench-owned warnings targeted by this line are absent from focused tests;   remaining upstream or intentional warnings are explicitly inventoried. - Focused backend/frontend tests, typecheck, formal verification, 64-operation   batch execution, and the host full gate pass on the final source commit.

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 4/38 (10.5%; 10.5 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/2)

## All failures

- None recorded.

## All errors

- #15 2026-08-13T12:19:12.000Z `planner_evaluator_name_error`; cause_status: `known`; cause: The tightened per-step schema scorer referenced spec_index before the loop introduced it.; resolution: `resolved`; lesson: Run the focused regression immediately after introducing an indexed validation loop and keep the loop index in the loop declaration.
- #16 2026-08-13T12:19:48.000Z `benchmark_fixture_schema_mismatch`; cause_status: `known`; cause: The benchmark test helper still emitted the old model.genesis column-bindings shape after the scorer began enforcing each live workflow step schema.; resolution: `resolved`; lesson: Test providers must construct candidates from the same workflow declaration shape used by the scorer.
- #35 2026-08-13T13:30:34.000Z `formal_event_schema_mismatch`; cause_status: `known`; cause: The first attempt to append the final gate evidence used an unsupported cause_status value and was rejected before the event log changed.; resolution: `resolved`; lesson: Validate event enum values from the repository schema before preparing formal evidence files.

## All gaps

- #38 2026-08-13T13:30:34.000Z `real_provider_benchmark_unverified`; cause_status: `known`; cause: The planner benchmark was intentionally run in preview mode and did not call an LLM provider; no external provider was added to the local Workbench scope.; resolution: `open`; lesson: A declaration-derived preview proves coverage and scorer behavior, not LLM planning quality; a future provider-backed run must be separately approved and recorded.

## All waste

- #2 2026-08-13T11:09:21.000Z `repository_python_environment_not_applied`; cause_status: `known`; cause: A read-only devline CLI help command used bare python3 instead of the repository interpreter and then a checksum command inherited an unsupported locale.; resolution: `resolved`; lesson: Run repository Python through the linked virtual environment with PYTHONPATH set, and use a locale-independent SHA-256 command for formal evidence.
- #18 2026-08-13T12:29:31.000Z `p7_runner_required_flag_missed`; cause_status: `known`; cause: The first manual P7 batch init probe omitted the required refill-per-second CLI argument.; resolution: `resolved`; lesson: Read the runner subcommand help and supply every required rate-policy argument before starting a temporary acceptance run.

## Root causes and solutions

- `fixture-follows-live-step-schema`: occurrences=1; cause_status: `known`; root cause: The benchmark test helper still emitted the old model.genesis column-bindings shape after the scorer began enforcing each live workflow step schema.; solution: `resolved`
- `formal-event-schema-validation`: occurrences=1; cause_status: `known`; root cause: The first attempt to append the final gate evidence used an unsupported cause_status value and was rejected before the event log changed.; solution: `resolved`
- `indexed-validation-regression`: occurrences=1; cause_status: `known`; root cause: The tightened per-step schema scorer referenced spec_index before the loop introduced it.; solution: `resolved`
- `provider-backed-planner-benchmark`: occurrences=1; cause_status: `known`; root cause: The planner benchmark was intentionally run in preview mode and did not call an LLM provider; no external provider was added to the local Workbench scope.; solution: `open`
- `repository-python-and-locale-command-boundary`: occurrences=1; cause_status: `known`; root cause: A read-only devline CLI help command used bare python3 instead of the repository interpreter and then a checksum command inherited an unsupported locale.; solution: `resolved`
- `runner-required-arguments`: occurrences=1; cause_status: `known`; root cause: The first manual P7 batch init probe omitted the required refill-per-second CLI argument.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `fixture-follows-live-step-schema`: line experience occurrence(s)=1
- `formal-event-schema-validation`: line experience occurrence(s)=1
- `indexed-validation-regression`: line experience occurrence(s)=1
- `provider-backed-planner-benchmark`: line experience occurrence(s)=1
- `repository-python-and-locale-command-boundary`: line experience occurrence(s)=1
- `runner-required-arguments`: line experience occurrence(s)=1

## Future guidance

- A declaration-derived preview proves coverage and scorer behavior, not LLM planning quality; a future provider-backed run must be separately approved and recorded.
- A mutation counts only when the test behavior changes; every probe asserted an anchor, a changed digest, a real red or warning, and source restoration.
- Keep warning ownership explicit and require a typed numerical contract before changing or suppressing a warning.
- Read the runner subcommand help and supply every required rate-policy argument before starting a temporary acceptance run.
- Run repository Python through the linked virtual environment with PYTHONPATH set, and use a locale-independent SHA-256 command for formal evidence.
- Run the focused regression immediately after introducing an indexed validation loop and keep the loop index in the loop declaration.
- Test providers must construct candidates from the same workflow declaration shape used by the scorer.
- Validate event enum values from the repository schema before preparing formal evidence files.

## Event index

- #1: `d933a7b2-1906-4434-98be-921f72615861` | 2026-08-13T11:05:37.685Z | STATE_CHANGE/line_started | incident=`bb0ada79-42a0-4a3a-bd94-9a1c489a2adb` | lesson_key=`frozen-context-before-start` | event_sha256=`c670a0620be05077ea74370f2b861b824f9653651f906f06f8ce4ad3ddd9f7ac`
- #2: `d978a68f-ad1b-43db-93fb-4abbf8b192e2` | 2026-08-13T11:09:21.000Z | WASTE/repository_python_environment_not_applied | incident=`320a2850-0bf3-4bc5-aad7-6349afe0b8ea` | lesson_key=`repository-python-and-locale-command-boundary` | event_sha256=`d2966cba2cff90b7c0677f367b788620af12c6ef5d0014c0dc441a2677f6acb7`
- #3: `b551103d-91ff-4fc7-bfa3-1210ab3272b5` | 2026-08-13T11:32:33.132Z | STATE_CHANGE/context_rescope_required | incident=`dcdaa3ab-66b7-4eee-a8ec-964cd6ca55fe` | lesson_key=`context-pack-rescope` | event_sha256=`69e336dad49cf4a4eb3a424e02bcebc28abea1c89cbc2a969813c4e5779d5ced`
- #4: `26fbeec3-ac0e-4a0d-bfad-a354c8fa8fb7` | 2026-08-13T11:32:33.135Z | STATE_CHANGE/context_rescoped | incident=`48915b3b-9177-47de-950b-7344f928eed1` | lesson_key=`context-pack-rescope` | event_sha256=`60c7c2a0d254365b912bf73591a43c503263fdad3bcdbec38c723aae7285e8e9`
- #5: `91606b4c-6eb0-4f49-8c6c-b36408c44e02` | 2026-08-13T11:32:57.790Z | STATE_CHANGE/context_rescope_required | incident=`c578c957-ac5c-4aee-a483-26d6d6e40bef` | lesson_key=`context-pack-rescope` | event_sha256=`103e63ca8fcb0109ae5aa85ab7c3606a31fef0df2f479f00d42ac58cd3c27d5d`
- #6: `201596e0-abbb-4382-8c23-c4bf819f2aef` | 2026-08-13T11:32:57.794Z | STATE_CHANGE/context_rescoped | incident=`5b946ae3-1d23-48c8-8333-1eb2b221d49d` | lesson_key=`context-pack-rescope` | event_sha256=`ecd1a00afc1594d5f9135142eb5aa0fd23b8be4bbeda063771314466e344a20e`
- #7: `868d1c70-3e21-4bce-9d4c-01494adc5ebb` | 2026-08-13T11:35:25.344Z | STATE_CHANGE/context_rescope_required | incident=`68e29441-66f5-458f-ad01-7498b7430c82` | lesson_key=`context-pack-rescope` | event_sha256=`63e4ddb8378fcb4476f7a8f6f1e64806feca84b1f94e0caa10cd281f0dd77641`
- #8: `ee86e006-18fb-4b8c-8edc-410aff18a5e5` | 2026-08-13T11:35:25.348Z | STATE_CHANGE/context_rescoped | incident=`a4a98adc-6ef6-4774-956b-c97b4ec59d4a` | lesson_key=`context-pack-rescope` | event_sha256=`97a6b8eab437bec893f14a34171bc5798204f1c185aa2e2a4dff4d6472898aa4`
- #9: `c3dd7b04-af93-4b81-af83-f1ceabb5204c` | 2026-08-13T11:47:58.170Z | STATE_CHANGE/context_rescope_required | incident=`a91fd226-daa1-49eb-9827-840015e5cdd2` | lesson_key=`context-pack-rescope` | event_sha256=`5e42b6fdcc251bab2b78a46b6254288df5ae250f1d1071ba853082048862efd1`
- #10: `5a0e0674-c36a-4362-9d1d-d3b4188c31f5` | 2026-08-13T11:47:58.176Z | STATE_CHANGE/context_rescoped | incident=`d96e4837-ac1a-4c7a-a96a-29c1d703b000` | lesson_key=`context-pack-rescope` | event_sha256=`c2e5bda1f38863de0ae5243ffefde82b21367baa902f0fed5b61452240c5ebab`
- #11: `6ec9afed-9321-4bdf-9983-7708c534c586` | 2026-08-13T11:51:44.657Z | STATE_CHANGE/context_rescope_required | incident=`fc9f2e7e-7843-45cc-a07c-41561de698b1` | lesson_key=`context-pack-rescope` | event_sha256=`1b78a483c88ec2ddb044e11c1b9596a958968e5a80f3c33499f6d4ae63e7a761`
- #12: `693ce10a-d3d5-4924-989b-46238226533a` | 2026-08-13T11:51:44.664Z | STATE_CHANGE/context_rescoped | incident=`1a1bc52b-c761-412d-b896-497480864c9e` | lesson_key=`context-pack-rescope` | event_sha256=`277473a920ffa727b4d74f38467d4dee06a141ffcb9c905fb1ee2705885c924b`
- #13: `063cd02a-9e72-463d-9385-35b80fc481cc` | 2026-08-13T11:55:14.539Z | STATE_CHANGE/context_rescope_required | incident=`d8d2d6bf-0f5f-42a8-af90-38937f411c1e` | lesson_key=`context-pack-rescope` | event_sha256=`6e5ef85bb84855e51dbf07e47a006d5f64548c275fab3c19aa501a6ef5d5471e`
- #14: `04dc6ec3-50d1-4bc9-b9ba-1cd37a914257` | 2026-08-13T11:55:14.547Z | STATE_CHANGE/context_rescoped | incident=`87fdf03d-f392-40d7-8ead-1938070060f0` | lesson_key=`context-pack-rescope` | event_sha256=`825379a365ea9d9b0145716e6b22232887bcc9ab7877c3afb96c670d88a698c5`
- #15: `a4b6c8d0-1234-4abc-8def-1234567890ab` | 2026-08-13T12:19:12.000Z | ERROR/planner_evaluator_name_error | incident=`b5c7d9e1-2345-4bcd-8efa-2345678901bc` | lesson_key=`indexed-validation-regression` | event_sha256=`bf42de3e3a65f19069adc399147a678e3a706daf0540645f5d3d3aa0d2607eff`
- #16: `c6d8e0f2-3456-4cde-8fab-3456789012cd` | 2026-08-13T12:19:48.000Z | ERROR/benchmark_fixture_schema_mismatch | incident=`d7e9f1a3-4567-4def-9abc-4567890123de` | lesson_key=`fixture-follows-live-step-schema` | event_sha256=`968457d4a9c5bda8a691bcee56b0cb299722e4ded09d68f5ef5f6302cbd7fecb`
- #17: `e8f0a2b4-5678-4efa-abcd-5678901234ef` | 2026-08-13T12:29:31.000Z | REVIEW/behavior_mutation_proof | incident=`f9a1b3c5-6789-4fab-bcde-6789012345f0` | lesson_key=`behavior-changing-mutation-proof` | event_sha256=`3c543c464ef8302d82fc6f46791c8745165993ec9203b9e6827bdd4511942dd5`
- #18: `0a2c4e6f-7890-4abc-def1-7890123456a1` | 2026-08-13T12:29:31.000Z | WASTE/p7_runner_required_flag_missed | incident=`1b3d5f7a-8901-4bcd-ef12-8901234567b2` | lesson_key=`runner-required-arguments` | event_sha256=`fb2b1d5c8f28af79f3be94aef39917f4f4221b070827b508b0fb2ebb66d4b3a5`
- #19: `4d61c691-47c6-4f68-ba5c-501e9f61a003` | 2026-08-13T12:47:17.771Z | STATE_CHANGE/context_rescope_required | incident=`7bf2ed45-d2a3-4291-bc12-07e1098953fe` | lesson_key=`context-pack-rescope` | event_sha256=`6045a310c342459a298f0eb2b6d6534ff65272e31ad2a600d80b6cf99c70b918`
- #20: `6a84f7f3-f856-4c96-a05e-79a2080f3955` | 2026-08-13T12:47:17.781Z | STATE_CHANGE/context_rescoped | incident=`bbea761d-4d01-4cf9-accb-78ef72e9ce94` | lesson_key=`context-pack-rescope` | event_sha256=`2f5702f9a5f1eb351ea75fbcd8e50aec0487c5ea549f197f69f145e513115b67`
- #21: `46390c32-f202-4c88-a804-150ad9a9fd95` | 2026-08-13T12:48:36.648Z | STATE_CHANGE/context_rescope_required | incident=`6a2ed74c-2615-4370-849e-1d68fc3de1ac` | lesson_key=`context-pack-rescope` | event_sha256=`b65121ff7784e99412595df623dfc2156a1c5d673ef1639cb30e0c37a10eccb5`
- #22: `7dd46a2e-8bc7-4b52-ab5a-3af9c45de4c9` | 2026-08-13T12:48:36.658Z | STATE_CHANGE/context_rescoped | incident=`614e6aed-e0c8-48ea-9dd5-24cc3fffdd54` | lesson_key=`context-pack-rescope` | event_sha256=`a127c160788f81f3f9ebaba2f84ed98456371f4be41f4c6f57ca179f5fef1382`
- #23: `511af930-69db-4bf2-aa6f-75bb58ce8968` | 2026-08-13T12:50:18.419Z | STATE_CHANGE/context_rescope_required | incident=`3a0e73a1-c28b-4c78-8371-f3046dcaf6fd` | lesson_key=`context-pack-rescope` | event_sha256=`6d9850561fc5331eacee02f0417604e7238b1edb432eb3140fc9bc102d96bdcf`
- #24: `025b1db8-f547-401e-b255-6192eb23af4a` | 2026-08-13T12:50:18.431Z | STATE_CHANGE/context_rescoped | incident=`887eff89-6739-4ec6-97c2-4e1aa40b4eb2` | lesson_key=`context-pack-rescope` | event_sha256=`f1b9c3041610bb1b2b1f968c22ed5cad8009f296890dec72f8725ecfa1e00145`
- #25: `c68a8a57-c66d-427c-a2ca-24d6116f2cbd` | 2026-08-13T12:51:23.646Z | STATE_CHANGE/context_rescope_required | incident=`1f97ff29-03e3-4765-b233-ba606b709862` | lesson_key=`context-pack-rescope` | event_sha256=`eb27fb1b4bb75f829a0ab12265819acf8c7deabb8cc2e04f1828c901a9353c21`
- #26: `c04b0b91-fbf6-47df-81f2-1daee6f86b05` | 2026-08-13T12:51:23.659Z | STATE_CHANGE/context_rescoped | incident=`5c720c00-fa67-4d3e-bdd4-5be0b5653a47` | lesson_key=`context-pack-rescope` | event_sha256=`c1cd07ff72b38c1352b04f1234b496b6a619a77dfd849c2dda1c03eeefde96c6`
- #27: `dbd51874-b9ee-4cad-9c09-f2e662398a68` | 2026-08-13T12:52:25.625Z | STATE_CHANGE/context_rescope_required | incident=`8ec9ef7e-1cae-4636-bd33-894fe1477719` | lesson_key=`context-pack-rescope` | event_sha256=`da0b5a459a2f0efd227babbe44b00db9da32080ecf5c81843cefa68244206bc3`
- #28: `3069c1ba-cf9f-47bd-979a-83d3311e19b2` | 2026-08-13T12:52:25.639Z | STATE_CHANGE/context_rescoped | incident=`d348739e-7a77-42f2-b0c8-590a8c4abeba` | lesson_key=`context-pack-rescope` | event_sha256=`fd274d3fe517e2d0c69b71900f71881f311cb0948df9ab9a7e3943295e20b440`
- #29: `d743b072-db56-41a7-aca9-cf0f667dd96d` | 2026-08-13T12:52:44.149Z | STATE_CHANGE/context_rescope_required | incident=`b6355e7c-89c6-4150-8829-59ae25246945` | lesson_key=`context-pack-rescope` | event_sha256=`0ce13778997f3cae39fe22bbfc39b64be6b734fdc1b8a325c200dc843cbc0c87`
- #30: `08fd2af9-dc6c-49da-b244-c8ac2dc9a92f` | 2026-08-13T12:52:44.165Z | STATE_CHANGE/context_rescoped | incident=`7636d360-aca6-4d25-9c9b-52dfe68f9146` | lesson_key=`context-pack-rescope` | event_sha256=`43fa3a491bccf98cfcc7e57566063662d26010804a9a3ce46d0638cd69e4d7d1`
- #31: `fef7ea51-e640-4de2-af80-82bb63e9e065` | 2026-08-13T13:07:55.800Z | STATE_CHANGE/context_rescope_required | incident=`0a4c8037-8eaf-4709-a597-058aa2527ecd` | lesson_key=`context-pack-rescope` | event_sha256=`9c1d1555d583af6ce4f8d8e5eb6f095319f8276f871b256387ea90c4375058ea`
- #32: `487f0684-9ccf-4c3c-8355-89dfad8fa0d2` | 2026-08-13T13:07:55.817Z | STATE_CHANGE/context_rescoped | incident=`7984d3fa-aa0d-4ca9-b155-28090bcf4cb5` | lesson_key=`context-pack-rescope` | event_sha256=`158c690e5155f7bea3cef4bf7ac162ed6913e771ab82d0a6844a75ce61099c78`
- #33: `32572a7b-a376-4592-9544-1ce0c4d7424a` | 2026-08-13T13:08:49.841Z | STATE_CHANGE/context_rescope_required | incident=`a63d364c-1326-43d1-8a55-a52a0435e30f` | lesson_key=`context-pack-rescope` | event_sha256=`2c3c53540571f6cb8bb5503a3d05300f62fd4c5aab6d73cede1255fd206a4db7`
- #34: `b3e6fd98-56a6-4e69-b59b-360efce63727` | 2026-08-13T13:08:49.859Z | STATE_CHANGE/context_rescoped | incident=`597afb29-80b0-425c-bbfb-54f2051de979` | lesson_key=`context-pack-rescope` | event_sha256=`64abe72e7f451b57a1dfab0d5cc1c7ea47252d68c7fabe0bf36530473971c430`
- #35: `7b3e9c1a-5d2f-4a80-b6e1-9f4c2d7a8035` | 2026-08-13T13:30:34.000Z | ERROR/formal_event_schema_mismatch | incident=`5c1e8a4b-7d2f-49a0-b6e3-1f4c8d7a9025` | lesson_key=`formal-event-schema-validation` | event_sha256=`9d7dcb6f5a8e25f34ce73043cb7a667cce66fc3a79588151b7f0064b2c72d659`
- #36: `9f2c8f7e-2b08-4b79-a1b9-2f1c1c7b8a01` | 2026-08-13T13:30:34.000Z | GATE/host_full_gate | incident=`4a0b5c8e-7f2a-4c6b-91d3-8e5f7a2b6c10` | lesson_key=`final-host-full-gate` | event_sha256=`0361a38841990801b399cf4f00b435a2b62cbec5e4f8e03a0c545c7ff7fd8956`
- #37: `2d7e9a41-6c3b-4f80-b5a2-1e8d4c7f9023` | 2026-08-13T13:30:34.000Z | REVIEW/warning_boundary_classification | incident=`8c1f6e3a-5b7d-4a90-9e2c-7f4b1d6a8035` | lesson_key=`warning-boundary-classification` | event_sha256=`30800e59a5d2b565a71f9f15b433af694952f9a48cbd2391826101c33b1b7e0c`
- #38: `6a4f1c8e-9b2d-47f0-a531-7e3c8d2b9046` | 2026-08-13T13:30:34.000Z | GAP/real_provider_benchmark_unverified | incident=`1e7c4a9b-3d8f-50a2-b6e1-9c4f7d2a8053` | lesson_key=`provider-backed-planner-benchmark` | event_sha256=`a0bc487dceb177787d6851ff168feb8764b6a1ee0a06d220838f5f1cbccf8645`
