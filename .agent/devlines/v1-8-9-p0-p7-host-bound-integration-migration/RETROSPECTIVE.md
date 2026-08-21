# Retrospective — v1-8-9-p0-p7-host-bound-integration-migration

## Goal

# Workbench v1.8.9 P0 P7 Host-bound Integration Migration  ## Objective  Make P7 integration and acceptance tests exercise the real deployment-owned workflow host boundary. Tests that need successful workflow execution must inject an explicit admitted host endpoint through the test seam; tests for missing authority must assert the typed fail-closed error. Never reintroduce a default endpoint or accept project/request metadata as host authority.  ## Scope  - \`tests/test_p7_acceptance_matrix.py\` - \`tests/test_p7_workflow_integration.py\`  ## Acceptance  - P7 success, failure, preflight, provenance, and CLI tests pass with explicit   host authority or typed blocked outcomes. - No production fallback endpoint, local key minting, or bypass is added. - Compile, diff check, formal verify, and retrospective pass.

## Final status

COMPLETED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `89973267-3ce6-438e-afe1-93d3793944cd` | 2026-08-21T08:24:12.876Z | STATE_CHANGE/line_started | incident=`442300ee-d602-424b-ba9a-00d459ac918a` | lesson_key=`frozen-context-before-start` | event_sha256=`5156ba49001f5453f021415ef10d474447295e3ff56325cd6b6374349ebdb27c`
- #2: `22222222-2222-4222-8222-222222222221` | 2026-08-21T08:47:29.805Z | GATE/p7_host_authority_green | incident=`22222222-2222-4222-8222-222222222222` | lesson_key=`host-authority-boundary` | event_sha256=`f69b0e440712408d5d0143cc5bdca472624d2b1874e37600aa487a869b509441`
- #3: `22222222-2222-4222-8222-222222222223` | 2026-08-21T08:47:29.953Z | STATE_CHANGE/line_completed | incident=`22222222-2222-4222-8222-222222222224` | lesson_key=`formal-closeout` | event_sha256=`c363a8e707acb767586d50f31e4bca1a6600576788d24aa736bd852194483042`
