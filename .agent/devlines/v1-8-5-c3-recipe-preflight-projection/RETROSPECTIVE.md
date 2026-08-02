# Retrospective — v1-8-5-c3-recipe-preflight-projection

## Goal

# v1.8.5 C3 — Recipe Preflight and Result Projection Objective  This is the bounded completion slice for C2 in \`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md\`. The parent design remains the only version-scope authority.  ## Objective  Complete the two RecipeContract promises that C2 left as labels rather than enforced behaviour: validate the selected time/value series before a Dataset Genesis Draft is persisted, and publish a deterministic, bounded public result projection for each admitted Recipe.  ## Scope  - Add a server-owned Recipe input preflight at Dataset Genesis materialization.   It resolves only the verified upload already pinned by the Notebook, uses the   selected Recipe's existing owner contract, and refuses a Draft when the   current source violates a blocking time-series prerequisite. - Reuse pack-owned validation semantics rather than reimplementing estimator   mathematics: ETS duplicate timestamps, interior missing values, regular   calendar gaps/irregularity, minimum sample size, multiplicative positivity,   and constant series; ARMA/GARCH time/value parsing, index semantics,   blocking diagnostics, and transform eligibility. - Preserve the existing execution-time validation as defence in depth. A   preflight never repairs, fills, reorders source data invisibly, infers a   cadence, changes a fitted model, or discloses raw rows to the provider. - Fail closed if the verified source cannot be read within the existing bounded   source-inspection policy; include a stable, actionable Recipe error code. - Replace opaque Recipe \`result_projection\` labels with published, recipe-owned   bounded projections that reuse already-persisted artifact types. Extend the   Agent public-artifact reader only where a Recipe has no current projection;   do not create a packet, artifact id, schema version, or unbounded raw-series   exposure. - Exercise accepted and rejected paths through materialization and Agent public   evidence. Existing Table/Report artifacts remain the source of truth; this   slice may not redesign their UI or alter estimator output.  ## Explicit non-scope  - No estimator, numerical method, diagnostic algorithm, artifact registry,   packet-schema registry, model-options vocabulary, default-target expansion,   memory mutation, time-series multi-step workflow, or automatic frequency   inference. - No new artifact type or unaudited artifact payload. No raw source rows,   arbitrary files, or visual conclusion are surfaced to an Agent. - No frontend redesign and no change to Proposal/Risk confirmation or execution   authority.  ## Acceptance  Tests must first fail, then pass, for an ETS blocking source and an ARMA/GARCH blocking/transform-ineligible source before any Draft is written. Valid sources must retain the existing Draft and execution path. Recipe public results must be bounded, contain artifact-backed evidence references, and refuse unsupported or malformed payloads without falling back to an OLS view. Existing ETS and ARMA/GARCH known-truth tests, focused Notebook/Agent evidence tests, naming gate, and TypeScript check remain green. Browser acceptance, if run, must distinguish visible Draft rejection from executed-result evidence.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/10 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=959000 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-01T21:14:13.000Z `tdd_red_recipe_preflight_absent`; cause_status: `known`; cause: RecipeContract published only source-column validation, so Dataset Genesis materialization could persist an ETS Draft without applying the pack-owned input contract.; resolution: `open`; lesson: A Recipe-owned input contract must be invoked before Draft persistence and must preserve the owner diagnostic code.

## All errors

- #6 2026-08-01T21:43:50.000Z `c3_targeted_gate_disk_full`; cause_status: `external`; cause: The initial focused C3 gate exhausted the temporary filesystem and pytest fixture creation returned Errno 28 no space left on device.; resolution: `resolved`; lesson: Run focused suites with a dedicated basetemp and check free space before treating setup failures as product regressions.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `c3-gate-dedicated-basetemp`: occurrences=1; cause_status: `external`; root cause: The initial focused C3 gate exhausted the temporary filesystem and pytest fixture creation returned Errno 28 no space left on device.; solution: `resolved`
- `recipe-preflight-before-draft`: occurrences=1; cause_status: `known`; root cause: RecipeContract published only source-column validation, so Dataset Genesis materialization could persist an ETS Draft without applying the pack-owned input contract.; solution: `open`

## Added tests

- `Focused C3 gate output recorded OSError Errno 28 before temporary-directory setup; later dedicated basetemp runs completed after disk cleanup.`
- `Focused red test: recipe contract lacks validate_input_preflight and duplicate ETS timestamps reached Draft materialization.`
- `Independent review of the C3 ETS projection and time-series routing found three P1 findings.`

## New rules

- `c3-gate-dedicated-basetemp`: line experience occurrence(s)=1
- `recipe-preflight-before-draft`: line experience occurrence(s)=1

## Future guidance

