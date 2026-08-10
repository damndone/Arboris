# Retrospective — v1-8-8-agent-chain-hardening

## Goal

# v1.8.8 Agent-chain hardening objective  Close the three known acceptance gaps on code baseline \`ad51d23\`: make Report provider output safely accepted and saved, validate Notebook artifacts against the option-owned contract while preserving the ambient index, and make the eighteen live reachability gaps executable through one declaration-driven workflow seam. Make Genesis draft editing consume a server-owned two-phase schema. Preserve proposal confirmation, numerical fail-closed behavior, typed provenance, and the prediction-only boundary for resampling.  The current shared capability inventory is \`118 / 4 / 94 / 98 / 2 / 18\` and the target is \`118 / 4 / 112 / 116 / 2 / 0\`. The eighteen IDs and the current P7 operation denominator must be queried from live declarations before tests are written. A host-side browser-visible matrix must cover every operation returned by the live P7 registry with a durable result or an explicit typed optional-dependency block; unit tests and direct adapter calls do not count.  Keep Report, Notebook, reachability, and Genesis changes module-isolated. Do not add per-operation orchestrator branches, silently retry typed Agent calls, silently drop provider content, or perform push, PR, merge, tag, or release.

## Final status

COMPLETED

## Metrics

- Failure frequency: 6/46 (13.0%; 13.0 per 100 events)
- Repeat rate: 0/6 (0.0%)
- Recurrence rate: 0/6 (0.0%)
- MTTR: median=0 ms (sample=4; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/4 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #13 2026-08-09T08:27:00.000Z `host_full_gate_regression`; cause_status: `known`; cause: The first host full gate reported three failures: the legacy graph smoke timed out after 5 seconds while importing plotting dependencies; cs_did failed with 422: model.genesis cs_did does not accept did_cohort_col, did_mode; sa_did failed with the analogous rejection.; resolution: `resolved`; lesson: A green focused suite is insufficient when the host gate still exposes startup and family-contract integration regressions.
- #17 2026-08-09T11:27:00.000Z `p7_false_success_guard`; cause_status: `known`; cause: A live P7 Hurdle negative-binomial execution returned a typed failed result, but the generic workflow executor previously committed it as completed.; resolution: `resolved`; lesson: Typed non-completed results must fail closed before artifact persistence.
- #41 2026-08-10T01:59:42.000Z `host_full_gate_calendar_projection_regression`; cause_status: `known`; cause: The first final host gate reported five failures: four memory fixtures became review_due after their hard-coded review date passed, and one graph projection assertion omitted the newly required immutable upload workflow source.; resolution: `resolved`; lesson: Calendar-sensitive fixtures must derive a future review boundary, and source projection tests must include the immutable workflow source without weakening runtime provenance.

## All errors

- #19 2026-08-09T11:27:02.000Z `report_upstream_retry`; cause_status: `external`; cause: Historical Report browser acceptance exposed duplicate figure marker coef_plot and a retry exposed LLM_UPSTREAM_ERROR: ReadError; the first complete report was withheld until a later retry succeeded.; resolution: `mitigated`; lesson: Transient upstream errors and duplicate markers must remain visible until a complete accepted report is independently observed.

## All gaps

- #23 2026-08-09T11:27:06.000Z `p7_manual_browser_coverage`; cause_status: `known`; cause: The P7 registry contains 64 operations; 14 unique operations were attempted in manually reviewed browser chains, 13 completed successfully, and one intentionally failed closed for non-convergence.; resolution: `open`; lesson: Generic workflow coverage is not equivalent to individually reviewed browser acceptance; preserve the remaining operation matrix as an explicit gap.
- #44 2026-08-10T01:59:45.000Z `qa_witness_trust_boundary`; cause_status: `known`; cause: The local acceptance runner coordinates immutable admissions and durable results but does not cryptographically prove that a browser observation or completion record was produced by an independent witness.; resolution: `accepted`; lesson: Do not promote a local QA coordinator into a cryptographic browser witness without a separate signed observer architecture and explicit production-neutral hooks.

## All waste

- None recorded.

## Root causes and solutions

- `host-gate-calendar-and-projection`: occurrences=1; cause_status: `known`; root cause: The first final host gate reported five failures: four memory fixtures became review_due after their hard-coded review date passed, and one graph projection assertion omitted the newly required immutable upload workflow source.; solution: `resolved`
- `host-gate-integration-before-claim`: occurrences=1; cause_status: `known`; root cause: The first host full gate reported three failures: the legacy graph smoke timed out after 5 seconds while importing plotting dependencies; cs_did failed with 422: model.genesis cs_did does not accept did_cohort_col, did_mode; sa_did failed with the analogous rejection.; solution: `resolved`
- `manual-browser-coverage-gap`: occurrences=1; cause_status: `known`; root cause: The P7 registry contains 64 operations; 14 unique operations were attempted in manually reviewed browser chains, 13 completed successfully, and one intentionally failed closed for non-convergence.; solution: `open`
- `qa-runner-is-not-cryptographic-witness`: occurrences=1; cause_status: `known`; root cause: The local acceptance runner coordinates immutable admissions and durable results but does not cryptographically prove that a browser observation or completion record was produced by an independent witness.; solution: `accepted`
- `report-upstream-retry-visible`: occurrences=1; cause_status: `external`; root cause: Historical Report browser acceptance exposed duplicate figure marker coef_plot and a retry exposed LLM_UPSTREAM_ERROR: ReadError; the first complete report was withheld until a later retry succeeded.; solution: `mitigated`
- `typed-failure-fail-closed`: occurrences=1; cause_status: `known`; root cause: A live P7 Hurdle negative-binomial execution returned a typed failed result, but the generic workflow executor previously committed it as completed.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `host-gate-calendar-and-projection`: line experience occurrence(s)=1
- `host-gate-integration-before-claim`: line experience occurrence(s)=1
- `manual-browser-coverage-gap`: line experience occurrence(s)=1
- `qa-runner-is-not-cryptographic-witness`: line experience occurrence(s)=1
- `report-upstream-retry-visible`: line experience occurrence(s)=1
- `typed-failure-fail-closed`: line experience occurrence(s)=1

## Future guidance

- A declaration-driven editor must distinguish an undeclared capability from a broken declared contract and never map the latter to an empty schema.
- A green focused suite is insufficient when the host gate still exposes startup and family-contract integration regressions.
- Artifact manifests must project the declared contract scope and reject ambient leakage without hiding it.
- Calendar-sensitive fixtures must derive a future review boundary, and source projection tests must include the immutable workflow source without weakening runtime provenance.
- Do not promote a local QA coordinator into a cryptographic browser witness without a separate signed observer architecture and explicit production-neutral hooks.
- Generic workflow coverage is not equivalent to individually reviewed browser acceptance; preserve the remaining operation matrix as an explicit gap.
- Live acceptance must verify both failure visibility and the absence of committed result artifacts.
- Real acceptance fixtures must match operation geometry and pass the same sample guards as production data.
- Report completion requires saved, exportable, provenance-backed state, not only a successful upstream request.
- Scale acceptance by deriving the full denominator from declarations and reserve expensive browser and provider work for family and cross-layer boundaries.
- Transient upstream errors and duplicate markers must remain visible until a complete accepted report is independently observed.
- Typed non-completed results must fail closed before artifact persistence.

## Event index

- #1: `745af1f7-0165-4fbd-970b-604a5b65960c` | 2026-08-09T03:56:05.410Z | STATE_CHANGE/line_started | incident=`dd14b9a4-de2c-44a6-ac1a-3b431e798e8e` | lesson_key=`frozen-context-before-start` | event_sha256=`42bf9403138fd366198b9afa61d0586878899a767fa3255d55be7b5f367d77cd`
- #2: `9af38d5f-2caa-42e8-8a8a-7a44837db476` | 2026-08-09T05:42:26.353Z | STATE_CHANGE/context_rescope_required | incident=`d178675c-abd6-4098-a202-9b3130234c6d` | lesson_key=`context-pack-rescope` | event_sha256=`1818ca92dc7f0f0c073ef14eda091a74e291d5a4d0d3d66d1cd7981a41097579`
- #3: `ec8a0dcb-969c-4da3-afeb-1c44263a316c` | 2026-08-09T05:42:26.358Z | STATE_CHANGE/context_rescoped | incident=`d0666f89-b5c8-4e2e-b7b1-bdef43ac3682` | lesson_key=`context-pack-rescope` | event_sha256=`70be7eff97235b35122a92594b038a43e65b6842267bce04c4793f31578e7844`
- #4: `fbd96824-65fe-4ddf-9762-6bd7ccc656c0` | 2026-08-09T05:42:50.143Z | STATE_CHANGE/context_rescope_required | incident=`082457d7-227f-4605-814f-001bed27935d` | lesson_key=`context-pack-rescope` | event_sha256=`a6996b8197b080444d0a83065982e8217796420f55d7a7f4091db26fc7564fa0`
- #5: `4517ecc7-3ea5-4db4-bee5-287497a7c928` | 2026-08-09T05:42:50.148Z | STATE_CHANGE/context_rescoped | incident=`928b896e-71cc-4338-91aa-bc56142f23e2` | lesson_key=`context-pack-rescope` | event_sha256=`638bb31ebf5fa19e13e806c70db6aff3d4a92316ea377555172cf7f9b51c42fa`
- #6: `a155cbee-7af6-44a0-a61c-9119d0fc6f61` | 2026-08-09T05:55:12.871Z | STATE_CHANGE/context_rescope_required | incident=`0d579a1a-bac1-4a57-9458-bf8cae106e50` | lesson_key=`context-pack-rescope` | event_sha256=`53cd8992b9cc0e98599cdd2935951835661407a879f6062861f63cd0e4205cc0`
- #7: `6ba21ae1-3e28-430b-87de-c987fc71ac53` | 2026-08-09T05:55:12.876Z | STATE_CHANGE/context_rescoped | incident=`eeb77d9d-505e-4ca2-b1c8-a0043cbdad08` | lesson_key=`context-pack-rescope` | event_sha256=`c5ee0d5c095b1d0b2982875a288a1558f34bfa7f3c3a2336ef100eb8478206c3`
- #8: `2704de45-bdfa-4eea-8c74-02f349af163d` | 2026-08-09T06:50:22.634Z | STATE_CHANGE/context_rescope_required | incident=`3acdbf96-f9db-42ad-9a81-f828272d08d5` | lesson_key=`context-pack-rescope` | event_sha256=`e0af52a682dd541c79cf34a7268f7459f7ce17703066b79223aaa66b2fbf0635`
- #9: `75fbae9b-5ea0-4cdf-af2b-8a15da7fda5e` | 2026-08-09T06:50:22.644Z | STATE_CHANGE/context_rescoped | incident=`cf6bafea-4515-478b-8c84-15c66c015312` | lesson_key=`context-pack-rescope` | event_sha256=`eb878cb160b85c59b043cddf7234d07372fbc43efe7b85c1ca2e3be41b51f356`
- #10: `76052f19-0f29-40ab-b51f-c5a4ae76ea60` | 2026-08-09T07:32:25.570Z | STATE_CHANGE/context_rescope_required | incident=`0b25d7d9-663b-4e10-b0ec-2ab682e6ba9d` | lesson_key=`context-pack-rescope` | event_sha256=`a100d342589f0b2539d8719459ac06690af52c8827f092c27d803e38af59d486`
- #11: `53b91be8-85a6-4efe-a5a8-7c2c406e6747` | 2026-08-09T07:32:25.582Z | STATE_CHANGE/context_rescoped | incident=`efb0170d-0146-4058-8318-d28e713b9518` | lesson_key=`context-pack-rescope` | event_sha256=`c1327aa806bcffca5816e40cf323b999bfa98587c76e37cc85ccb48a12b123ed`
- #12: `2d2b9d04-cd4f-4ce0-9e0b-10d38f15d5db` | 2026-08-09T08:26:00.000Z | GATE/sandbox_gate_environment | incident=`6dbbd3cd-e7e0-4d47-a5d3-1d62ae61b3a0` | lesson_key=`host-sandbox-gate-separation` | event_sha256=`d90e4d6fe61569db5e5e815ca943617d32372bdcd4b91db51be1b02113e55d3a`
- #13: `3cf85dd6-2ce0-4b65-84ce-a8bdc7688fd2` | 2026-08-09T08:27:00.000Z | FAILURE/host_full_gate_regression | incident=`8d45efb0-fb3d-4bd1-b0b1-104f0d6590b2` | lesson_key=`host-gate-integration-before-claim` | event_sha256=`eb5bd520d93db65868640026ea24af8f458466db88e00ca6cb88d07ad9ba7d48`
- #14: `f182665e-34d1-45d6-a1b9-2410fb6b0e2d` | 2026-08-09T08:28:00.000Z | GATE/host_full_gate_passed | incident=`1e1bcf85-5f31-4bc6-8f63-e4d39e65e9f3` | lesson_key=`integrated-gate-before-completion` | event_sha256=`d744fa4d3b0240af3f5a10559478e36968608ab18875d1ed28f6aea4ce39bcf0`
- #15: `585dcff0-f544-420b-ba45-6c8f546e4181` | 2026-08-09T08:27:14.761Z | STATE_CHANGE/context_rescope_required | incident=`3c7ac909-3b7a-4ca6-a9d9-91b5882901a9` | lesson_key=`context-pack-rescope` | event_sha256=`6a10986e463446073492e0481292c04f379f4490bcf83be4dd3f7c7c0d4c588e`
- #16: `e63aa657-1f12-4c23-bc4a-c8d49f15554e` | 2026-08-09T08:27:14.772Z | STATE_CHANGE/context_rescoped | incident=`e649fdcb-6d63-4fee-b84a-58b413dade78` | lesson_key=`context-pack-rescope` | event_sha256=`ea1e6e28509c967640f504a0613147b924f383a6764cdd427efc7f07127645b3`
- #17: `c1b44ee7-02b1-4b0f-9cc7-29d6c3eb8e01` | 2026-08-09T11:27:00.000Z | FAILURE/p7_false_success_guard | incident=`c0b5f8ae-363b-4f0e-8d3a-48f05e1b9301` | lesson_key=`typed-failure-fail-closed` | event_sha256=`55a3426b05cdf556282c26f383664958843f68bbfd335fd2237776de280115f8`
- #18: `d5e5cbf7-ef66-4b4e-a5fb-b8d4b3ae2f02` | 2026-08-09T11:27:01.000Z | REVIEW/p7_failure_live_acceptance | incident=`6d1b40d6-8d27-4f5f-9516-a8a08e25c9c2` | lesson_key=`live-failure-visibility` | event_sha256=`eadfe10ec20bc5b878afa85202e5c7e4a9f05edeb7db0b9aac781d4feb49df91`
- #19: `a6d0ac02-4a9c-4eb3-a3ef-61c4fa3ea103` | 2026-08-09T11:27:02.000Z | ERROR/report_upstream_retry | incident=`2e8e46be-5b64-44ab-9ffb-1fc82a4e5c03` | lesson_key=`report-upstream-retry-visible` | event_sha256=`f2aac16d9fb7a53f3c94860d691480e3a1846195f1456ea9e9cc18e5d3456869`
- #20: `b7c1e8b8-fb8d-44ba-9513-0fc8f04f7a04` | 2026-08-09T11:27:03.000Z | REVIEW/report_browser_acceptance | incident=`f047e97d-b38c-41e7-bc99-b2eb4fa58a05` | lesson_key=`report-browser-acceptance` | event_sha256=`829df15597704aff33c3b0c7495e2d30bb173aa69f8ae337a5b97d833c1b0c61`
- #21: `c8b0d1b8-0b8c-44d3-ae4e-f2e4db6b8105` | 2026-08-09T11:27:04.000Z | REVIEW/notebook_artifact_projection | incident=`c4bd39d2-bfb0-4c8a-82b1-cd56c78b9e06` | lesson_key=`notebook-artifact-scope` | event_sha256=`bfae05fa61f2e1b71f67915747fc4ba7427bb6883b9bb8e2156bafb36352cad6`
- #22: `d9b4a2b1-1475-4c8d-970d-75c8b2c6f906` | 2026-08-09T11:27:05.000Z | REVIEW/synthetic_control_browser_acceptance | incident=`e6c9fdf2-cc60-467a-bf0c-5c49d7b4c807` | lesson_key=`synthetic-control-shape-guard` | event_sha256=`bb0a0bb50d557d656644e6d84447b59cf3abba6eb6fdf6cbc9aaa56e1a14c110`
- #23: `e0c9e1b2-9f47-4b5d-8d12-4b8de7eaa207` | 2026-08-09T11:27:06.000Z | GAP/p7_manual_browser_coverage | incident=`f6c4a4c0-9a65-4497-bfa0-aab82c4bd908` | lesson_key=`manual-browser-coverage-gap` | event_sha256=`e2a180ff57778c731a3cdff42cb302e330502cbf1ed0b8da9eabd7e376d9905d`
- #24: `f1f6b3b0-3959-4ec4-bd1a-2f6f67a9d708` | 2026-08-09T11:40:00.000Z | GATE/host_full_gate_passed | incident=`ac72ca50-32c6-4db8-a251-7be7f6f94f09` | lesson_key=`integrated-gate-before-completion` | event_sha256=`44aca822109dc724e386b22a5078a720f29f178843391d7af97f0415d02e348e`
- #25: `e269e1f0-5ea6-4d95-9366-4f6f6c02328b` | 2026-08-09T20:54:50.591Z | STATE_CHANGE/context_rescope_required | incident=`402c41d9-5fa1-45ee-b976-1c2c4ae66c4d` | lesson_key=`context-pack-rescope` | event_sha256=`a4d63532d19059c0a2bdbb7f942a66437d00c9962629436ce90e64f9d772bdb9`
- #26: `a566f4a6-8fa1-418d-af1d-803e54aa94c9` | 2026-08-09T20:54:50.613Z | STATE_CHANGE/context_rescoped | incident=`1c6d78ce-9704-4d13-b673-5e0b07d58cbb` | lesson_key=`context-pack-rescope` | event_sha256=`b2b8851b0c9acca7423e78cebac48586115bbbceac3c686c7b036604c2d3ce3e`
- #27: `21e8ab06-34c4-4f58-8a84-869974982216` | 2026-08-09T21:14:36.310Z | STATE_CHANGE/context_rescope_required | incident=`3a4bb60a-5226-47c2-b91a-d42ddfdd6f87` | lesson_key=`context-pack-rescope` | event_sha256=`f96eb65ba51c4f2fd06a5355d4ffb92c1c4b4bd20e7f29f95a1deaaa009306c4`
- #28: `4762e9b9-b0d5-495e-8602-4b0ca4a1e244` | 2026-08-09T21:14:36.331Z | STATE_CHANGE/context_rescoped | incident=`bd92c19a-9757-41d7-9aa4-e6a816bf97e2` | lesson_key=`context-pack-rescope` | event_sha256=`a33bf02852db6b84d5123c79b7da616c08d12fcd0fce72048e7e2e08f53ba9e6`
- #29: `08a2bedf-5b12-4fdc-baa9-3c164adf6fc7` | 2026-08-09T21:37:25.830Z | STATE_CHANGE/context_rescope_required | incident=`6e2e7681-2ee2-4d1b-9aaa-63d1f5a83002` | lesson_key=`context-pack-rescope` | event_sha256=`7484e05be12ba7ac84acb06c447aad5127c877087127d730c0a5a738a890ab47`
- #30: `efd5759a-0725-414b-ba45-a92f5a634f52` | 2026-08-09T21:37:25.852Z | STATE_CHANGE/context_rescoped | incident=`a0fc6aea-7d80-40cf-9fbc-f229087cb999` | lesson_key=`context-pack-rescope` | event_sha256=`5955262d5dc05a381fda1ef0b0bf48ff4dac391084d9e6834d6df128f9717a0c`
- #31: `aa8294af-12fc-42d9-9cc0-9f2d64e653dd` | 2026-08-09T21:50:52.549Z | STATE_CHANGE/context_rescope_required | incident=`4202b194-c0bf-4efe-8b92-d505090d0e5d` | lesson_key=`context-pack-rescope` | event_sha256=`33f04b82c68d9df2331db34b514c7f466c96e2491591b9d8f4f9766c2f2573de`
- #32: `37bc054c-7c14-4c61-81a2-c659c9b70a18` | 2026-08-09T21:50:52.575Z | STATE_CHANGE/context_rescoped | incident=`e3f9cb40-b11b-43b1-937b-bc445f74b964` | lesson_key=`context-pack-rescope` | event_sha256=`f602c7eda11d565564f7fd0d8c1d0e58d45ec814737a690c38b00dbda31c0180`
- #33: `fc8d7d63-beef-4464-8d7c-8549b88466a2` | 2026-08-09T21:56:35.659Z | STATE_CHANGE/context_rescope_required | incident=`b70e8d1b-c86a-47ae-9146-0c247b3ee97f` | lesson_key=`context-pack-rescope` | event_sha256=`64c8f2a25a9db883b90892caf59ee2d77d2f06e0cd3e338b2c148d90de07fe0a`
- #34: `ef238d0e-da42-4f0b-b507-e5d0f7204bf9` | 2026-08-09T21:56:35.687Z | STATE_CHANGE/context_rescoped | incident=`ede41377-f995-4af8-ac72-650afcd33acc` | lesson_key=`context-pack-rescope` | event_sha256=`7302448ad2ba6c776e9ad7380bd81af851592a0f75a6744760c62dc3cec1e7bb`
- #35: `9b9ab154-0eb9-4627-a1b0-de49a9de9ec7` | 2026-08-09T22:04:20.206Z | STATE_CHANGE/context_rescope_required | incident=`dc18b774-3b8f-4020-82c6-c8c39a6d2971` | lesson_key=`context-pack-rescope` | event_sha256=`072743e998b17026e54064ee1b886895034ce0f3dc871547d0b3e47bf5080889`
- #36: `7cc30b72-703c-4bf7-9ab4-8198ec8598a9` | 2026-08-09T22:04:20.236Z | STATE_CHANGE/context_rescoped | incident=`862a8430-109e-4ec7-b4cc-68df517c1510` | lesson_key=`context-pack-rescope` | event_sha256=`963785f1fd235d5131f00a64714dd723c96c25fb7dbf05933edab096265a9eac`
- #37: `2f39fc37-0bf3-4f0d-b62d-7b8770da903f` | 2026-08-10T01:25:50.469Z | STATE_CHANGE/context_rescope_required | incident=`0a5a934e-dd53-421a-a80e-2f25200b8fb8` | lesson_key=`context-pack-rescope` | event_sha256=`ce8b722445f6e2a3013c776ec00571b9962966f420b691de638d0cb15fc1bcd2`
- #38: `fdba251c-9189-430a-ae0f-ba75c491865c` | 2026-08-10T01:25:50.507Z | STATE_CHANGE/context_rescoped | incident=`f7780fab-d368-49c0-9b4e-e8fc45f231a2` | lesson_key=`context-pack-rescope` | event_sha256=`8c9a56688d0aaf6195cb9559cc24984c415754ab8d785cea1ef246b58bae106f`
- #39: `9c7cc2c2-9f6d-4491-83ee-d4a19e8c9809` | 2026-08-10T01:41:33.302Z | STATE_CHANGE/context_rescope_required | incident=`28311d49-cf5e-4dcb-9f77-4e916f1f48cf` | lesson_key=`context-pack-rescope` | event_sha256=`170b5df133c58d06531fd8a262b43925948013327c89e25a6b7770b616c44410`
- #40: `c03530fa-c8c7-4be7-852b-45f7219b7441` | 2026-08-10T01:41:33.343Z | STATE_CHANGE/context_rescoped | incident=`595f2a67-41ea-4d6b-944a-49e63c42298b` | lesson_key=`context-pack-rescope` | event_sha256=`7b58424074a858c46282ed352bbb1bb951dc890c47df6095a89d34b78712e891`
- #41: `5c45ac3a-d3ff-4be6-bfda-0448e02abe40` | 2026-08-10T01:59:42.000Z | FAILURE/host_full_gate_calendar_projection_regression | incident=`2d945ae0-7376-47b3-9622-32be0a6b1581` | lesson_key=`host-gate-calendar-and-projection` | event_sha256=`f1c842b98b8ae1c2d635856eb373ada36f4930bcb8b04175f91d5be503952939`
- #42: `b28e5a9d-1046-423a-979f-9ecbe6229df3` | 2026-08-10T01:59:43.000Z | REVIEW/p7_browser_coverage_strategy | incident=`f6c4a4c0-9a65-4497-bfa0-aab82c4bd908` | lesson_key=`registry-derived-browser-sampling` | event_sha256=`800cfda7acc31a4914154891ef07d0edaf4105e397840669234c4a9ed1e000a5`
- #43: `ae8609b2-5604-4203-8a6a-13ff5d39eaaf` | 2026-08-10T01:59:44.000Z | REVIEW/genesis_family_schema_fail_closed | incident=`3480a824-fa01-4c97-8826-0bab44dce5b6` | lesson_key=`declared-schema-never-silent-fallback` | event_sha256=`8be592765fd90945273df83a8118e55404ee1103917018cfc0fc99f3d59cc5ea`
- #44: `f20b5c5e-90cd-42c3-ba9a-38e228edfd50` | 2026-08-10T01:59:45.000Z | GAP/qa_witness_trust_boundary | incident=`9698c44d-6ab9-486d-8eb4-db40c696c540` | lesson_key=`qa-runner-is-not-cryptographic-witness` | event_sha256=`fc3b675304bc1f9e53b80808692edd6afb7c0442e1f63062d2edf1ec3f5a0cea`
- #45: `c2dba600-09ef-47b2-bb0d-10be5ede361f` | 2026-08-10T01:59:46.000Z | GATE/host_full_gate_passed | incident=`2d945ae0-7376-47b3-9622-32be0a6b1581` | lesson_key=`final-stable-code-host-gate` | event_sha256=`68656b25ea8656363530b39bb6f912d7235af9547496d2ff1822ed0cfe7aa7f9`
- #46: `9698c44d-6ab9-486d-8eb4-db40c696c540` | 2026-08-10T01:59:47.000Z | STATE_CHANGE/objective_completed | incident=`ae8609b2-5604-4203-8a6a-13ff5d39eaaf` | lesson_key=`layered-acceptance-before-completion` | event_sha256=`13f9e89aff11eb58d1e768051b6f83168d52d979c3fdf929193bb131f18a70c4`
