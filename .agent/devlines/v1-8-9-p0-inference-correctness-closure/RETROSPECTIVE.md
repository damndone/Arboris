# Retrospective — v1-8-9-p0-inference-correctness-closure

## Goal

# Workbench v1.8.9 P0 Post-estimation Family Correctness  ## Objective  Prove and, if necessary, repair the post-estimation family boundary so that OLS-only inference adapters can never refit a non-OLS branch or emit an OLS statistic under a foreign model identity. Unsupported families must fail closed with the registered typed reason; supported OLS paths must retain the declared covariance, model artifact identity, and evidence provenance.  ## Scope  - \`backend/workbench/agent/workflow_runtime.py\` - \`backend/workbench/agent/post_estimation_registry.py\` - \`tests/test_v189_workflow_truth.py\` - \`tests/test_workflow_runtime.py\`  ## Acceptance  - A non-OLS branch presented to an OLS post-estimation operation is rejected   before refit/persistence with the stable unsupported-family contract. - OLS post-estimation tests remain numerically correct and preserve covariance   and source/model evidence bindings. - No hard-coded model identity can be used to authorize foreign evidence. - Compile, diff check, formal verify, retrospective, and scoped tests pass.  ## Non-goals  Do not add new post-estimation model families in this line or weaken the registry/exact result contracts.

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

- #2 2026-08-21T19:46:05.547Z `p0c_tdd_red`; cause_status: `known`; cause: The new direct refit identity and quantile finite-state regression tests reproduced the review findings before the production changes were applied.; resolution: `resolved`; lesson: Write behavior-changing direct and numeric-boundary regressions before the production fix and verify the expected red state.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `p0c-red-before-fix`: occurrences=1; cause_status: `known`; root cause: The new direct refit identity and quantile finite-state regression tests reproduced the review findings before the production changes were applied.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `p0c-red-before-fix`: line experience occurrence(s)=1

## Future guidance

- Unsupported post-estimation families must reject before reconstruction, and approximate uncertainty must expose its method and finite-data status.
- Write behavior-changing direct and numeric-boundary regressions before the production fix and verify the expected red state.

## Event index

- #1: `d025a4f3-eb93-4675-ab0f-2f22fc307c73` | 2026-08-21T18:31:47.808Z | STATE_CHANGE/line_started | incident=`d7d6e4b1-fef5-4c9e-a2a3-5a9f41ac7b59` | lesson_key=`frozen-context-before-start` | event_sha256=`b83ebd352299a8d630bbf00d43d5e17535804d262a2c37bd96865d7bd8c051d6`
- #2: `3f75f4f5-8df4-4f0c-bf5d-1c9d1c8b7f13` | 2026-08-21T19:46:05.547Z | FAILURE/p0c_tdd_red | incident=`6f2d54c3-8d0c-4d17-a96e-6e6b5a43c8f1` | lesson_key=`p0c-red-before-fix` | event_sha256=`6219c0581a4797e8740d435f4d1eeccd53760275678f49d6d262210e64273087`
- #3: `c7b6f5e4-d3c2-4b1a-9f80-7e6d5c4b3a21` | 2026-08-21T20:40:51.997Z | REVIEW/p0_c_inference_correctness_review_green | incident=`f6c4b8d2-1a3e-4f59-b7c0-2d8e6a4f1b93` | lesson_key=`family-aware-post-estimation-correctness` | event_sha256=`d95bf718b221ce080eb5288381838d5e30a575d84e35bcdec8719ccc12d407d3`
- #4: `f7e6d5c4-b3a2-410f-9ed8-c7b6a5d4e3f2` | 2026-08-21T20:41:48.485Z | GATE/p0_c_matrix_green | incident=`f6c4b8d2-1a3e-4f59-b7c0-2d8e6a4f1b93` | lesson_key=`p0-c-gate-evidence` | event_sha256=`5e9e10f2cae5d04ae20cb191151072187e40972e0ad8d0691b88b2df44508ed5`
- #5: `c3d4e5f6-a7b8-4901-9234-5c6d7e8f9012` | 2026-08-21T20:42:52.304Z | STATE_CHANGE/p0_c_completed | incident=`f6c4b8d2-1a3e-4f59-b7c0-2d8e6a4f1b93` | lesson_key=`p0-formal-closeout-boundary` | event_sha256=`a850610637691739e6b49d16b2aaf4c01e0184e51ca655257cfe7f2bed4636f4`
