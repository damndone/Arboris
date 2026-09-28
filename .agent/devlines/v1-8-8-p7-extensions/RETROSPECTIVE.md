# Retrospective — v1-8-8-p7-extensions

## Goal

# v1.8.8 P7 extensions objective  Implement standalone, modular clustering, discriminant, and time-series statistical kernels in the existing P7 multivariate worktree. The kernels must be deterministic where a seed is declared, fail closed on unsafe numeric input, expose explicit policies and provenance, produce bounded JSON-safe evidence, and remain disconnected from Claude's Agent/P0/P1/P2 files until the later integration wave.

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 14/68 (20.6%; 20.6 per 100 events)
- Repeat rate: 0/14 (0.0%)
- Recurrence rate: 0/14 (0.0%)
- MTTR: median=0 ms (sample=13; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/13 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/2)

## All failures

- #41 2026-08-08T02:50:51.000Z `tdd_red_tests`; cause_status: `known`; cause: The corrected MI and Rubin contracts intentionally fail before production implementation.; resolution: `open`; lesson: Keep the corrected statistical and lineage contract red until production behavior satisfies it.
- #43 2026-08-08T05:39:37.000Z `tdd_red_missing_data_pack`; cause_status: `known`; cause: The missingness and Rubin contracts were intentionally red before production implementation.; resolution: `resolved`; lesson: Keep the descriptive missingness and Rubin statistical contracts red until the production pack owns their validation and numerical semantics.
- #45 2026-08-08T06:10:00.000Z `tdd_red_resampling`; cause_status: `known`; cause: The new Bootstrap, permutation, and resampling envelope tests were intentionally added before their production modules.; resolution: `resolved`; lesson: Keep each resampling consumer red until its typed strategy, adapter, combiner, and safety boundary exist.
- #46 2026-08-08T06:14:00.000Z `oracle_output_precision`; cause_status: `known`; cause: The first R Oracle assertion compared 1e-14 against R's default six-digit console rendering, so correct values were truncated before comparison.; resolution: `resolved`; lesson: External numerical Oracles must fix their serialization precision before applying tight equality tolerances.
- #48 2026-08-08T07:20:00.000Z `tdd_red_gmm`; cause_status: `known`; cause: The explicit GMM and weak-instrument contracts were added before their production pack existed.; resolution: `resolved`; lesson: Keep the GMM estimator and weak-instrument diagnostic boundary red until closed-form numerical semantics and fail-closed input validation exist.
- #53 2026-08-08T08:28:00.000Z `tdd_red_survey_adapter`; cause_status: `known`; cause: The new typed survey bridge was specified before its adapter module existed; the existing survey mathematics remained present but no new pack could consume it through the shared replicate boundary.; resolution: `resolved`; lesson: Add survey support at a typed adapter boundary so existing design mathematics can be reused without adding a family enumeration or editing the survey kernel.
- #59 2026-08-08T13:05:00.000Z `tdd_red_required_after_delegation_miss`; cause_status: `known`; cause: A delegated implementation attempt wrote production files before the required red test; the files were removed and the task was restarted test first.; resolution: `resolved`; lesson: For delegated coding, require a failing test artifact before accepting any production patch; when the order is violated, remove the patch and restart from the red test.

## All errors

- #5 2026-08-07T19:16:50.000Z `numeric_boundary`; cause_status: `known`; cause: statsmodels VECM returned a complex scalar with a zero imaginary part for log likelihood, which the strict JSON contract correctly rejected.; resolution: `resolved`; lesson: Keep numerical-library scalar normalization explicit and fail closed when a complex result is not numerically real.
- #6 2026-08-07T19:16:51.000Z `oracle_fixture`; cause_status: `known`; cause: The first CA oracle fixture had repeated singular values, so R and NumPy selected different valid bases for the same singular subspace.; resolution: `resolved`; lesson: External SVD oracles must avoid repeated singular values or compare invariant subspaces rather than arbitrary basis vectors.
- #34 2026-08-08T00:43:34.000Z `unsupported_fms_command`; cause_status: `known`; cause: An unsupported status subcommand was attempted during formal-line inspection; the CLI rejected it before touching the development line.; resolution: `resolved`; lesson: Use only the supported formal development-line commands and confirm command help before recording FMS evidence.
- #60 2026-08-08T13:06:00.000Z `formal_event_fixture_rejected`; cause_status: `known`; cause: The first temporary formal event fixture used a malformed UUID and was rejected before it could be appended; the fixture was corrected and the intended failure event was appended.; resolution: `resolved`; lesson: Validate UUIDs and event shape locally before invoking the formal append command.
- #63 2026-08-08T14:10:00.000Z `glm_oracle_estimand_assertion`; cause_status: `known`; cause: The first hurdle GLM Oracle assertion compared the product of marginal gate and truncated means with the observation-wise mean of their product, conflating two distinct predictive estimands.; resolution: `resolved`; lesson: Keep conditional and marginal predictive estimands separate; a scalar identity that looks plausible must not replace the observation-wise estimand.
- #64 2026-08-08T14:12:00.000Z `synthetic_control_oracle_fixture_gradient`; cause_status: `known`; cause: The first base-R Synthetic Control fixture passed grad=NULL to constrOptim, so the external Oracle failed before evaluating the constrained optimum.; resolution: `resolved`; lesson: A constrained external Oracle must test the numerical reference itself before it can validate the production estimator; fixture optimizer arguments are part of the evidence boundary.
- #65 2026-08-08T14:13:00.000Z `formal_event_fixture_lesson_key`; cause_status: `known`; cause: A temporary formal event fixture used an underscore in lesson_key, while the devline event schema accepts normalized hyphenated identifiers only; append was rejected before changing the event chain.; resolution: `resolved`; lesson: Validate event identifiers against the formal schema before invoking append; a rejected temporary fixture must be corrected without bypassing the controlled writer.

