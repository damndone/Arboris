# Retrospective — v1-8-9-consumer-catalog-contract

## Goal

# Workbench v1.8.9 consumer catalog contract objective  ## Objective  Replace the refs-only consumer catalog seam with a versioned provider-owned declaration contract. A consumer projection row must declare which evidence and envelope contracts it accepts, which fact kinds it may select, its policy, renderer identity, budgets, ordering, and whether coverage is required or explicitly exempt. The shared projection registry must read those declarations and fail closed when a required declaration is missing or inconsistent.  This is a contract and wiring slice, not a claim that every package projection is already executable. Package-specific rows may remain blocked until their runtime adapter is registered; the catalog must make that state explicit.  ## Required outcomes  1. Add a typed, immutable \`ConsumerProjectionDeclarationV1\` to the provider    contract and persist it in every builtin manifest. 2. Validate declaration identity against the owning exposure path and its    projection ref, policy/renderer refs, evidence refs, budgets, ordering,    fact kinds, and explicit required/exempt coverage ownership. 3. Make the core consumer projection registry derive its policy, renderer,    budgets, sensitivity and ordering from the server-owned catalog declaration;    no consumer-side fallback defaults may create a covered row. 4. Keep package-specific projection refs blocked when no runtime adapter is    registered. Do not rewrite real provider refs to the core projection ref. 5. Prove malformed, missing, duplicate, mismatched and exempt declarations    fail closed through direct contract and catalog integration tests.  ## Acceptance boundary  Required: RED/GREEN contract tests, builtin catalog loading, projection registry/coverage sentinel tests, compileall and diff check. Browser, real provider, host identity, full repository gate, merge, push, tag and release remain follow-up gates.

## Final status

COMPLETED_WITH_LIMITS

## Metrics

