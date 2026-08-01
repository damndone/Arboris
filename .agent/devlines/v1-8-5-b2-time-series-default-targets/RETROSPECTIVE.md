# Retrospective — v1-8-5-b2-time-series-default-targets

## Goal

# v1.8.5 B2 — Time-Series Memory Default Targets Objective  This is the bounded B2 slice of \`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md\`.  The parent design remains the only version-scope authority.  ## Objective  After C2 has published server-owned \`RecipeContract\` vocabularies, admit one strictly bounded \`suggest_default\` surface for each existing time-series Recipe: \`model_options.time_index_semantics\`.  The registry—not a memory's prose—owns the executable id, exact field, three literal values, method-risk presentation, source-column prerequisites, and provenance.  A memory can propose the interpretation of an already selected time index; it cannot select a series, infer a cadence, choose an estimator, choose ARMA/GARCH orders or transformations, alter a sample, or bypass a Recipe's planning/data validation.  ## Scope  - Publish the six exact targets for \`time_series.ets\` and   \`time_series.arma_garch\`: \`regular_calendar\`,   \`business_or_trading_observations\`, and \`observation_order\`. - Make every target require the Recipe's already-declared non-empty   \`time_column\` and \`value_column\` fields before a default can be injected.   Existing Recipe planning validation must still verify that those names occur   in current completed column evidence.  This is not frequency inference. - Publish the same target identifiers in the Recipe payload that the Notebook   gives the Agent, so a future approved memory cannot reference a hidden or   stale writable field. - Preserve B1 priority and safety semantics: explicit user/Agent values win;   conflicting same-scope memories do not choose a winner; unsupported or   legacy targets do not patch a proposal; every applied value carries an exact   \`memory_id\`, revision and target reference; revalidation is fail-closed. - Add red-first unit and planning-submission coverage for application,   explicit-value precedence, missing recipe inputs, source-column refusal, and   payload/registry identity. - Perform one visible Workbench acceptance on the existing local time-series   project using an approved local memory: planning → visible source/default →   confirmation → Draft validation.  Execution is optional only when the   generated specification is otherwise supported; no new estimator is added.  ## Explicit non-scope  - No automatic frequency inference, cadence detection, seasonal-period,   transform, ARMA/GARCH-order, dependent-variable, training-sample, or   estimator selection. - No arbitrary \`model_options\` patching, new Recipe, model family, estimator,   workflow, artifact type, retrieval system, or frontend redesign. - No relaxation of Proposal/Risk confirmation, evidence admission, current   source-column validation, or memory validity rules.  ## Acceptance  The new tests must fail before registry/payload implementation and pass after. The focused memory, Recipe and Notebook-planning suites must stay green, as must \`tests/test_no_exercise_specific_naming.py\` and TypeScript.  Browser evidence must distinguish a visible Draft/default from an executed Run; it must not claim a memory default proves calendar frequency or an estimator's statistical validity.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/12 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=15115000 ms (sample=3; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-01T18:34:19.000Z `tdd_red_recipe_time_index_default_targets_missing`; cause_status: `known`; cause: B1's server-owned default registry contains only OLS and Panel covariance targets, and C2 Recipe payloads publish an empty memory target list.; resolution: `open`; lesson: A Recipe default must be published by both the server-owned writable-target registry and the matching Recipe vocabulary; either half alone is not an executable authority boundary.

## All errors

- None recorded.

## All gaps

- #3 2026-08-01T18:49:05.000Z `domain_memory_candidate_review_not_wired_to_notebook`; cause_status: `known`; cause: The frontend has a candidate-review component and review API, but NotebookRouteView neither fetches pending candidates nor passes review handlers to NotebookSurface; the control plane also exposes no candidate-list read endpoint.; resolution: `open`; lesson: A review component is not a product capability until the route obtains its server-owned queue and wires explicit user actions back to the review service; do not substitute fixture setup for that user workflow.
- #5 2026-08-01T21:53:40.000Z `b2_browser_acceptance_url_policy_blocked`; cause_status: `external`; cause: After the local backend and frontend were restored, the in-app browser refused the existing dynamic Workbench project URL under its URL policy.; resolution: `open`; lesson: Keep browser URL-policy failures separate from product acceptance and never bypass the requested UI boundary with direct HTTP or guessed navigation.

