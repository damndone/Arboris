# Retrospective — v1-8-9-p1-evidence-surface-integration

## Goal

# v1.8.9 P1 evidence-surface integration objective  ## Objective  Complete the remaining central product-surface composition for the P1 evidence layer: the Report UI must consume the server-owned data-consumer projection, and Survey evidence must be available through the same server-owned run-detail surface used by Agent and Notebook. Preserve fail-closed behavior: unknown, missing, forged, stale, or unsupported evidence is typed \`UNAVAILABLE\` and is never rendered from raw artifact JSON or caller-supplied paths.  ## Baseline  - Integration worktree: \`workbench-v1.8.9-hardening-integration\` - Exact baseline SHA: \`91ee6a05eab2a1892844c8a3057e1e607359a29e\` - Existing dirty v1.8.9 changes are in scope and must be preserved.  ## Boundaries  - In scope: server run-detail Survey projection, Report-side Survey and data   consumer typed evidence state/rendering, matching contract tests, and the   formal handoff. - Out of scope: estimator formulas, survey variance semantics, new model   families, browser acceptance, external providers, cross-process deployment,   full-repository release gate, merge, tag, and release. - No raw artifact payload, project path, or client identity may become a   consumer authority input.  ## Required outcomes  1. A run detail with a valid server-owned Survey artifact exposes one typed    Survey projection; missing or unsupported Survey artifacts remain typed    unavailable with bounded reasons and identity. 2. Agent, Notebook, and Report Survey reads share the same projection contract. 3. Report reads and renders the server-owned data-consumer projection, including    status, evidence identity, lineage, and blocked/unavailable reason, without    recomputing or accepting raw JSON. 4. Tests prove success, unavailable, identity binding, and no raw-payload    fallback for both surfaces.  ## Known gates  - Browser-visible acceptance is not yet verified. - Real external provider, cross-process authority, full host, full-repository   gate, merge, tag, release, and root-main synchronization are not yet   verified. - \`.sav/.zsav/.dta\` remain optional-dependency unavailable when \`pyreadstat\` is   absent.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/20 (15.0%; 15.0 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/2)

## All failures

- #14 2026-08-21T02:14:36.680Z `survey_catalog_missing_red`; cause_status: `known`; cause: The first Survey central-consumer probe found that the Report path was not admitted by the provider catalog and three required projection cases failed before catalog wiring was added.; resolution: `resolved`; lesson: A central consumer projection is incomplete until provider catalog admission, projection identity, evidence, policy, and renderer bindings are all present.
- #15 2026-08-21T02:14:36.806Z `survey_catalog_digest_red`; cause_status: `known`; cause: The first catalog contribution used an invalid projection digest shape, so four identity and coverage assertions failed before the digest and projection declarations were corrected.; resolution: `resolved`; lesson: Projection identity must be validated at the catalog boundary with exact digest and reference ownership before consumers can read it.
- #16 2026-08-21T02:14:36.936Z `survey_run_detail_binding_red`; cause_status: `known`; cause: The first run-detail integration probe failed because the generated Survey artifact lacked an explicit validated evidence status and the strict report assertion treated a typed catalog path identifier as if it were a raw filesystem path.; resolution: `resolved`; lesson: Strict evidence validation must follow the producer artifact contract and distinguish opaque typed identity from forbidden raw path disclosure.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- #4 2026-08-21T01:18:58.828Z `parallel_subagents_no_delivery`; cause_status: `known`; cause: Two bounded subagents were spawned for disjoint frontend and Survey integration lanes, but both remained running through two bounded waits and returned no files or handoff before being closed.; resolution: `mitigated`; lesson: Bound subagent waits; when no delivery arrives, close the worker and keep the critical path moving with direct implementation and explicit review.
- #18 2026-08-21T02:14:37.198Z `bounded_spec_review_no_delivery`; cause_status: `known`; cause: The bounded independent spec-review subagent remained running through the wait budget and returned no review or handoff, so no independent spec-review pass is claimed for this line.; resolution: `mitigated`; lesson: Bound parallel review work and record the absence of delivery explicitly; do not convert a non-response into review evidence.

## Root causes and solutions

- `bounded-subagent-delivery`: occurrences=1; cause_status: `known`; root cause: Two bounded subagents were spawned for disjoint frontend and Survey integration lanes, but both remained running through two bounded waits and returned no files or handoff before being closed.; solution: `mitigated`
- `catalog-admission-before-projection-green`: occurrences=1; cause_status: `known`; root cause: The first Survey central-consumer probe found that the Report path was not admitted by the provider catalog and three required projection cases failed before catalog wiring was added.; solution: `resolved`
- `no-review-delivery-no-review-claim`: occurrences=1; cause_status: `known`; root cause: The bounded independent spec-review subagent remained running through the wait budget and returned no review or handoff, so no independent spec-review pass is claimed for this line.; solution: `mitigated`
- `producer-contract-before-strict-consumer`: occurrences=1; cause_status: `known`; root cause: The first run-detail integration probe failed because the generated Survey artifact lacked an explicit validated evidence status and the strict report assertion treated a typed catalog path identifier as if it were a raw filesystem path.; solution: `resolved`
- `projection-identity-digest-boundary`: occurrences=1; cause_status: `known`; root cause: The first catalog contribution used an invalid projection digest shape, so four identity and coverage assertions failed before the digest and projection declarations were corrected.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `bounded-subagent-delivery`: line experience occurrence(s)=1
- `catalog-admission-before-projection-green`: line experience occurrence(s)=1
- `no-review-delivery-no-review-claim`: line experience occurrence(s)=1
- `producer-contract-before-strict-consumer`: line experience occurrence(s)=1
- `projection-identity-digest-boundary`: line experience occurrence(s)=1

