# Retrospective — v1-8-5-b3-recipe-default-materialization

## Goal

# v1.8.5 B3 — Recipe Default Materialization Objective  This is a deliberately narrow correction slice of \`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md\`. The parent design remains the only version-scope authority.  ## Objective  Make an already approved, current \`suggest_default\` for a published time-series Recipe usable in the real Notebook planning path. A provider may omit \`model_options.time_index_semantics\` only when the server has supplied an exact eligible default for that Recipe; before Draft validation the server must resolve the field through that default or reject the option. A missing, expired, mismatched, conflicting, or cross-Recipe memory must never fill the field.  ## Scope  - Preserve the final Recipe planning disclosure gate: every ETS or ARMA/GARCH   Draft has a resolved \`time_index_semantics\` before validation/materialization. - Replace the planner-facing instruction that unconditionally requires the   provider to state the field explicitly with the exact conditional rule above. - Extend the server-owned Notebook memory projection with a bounded,   deterministic per-Recipe retrieval bridge for only published   \`DefaultTargetContract\` Recipe targets. The bridge must use existing runtime   validity, scope, vocabulary, byte, and entry controls, deduplicate results,   and retain the existing generic projection behaviour. - Bind no target outside the proposal's selected Recipe. Existing   \`apply_memory_defaults\` remains the only proposal mutation boundary and   continues to preserve explicit-value precedence and provenance. - Add red-first tests for real local-runtime retrieval, conditional planner   instructions, correct ETS application, wrong-Recipe refusal, and absent or   invalid-default rejection. Perform a visible local Workbench planning/Draft   acceptance with an approved memory if the current host/provider is available.  ## Explicit non-scope  - No change to generic domain-memory predicate semantics, vector/semantic   retrieval, frequency inference, estimator selection, ARMA/GARCH orders,   execution authorization, or automatic execution. - No new Recipe, model family, estimator, artifact, packet schema, UI redesign,   or arbitrary model-option patching. - No weakening of current evidence, source-column, Proposal/Risk, vocabulary,   verifier, conflict, or provenance gates.  ## Acceptance  The new tests must fail before production changes and pass after them. Focused memory, Notebook route/planning, Recipe, naming, and TypeScript checks must remain green. Browser evidence must state whether it proves planning/Draft default visibility only or an executed analysis separately.

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 9/23 (39.1%; 39.1 per 100 events)
- Repeat rate: 0/9 (0.0%)
- Recurrence rate: 0/9 (0.0%)
- MTTR: median=1734000 ms (sample=9; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/10 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-01T19:47:00.000Z `tdd_red_recipe_default_not_materialized`; cause_status: `known`; cause: Notebook context retrieval only used generic analysis facts before a Recipe was selected, and the planner prompt independently required the provider to state time_index_semantics explicitly.; resolution: `open`; lesson: A suggestion default must be materialized from a server-owned exact target before the provider chooses a Recipe, while final Draft validation still requires the resolved field.
- #3 2026-08-01T20:03:00.000Z `tdd_red_recipe_default_projection_not_bounded`; cause_status: `known`; cause: The first bridge accepted verifier-stale inform_only Recipe hints and accumulated omission records from every preselection lookup without an overall context bound.; resolution: `open`; lesson: Recipe preselection must include only current suggest_default entries and must expose no more omission detail than the single generic retrieval contract can safely carry.
- #4 2026-08-01T20:06:01.000Z `review_generic_recipe_hints_reach_provider`; cause_status: `known`; cause: The final bridge merged generic retrieval entries after filtering only per-Recipe retrievals, so known Recipe targets and downgraded inform-only entries could still reach the provider through the generic fallback.; resolution: `open`; lesson: Known Recipe default targets must enter planning context only through their exact current per-Recipe admission path; generic fallback keeps only non-Recipe hints.
- #5 2026-08-01T20:06:01.000Z `review_recipe_default_truncation_can_choose_value`; cause_status: `known`; cause: Per-Recipe retrieval applied its eight-entry budget before the bridge considered conflicts, so a ninth current target with a different value could be omitted while the first eight still defaulted the field.; resolution: `open`; lesson: Any entry or byte budget omission in a Recipe-specific default lookup makes that Recipe default set incomplete and must fail closed without materialization.
- #6 2026-08-01T20:06:01.000Z `review_generic_omissions_exceed_context_limit`; cause_status: `known`; cause: The bridge passed generic retrieval omissions through unchanged even though the context contract allows at most thirty-two omission records.; resolution: `open`; lesson: The route boundary must deterministically cap publicly projected generic omissions to the context contract limit; extra per-Recipe omissions remain internal.
- #7 2026-08-01T20:12:55.000Z `review_complete_memory_projection_exceeds_byte_budget`; cause_status: `known`; cause: The bridge budgeted serialized entries but added public omission records afterward, so the complete context projection could exceed its 8 KiB contract despite each component being individually bounded.; resolution: `open`; lesson: Budget the complete serialized context envelope, removing omission detail first and entire Recipe-default groups rather than partial default candidates.
- #8 2026-08-01T20:17:57.000Z `review_memory_projection_byte_budget_counted_characters`; cause_status: `known`; cause: The complete projection budget used the length of a Python string instead of its UTF-8 encoding, undercounting non-ASCII memory content.; resolution: `open`; lesson: All payload limits must be measured against the canonical UTF-8 bytes sent over the boundary, not language-dependent character counts.
- #11 2026-08-01T20:24:21.000Z `review_external_memory_projection_utf8_budget_bypass`; cause_status: `known`; cause: The shared context attachment boundary used character count rather than canonical UTF-8 bytes, so an external memory provider could bypass the local-route budget enforcement.; resolution: `open`; lesson: The shared attachment contract and every producer must enforce the same canonical UTF-8 byte budget.
- #12 2026-08-01T20:24:21.000Z `review_global_budget_partially_admits_recipe_default_group`; cause_status: `known`; cause: The bridge filled a global entry budget one entry at a time across Recipe retrievals, which could cut one Recipe group after only a subset of its conflicting candidates had entered context.; resolution: `open`; lesson: Apply the global entry and byte budget to whole Recipe candidate groups; do not transform a group-level conflict into a per-entry selection order.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `external-memory-projection-utf8-budget`: occurrences=1; cause_status: `known`; root cause: The shared context attachment boundary used character count rather than canonical UTF-8 bytes, so an external memory provider could bypass the local-route budget enforcement.; solution: `open`
- `generic-memory-omissions-must-fit-context-contract`: occurrences=1; cause_status: `known`; root cause: The bridge passed generic retrieval omissions through unchanged even though the context contract allows at most thirty-two omission records.; solution: `open`
- `memory-payload-budget-is-utf8-bytes`: occurrences=1; cause_status: `known`; root cause: The complete projection budget used the length of a Python string instead of its UTF-8 encoding, undercounting non-ASCII memory content.; solution: `open`
- `memory-projection-budget-must-cover-envelope`: occurrences=1; cause_status: `known`; root cause: The bridge budgeted serialized entries but added public omission records afterward, so the complete context projection could exceed its 8 KiB contract despite each component being individually bounded.; solution: `open`
- `recipe-default-bridge-currentness-and-omission-budget`: occurrences=1; cause_status: `known`; root cause: The first bridge accepted verifier-stale inform_only Recipe hints and accumulated omission records from every preselection lookup without an overall context bound.; solution: `open`
- `recipe-default-groups-must-be-budget-atomic`: occurrences=1; cause_status: `known`; root cause: The bridge filled a global entry budget one entry at a time across Recipe retrievals, which could cut one Recipe group after only a subset of its conflicting candidates had entered context.; solution: `open`
- `recipe-default-materialization-before-provider-choice`: occurrences=1; cause_status: `known`; root cause: Notebook context retrieval only used generic analysis facts before a Recipe was selected, and the planner prompt independently required the provider to state time_index_semantics explicitly.; solution: `open`
- `recipe-default-truncation-must-fail-closed`: occurrences=1; cause_status: `known`; root cause: Per-Recipe retrieval applied its eight-entry budget before the bridge considered conflicts, so a ninth current target with a different value could be omitted while the first eight still defaulted the field.; solution: `open`
- `recipe-defaults-not-generic-provider-hints`: occurrences=1; cause_status: `known`; root cause: The final bridge merged generic retrieval entries after filtering only per-Recipe retrievals, so known Recipe targets and downgraded inform-only entries could still reach the provider through the generic fallback.; solution: `open`

## Added tests

- `B3 focused regression: 142 passed, 1 skipped; TypeScript passed`
- `pytest targeted memory projection and planner prompt tests: 2 failed`
- `pytest test_memory_projection_rejects_non_ascii_payload_over_utf8_byte_budget: external projection was accepted below the character limit while its UTF-8 bytes exceeded 8 KiB`
- `pytest test_recipe_default_bridge_blocks_truncated_recipe_candidates: expected no entries, received eight same-value candidates while an opposite ninth candidate was omitted`
- `pytest test_recipe_default_bridge_budgets_the_complete_projection_payload: attach rejected the combined entry and omission payload as over 8 KiB`
- `pytest test_recipe_default_bridge_budgets_the_complete_projection_payload: canonical characters were under 8192 while UTF-8 bytes were 10399`
- `pytest test_recipe_default_bridge_caps_generic_omissions_at_context_boundary: thirty-three generic predicate omissions exceeded the projection contract`
- `pytest test_recipe_default_bridge_excludes_noncurrent_hints_and_bounds_projection: stale hint entered projection`
- `pytest test_recipe_default_bridge_excludes_recipe_hints_from_generic_fallback: expected no entries, received wrong-Recipe and inform-only entries`
- `pytest test_recipe_default_bridge_never_partially_admits_a_recipe_group: five ARMA entries consumed slots and an ETS conflict group was partially admitted`

## New rules

- `external-memory-projection-utf8-budget`: line experience occurrence(s)=1
- `generic-memory-omissions-must-fit-context-contract`: line experience occurrence(s)=1
- `memory-payload-budget-is-utf8-bytes`: line experience occurrence(s)=1
- `memory-projection-budget-must-cover-envelope`: line experience occurrence(s)=1
- `recipe-default-bridge-currentness-and-omission-budget`: line experience occurrence(s)=1
- `recipe-default-groups-must-be-budget-atomic`: line experience occurrence(s)=1
- `recipe-default-materialization-before-provider-choice`: line experience occurrence(s)=1
- `recipe-default-truncation-must-fail-closed`: line experience occurrence(s)=1
- `recipe-defaults-not-generic-provider-hints`: line experience occurrence(s)=1

## Future guidance

- A suggestion default must be materialized from a server-owned exact target before the provider chooses a Recipe, while final Draft validation still requires the resolved field.
- All payload limits must be measured against the canonical UTF-8 bytes sent over the boundary, not language-dependent character counts.
- Any entry or byte budget omission in a Recipe-specific default lookup makes that Recipe default set incomplete and must fail closed without materialization.
- Apply the global entry and byte budget to whole Recipe candidate groups; do not transform a group-level conflict into a per-entry selection order.
- Budget the complete serialized context envelope, removing omission detail first and entire Recipe-default groups rather than partial default candidates.
- Known Recipe default targets must enter planning context only through their exact current per-Recipe admission path; generic fallback keeps only non-Recipe hints.
- Recipe preselection must include only current suggest_default entries and must expose no more omission detail than the single generic retrieval contract can safely carry.
- Review complete packets across every producer and consumer boundary, then retest multilingual and group-conflict cases.
- The route boundary must deterministically cap publicly projected generic omissions to the context contract limit; extra per-Recipe omissions remain internal.
- The shared attachment contract and every producer must enforce the same canonical UTF-8 byte budget.

## Event index

- #1: `ecf95418-4463-444b-85f0-609412dd29a8` | 2026-08-01T19:41:14.574Z | STATE_CHANGE/line_started | incident=`2adea56f-c40b-4d75-9432-25024f1ed4ee` | lesson_key=`frozen-context-before-start` | event_sha256=`7735f8cf1bdc59fa9b990a3dbd4038481b9ec7c02e222f5b68768209be1c110d`
- #2: `3ed3d19f-00d8-4361-a2af-bac6bea87ee0` | 2026-08-01T19:47:00.000Z | FAILURE/tdd_red_recipe_default_not_materialized | incident=`6820fd69-0b77-45cf-bcf2-2c8979412739` | lesson_key=`recipe-default-materialization-before-provider-choice` | event_sha256=`5f73e1887f9112e9d76f807023be3603662dde924e7df39c9f694403b63e7af9`
- #3: `4d246786-2ef5-4ec7-b285-e80f0cfdb3a4` | 2026-08-01T20:03:00.000Z | FAILURE/tdd_red_recipe_default_projection_not_bounded | incident=`2f4d41a4-30af-42e5-ab63-beb903c85018` | lesson_key=`recipe-default-bridge-currentness-and-omission-budget` | event_sha256=`ce87ab78b1bdbaac7f545e962b81068709334b6e36de281792f7c78733a91965`
- #4: `d30f2a07-2da0-424e-b1c5-3faa38cc6695` | 2026-08-01T20:06:01.000Z | FAILURE/review_generic_recipe_hints_reach_provider | incident=`e62412a0-f283-46c1-9d0a-95b5b3f06420` | lesson_key=`recipe-defaults-not-generic-provider-hints` | event_sha256=`0e3fd4c45bc54b292e73b94e99db51fc678a147cc7a41b135ae4af37298482f4`
- #5: `e62412a0-f283-46c1-9d0a-95b5b3f06420` | 2026-08-01T20:06:01.000Z | FAILURE/review_recipe_default_truncation_can_choose_value | incident=`335e096b-cd42-45e3-b35e-7cc594f56b85` | lesson_key=`recipe-default-truncation-must-fail-closed` | event_sha256=`3cd1b86ed1f4f56820f269c43c04303e334c16dfa416d4599427f73a5915d48f`
- #6: `8e40b386-fa07-4abb-b2a9-9b2a9016cde0` | 2026-08-01T20:06:01.000Z | FAILURE/review_generic_omissions_exceed_context_limit | incident=`304e338c-6e14-4a10-a791-4f7b34073e69` | lesson_key=`generic-memory-omissions-must-fit-context-contract` | event_sha256=`af3a42c6c7caa4afd33e4c4cf67a3cb33e3f75d0b3831862b74b499cb3072768`
- #7: `0ce773db-581e-4647-9397-0d49d95e2e52` | 2026-08-01T20:12:55.000Z | FAILURE/review_complete_memory_projection_exceeds_byte_budget | incident=`76b6dfe1-63b8-4678-8a9a-12dd7fc8518d` | lesson_key=`memory-projection-budget-must-cover-envelope` | event_sha256=`a9be6c8ecf43bbe92ac5c2fbc94d315635bb3d742984b0d1760585c891167992`
- #8: `0c479719-d567-49cc-9a07-f24f893e6913` | 2026-08-01T20:17:57.000Z | FAILURE/review_memory_projection_byte_budget_counted_characters | incident=`c467ea01-f274-445f-a07c-bf44b412f7fd` | lesson_key=`memory-payload-budget-is-utf8-bytes` | event_sha256=`0fe188f3804c48fa0b961aed835d2339d62179e0ec31e9cd8d51ae0b2d61cb44`
- #9: `e3d6f89a-8f7c-4674-a8fa-7ea7892a0f1b` | 2026-08-01T20:22:12.408Z | STATE_CHANGE/context_rescope_required | incident=`94724dc7-8965-4032-ae37-7a583c57d308` | lesson_key=`context-pack-rescope` | event_sha256=`a926579dc4ce035597a6678dff9e1c1bf91f6df0220ca213eba2ad45e9f6f27e`
- #10: `a6a503cf-fd1d-459e-90b0-dabe78d67f3c` | 2026-08-01T20:22:12.414Z | STATE_CHANGE/context_rescoped | incident=`ddf732fa-8da3-4697-825c-03b1da9d8d59` | lesson_key=`context-pack-rescope` | event_sha256=`ed3e161670f84a8fa34f8027fcf3f5324e728188933d9d125146cf345f63abc0`
- #11: `366a88f7-af33-4185-8205-71fbf3c843aa` | 2026-08-01T20:24:21.000Z | FAILURE/review_external_memory_projection_utf8_budget_bypass | incident=`d0e00586-8007-44e3-917e-865fc6af0852` | lesson_key=`external-memory-projection-utf8-budget` | event_sha256=`28c724080db9f41a8ebf135ad093e62df5865f054557b71a497d3a245a1b4225`
- #12: `b2ff9ffe-bf01-4887-be1a-641a406c0f93` | 2026-08-01T20:24:21.000Z | FAILURE/review_global_budget_partially_admits_recipe_default_group | incident=`4ce246da-b63f-4cf1-af6a-7bd1dbc7e0d2` | lesson_key=`recipe-default-groups-must-be-budget-atomic` | event_sha256=`d830889547248479bb79a897580c65b4800f8885ba73c23ff724dba4fa6fc5f5`
- #13: `a9eeb86f-6081-4d04-81f2-f8e90c1a024c` | 2026-08-01T20:34:55.000Z | GATE/b3_visible_provider_acceptance_not_verified | incident=`a58d49cc-606e-42af-8977-fdd41048ef1a` | lesson_key=`visible-provider-acceptance-distinct-from-local-draft-chain` | event_sha256=`e21cda6e60aaafd078128a92312909db029219a91f8840dda2b157fb3923b79f`
- #14: `00396f1a-15d4-4951-b1f9-a162172e1308` | 2026-08-01T20:34:55.000Z | REVIEW/b3_independent_review_approved | incident=`3ad4c968-ea2d-4bb9-85b3-2c0a568fff90` | lesson_key=`b3-final-cross-boundary-review` | event_sha256=`98e787050428a896f50be8bda8069aaa646bb053100e978f85db28e0a92d45d2`
- #15: `d45a5b7b-df25-47e9-b196-c9cfc9594c81` | 2026-08-01T20:34:55.000Z | GATE/b3_recipe_default_materialization_gate_passed | incident=`6820fd69-0b77-45cf-bcf2-2c8979412739` | lesson_key=`recipe-default-materialization-before-provider-choice` | event_sha256=`eb3ccd3f55f351fbc488e2a3993ec92997eace0ffcb3da2382c2e230e9dfed14`
- #16: `03bb2efb-0332-4ae9-acdd-f6929e71ab0b` | 2026-08-01T20:34:55.000Z | GATE/b3_recipe_default_currentness_gate_passed | incident=`2f4d41a4-30af-42e5-ab63-beb903c85018` | lesson_key=`recipe-default-bridge-currentness-and-omission-budget` | event_sha256=`8cfa0a8379d5234db647f392bdcffcbd59396b2d5dddd7e4bd513d048b48d5c3`
- #17: `163445f7-404a-42e1-8941-c5d8e1ed8894` | 2026-08-01T20:34:55.000Z | GATE/b3_generic_recipe_hint_gate_passed | incident=`e62412a0-f283-46c1-9d0a-95b5b3f06420` | lesson_key=`recipe-defaults-not-generic-provider-hints` | event_sha256=`186575690f9a9fde467c4752c4f4c28c2f80ac9227eb758dd008be562d3bc5ed`
- #18: `c4aa74cc-fb92-4cc1-b345-91273d964062` | 2026-08-01T20:34:55.000Z | GATE/b3_recipe_truncation_gate_passed | incident=`335e096b-cd42-45e3-b35e-7cc594f56b85` | lesson_key=`recipe-default-truncation-must-fail-closed` | event_sha256=`6ce6e6c4786e12d30f889d1dbe73732aaa82ab0bf9e5af7eb140b71440ebdb3a`
- #19: `6093dcd3-8e89-4b82-a104-d1ede3ba1c7a` | 2026-08-01T20:34:55.000Z | GATE/b3_generic_omission_budget_gate_passed | incident=`304e338c-6e14-4a10-a791-4f7b34073e69` | lesson_key=`generic-memory-omissions-must-fit-context-contract` | event_sha256=`c240e710c8ce0b0830973bfaf5ec3d73d5bf742d8ce86be20035229e8542dd78`
- #20: `d1ad942f-f860-4d9c-8098-c77230df9430` | 2026-08-01T20:34:55.000Z | GATE/b3_complete_projection_budget_gate_passed | incident=`76b6dfe1-63b8-4678-8a9a-12dd7fc8518d` | lesson_key=`memory-projection-budget-must-cover-envelope` | event_sha256=`48bd4d001511dd1d280ca82b9d2d77121bc01459f46865a14b9c984ec75dd16a`
- #21: `e5c10a3a-a55d-4be5-9c88-4b9c9857ad9e` | 2026-08-01T20:34:55.000Z | GATE/b3_route_utf8_budget_gate_passed | incident=`c467ea01-f274-445f-a07c-bf44b412f7fd` | lesson_key=`memory-payload-budget-is-utf8-bytes` | event_sha256=`2a4a03530b99ead647a941740dde0a89f44ec4e251d1ffb9e33804272bcab001`
- #22: `a9fbd649-b853-4522-9f6a-2528c3c5e001` | 2026-08-01T20:34:55.000Z | GATE/b3_shared_utf8_projection_gate_passed | incident=`d0e00586-8007-44e3-917e-865fc6af0852` | lesson_key=`external-memory-projection-utf8-budget` | event_sha256=`74453c75af08a761e63bc90902c9f2d53bfb9483293963fb4e260c6c85424229`
- #23: `dcd5d00e-df73-48d3-a1ad-28f738d9972e` | 2026-08-01T20:34:55.000Z | GATE/b3_recipe_group_atomic_budget_gate_passed | incident=`4ce246da-b63f-4cf1-af6a-7bd1dbc7e0d2` | lesson_key=`recipe-default-groups-must-be-budget-atomic` | event_sha256=`bf89673f988c0a6ff2f573a54ef011d37631bf540592d5121bc7f617acc78db6`