- Failure frequency: 1/14 (7.1%; 7.1 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T14:40:17.427Z `consumer_catalog_declaration_red`; cause_status: `known`; cause: The new provider-owned consumer declaration tests fail before implementation because ProviderContributionV1 has no projection_declarations field and the central projection registry still uses hardcoded policy, budget and ordering defaults.; resolution: `open`; lesson: Run the declaration contract RED probe before changing catalog parsing so missing semantics cannot be hidden by consumer-side defaults.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `consumer-catalog-declaration-red`: occurrences=1; cause_status: `known`; root cause: The new provider-owned consumer declaration tests fail before implementation because ProviderContributionV1 has no projection_declarations field and the central projection registry still uses hardcoded policy, budget and ordering defaults.; solution: `open`

## Added tests

- `tests/test_v189_consumer_catalog_contract.py`
- `tests/test_v189_consumer_catalog_contract.py tests/test_v189_consumer_coverage.py tests/test_v189_consumer_projection.py`
- `tests/test_v189_consumer_catalog_contract.py tests/test_v189_consumer_coverage.py tests/test_v189_consumer_projection.py tests/contracts/test_v189_contract_lock.py tests/test_v189_data_operation_manifest.py`

## New rules

- `consumer-catalog-declaration-red`: line experience occurrence(s)=1

## Future guidance

- Authenticity digests must cover closure-owned authority state as well as visible value fields; otherwise immutable-looking capability objects can be selectively replaced.
- Provider-owned declarations must be the source of truth, but server-owned catalog admission and runtime identity checks must independently constrain what any declaration can authorize.
- Run the declaration contract RED probe before changing catalog parsing so missing semantics cannot be hidden by consumer-side defaults.

## Event index

- #1: `eae73dba-913c-4ec9-b9bf-7fc6973b5ae1` | 2026-08-20T14:36:27.113Z | STATE_CHANGE/line_started | incident=`b233ccca-7915-4284-b4a1-ea0495bab3ea` | lesson_key=`frozen-context-before-start` | event_sha256=`47fb8a7a1c44ee03e122009465fd4a30070a1a565853c87bb09a083aa3685adb`
- #2: `6d4f2a8e-7c1b-4e9d-b5f3-0a6c8e2d1f7b` | 2026-08-20T14:40:17.427Z | FAILURE/consumer_catalog_declaration_red | incident=`5e2c7a9d-4f1b-48d6-a0e3-9c7f2b5d8a1e` | lesson_key=`consumer-catalog-declaration-red` | event_sha256=`f24faf578da87a28df2b435c5f6df20f1e4e7984f4c818b2a698f5859b06c16d`
- #3: `b8d1e4f0-2a73-4c9e-8f16-5d0b6a7c2e91` | 2026-08-20T15:08:52.524Z | REVIEW/catalog_adversarial_review | incident=`c3a7e1d9-6b42-4f80-9c15-2e8a5d0b7f34` | lesson_key=`catalog-declaration-authority` | event_sha256=`798a1a67a8d754636f2e0591fd002cd87d0e1cecf17a5d046c807b7390039e31`
- #4: `d4f0a8c2-7e31-4b95-9a16-5c0d2e8f7b43` | 2026-08-20T15:09:11.386Z | GATE/catalog_contract_verification | incident=`e6b2c9f4-1a73-48d0-8e25-6f0c3b7d9a12` | lesson_key=`catalog-end-to-end-gate` | event_sha256=`2175e94df8214fc62dd4d40befa9186daf553c0c007c0f881376d2a4ad5f7227`
- #5: `a5e0c7f2-9b14-4d86-1f3a-7c2e8b0d6a95` | 2026-08-20T15:10:39.577Z | STATE_CHANGE/bounded_line_complete | incident=`b6d1f8a3-4c70-5e29-9a16-2f8c0d7b3e54` | lesson_key=`catalog-bounded-line-closeout` | event_sha256=`81c7008b298d0b87f87053047b25fb580209aeb25430cfbbe22443d3d10230a8`
- #6: `b7e3f0a9-2c14-4d86-5f20-8a1c6e9d3b75` | 2026-08-20T15:13:27.956Z | REVIEW/catalog_resolver_authority_gap | incident=`c8f1a6d2-4b70-5e93-9a16-2d8c0f7e3b54` | lesson_key=`catalog-resolver-digest-binding` | event_sha256=`317225808d3c1321f491e8ae77c3a5b881fdf0c58fbcda598cffa49bef1e7afb`
- #7: `5e6a4e84-f34f-44aa-ad87-995e05c8ddf5` | 2026-08-20T15:14:59.880Z | STATE_CHANGE/context_rescope_required | incident=`71bf1f86-e541-42a6-91f4-380857f05551` | lesson_key=`context-pack-rescope` | event_sha256=`ab25bdc1c3120d7e7ec3362aa4296156ad287da50a64cef8fa7f3e5a2d91cfb9`
- #8: `548bcc08-932f-4c25-9a20-5b3d9962f838` | 2026-08-20T15:14:59.887Z | STATE_CHANGE/context_rescoped | incident=`dc5accdc-d420-467e-8555-6d46e2ae0f74` | lesson_key=`context-pack-rescope` | event_sha256=`7a25945ac777f9132d78af3164d1e86e0f748031563bb23f14447acdc24f608e`
- #9: `3f619260-3ef3-4044-997a-ad2be62fa338` | 2026-08-20T15:15:28.290Z | STATE_CHANGE/context_rescope_required | incident=`d8ee39f9-d340-4583-8297-281d32bfb96a` | lesson_key=`context-pack-rescope` | event_sha256=`0c5fa5f8047ed66278aa90b68dbed8da7b5e53279f4579883fed47a2459a5b0e`
- #10: `420b6b19-5832-47cc-8a3c-eb8e2d31b738` | 2026-08-20T15:15:28.297Z | STATE_CHANGE/context_rescoped | incident=`2e7656a0-f75a-4e8e-b364-511374c7e182` | lesson_key=`context-pack-rescope` | event_sha256=`5312353f00a1a588c36a923895debda9251ca33a86fe1fd3ebd9bfc8711db551`
- #11: `8a066563-343c-4c20-9ef8-b4f5246eb281` | 2026-08-20T15:17:10.450Z | STATE_CHANGE/context_rescope_required | incident=`b5348d08-2ff2-4f0e-aa8a-765f3a6938aa` | lesson_key=`context-pack-rescope` | event_sha256=`78866d06e91ffc660f7651465cd8381619c658531afd465ba69d569e953b6de2`
- #12: `94507f46-19fe-4b70-99eb-70b0dce027f3` | 2026-08-20T15:17:10.458Z | STATE_CHANGE/context_rescoped | incident=`b7e4609d-c752-4b4e-96ca-cb1487feed6e` | lesson_key=`context-pack-rescope` | event_sha256=`ca9fba105cafba4c862a314b48c7a32aa7eba55c86131d879163604ecc7e69be`
- #13: `c9f4a1e7-2b63-48d0-5e17-8a0f3d6b7c92` | 2026-08-20T15:19:17.609Z | GATE/catalog_authority_final_gate | incident=`d0b6e2f8-4c71-5a93-9e16-2f8c0d7b3a54` | lesson_key=`catalog-authority-compatibility-gate` | event_sha256=`0f9b732b3faeaee11c0dd6278e998cc64c2e63d62fbe9cabe3cfed9ed34543a8`
- #14: `e2a7f0c5-9b14-4d83-6f20-1c8a5d3b7e94` | 2026-08-20T15:19:43.019Z | STATE_CHANGE/bounded_line_complete_after_authority_fix | incident=`f3b6d1a8-4c70-5e29-9a16-2f8c0d7b3e54` | lesson_key=`catalog-wire-complete-with-limits` | event_sha256=`e6c81fea6159c437e056c2a689674998f1462e0c2a5b53e48ae41a03f79d8329`