## Future guidance

- A central consumer projection is incomplete until provider catalog admission, projection identity, evidence, policy, and renderer bindings are all present.
- Bound parallel review work and record the absence of delivery explicitly; do not convert a non-response into review evidence.
- Bound subagent waits; when no delivery arrives, close the worker and keep the critical path moving with direct implementation and explicit review.
- Consumer renderers must independently verify source identity, catalog ownership, evidence receipt, projection digest, and availability status instead of trusting a self-consistent payload.
- Projection identity must be validated at the catalog boundary with exact digest and reference ownership before consumers can read it.
- Strict evidence validation must follow the producer artifact contract and distinguish opaque typed identity from forbidden raw path disclosure.

## Event index

- #1: `b35e29c2-69f5-4f3d-abdc-b3854370333b` | 2026-08-21T01:15:36.109Z | STATE_CHANGE/line_started | incident=`9455a2f5-929d-47ea-b6fa-45937b3f408a` | lesson_key=`frozen-context-before-start` | event_sha256=`e06974d7fe5fa38e286dd1f5f05cb4a151679c10f04e1474bff222346e9eb89d`
- #2: `f201a882-17db-4393-8677-71ad39c6eec4` | 2026-08-21T01:17:40.380Z | STATE_CHANGE/context_rescope_required | incident=`73b4187a-2c36-471d-8fc4-abd1d07c08f6` | lesson_key=`context-pack-rescope` | event_sha256=`50da012b3652153b19a1ad5cd203dc8e71fba99e80d3761c95a65bbd4b9772e8`
- #3: `08930f7b-060e-430a-b4bb-58cb43c2f666` | 2026-08-21T01:17:40.384Z | STATE_CHANGE/context_rescoped | incident=`a7094703-4d50-47da-a128-0aef520bd5ce` | lesson_key=`context-pack-rescope` | event_sha256=`8b3a68fc1fc5c897b082c82de403e0d1f355e0815c4a63c11e5580f23fbfdb97`
- #4: `a1b2c3d4-e5f6-4789-9012-3456789abcdf` | 2026-08-21T01:18:58.828Z | WASTE/parallel_subagents_no_delivery | incident=`a1b2c3d4-e5f6-4789-9012-3456789abcde` | lesson_key=`bounded-subagent-delivery` | event_sha256=`7135b727ae4a8d32278b621ad38811d33398e8fce0faac7281546eff5b3a8527`
- #5: `12cf45c1-0d1c-40a9-ad1e-90d996afe2a5` | 2026-08-21T01:20:00.954Z | STATE_CHANGE/context_rescope_required | incident=`5277924d-7cf6-4ca5-b231-deb78e5e6c61` | lesson_key=`context-pack-rescope` | event_sha256=`f326321a66d4a59f756d92484a840bf2fc50a63622ae1b6d67be77f0ad7ea3b8`
- #6: `e89c8169-f191-401f-8e44-b82c205f73dd` | 2026-08-21T01:20:00.958Z | STATE_CHANGE/context_rescoped | incident=`3dc04a66-2bc2-4576-81ec-067b3bdda83d` | lesson_key=`context-pack-rescope` | event_sha256=`e15856217ba575ce291764c681dc8e09d15d51fd3d1f9db9bee50ad08e9c4fce`
- #7: `27b47e91-da2c-409d-a5a7-d7f491021993` | 2026-08-21T01:47:01.429Z | STATE_CHANGE/context_rescope_required | incident=`c2d21e20-fd84-413a-b6be-728d7fc06352` | lesson_key=`context-pack-rescope` | event_sha256=`c2d5d2507121913b2ca87861406139fb0792f6d235183b38a37b13e83c7a31e4`
- #8: `978c90b7-f460-4f66-9406-0b2c3f5e1f22` | 2026-08-21T01:47:01.434Z | STATE_CHANGE/context_rescoped | incident=`a42acc61-1291-46ab-a584-1d012b884fb5` | lesson_key=`context-pack-rescope` | event_sha256=`31089bc12a86a9ce0a049b50f37b597cd1535d0e21de0cac42b77235244777b7`
- #9: `c1736664-cf48-4a38-ac8f-c1c0dc04d990` | 2026-08-21T01:48:03.961Z | STATE_CHANGE/context_rescope_required | incident=`359f4a63-12e3-4253-81f7-cc6959be9ea5` | lesson_key=`context-pack-rescope` | event_sha256=`e1526e1bc40cdec629c14838651a640e12dcb30d37a2b72d884bc7e0e7d24c75`
- #10: `627149cb-59a7-4942-a25e-b30b645db8b4` | 2026-08-21T01:48:03.963Z | STATE_CHANGE/context_rescope_required | incident=`b4e22466-cb95-4755-8083-2865418c6bd2` | lesson_key=`context-pack-rescope` | event_sha256=`7ad9320428e5ad0ddbcaf25c4cf3d8ac38c13eb37891e67ea9ba05852930d054`
- #11: `ce0fd772-81d7-4855-a993-76ef0b151f04` | 2026-08-21T01:48:03.968Z | STATE_CHANGE/context_rescoped | incident=`c8ba7de9-a460-4faf-978a-27fe677e5af3` | lesson_key=`context-pack-rescope` | event_sha256=`41d0350d141af0d6fbffc33c4e29f27b84aa0827691a7836632a20c57244bef9`
- #12: `41eb4564-f3e1-4e86-aec1-9d7ce3b33f2e` | 2026-08-21T01:48:38.789Z | STATE_CHANGE/context_rescope_required | incident=`9a87c6e6-d195-4938-b0bb-04dbceea6cd4` | lesson_key=`context-pack-rescope` | event_sha256=`2a207e0f1b353a38ada5fd9f8615a16bb0e2ecb9e01635a5c148ce80b523b1c5`
- #13: `69e86507-9a47-4ff1-81e9-f879a3ec2a20` | 2026-08-21T01:48:38.795Z | STATE_CHANGE/context_rescoped | incident=`0024cec4-0ae3-4695-9516-dce597fedfba` | lesson_key=`context-pack-rescope` | event_sha256=`c31901394e05642d5b8e08935abb185e534626ee9e7e5550f0cd0d50d82f960d`
- #14: `c0f2a1d4-8e67-4b29-91a3-5d7e2f6c4b10` | 2026-08-21T02:14:36.680Z | FAILURE/survey_catalog_missing_red | incident=`d1f3b2e5-9a78-4c30-82b4-6e8f3a7c5d21` | lesson_key=`catalog-admission-before-projection-green` | event_sha256=`0abe9f4f05ce2d317439298877a484f4dc0e651f56bfd2cb4c888e34f383c959`
- #15: `d1a3b2c4-9e78-4f30-82b5-6c7d8e5f4a21` | 2026-08-21T02:14:36.806Z | FAILURE/survey_catalog_digest_red | incident=`e2b4c3d5-0a89-4f31-93c5-7d9e4b8a6f20` | lesson_key=`projection-identity-digest-boundary` | event_sha256=`c6adbf3dc6808a2ded81f184c087438a5a423102a46753cbaee7ec26e6298906`
- #16: `e2b4c3d5-0a89-4f31-93c5-7d9e4b8a6f20` | 2026-08-21T02:14:36.936Z | FAILURE/survey_run_detail_binding_red | incident=`f3c5d4e6-1b90-4a42-84d6-8e0f5b9c7a31` | lesson_key=`producer-contract-before-strict-consumer` | event_sha256=`f5408efa23b01bc56390857ee3dc9eba7889685b48d539cdda51dbb7ca46c51e`
- #17: `f3c5d4e6-1b90-4a42-84d6-8e0f5b9c7a31` | 2026-08-21T02:14:37.067Z | REVIEW/survey_report_security_review_resolved | incident=`a4d6e5f7-2c01-4b53-95e7-9f1a6c8d0b42` | lesson_key=`consumer-evidence-independent-binding` | event_sha256=`ab1672cde460bccfa23b662622f3d78a85edc613361eceaee04f9feb4428f08c`
- #18: `a4d6e5f7-2c01-4b53-95e7-9f1a6c8d0b42` | 2026-08-21T02:14:37.198Z | WASTE/bounded_spec_review_no_delivery | incident=`b5e7f6a8-3d12-4c64-a6f8-0b2c7d9e1a53` | lesson_key=`no-review-delivery-no-review-claim` | event_sha256=`4cbf0eda974ef6187dcd2af3051e31319d2e6309b7e035c8c5eaf8c34ce6f484`
- #19: `b5e7f6a8-3d12-4c64-a6f8-0b2c7d9e1a53` | 2026-08-21T02:14:37.332Z | GATE/evidence_surface_targeted_gate | incident=`c6f8a7b9-4e23-5d75-b809-1c3e8f0a2b64` | lesson_key=`bounded-green-not-product-release` | event_sha256=`7c28c4850977de4dd084876c9a0674435eecd3ca941ad55fd6171dc9ff8fc79d`
- #20: `c6f8a7b9-4e23-5d75-b809-1c3e8f0a2b64` | 2026-08-21T02:15:48.308Z | STATE_CHANGE/line_completed | incident=`d7a9b8c0-5f34-6e86-c91a-2d4f9b1e3c75` | lesson_key=`evidence-surface-bounded-closeout` | event_sha256=`8d3d6d6616ccb468c022275e3ab7f3bbd83b7f74ac13eb4243c12099ff55446c`