## All waste

- None recorded.

## Root causes and solutions

- `b2-browser-acceptance-url-policy`: occurrences=1; cause_status: `external`; root cause: After the local backend and frontend were restored, the in-app browser refused the existing dynamic Workbench project URL under its URL policy.; solution: `open`
- `memory-candidate-controls-need-read-write-ui-loop`: occurrences=1; cause_status: `known`; root cause: The frontend has a candidate-review component and review API, but NotebookRouteView neither fetches pending candidates nor passes review handlers to NotebookSurface; the control plane also exposes no candidate-list read endpoint.; solution: `open`
- `recipe-default-target-must-have-registry-and-vocabulary`: occurrences=1; cause_status: `known`; root cause: B1's server-owned default registry contains only OLS and Panel covariance targets, and C2 Recipe payloads publish an empty memory target list.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `b2-browser-acceptance-url-policy`: line experience occurrence(s)=1
- `memory-candidate-controls-need-read-write-ui-loop`: line experience occurrence(s)=1
- `recipe-default-target-must-have-registry-and-vocabulary`: line experience occurrence(s)=1

## Future guidance

- A Recipe default must be published by both the server-owned writable-target registry and the matching Recipe vocabulary; either half alone is not an executable authority boundary.
- A component and endpoint form a capability only after the route owns current-project loading, freshness guards, and explicit revision-bound actions.
- A review component is not a product capability until the route obtains its server-owned queue and wires explicit user actions back to the review service; do not substitute fixture setup for that user workflow.
- Keep browser URL-policy failures separate from product acceptance and never bypass the requested UI boundary with direct HTTP or another browser.
- Keep browser URL-policy failures separate from product acceptance and never bypass the requested UI boundary with direct HTTP or guessed navigation.
- When a memory may affect a model proposal, review must confirm both the exact writable path and the information it never reads; absence of frequency inference is as material as field-level allowlisting.

## Event index

