# Retrospective — v1-8-9-p0-post-estimation-family-correctness

## Goal

# Workbench v1.8.9 P0 Post-estimation Family Correctness  ## Objective  Prove and, if necessary, repair the post-estimation family boundary so that OLS-only inference adapters can never refit a non-OLS branch or emit an OLS statistic under a foreign model identity. Unsupported families must fail closed with the registered typed reason; supported OLS paths must retain the declared covariance, model artifact identity, and evidence provenance.  ## Scope  - \`backend/workbench/agent/workflow_runtime.py\` - \`backend/workbench/agent/post_estimation_registry.py\` - \`tests/test_v189_workflow_truth.py\` - \`tests/test_workflow_runtime.py\`  ## Acceptance  - A non-OLS branch presented to an OLS post-estimation operation is rejected   before refit/persistence with the stable unsupported-family contract. - OLS post-estimation tests remain numerically correct and preserve covariance   and source/model evidence bindings. - No hard-coded model identity can be used to authorize foreign evidence. - Compile, diff check, formal verify, retrospective, and scoped tests pass.  ## Non-goals  Do not add new post-estimation model families in this line or weaken the registry/exact result contracts.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T08:00:53.360Z `tdd_red_post_estimation_family`; cause_status: `known`; cause: The new focused regression showed that a foreign top-level model family could be paired with a nested OLS branch specification; registry admission accepted the nested identity and execution reached persisted-model validation instead of the registered unsupported-family refusal.; resolution: `open`; lesson: Bind both persisted and nested model-family identities before OLS post-estimation dispatch.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `post-estimation-family-identity`: occurrences=1; cause_status: `known`; root cause: The new focused regression showed that a foreign top-level model family could be paired with a nested OLS branch specification; registry admission accepted the nested identity and execution reached persisted-model validation instead of the registered unsupported-family refusal.; solution: `open`

## Added tests

- `tests/test_v189_workflow_truth.py`

## New rules

- `post-estimation-family-identity`: line experience occurrence(s)=1

## Future guidance

- Bind both persisted and nested model-family identities before OLS post-estimation dispatch.
- Bind every explicit model-family identity before selecting an OLS-only post-estimation adapter.

## Event index

- #1: `54f7fc5d-ba83-4af3-b20e-add065b4061a` | 2026-08-21T07:50:17.799Z | STATE_CHANGE/line_started | incident=`9160016f-411c-4ae7-b5e6-21c584956720` | lesson_key=`frozen-context-before-start` | event_sha256=`39eed05f8f4658b960113238ccc972e027ec4d7e040cb60a10f6e45c43eb91d6`
- #2: `d9fd0b8d-5c65-4d5b-a3da-21b2dbd3b75b` | 2026-08-21T08:00:53.360Z | FAILURE/tdd_red_post_estimation_family | incident=`2c72a78a-c9f2-4ebd-8b9e-28c333d38b5b` | lesson_key=`post-estimation-family-identity` | event_sha256=`d1ac20fbbf9857de9cc71dad4676d121f66a58273cae66bac02b97a8d3137e80`
- #3: `7c7d1d35-cb4a-48f6-a2c9-07f6347206a8` | 2026-08-21T08:06:30.351Z | REVIEW/post_estimation_family_boundary_review | incident=`bb2a2ad9-2ba8-4df8-a3e4-20523d7ba19f` | lesson_key=`post-estimation-family-identity` | event_sha256=`1f7afea1e0a263a204c22347cf3bac7b2b251efc4190221e95c55a773a63f41d`
- #4: `1c8a1f0e-1d7d-4a75-9cf0-42a71faea4fa` | 2026-08-21T08:08:16.088Z | GATE/post_estimation_family_scoped_gate | incident=`f88e36dd-7561-4e86-908a-a979b5d440ab` | lesson_key=`scoped-gate-evidence` | event_sha256=`147daca99d83fcf4e8fadf8bd051811437dc89367f2d5e8613c2c1bf96f99276`
- #5: `5bc8de3b-7b0e-4f34-9ec0-a1abf6e9d0a2` | 2026-08-21T08:08:39.436Z | STATE_CHANGE/line_completed | incident=`d8a1f0b3-ecb2-4d4b-8e3a-4d213d6df7d9` | lesson_key=`close-at-verified-boundary` | event_sha256=`bf86b8fc73f22811b99f78f689f8334cf1dc2d45f238b85c12d8dbd5252c6e1e`