## All gaps

- None recorded.

## All waste

- #55 2026-08-08T09:12:00.000Z `gate_argument_quoting`; cause_status: `known`; cause: The first cross-pack pytest command placed the complete file list in one quoted shell variable expansion, so pytest received one nonexistent path instead of individual test arguments.; resolution: `resolved`; lesson: Keep bounded gate command paths as explicit arguments; a shell aggregation error must not be mistaken for a test result.
- #62 2026-08-08T13:45:00.000Z `parallel_pack_agents_timeout`; cause_status: `known`; cause: Five independently dispatched P7 pack agents remained running across repeated bounded waits and returned no code, tests, or RED evidence; they were closed to prevent an unbounded wait.; resolution: `resolved`; lesson: Use bounded subagent tasks with an explicit checkpoint and recover to smaller sequential slices when parallel workers remain running without verifiable artifacts.

## Root causes and solutions

- `bounded-subagent-recovery`: occurrences=1; cause_status: `known`; root cause: Five independently dispatched P7 pack agents remained running across repeated bounded waits and returned no code, tests, or RED evidence; they were closed to prevent an unbounded wait.; solution: `resolved`
- `formal-event-fixture-identifier`: occurrences=1; cause_status: `known`; root cause: A temporary formal event fixture used an underscore in lesson_key, while the devline event schema accepts normalized hyphenated identifiers only; append was rejected before changing the event chain.; solution: `resolved`
- `gate-argument-quoting`: occurrences=1; cause_status: `known`; root cause: The first cross-pack pytest command placed the complete file list in one quoted shell variable expansion, so pytest received one nonexistent path instead of individual test arguments.; solution: `resolved`
- `glm-estimand-layer-separation`: occurrences=1; cause_status: `known`; root cause: The first hurdle GLM Oracle assertion compared the product of marginal gate and truncated means with the observation-wise mean of their product, conflating two distinct predictive estimands.; solution: `resolved`
- `gmm-tdd-red`: occurrences=1; cause_status: `known`; root cause: The explicit GMM and weak-instrument contracts were added before their production pack existed.; solution: `resolved`
- `missing-data-tdd-red`: occurrences=1; cause_status: `known`; root cause: The missingness and Rubin contracts were intentionally red before production implementation.; solution: `resolved`
- `oracle-precision-binding`: occurrences=1; cause_status: `known`; root cause: The first R Oracle assertion compared 1e-14 against R's default six-digit console rendering, so correct values were truncated before comparison.; solution: `resolved`
- `oracle-singular-subspace`: occurrences=1; cause_status: `known`; root cause: The first CA oracle fixture had repeated singular values, so R and NumPy selected different valid bases for the same singular subspace.; solution: `resolved`
- `resampling-tdd-red`: occurrences=1; cause_status: `known`; root cause: The new Bootstrap, permutation, and resampling envelope tests were intentionally added before their production modules.; solution: `resolved`
- `survey-adapter-tdd-red`: occurrences=1; cause_status: `known`; root cause: The new typed survey bridge was specified before its adapter module existed; the existing survey mathematics remained present but no new pack could consume it through the shared replicate boundary.; solution: `resolved`
- `synthetic-control-oracle-fixture`: occurrences=1; cause_status: `known`; root cause: The first base-R Synthetic Control fixture passed grad=NULL to constrOptim, so the external Oracle failed before evaluating the constrained optimum.; solution: `resolved`
- `tdd-red-before-production`: occurrences=1; cause_status: `known`; root cause: A delegated implementation attempt wrote production files before the required red test; the files were removed and the task was restarted test first.; solution: `resolved`
- `tdd-red-contract`: occurrences=1; cause_status: `known`; root cause: The corrected MI and Rubin contracts intentionally fail before production implementation.; solution: `open`
- `time-series-json-boundary`: occurrences=1; cause_status: `known`; root cause: statsmodels VECM returned a complex scalar with a zero imaginary part for log likelihood, which the strict JSON contract correctly rejected.; solution: `resolved`
- `use-supported-fms-command`: occurrences=1; cause_status: `known`; root cause: An unsupported status subcommand was attempted during formal-line inspection; the CLI rejected it before touching the development line.; solution: `resolved`
- `validate-event-fixtures`: occurrences=1; cause_status: `known`; root cause: The first temporary formal event fixture used a malformed UUID and was rejected before it could be appended; the fixture was corrected and the intended failure event was appended.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `bounded-subagent-recovery`: line experience occurrence(s)=1
- `formal-event-fixture-identifier`: line experience occurrence(s)=1
- `gate-argument-quoting`: line experience occurrence(s)=1
- `glm-estimand-layer-separation`: line experience occurrence(s)=1
- `gmm-tdd-red`: line experience occurrence(s)=1
- `missing-data-tdd-red`: line experience occurrence(s)=1
- `oracle-precision-binding`: line experience occurrence(s)=1
- `oracle-singular-subspace`: line experience occurrence(s)=1
- `resampling-tdd-red`: line experience occurrence(s)=1
- `survey-adapter-tdd-red`: line experience occurrence(s)=1
- `synthetic-control-oracle-fixture`: line experience occurrence(s)=1
- `tdd-red-before-production`: line experience occurrence(s)=1
- `tdd-red-contract`: line experience occurrence(s)=1
- `time-series-json-boundary`: line experience occurrence(s)=1
- `use-supported-fms-command`: line experience occurrence(s)=1
- `validate-event-fixtures`: line experience occurrence(s)=1

