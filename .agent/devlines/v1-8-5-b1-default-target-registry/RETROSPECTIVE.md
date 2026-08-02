# Retrospective — v1-8-5-b1-default-target-registry

## Goal

# v1.8.5 B1 — Default Target Registry Objective  This is the bounded implementation objective for B1 of \`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md\`.  The parent design remains the sole version-scope authority.  ## Objective  Replace the OLS-only memory-default table with a server-owned \`DefaultTargetContract\` registry.  A current \`suggest_default\` memory may fill only an absent, registered Draft default; it never changes evidence, execution authority, or an explicit user/Agent value.  ## Scope  - Register and validate OLS and Panel covariance targets from the same   contract shape, including the existing cluster/entity prerequisite. - Carry a complete, server-owned source (\`memory_id\`, \`revision\`,   \`target_ref\`) through option persistence and revalidation. - Fail closed for unregistered targets, invalid source, expired verifier,   vocabulary mismatch, equal-layer conflict, and more than one independent   writable field. - Respect priority: explicit current request, then current project memory,   then current global memory.  Never select a winner through hidden ordering. - Render target, source revision, method risk, and the prior/restorable value   on the Notebook option card.  ## Explicit non-scope  - No new estimator, execution path, artifact packet, browser-owned write   surface, or automatic execution. - No time-series target: B2 must derive those only from a published   \`RecipeContract\`. - No broad retrieval, semantic search, candidate curator, or model-family   expansion.  ## Acceptance  Tests must first fail and then pass for the registered OLS/Panel cases and for each refusal/priority rule above.  Existing OLS/Panel numerical behavior must not change.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/19 (15.8%; 15.8 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=1143000 ms (sample=3; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-01T12:25:38.000Z `tdd_red_default_target_authority`; cause_status: `known`; cause: The OLS-only memory-default table has no registered Panel target and does not validate projection vocabulary or project-versus-global source priority.; resolution: `open`; lesson: A memory default must be selected from a server-owned target contract after its vocabulary, source scope, and target preconditions are proven; list ordering is not a priority policy.

## All errors

- #13 2026-08-01T12:41:00.000Z `context_projection_version_boundary_missing`; cause_status: `known`; cause: The v2 context packet had no immutable vocabulary or source-scope fields, while the default authority adapter requires both to select a project-over-global suggestion safely.; resolution: `open`; lesson: A packet that gains authority-relevant fields needs a successor contract version; do not widen an exact historical packet in place.
- #14 2026-08-01T12:41:00.000Z `memory_default_source_roundtrip_type_error`; cause_status: `known`; cause: The exact-key check built a set containing mutable sets when a V1.4 source was re-read from persistence.; resolution: `open`; lesson: Round-trip tests must exercise exact schema checks after persistence, not only object construction before writing.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `default-target-registry-needs-explicit-scope-and-vocabulary`: occurrences=1; cause_status: `known`; root cause: The OLS-only memory-default table has no registered Panel target and does not validate projection vocabulary or project-versus-global source priority.; solution: `open`
- `memory-default-source-roundtrip-exact-keys`: occurrences=1; cause_status: `known`; root cause: The exact-key check built a set containing mutable sets when a V1.4 source was re-read from persistence.; solution: `open`
- `memory-projection-versioned-authority-boundary`: occurrences=1; cause_status: `known`; root cause: The v2 context packet had no immutable vocabulary or source-scope fields, while the default authority adapter requires both to select a project-over-global suggestion safely.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `default-target-registry-needs-explicit-scope-and-vocabulary`: line experience occurrence(s)=1
- `memory-default-source-roundtrip-exact-keys`: line experience occurrence(s)=1
- `memory-projection-versioned-authority-boundary`: line experience occurrence(s)=1

## Future guidance

- A memory default must be selected from a server-owned target contract after its vocabulary, source scope, and target preconditions are proven; list ordering is not a priority policy.
- A packet that gains authority-relevant fields needs a successor contract version; do not widen an exact historical packet in place.
- Authority-relevant packet fields require a new exact contract version while historical packets remain read compatible.
- Contract additions require write-read-revalidate coverage, not merely in-memory construction coverage.
- Priority, registered field ownership, and persisted provenance must be explicit contract facts, never inferred from hint order or free text.
- Round-trip tests must exercise exact schema checks after persistence, not only object construction before writing.

