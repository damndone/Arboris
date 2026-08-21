# Retrospective — v1-8-9-provider-projection-identity

## Goal

# Workbench v1.8.9 provider projection identity objective  ## Objective  Create a read-only identity sentinel for the provider catalog's consumer projection declarations. Every declared row must preserve the exact tuple \`(provider_id, exposure_path, consumer_id, projection_ref)\` and remain auditable without silently rewriting package-owned projection references.  This line does not change runtime adapters, provider manifests, coverage semantics, or central Agent/Notebook/Report mounts. It proves the current catalog denominator and makes the next central consumer integration line safe to implement in disjoint, package-owned steps.  ## Required outcomes  1. Load the repository builtin catalog through the server-owned loader. 2. Assert the current declaration counts are explicit: 7 providers, 15 rows,    12 composable paths, and 3 direct paths. 3. Assert every row's provider, path, consumer, and projection reference is    unique and internally stable; provider identity must not be inferred from a    consumer-only registry key. 4. Preserve the current status split as evidence: 5 covered and 10 blocked    \`projection_ref_mismatch\` rows. The test must not turn blocked rows into    coverage by changing refs.  ## Boundary  Only the sentinel test and this line's objective/plan/handoff are owned. No product runtime, provider manifest, frontend, central consumer, or release artifact may be changed.  ## Acceptance  Run the sentinel test, the existing catalog/coverage focused tests, Python compileall for the touched test module, \`git diff --check\`, and formal devline verification. Browser, provider, host, full-gate, merge, push, tag, and release remain unverified.

## Final status

STARTED

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

- `tests/test_v189_provider_projection_identity.py`

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `463ea84e-fbc0-4de9-8ee3-ec2bab54870c` | 2026-08-20T13:33:48.994Z | STATE_CHANGE/line_started | incident=`49a2c9f6-a92e-4058-92d4-04f5b1f74548` | lesson_key=`frozen-context-before-start` | event_sha256=`5b7cea533ebf4f931edc6d828606f13487df4fac2bdcae079646c6678411e3cb`
- #2: `9a2191d9-b725-4e8a-b0f0-0b6e2a3e1c4d` | 2026-08-20T13:47:38.538Z | GATE/provider_projection_identity_sentinel | incident=`d6d58877-f780-4583-a837-a9d5fefcfcaf` | lesson_key=`provider-projection-identity` | event_sha256=`75697dd7877736d3c46c4b9f3581f9caef2ccceac762ada8a6cba5cd312b9e94`