- #1: `4cf4d2f4-b5ab-49b0-92cd-52befcc1eb69` | 2026-08-01T18:33:06.151Z | STATE_CHANGE/line_started | incident=`fd75ddc1-64cf-4505-985b-67c3249879e9` | lesson_key=`frozen-context-before-start` | event_sha256=`d92099775b32fb3c52d6533063fccf442b1a9d6d387ad0d43863430cb7c5bd4a`
- #2: `775d3ac9-52bf-4d69-a4cc-22d6e2fca26f` | 2026-08-01T18:34:19.000Z | FAILURE/tdd_red_recipe_time_index_default_targets_missing | incident=`cd10f276-1d32-4700-a1bd-274368912ab2` | lesson_key=`recipe-default-target-must-have-registry-and-vocabulary` | event_sha256=`c7efcc0a12c13e053f3572900d5557793962631e47c11ca821a9a22ef0e2799b`
- #3: `8068dcce-23bb-48cf-91a3-95a961791a7f` | 2026-08-01T18:49:05.000Z | GAP/domain_memory_candidate_review_not_wired_to_notebook | incident=`5d44accc-66c3-4178-922b-aa86a27291ce` | lesson_key=`memory-candidate-controls-need-read-write-ui-loop` | event_sha256=`2faf8915efd8fec7828a57b1949b4fe0ae6b7bdffe60da07d24762467755aa66`
- #4: `25c0d429-f20c-453e-8c6e-2b7c0cb7fecf` | 2026-08-01T18:51:16.000Z | REVIEW/b2_independent_code_quality_review_approved | incident=`cd10f276-1d32-4700-a1bd-274368912ab2` | lesson_key=`review-bounded-default-targets-for-hidden-inference` | event_sha256=`f91974fe6fa84d9b397f3f60f0f67df1a9d3232c0a1cc62acc0a83fe32e200af`
- #5: `4a378623-77aa-4d61-9a25-4da1ba443bd3` | 2026-08-01T21:53:40.000Z | GAP/b2_browser_acceptance_url_policy_blocked | incident=`f9ab7b98-6ca2-4caa-8f57-0ac451122a38` | lesson_key=`b2-browser-acceptance-url-policy` | event_sha256=`b545382c19cd79be1cea3e14bc9ed38d259709e88da61cd3304c851abddbd03f`
- #6: `8d2e30a5-7a47-4f5c-a0f9-9a4d1f5f5b01` | 2026-08-01T23:01:00.000Z | REVIEW/domain_memory_candidate_review_not_wired_to_notebook | incident=`5d44accc-66c3-4178-922b-aa86a27291ce` | lesson_key=`memory-candidate-controls-need-read-write-ui-loop` | event_sha256=`5ea75d71b81ae56a6765488bb7146d32a26147a4165bdd0c6d8df56c6e119de6`
- #7: `6c44c706-3ee7-4fdf-b5af-52d9c93f0a02` | 2026-08-01T23:02:00.000Z | REVIEW/b2_browser_acceptance_url_policy_blocked | incident=`f9ab7b98-6ca2-4caa-8f57-0ac451122a38` | lesson_key=`b2-browser-acceptance-url-policy` | event_sha256=`9eca2055d2acd7dc2e57073c8ec67f63ed81f2bd0c3c9c9174d832d183045ed2`
- #8: `a8d4c3e2-0be1-4a4e-bb92-8f3d5c6a7e03` | 2026-08-01T23:03:00.000Z | GATE/b2_time_series_memory_default_browser_evidence | incident=`b7f3d9e1-2c6a-4b8e-9d0f-1a5c7e3b8f04` | lesson_key=`b2-browser-default-visibility-separate-from-statistical-validity` | event_sha256=`255b85ce0df5f1b136fdd38e172c6b2fe5eb4ee36b7a1e74c19905b5158785dd`
- #9: `c3e7a1b5-9d2f-4c6b-8e0a-7f3d1b5c9a04` | 2026-08-01T23:04:00.000Z | STATE_CHANGE/b2_time_series_default_targets_completed | incident=`d4a8c6e2-0b7f-4d9a-1c5e-8b3f7a2d6e05` | lesson_key=`close-b2-with-bounded-browser-and-contract-evidence` | event_sha256=`90adf806126da706a9ea7ecd3efa3ef6e7bbcf538130dcbc42d524bad5e89d99`
- #10: `7f2a9c4e-1b6d-48f0-a3c5-9e7b2d4a6f10` | 2026-08-01T23:05:00.000Z | STATE_CHANGE/tdd_red_recipe_time_index_default_targets_missing | incident=`cd10f276-1d32-4700-a1bd-274368912ab2` | lesson_key=`recipe-default-target-must-have-registry-and-vocabulary` | event_sha256=`5ab00c1925c58eda946a912b7e97613ecd86d4dfbb6f5dcbe911bc1fb0bb6cb9`
- #11: `7a4e1c9b-5d2f-48f0-b6c3-9e7a2d4b8f11` | 2026-08-01T23:06:00.000Z | STATE_CHANGE/domain_memory_candidate_review_not_wired_to_notebook | incident=`5d44accc-66c3-4178-922b-aa86a27291ce` | lesson_key=`memory-candidate-controls-need-read-write-ui-loop` | event_sha256=`92be705318d2e439f92f368b790f0f6fe53ec081b322540396dbf1eb0330424a`
- #12: `7b5f2d8a-4c1e-49f0-a6d3-8e2b7c5a9f12` | 2026-08-01T23:07:00.000Z | STATE_CHANGE/b2_browser_acceptance_url_policy_blocked | incident=`f9ab7b98-6ca2-4caa-8f57-0ac451122a38` | lesson_key=`b2-browser-acceptance-url-policy` | event_sha256=`4fd3f8152e10bfc45e4a299e74c2f6d1e2539263a8ca4accc5cc973356b40a2c`
