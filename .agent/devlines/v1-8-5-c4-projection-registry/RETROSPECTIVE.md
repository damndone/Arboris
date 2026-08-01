# Retrospective — v1-8-5-c4-projection-registry

## Goal

# v1.8.5 C4 — Recipe-owned Public Projection Registry  This is a narrow follow-up to the v1.8.5 C3 Recipe projection boundary. The parent design remains the only version-scope authority.  ## Objective  Replace the Agent context reader's model-type-specific public-result dispatch with a server-owned registry that resolves each published Recipe to exactly one bounded projection builder. Existing ETS and ARMA/GARCH result shapes, artifact references, and fail-closed behaviour must remain unchanged.  ## Scope  - Add a lazy, immutable-in-use projection registry under   \`backend/workbench/agent/recipes/registry.py\`. - Let \`RecipeContract\` resolve its published projection through that registry;   keep the serialized projection identifier backward compatible. - Route ETS and ARMA/GARCH public evidence through the registry from   \`context_tools.py\`. - Add focused tests for registry ownership, unknown Recipe refusal, and the   existing ETS/ARMA evidence envelopes.  ## Explicit non-scope  - No frontend work, estimator changes, artifact changes, packet schema work,   raw-series exposure, or new Recipe. - No change to Proposal/Risk authority, memory defaults, or execution.  ## Acceptance  The new registry test must fail before implementation and pass afterward. The focused Recipe/Agent context suites, naming gate, TypeScript check, and diff check must pass. The result remains bounded and artifact-backed; unsupported Recipes return a stable reason code rather than falling back to OLS.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-01T21:58:07.000Z `tdd_red_projection_registry_absent`; cause_status: `known`; cause: The Recipe projection boundary had no server-owned resolver; the new registry test failed with ImportError before implementation.; resolution: `open`; lesson: Projection ownership must be tested as a registry contract before a new Recipe is admitted.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `projection-registry-before-recipe-growth`: occurrences=1; cause_status: `known`; root cause: The Recipe projection boundary had no server-owned resolver; the new registry test failed with ImportError before implementation.; solution: `open`

## Added tests

- `pytest tests/test_recipe_contracts.py::test_registered_recipes_resolve_server_owned_public_projection_builders -q: ImportError for missing resolve_public_result_projection.`

## New rules

- `projection-registry-before-recipe-growth`: line experience occurrence(s)=1

## Future guidance

- Keep projection identifiers serializable for compatibility, but resolve their executable builder only through a server-owned registry.
- Projection ownership must be tested as a registry contract before a new Recipe is admitted.

## Event index

- #1: `6a5f9892-6648-4e73-bcf6-e436e2cc8a75` | 2026-08-01T21:55:29.329Z | STATE_CHANGE/line_started | incident=`978cb480-32b4-4d2b-8d47-580f14b6eb5c` | lesson_key=`frozen-context-before-start` | event_sha256=`cdc2dec76e651bd3e6006bf77f8c62ea7af6b137bb8a7ab9f3e93d1c5b4461b2`
- #2: `d5ce3cd0-caad-4b49-ae27-a3fef8dc321d` | 2026-08-01T21:58:07.000Z | FAILURE/tdd_red_projection_registry_absent | incident=`3c57a9db-a5d5-4745-a9c0-efb82d17d112` | lesson_key=`projection-registry-before-recipe-growth` | event_sha256=`b788f04a1c83189440d5504d361670892bba889a8c515ef148cbcc60ec18bb4d`
- #3: `a5dd2c4a-42d6-452b-9cd2-68d2b355c3c8` | 2026-08-01T21:58:07.000Z | REVIEW/c4_projection_registry_review_verified | incident=`3c57a9db-a5d5-4745-a9c0-efb82d17d112` | lesson_key=`projection-registry-before-recipe-growth` | event_sha256=`6dc737f5feb244224bf28e516158446eca5be2479f84e2b9871be109a33d36db`
- #4: `44da6de0-6e20-4648-9c41-2e793b5c400f` | 2026-08-01T21:58:07.000Z | GATE/c4_projection_registry_gate_passed | incident=`44da6de0-6e20-4648-9c41-2e793b5c400f` | lesson_key=`c4-projection-registry-gate` | event_sha256=`3144530902eb7835732bd9d99474d909506bf7e3e522b522ff25cbf77b53ddc8`
- #5: `d42f3c42-0a1b-4c57-9136-1a2f20e4c320` | 2026-08-01T21:58:07.000Z | STATE_CHANGE/c4_projection_registry_completed | incident=`d42f3c42-0a1b-4c57-9136-1a2f20e4c320` | lesson_key=`close-c4-projection-registry` | event_sha256=`ca688d4cc63c44a14a9c0794d742fcd564fe76a12dcd8404349bd7897f9ffd8e`