- A Recipe-owned input contract must be invoked before Draft persistence and must preserve the owner diagnostic code.
- Independent review must exercise malformed, oversized, and contradictory persisted evidence, not only the happy-path packet.
- Keep Notebook preflight and executor validation aligned through the owner Recipe contract without copying Pack statistics.
- Public result projections must validate nested shapes, bound every repeated field, and fail closed on conflicting model identity declarations.
- Run focused suites with a dedicated basetemp and check free space before treating setup failures as product regressions.

## Event index

- #1: `a6df3616-cf79-42f0-ab66-78a596c4d600` | 2026-08-01T21:09:22.640Z | STATE_CHANGE/line_started | incident=`c5d6847c-ad4d-40ee-ae07-e7b78a0cf860` | lesson_key=`frozen-context-before-start` | event_sha256=`e3652dd9710fb16c9fad7938c608cb2ca9f4ed7df5f61867180fd848c4f80d9c`
- #2: `a855a256-8ad1-4bc6-a684-997c8a3c1827` | 2026-08-01T21:12:22.904Z | STATE_CHANGE/context_rescope_required | incident=`140f23c9-7343-4ff5-9a41-86f0c09c62f7` | lesson_key=`context-pack-rescope` | event_sha256=`eb33685480fc92cabae1228d5ab108c678a2ce0ca5a4ca61e0e1c9c2fecf5904`
- #3: `a8fef88a-7f5c-4493-a06d-7aec0290de8c` | 2026-08-01T21:12:22.909Z | STATE_CHANGE/context_rescoped | incident=`8a73d3ec-d93c-4978-b0f4-be9a74ea95bb` | lesson_key=`context-pack-rescope` | event_sha256=`ec96b4c92ba2b734f2c883bf513201cd873d04f7d13ea8d8555dc9b02aba277c`
- #4: `5a038285-b94e-4658-8f1f-a6ae8ab7b99e` | 2026-08-01T21:14:13.000Z | FAILURE/tdd_red_recipe_preflight_absent | incident=`3d8c3d6f-59ca-4e73-a0fd-7d92e53fc999` | lesson_key=`recipe-preflight-before-draft` | event_sha256=`bdc8ebb920eb007f5dcc514f55a47a0b81773f043575fa6d73c51120dc5e971a`
- #5: `e69d6b3e-68d5-4d02-9cc1-c4e95b2cf9af` | 2026-08-01T21:43:50.000Z | REVIEW/c3_independent_review_p1_findings | incident=`e6d8de48-66af-4ba5-87f0-23e5e38ef4df` | lesson_key=`c3-public-projection-review-findings` | event_sha256=`aa1d407cc224ea45b7dc6cd0e781aaf3ab3d2ace839176177e292d00bb6c42b1`
- #6: `e0d357b3-6861-4b12-b0b4-4f824a4e83ac` | 2026-08-01T21:43:50.000Z | ERROR/c3_targeted_gate_disk_full | incident=`c2ef0fd9-f00b-4572-919f-97cd8d8dc055` | lesson_key=`c3-gate-dedicated-basetemp` | event_sha256=`431b263d524a9b132c7b48cbbc5b04eb2f13a616cb39f536e770b3bab2e49fae`
- #7: `f2ee7617-5d1f-4a87-94e0-1bdb3d69d96c` | 2026-08-01T21:46:11.000Z | REVIEW/c3_recipe_preflight_verified | incident=`3d8c3d6f-59ca-4e73-a0fd-7d92e53fc999` | lesson_key=`recipe-preflight-before-draft` | event_sha256=`303ceb12c9fb04d4f219287b7d0722be370c53447d08c9f88ce98885ada24a79`
- #8: `8a8bd53e-28b8-4b93-87b4-5b5fdd65e95d` | 2026-08-01T21:46:11.000Z | REVIEW/c3_public_projection_review_verified | incident=`e6d8de48-66af-4ba5-87f0-23e5e38ef4df` | lesson_key=`c3-public-projection-review-findings` | event_sha256=`f177892054a5203ff3c3152ebd2a5ff122ed35272615675ff9360e2358f75c1d`
- #9: `f5eeb7be-cf9c-4a21-8f30-d72076048dab` | 2026-08-01T21:46:11.000Z | GATE/c3_focused_gate_passed | incident=`2f8838d3-cfba-4ea5-8bfd-d2ac04f392a3` | lesson_key=`c3-focused-gate-evidence` | event_sha256=`0784bed8aaa96844bd8a3e7921f22f9708dd4441cacec4d221b409c29293e8bf`
- #10: `a7c2c953-4d17-40b3-a79f-d8a85e775e35` | 2026-08-01T21:47:00.000Z | STATE_CHANGE/c3_recipe_preflight_projection_completed | incident=`d6ac6d89-2a82-4184-ae6f-9587fe7c1c85` | lesson_key=`close-c3-recipe-preflight-projection` | event_sha256=`f15e71fde2ac0a5f49e066a48f0d6d68b81c0310bfbe16b9a4d84ba5bf0e668a`