## Future guidance

- A constrained external Oracle must test the numerical reference itself before it can validate the production estimator; fixture optimizer arguments are part of the evidence boundary.
- A statistical kernel is ready for adoption only when its numerical output, estimand labels, unsupported extensions, and integration boundary are reviewed together.
- Add survey support at a typed adapter boundary so existing design mathematics can be reused without adding a family enumeration or editing the survey kernel.
- An external numerical Oracle must validate its own degrees-of-freedom algebra and serialization precision; library tail limits must be treated as a correctness boundary, not a harmless approximation.
- External SVD oracles must avoid repeated singular values or compare invariant subspaces rather than arbitrary basis vectors.
- External numerical Oracles must fix their serialization precision before applying tight equality tolerances.
- For delegated coding, require a failing test artifact before accepting any production patch; when the order is violated, remove the patch and restart from the red test.
- Keep bounded gate command paths as explicit arguments; a shell aggregation error must not be mistaken for a test result.
- Keep conditional and marginal predictive estimands separate; a scalar identity that looks plausible must not replace the observation-wise estimand.
- Keep each resampling consumer red until its typed strategy, adapter, combiner, and safety boundary exist.
- Keep numerical-library scalar normalization explicit and fail closed when a complex result is not numerically real.
- Keep statistical kernels modular and evidence-bearing, and require an independent numerical Oracle before exposing them to higher workflow layers.
- Keep the GMM estimator and weak-instrument diagnostic boundary red until closed-form numerical semantics and fail-closed input validation exist.
- Keep the corrected statistical and lineage contract red until production behavior satisfies it.
- Keep the descriptive missingness and Rubin statistical contracts red until the production pack owns their validation and numerical semantics.
- Numerical Oracles must compare like-for-like estimators; optimizer output is not a valid reference for a closed-form one-step GMM implementation.
- Represent P7 applicability and limitations as a bounded typed contract, and test both unsafe path/code shapes and safe statistical prose before pack implementation.
- Require independent numerical Oracles and a second quality review before exposing a statistical kernel to higher workflow layers.
- Use bounded subagent tasks with an explicit checkpoint and recover to smaller sequential slices when parallel workers remain running without verifiable artifacts.
- Use only the supported formal development-line commands and confirm command help before recording FMS evidence.
- Validate UUIDs and event shape locally before invoking the formal append command.
- Validate event identifiers against the formal schema before invoking append; a rejected temporary fixture must be corrected without bypassing the controlled writer.

## Event index