## Event index

- #1: `740665a4-34c3-44c1-b89e-deb2beb9eb73` | 2026-08-01T12:20:14.949Z | STATE_CHANGE/line_started | incident=`c8cb0fae-cb37-4b19-9c91-52ea48be36d4` | lesson_key=`frozen-context-before-start` | event_sha256=`2ff4b2d3a3bfe04979473128c57a0b6c8503fb508f7ae332d2950ced7a878342`
- #2: `72c849b8-28a6-4b31-be86-c73b42f946f7` | 2026-08-01T12:23:27.098Z | STATE_CHANGE/context_rescope_required | incident=`285d93ac-c2b2-4553-97ba-b72c7784dd4a` | lesson_key=`context-pack-rescope` | event_sha256=`393b8c001a9112236356943128e18e328a7aa84f4a2179bdd57a51060a47d572`
- #3: `e8eab79f-4513-4d56-98aa-2e016def7c7d` | 2026-08-01T12:23:27.101Z | STATE_CHANGE/context_rescoped | incident=`3617d9b7-1d7b-4277-8793-832bfdf8ff45` | lesson_key=`context-pack-rescope` | event_sha256=`d61d0a47f610fb2ccbc4f60ad0e1d17c037e499ae4baad0e989058e9065a8c53`
- #4: `0c96018f-d66a-41c7-965c-6c2bf07479ba` | 2026-08-01T12:25:38.000Z | FAILURE/tdd_red_default_target_authority | incident=`7f5b3f2c-0e75-4b5f-b472-92f4cba0f4f1` | lesson_key=`default-target-registry-needs-explicit-scope-and-vocabulary` | event_sha256=`dcb2e2883f850694af751c24a026e45bd7cf3e8d3585c466d636c7737caa171f`
- #5: `7e7e61a5-a853-478b-8187-cb02f28e4c2e` | 2026-08-01T12:27:18.473Z | STATE_CHANGE/context_rescope_required | incident=`47e9446e-691e-40b0-89c9-9df62c8a265e` | lesson_key=`context-pack-rescope` | event_sha256=`2f10dc6487498fe3dafaaf07a1b7f6323b367e3aa39c5072e6992840dc4ca800`
- #6: `368dfcee-631b-4d8f-b33e-0384116c8033` | 2026-08-01T12:27:18.476Z | STATE_CHANGE/context_rescoped | incident=`97c3e455-ac8c-473d-bda4-50f714aaf9be` | lesson_key=`context-pack-rescope` | event_sha256=`f21620209a869b5939f91e6bf935be668b57c72bdbcbcefa1388f95f6ed9ec05`
- #7: `81eccaf1-6b3d-4caa-8808-8ed32ec3d067` | 2026-08-01T12:27:55.665Z | STATE_CHANGE/context_rescope_required | incident=`0c0741a7-b038-4099-b0f2-382bac4e393b` | lesson_key=`context-pack-rescope` | event_sha256=`11bf10e66aa492dce427d6a304cee480e2d4ad7dead3993f9d17d58fe8ea3584`
- #8: `0f9c1a92-74fc-41dc-9b53-686f5f971e19` | 2026-08-01T12:27:55.671Z | STATE_CHANGE/context_rescoped | incident=`93ff1f4c-5d91-40b4-82be-fd89c85a20a4` | lesson_key=`context-pack-rescope` | event_sha256=`7a730ab443db59e69e1d731261bbd17dd029b5df3f39914c6b76cb789c094605`
- #9: `1371730c-f440-43cf-ad39-0152c38d24df` | 2026-08-01T12:36:34.085Z | STATE_CHANGE/context_rescope_required | incident=`49d73e63-78a2-4b67-a6af-788ecf0cc20d` | lesson_key=`context-pack-rescope` | event_sha256=`418c88a89381233b254674c91b3648fd743a8c11aff994d8cc43068c210b2575`
- #10: `38488d28-3cfb-4bb8-90b4-c4584dd4c06e` | 2026-08-01T12:36:34.092Z | STATE_CHANGE/context_rescoped | incident=`e20f9753-a718-4a93-95de-58a4ff20ae57` | lesson_key=`context-pack-rescope` | event_sha256=`e2ddd93293c848e9d785b9cd80f6eff1aeff046005513da9ba2e80fa133a7be3`
- #11: `cfedaebe-d074-41ee-bd37-b796566b4a6a` | 2026-08-01T12:37:23.150Z | STATE_CHANGE/context_rescope_required | incident=`a4756d7f-3bc1-41a4-b412-a65e6049b129` | lesson_key=`context-pack-rescope` | event_sha256=`ac28f8a1afc8cc786facf9704183832ec47db98717cc2de637b14147896e1ba0`
- #12: `42b8be3c-ad71-4ac2-996e-a09b75eea02a` | 2026-08-01T12:37:23.158Z | STATE_CHANGE/context_rescoped | incident=`883c5ba8-9d47-49b7-9384-611b56e30cd1` | lesson_key=`context-pack-rescope` | event_sha256=`6581415ad449b8d9517634cca2eec766b832c4cf88afd398995333525d65cc64`
- #13: `c3bf73d7-9cd8-4a70-b52c-0ef1018d0f0d` | 2026-08-01T12:41:00.000Z | ERROR/context_projection_version_boundary_missing | incident=`2c515a29-f00b-4bd1-a19b-202856f7e005` | lesson_key=`memory-projection-versioned-authority-boundary` | event_sha256=`1f1f0c9deabeb178d5a545b5260b0a53c8a4394b12632e9e3db52e5d20cf7f28`
- #14: `2f0b8727-dbc4-47d6-b139-df0b1fed42cc` | 2026-08-01T12:41:00.000Z | ERROR/memory_default_source_roundtrip_type_error | incident=`ce250773-9dfe-4545-a162-43ef76a76059` | lesson_key=`memory-default-source-roundtrip-exact-keys` | event_sha256=`3ff626a33f86db205dec7da346d4adb99f83f35b4b53989d661b36ca08374575`
- #15: `6cc59310-d37d-4919-9bca-50dbbcfd510a` | 2026-08-01T13:00:00.000Z | GATE/seatbelt_gate_blocked | incident=`2b84b987-d5c2-4d23-9ad5-211e8ed3f261` | lesson_key=`nested-seatbelt-full-gate-boundary` | event_sha256=`1adcce4b37f4532a880641aac21298ff3acb40a2a105b6a6b4b9c354502f0f80`
- #16: `e05d35a0-fd20-49e4-8a9d-9747f6ca0c8f` | 2026-08-01T13:00:01.000Z | REVIEW/default_target_review | incident=`7f5b3f2c-0e75-4b5f-b472-92f4cba0f4f1` | lesson_key=`default-target-registry-reviewed` | event_sha256=`9cb181dbc53d5eeb61bc2b6abd94d3f79ed6dbc64f0a0b99ae5cd3b452d20801`
- #17: `95a7d791-d2e0-448d-ac5f-a4cc8fd4cae8` | 2026-08-01T13:00:02.000Z | REVIEW/context_v3_review | incident=`2c515a29-f00b-4bd1-a19b-202856f7e005` | lesson_key=`context-projection-v3-reviewed` | event_sha256=`cb685dbf23011215e234ce34d12751711a2ba4bef49bed00fded28ecdc1e1087`
- #18: `6555859f-73d4-4d08-9301-0a2d07829609` | 2026-08-01T13:00:03.000Z | REVIEW/memory_source_review | incident=`ce250773-9dfe-4545-a162-43ef76a76059` | lesson_key=`memory-source-roundtrip-reviewed` | event_sha256=`aa4333ee8601a278f93c59d1b83e813648b687cfd2aad8d146b760dfb566e3e1`
- #19: `96d1c1cb-7da8-4ad9-9a3f-3442d7fa78df` | 2026-08-01T13:00:04.000Z | STATE_CHANGE/completed | incident=`df819fa8-895d-43ef-b695-7f1db95ec42f` | lesson_key=`bounded-line-completion-with-host-gate` | event_sha256=`aaac20194656b56cd2961ce5acd3bb24efed02712d483da6806ed3d8c1bf34c3`