- #1: `149c820a-0eca-4b8b-a81a-9a57f7983aee` | 2026-08-07T18:04:33.086Z | STATE_CHANGE/line_started | incident=`81213bee-d606-4c26-9844-15613c2880bf` | lesson_key=`frozen-context-before-start` | event_sha256=`45b197bf437a60bd44de951051b7643d90c69caba414259450072c87b224c44d`
- #2: `92412d39-053c-463b-bce5-0d55f7891e26` | 2026-08-07T18:05:35.072Z | STATE_CHANGE/context_rescope_required | incident=`93508acf-96c7-46ab-9cda-10daa173dbcb` | lesson_key=`context-pack-rescope` | event_sha256=`aa40f3295fe9ac333a3afc30bf38a8bbcebe0c847085629f0bc70e88a646c4f7`
- #3: `6fb01257-63da-4f89-8f02-5e06939271e1` | 2026-08-07T18:05:35.076Z | STATE_CHANGE/context_rescoped | incident=`df7b5b1a-828e-45ee-8285-5f956fe08343` | lesson_key=`context-pack-rescope` | event_sha256=`e5a0152be8819bd24fa379791217266c7b2bf295893f660dc5533260bfc72068`
- #4: `e28f4d36-27cc-48c1-9da6-97a8ed7bd6b6` | 2026-08-07T18:25:58.000Z | GATE/targeted_tests | incident=`86d4a3f3-fd6d-46ab-9e6a-3d0f8e95b267` | lesson_key=`p7-extensions-gate` | event_sha256=`01654c675e72be54e364a1329f381389f1096b7058c3e87207218a33cd6f2b84`
- #5: `4a668ac1-f036-49ec-bc69-64bebc10b22b` | 2026-08-07T19:16:50.000Z | ERROR/numeric_boundary | incident=`c9d57698-c3ef-4b7c-8fa6-75fb1ff4d6aa` | lesson_key=`time-series-json-boundary` | event_sha256=`838c9b371404f60b76d8f3d1bd771c8064974f0c106240d1551e1c4d4875fc0f`
- #6: `d15d7b18-6899-4d29-9d3a-71a1f879eb0b` | 2026-08-07T19:16:51.000Z | ERROR/oracle_fixture | incident=`9a8d7a25-eaad-4c94-8cb9-4a716222135b` | lesson_key=`oracle-singular-subspace` | event_sha256=`04159928d1aef967f68cbf33af334cba301aad5b7c7784c99a060b81f0705a18`
- #7: `6c08a9ab-74fd-4c3f-b4c7-e94c83c9fb0e` | 2026-08-07T19:17:53.000Z | GATE/phase2_targeted_tests | incident=`b21ca952-2bd5-4617-8f2e-6bc4d1bd2275` | lesson_key=`p7-phase2-gate` | event_sha256=`5d8bf6900e8cd699c69dd27e2965bf4308085ae161041ce161087a0b36c36a57`
- #8: `d07e0615-519d-45ac-b3f5-d39eb383a079` | 2026-08-07T20:31:46.215Z | STATE_CHANGE/context_rescope_required | incident=`2bd2f7fc-53e8-4f41-857e-1769a8aba102` | lesson_key=`context-pack-rescope` | event_sha256=`7b4ab571b78c818d0d231f081114573edd3ad46d1af037e5a4b1b0604d23d447`
- #9: `005e010b-7ed0-44c3-b689-cd133325187a` | 2026-08-07T20:31:46.221Z | STATE_CHANGE/context_rescoped | incident=`12653746-8ec2-45f7-b9c6-7b01a2a777b1` | lesson_key=`context-pack-rescope` | event_sha256=`4d903581fbb8a11ee702319c65263ed961df0e370f1f2a674be4e5b682425a4b`
- #10: `77bc5ad7-fef2-493f-b5e9-6007fc3fe808` | 2026-08-07T20:31:46.344Z | STATE_CHANGE/context_rescope_required | incident=`d98c6590-10a5-4be2-9ece-69ab63df1e5e` | lesson_key=`context-pack-rescope` | event_sha256=`d3f86de653028d2ef284fc807cba742b5647f5e4d849029f9dbf9c47b4e22d95`
- #11: `8c3ef896-b169-4b25-936b-221055ea3b8c` | 2026-08-07T20:31:46.350Z | STATE_CHANGE/context_rescoped | incident=`10c2c87b-137c-4840-8d58-bc6d45070ef8` | lesson_key=`context-pack-rescope` | event_sha256=`303d856c898b38ad78fe2931ef953068faf3233b19f35d86d8387130d5ad7d9c`
- #12: `eaace52d-eb80-4eb5-97cd-339a278e5560` | 2026-08-07T20:31:46.471Z | STATE_CHANGE/context_rescope_required | incident=`d9c8da0e-a7e2-46ed-ab1e-f58df33ce569` | lesson_key=`context-pack-rescope` | event_sha256=`36f75ca4ea3e65768f8db554ea2e65bc10fd22163451faf5135260766a92c71f`
- #13: `76a90ab9-e233-4a6d-b914-a4a64b445028` | 2026-08-07T20:31:46.477Z | STATE_CHANGE/context_rescoped | incident=`71ff4aaf-eb02-4d34-9d50-ba1683454fcb` | lesson_key=`context-pack-rescope` | event_sha256=`346571f4d606ade9b05ede565a9580c4a3598a32f392c9bc4a22d4a0fde24398`
- #14: `f451568f-0f31-4307-bf5b-d66eba97340b` | 2026-08-07T20:31:46.615Z | STATE_CHANGE/context_rescope_required | incident=`528fc38d-7574-4c4d-8942-ecfdfe6f9110` | lesson_key=`context-pack-rescope` | event_sha256=`e98f1097fc03019de0074b04c68977acb5630e1aa35654ab6cff28fc70d75c8d`
- #15: `c9fd4a71-78a4-41bc-b891-bcf2bae7037d` | 2026-08-07T20:31:46.622Z | STATE_CHANGE/context_rescoped | incident=`817158da-1b81-4c4d-b8dc-1be43533a650` | lesson_key=`context-pack-rescope` | event_sha256=`f726b01350dd0bef0bc10d9840aa570010d847af59d68c912627f3f27706b719`
- #16: `9186546d-ed81-4dfa-a0f2-5f168e08079a` | 2026-08-07T20:31:46.743Z | STATE_CHANGE/context_rescope_required | incident=`f47a3731-9262-4e6f-ad36-dd02445e8aaf` | lesson_key=`context-pack-rescope` | event_sha256=`d2300b9e5ff0aa2c054522ee065af51ba72820414121ad1125ab40d4898f942e`
- #17: `7b8e6f7f-2a24-4dcc-b324-ac2537168924` | 2026-08-07T20:31:46.751Z | STATE_CHANGE/context_rescoped | incident=`38bc2217-cca9-48d6-ada4-93ef67233314` | lesson_key=`context-pack-rescope` | event_sha256=`d1a6f371746cfa77638270ae0b641467c7fac0e7779e858330d40970881e43ee`
- #18: `c31f2146-3f34-456f-aed4-2fa8ae5a8da5` | 2026-08-07T20:31:46.873Z | STATE_CHANGE/context_rescope_required | incident=`127b5461-079e-4bde-a19e-2546e07d7fc7` | lesson_key=`context-pack-rescope` | event_sha256=`53f7a24b8766399deb9381476093f81da827346796262f3f41f8c681ec4ed36e`
- #19: `3ff15451-bd38-4668-8bea-ae1c2fb55547` | 2026-08-07T20:31:46.882Z | STATE_CHANGE/context_rescoped | incident=`18f83d5c-20a2-4aa3-8221-72fe143e9349` | lesson_key=`context-pack-rescope` | event_sha256=`26a2c1733ff1d67bf16b877ec915e3d3fc0ae952d972412f4418569a9f3cb575`
- #20: `5e9f605e-79a1-4ced-b709-c75f607e9cd8` | 2026-08-07T20:31:47.003Z | STATE_CHANGE/context_rescope_required | incident=`44c310f3-a3a2-4abe-aced-724c7eb0f519` | lesson_key=`context-pack-rescope` | event_sha256=`dd833a0e5aea0413d688d8abdad1b605b169133e9e1fe1096c2fab883c368801`
- #21: `412a965a-9e7a-43cd-9c15-cbf45b0d6484` | 2026-08-07T20:31:47.012Z | STATE_CHANGE/context_rescoped | incident=`342b6512-a25e-4c2d-9dfc-ddce3636328b` | lesson_key=`context-pack-rescope` | event_sha256=`cecb39abd2315e35b21ec150a4b1543c3067f5571c6fa159486dbce7cc37d249`
- #22: `d9ad2c66-b19f-4671-b3db-70a4c780b96c` | 2026-08-07T20:31:47.132Z | STATE_CHANGE/context_rescope_required | incident=`3ab15f22-3bc4-42bb-98c1-9b186f95bd43` | lesson_key=`context-pack-rescope` | event_sha256=`be32d4b841a2228e33d9a3b29aa7625c3b1c7db266d9e7973fe5bbbeba61b10f`
- #23: `1da3d925-c3ba-44f8-974f-29a0f3c71900` | 2026-08-07T20:31:47.141Z | STATE_CHANGE/context_rescoped | incident=`36bcf7c4-c303-47cd-89c5-a59b2951d700` | lesson_key=`context-pack-rescope` | event_sha256=`d3790b8530d1d66f69bbad3a49c8a09e99e3b83cb6f38ec1a8873e40af78de1c`
- #24: `dec470e2-d3b1-4c04-8d52-043bfbd33238` | 2026-08-07T20:31:47.263Z | STATE_CHANGE/context_rescope_required | incident=`188bdfdb-3b9d-4a47-b63c-4ec9fd48e0c5` | lesson_key=`context-pack-rescope` | event_sha256=`82c55f235ece773b6b97727c1afee8f1f3d0906e6605575d538f8f48891265b1`
- #25: `51c28a0b-f798-4e54-8e29-edf2a2c423d8` | 2026-08-07T20:31:47.274Z | STATE_CHANGE/context_rescoped | incident=`0901e576-2343-438c-90a2-c4d21af154dc` | lesson_key=`context-pack-rescope` | event_sha256=`614dbf972118811cbd056d65c5fc9179531cfc14d56a710c3876124a42d0493c`
- #26: `2fb516c0-e647-4f92-be89-849935139c7e` | 2026-08-07T20:31:47.396Z | STATE_CHANGE/context_rescope_required | incident=`f885fb20-926d-4ad1-90ec-cd20b6a43147` | lesson_key=`context-pack-rescope` | event_sha256=`28cdc874f57a360072d542806de52fd8ef3695136e27a1734181293a25db1fd2`
- #27: `8d71c192-6cb9-4731-b5b4-a2de4ba42416` | 2026-08-07T20:31:47.407Z | STATE_CHANGE/context_rescoped | incident=`3c49a5ab-cf2b-4373-afd2-427ac005d387` | lesson_key=`context-pack-rescope` | event_sha256=`37c6665b8468ddc9f99df9ef3567deba9c342c7b3bcdd790d08e1a90a2b79271`
- #28: `d8530ea1-70ec-4a39-a8a3-16356e4d4205` | 2026-08-07T20:55:25.566Z | STATE_CHANGE/context_rescope_required | incident=`2660c50f-f9a2-4683-aba9-efd85a31523f` | lesson_key=`context-pack-rescope` | event_sha256=`3a8ee9d5e9690aadcb4bc7a4366638189b600663f63a662ff0f244a04a5b733b`
- #29: `c026ed88-47a8-4f30-95eb-17a4cb0fe6a9` | 2026-08-07T20:55:25.579Z | STATE_CHANGE/context_rescoped | incident=`01819a5e-ed5b-4d1c-a193-6aaeb374902a` | lesson_key=`context-pack-rescope` | event_sha256=`91840ff6db834284e145e0207583839aa2417fa7ccbf22efade165054fbd12b4`
- #30: `6f3f3af9-2e13-4a9f-8f7f-0a9c9b5c11e1` | 2026-08-07T21:10:00.000Z | REVIEW/p7_manova_power_categorical_quality_accepted | incident=`8d19c0e6-5d6e-44e0-b8f7-89da2bce7e3c` | lesson_key=`oracle-before-agent-exposure` | event_sha256=`be92ee97a393a8700768972a49aa370999ca39e503cc4ea39f6a7ab1a73bbc29`
- #31: `c0bb4d46-8f78-458b-b064-74b6f3ec87d2` | 2026-08-07T21:11:00.000Z | GATE/p7_focused_integration_gate_passed | incident=`f09e4da7-8152-45d1-99cb-33f1b3d3ed22` | lesson_key=`separate-kernel-and-integration-gates` | event_sha256=`a561246c6b12b7d3b6f0c0bc16e06c2237528fbf7d682e8e401c1cea8ced23eb`
- #32: `994477e0-ed1a-450b-9429-eb8d031fdeb2` | 2026-08-07T22:35:05.055Z | STATE_CHANGE/context_rescope_required | incident=`9ab1790b-85cc-42db-b62d-a7b5ccdd32bc` | lesson_key=`context-pack-rescope` | event_sha256=`8bdfe07e7a2e0a0348d52209a8031cfe35e3618019bd8a37574d7bd6e2044755`
- #33: `aba39b84-aef8-4702-a39e-a6d21a865ce3` | 2026-08-07T22:35:05.071Z | STATE_CHANGE/context_rescoped | incident=`6bd436db-5bec-4f76-bf3f-8547289e176e` | lesson_key=`context-pack-rescope` | event_sha256=`abdd3075734ab269670fff9b2785aee34cb217d2e6de38a86e55f41c2a0b081d`
- #34: `E3111018-F6BC-4413-8F45-590C566249DF` | 2026-08-08T00:43:34.000Z | ERROR/unsupported_fms_command | incident=`02BC83A1-E0E0-4F81-8FC2-171E863303FC` | lesson_key=`use-supported-fms-command` | event_sha256=`781bf4fe76e695118d05b95576fcd037818ab6a0c05c4ca06f14df9c42b20be7`
- #35: `D965ADB7-5011-455A-909D-B97438CDF30E` | 2026-08-08T00:43:34.000Z | REVIEW/stage11_quality_approved | incident=`D965ADB7-5011-455A-909D-B97438CDF30E` | lesson_key=`oracle-before-agent-exposure` | event_sha256=`b1d4b1c17bfb3a6ed11c30bbdef7763b9dc6a413b41df8a6364f4bac6fd8f581`
- #36: `02BC83A1-E0E0-4F81-8FC2-171E863303FC` | 2026-08-08T00:43:34.000Z | GATE/stage11_final_gate | incident=`E3111018-F6BC-4413-8F45-590C566249DF` | lesson_key=`separate-kernel-and-integration-gates` | event_sha256=`0ac564d5c545b967aa698b642e830f8e70df22e149000ea884f2e7b01c6024dc`
- #37: `99063084-a65c-4241-8f38-64d7d4e47b2d` | 2026-08-08T01:54:54.294Z | STATE_CHANGE/context_rescope_required | incident=`ee0b09d3-961b-4592-8b18-a5ab91c9e5c3` | lesson_key=`context-pack-rescope` | event_sha256=`06a892c2a3953526a9197dbc58dffaa9fc46caf00e76553ccc825f16d3a1cfeb`
- #38: `0088f2be-80d0-44b0-8fe4-5aa384f733da` | 2026-08-08T01:54:54.318Z | STATE_CHANGE/context_rescoped | incident=`d6d1570c-7154-4cee-a6c3-ae8f1de4045c` | lesson_key=`context-pack-rescope` | event_sha256=`3f72abd983390e74f5aa9bc95443439bd01c2d98b17a72fc9aaeb940abddfe9a`
- #39: `f85b45a7-0d8c-4bad-8de8-d14a573453bc` | 2026-08-08T02:06:54.301Z | STATE_CHANGE/context_rescope_required | incident=`1af42983-7745-4a83-94ac-d21e21e53bcf` | lesson_key=`context-pack-rescope` | event_sha256=`6bfd0ce180e415cdf13c8dc64485206086a02b4847f1f0e0270a9141a6e1d6c2`
- #40: `b919ad52-31dc-4f93-b838-fe91e7a23b03` | 2026-08-08T02:06:54.326Z | STATE_CHANGE/context_rescoped | incident=`32d4ee35-11a8-456a-adb1-7fa1a65b5283` | lesson_key=`context-pack-rescope` | event_sha256=`18d76d7ffbd434d586b5a9ea55065277c0e53db424790f5c2785c1c74550195a`
- #41: `a4d1e1f4-b977-4b7e-92c2-51e21d5d6d80` | 2026-08-08T02:50:51.000Z | FAILURE/tdd_red_tests | incident=`e53a7e05-40f4-481c-a8e6-4c52a1c9c826` | lesson_key=`tdd-red-contract` | event_sha256=`8ca0fefe7c380f408320855de46d233c231e18bfee7424bc550c5810483e9d6b`
- #42: `d3b2f1cc-7b6b-4d28-9ca4-5a9d25bd0e4d` | 2026-08-08T05:30:56.000Z | GATE/replicate_combine_foundation | incident=`2a8b8cb9-865f-4d58-ae5e-7fa49f3e0db3` | lesson_key=`replicate-combine-boundary` | event_sha256=`e797c3f9f32da6f0639c07221d0e5342088f6d2075efe5b8128dd14873cabeae`
- #43: `e8bf2b84-37a1-40e0-a7aa-09dc462251e3` | 2026-08-08T05:39:37.000Z | FAILURE/tdd_red_missing_data_pack | incident=`a8f1387e-7873-4de8-bc2c-05db1a70956b` | lesson_key=`missing-data-tdd-red` | event_sha256=`6dd704a828bf4183cb2926d8b3a168afe93b87b80c8c755bd2a38a1747101115`
- #44: `d2f9aaf1-6a2f-4e1f-bd0f-78cf0a8f2e31` | 2026-08-08T06:18:00.000Z | GATE/mi_rubin_ols_verified | incident=`4f4ef2a2-b457-49f3-8a7b-0d45f0e1e7bc` | lesson_key=`mi-first-fit-leakage` | event_sha256=`3685a7de2db79ee62423f49d4e1b54669e36d2ec21df0be46b58b6c265e82381`
- #45: `2be31b95-fd4e-4f29-94a4-f80a2fb9b19c` | 2026-08-08T06:10:00.000Z | FAILURE/tdd_red_resampling | incident=`18ac1881-63aa-42c0-a717-927ac33f1cdd` | lesson_key=`resampling-tdd-red` | event_sha256=`afd276855f3a702e0b7adcaf2a4642fb9e84e2e8b52ee24498c72a0257d40203`
- #46: `a88acfa7-fb25-4c85-b5d0-0d4886a60a80` | 2026-08-08T06:14:00.000Z | FAILURE/oracle_output_precision | incident=`d70d4ccd-8d04-4a24-a74f-9dd5838bc88f` | lesson_key=`oracle-precision-binding` | event_sha256=`ad0f769d0e99d4b7fecf01183f3fd4c5b9ae91bb460558b33515ca2a55de0fef`
- #47: `9f856e6c-f2b2-44a9-92d1-a8e2a0af6125` | 2026-08-08T06:19:00.000Z | GATE/resampling_inference_verified | incident=`f83a33bb-fd8c-4e7c-bcbf-fc833cf45a36` | lesson_key=`resampling-shared-boundary` | event_sha256=`b15e791039879c15586193061e2cdf3c145db34bed5c00e4b4fca5391a111480`
- #48: `c1f42e58-8e46-4f75-a37e-cc24ef3f69e4` | 2026-08-08T07:20:00.000Z | FAILURE/tdd_red_gmm | incident=`e75bce9e-0a27-43e1-8a35-50fc43d5fe4d` | lesson_key=`gmm-tdd-red` | event_sha256=`502c1b816fd3a6438b221807d134033de3b655f65857adce2b8b468596eb78b2`
- #49: `8b66061c-5f17-4f41-b985-84bba57a9db6` | 2026-08-08T07:34:00.000Z | REVIEW/gmm_boundary_debug | incident=`2b832df2-8dc8-4c58-bf5c-0a7de239da8e` | lesson_key=`gmm-oracle-boundary` | event_sha256=`61f3e5f8638a26bcff36750fe0f4e3ec45bceaffdfaf56fa19d7b2844426be8e`
- #50: `bd6d729e-c5d4-46f3-aed8-a27402a4e8a3` | 2026-08-08T07:48:00.000Z | GATE/gmm_verified | incident=`3e5ad9d4-872e-4174-b872-37f1c195a100` | lesson_key=`gmm-shared-evidence-boundary` | event_sha256=`fd0b2dda2145f7672bfaa30ce3633aadf9c3733a9d15eb24b555ea97ed204eb7`
- #51: `5bcbdef0-934d-4d3a-b34a-7b4e6e52e8ca` | 2026-08-08T08:04:00.000Z | REVIEW/multiple_comparisons_oracle_debug | incident=`be4af25a-331f-4c42-90a7-3152f77678e2` | lesson_key=`posthoc-oracle-tail-boundary` | event_sha256=`e1a6dda60ecd60f383a07e3205ffdc77faa44871207b769dad4829d573fb1020`
- #52: `f2de2bb9-7278-45bf-8e0c-75a6e4e8c3dc` | 2026-08-08T08:12:00.000Z | GATE/multiple_comparisons_verified | incident=`2cdbf1ed-8728-4a72-812b-9b6d47edb9ac` | lesson_key=`posthoc-separate-combiners` | event_sha256=`3f265af8c7ee8dc10c827e79d808ff7718957616232d0c25c4e279b2d1b744eb`
- #53: `d9b099ef-7d89-49bd-b32b-0c7946c0a10e` | 2026-08-08T08:28:00.000Z | FAILURE/tdd_red_survey_adapter | incident=`4cfebfc0-66ba-4f7b-974a-a0b11f7e7f8f` | lesson_key=`survey-adapter-tdd-red` | event_sha256=`2587aa80b10d003ba131bd415b1ac1d034189f30d8fa1fbf425f7e9e8a7ad636`
- #54: `78f8d28d-f741-43e5-b7d0-76a51878e1a4` | 2026-08-08T08:46:00.000Z | GATE/survey_adapter_verified | incident=`bf71f1dd-cb34-48c2-92e1-50911e0b0df7` | lesson_key=`survey-typed-adapter-boundary` | event_sha256=`b4c9fe66b4324ab9f9395059336a45ba6101e8b2e9bfa1d61341f8555ab939a9`
- #55: `b6c5d75d-50ef-4d29-b2ea-1e61facb33d9` | 2026-08-08T09:12:00.000Z | WASTE/gate_argument_quoting | incident=`c66a8f79-e5d5-4ba9-b5a0-98e369df34ec` | lesson_key=`gate-argument-quoting` | event_sha256=`78aecc24ac538ba25968e2d69789d725a3870f11ab21201fd02d196de9dd0527`
- #56: `ab205c16-38d9-4f4c-80d3-bae0de5fd2c2` | 2026-08-08T09:26:00.000Z | GATE/p7_extensions_cross_pack_verified | incident=`de3a699f-b28c-492e-95bd-8b0fc8fe77d4` | lesson_key=`p7-cross-pack-closeout` | event_sha256=`d4d5fa240846fffb89769c6ceed65241f503d69c56c7e11c8d05b4854e253b81`
- #57: `c279c352-4c56-4b87-af02-c67bcad9943f` | 2026-08-08T12:40:38.625Z | STATE_CHANGE/context_rescope_required | incident=`d1f3ef5a-ef1a-4cf9-b903-4eb246d5fd5a` | lesson_key=`context-pack-rescope` | event_sha256=`23fe6a4f1e24e6d1ee123fb5ea1ea4bf16187a3c50f58f5b4fe52af3d4160f35`
- #58: `cb7aa4d0-ca59-4158-9f43-2a99e5847267` | 2026-08-08T12:40:38.663Z | STATE_CHANGE/context_rescoped | incident=`d1468abe-e369-4bb8-8651-8ef8bf264a3a` | lesson_key=`context-pack-rescope` | event_sha256=`8c3ebca12a6294bc3bbb191e554a6f7d1cb0134bfbac663b42c73350775bdb83`
- #59: `0a5d9fc5-9162-46d0-aee9-9f3aa2fb43fa` | 2026-08-08T13:05:00.000Z | FAILURE/tdd_red_required_after_delegation_miss | incident=`9a4f7b04-1c6d-4eab-82a8-6db4bfde7d19` | lesson_key=`tdd-red-before-production` | event_sha256=`93e26de49d4e770c5216ba871e7876b1f51ce4219e840eecd33ebb2939316490`
- #60: `3f38f3e2-f16f-4d86-9125-5e2745a1b8c4` | 2026-08-08T13:06:00.000Z | ERROR/formal_event_fixture_rejected | incident=`c9a4cfe8-5c70-42ef-9a9c-2dd5d640e3ab` | lesson_key=`validate-event-fixtures` | event_sha256=`969267bb1d648428184365305a7b79e482bf9854e184c5e67ddf3accf4440461`
- #61: `4e2c2b44-fb2d-47a2-bd39-a4a0e9d0b6d1` | 2026-08-08T13:30:00.000Z | REVIEW/p7_scope_contract_quality_approved | incident=`7a8c3d4e-3b22-4d8e-b7c1-59e4a6f2d0b9` | lesson_key=`p7-bounded-scope-contract` | event_sha256=`28bdf592c75eccc0c3be80c372cfde6bd6f2940fd2143955e7533e0b1a121b63`
- #62: `a7d5f6c1-3e4b-4a82-9d1f-6b8c0e2a5f73` | 2026-08-08T13:45:00.000Z | WASTE/parallel_pack_agents_timeout | incident=`e6a3b9c2-7d1f-4e85-a0b6-5c9d2f7a1b43` | lesson_key=`bounded-subagent-recovery` | event_sha256=`86b5fd10c871cf1065e361e5993d3a1c85479bdcd2b396e282f97d2d6337753c`
- #63: `c1e4a7b2-8d36-4f91-a0c5-2e7b9d4f6a18` | 2026-08-08T14:10:00.000Z | ERROR/glm_oracle_estimand_assertion | incident=`8f3b2c1d-6e7a-4b90-a5d4-1c2e9f7b6a03` | lesson_key=`glm-estimand-layer-separation` | event_sha256=`de868c5f779c815186f3b566744d69dd9f4080d8bdd75170061c422c6be75c8b`
- #64: `d2f5a8c1-7b34-4e90-a6d2-1f8c3b5e7a09` | 2026-08-08T14:12:00.000Z | ERROR/synthetic_control_oracle_fixture_gradient | incident=`7c1e9a4b-5d2f-40b8-a6e3-1f9c7b2d4a08` | lesson_key=`synthetic-control-oracle-fixture` | event_sha256=`0f38d398a0a2eeadc98e59e2aea8d79452e85f0d2f7faed53c45a57de8986c5d`
- #65: `e3a6c9f2-1b47-4d80-a5e3-7c2f9b1a6d04` | 2026-08-08T14:13:00.000Z | ERROR/formal_event_fixture_lesson_key | incident=`4b7e2c9a-1d5f-40a8-b6e3-2f9c7a1d5b08` | lesson_key=`formal-event-fixture-identifier` | event_sha256=`f6fca31b6c0e188a66645bfef20adef5471b146087a348e9c340222b625a3787`
- #66: `f4b7d2a9-6c1e-4085-a3f7-9b2d5e1c7a04` | 2026-08-08T14:20:00.000Z | REVIEW/p7_final_extension_review_approved | incident=`1a6e3c9f-7b2d-4058-a1f4-9c7e2b5d6a08` | lesson_key=`p7-final-extension-review` | event_sha256=`eb246983f467599b75233c3a3f41785a16fe2bc5efff7bd69d9008b99b97bf93`
- #67: `a5d8c2f1-7b3e-4096-a1f5-2c9e6d4b8a07` | 2026-08-08T14:25:00.000Z | GATE/p7_final_extension_verified | incident=`6f2a9c4e-1b7d-4058-a3f9-2c6e8b1d5a07` | lesson_key=`p7-final-extension-gate` | event_sha256=`f596dd7c515d2e8111bf9804ec0d6813d88bef28f560a245fb88215ecc7b581d`
- #68: `b6e9c3f1-2a7d-4058-b1f4-9c6e2d8a7b03` | 2026-08-08T14:35:00.000Z | GATE/p7_affected_regression_verified | incident=`7d2a9c4e-1b6f-4058-a3e9-2c7d8b1f5a06` | lesson_key=`p7-affected-regression` | event_sha256=`e28b7a18ed4d1bcb596a12970248f89bd55c990c6ffe51e84dc5aea846687fb4`
