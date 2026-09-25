# Retrospective — v1-8-9-p1-survey-correctness-closure

## Goal

# Workbench v1.8.9 P1 survey correctness and evidence closure  Close the audited complex-survey correctness gaps while preserving the existing design-based estimator architecture and server-owned evidence boundary.  Required outcomes:  - generated bootstrap replicate weights are finite and non-negative, and every   replicate matrix is validated before estimation; - custom BRR matrices are admitted only when their encoded half-samples are   balanced and orthogonal, while the existing published 0/1 fixture remains   supported; - missing or blank strata/PSU identifiers fail closed at design construction; - survey design projections require explicit supported variance method and   variance source, so incomplete or naive metadata cannot be presented as   design-based evidence; - the executable survey artifact records the variance source and central   Agent/Notebook/Report projections accept all currently wired supported   families, including Probit and Poisson; - design effects remain finite for normalized weights whose total is not larger   than the observation count, using an explicit with-replacement reference   rather than an invalid negative finite-population correction; - focused tests prove the red failures and green fixes, and browser/provider/   host/release acceptance remain separate NOT VERIFIED gates.  This line does not add unimplemented survey model families, infer a design from raw data, or turn naive standard errors into survey evidence.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/4 (25.0%; 25.0 per 100 events)
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

- #2 2026-08-22T17:56:04.732Z `red_test`; cause_status: `known`; cause: Survey adversarial probes showed negative bootstrap weights, unvalidated BRR balance, missing design identifiers accepted as strings, incomplete variance metadata accepted by projection, and central Probit/Poisson family mapping unavailable.; resolution: `open`; lesson: Survey design validation must cover generated replicate weights, identifiers, projection metadata, and family coverage together.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `survey-p1-adversarial-closure`: occurrences=1; cause_status: `known`; root cause: Survey adversarial probes showed negative bootstrap weights, unvalidated BRR balance, missing design identifiers accepted as strings, incomplete variance metadata accepted by projection, and central Probit/Poisson family mapping unavailable.; solution: `open`

## Added tests

- `survey focused suite: 146 passed, 2 warnings; report projection unavailable-boundary regression passed`

## New rules

- `survey-p1-adversarial-closure`: line experience occurrence(s)=1

## Future guidance

- Survey design validation must cover generated replicate weights, identifiers, projection metadata, and family coverage together.

## Event index

- #1: `f5968b41-a0e0-4f04-b92b-671be37f491f` | 2026-08-22T17:51:33.264Z | STATE_CHANGE/line_started | incident=`86667c2a-6838-4305-883e-50df9e117e8e` | lesson_key=`frozen-context-before-start` | event_sha256=`251f8057be1ff5608408ecccc2349591a38491b23999e9e13da8ae4e740d0be5`
- #2: `6b5d2b82-5c3d-4f2c-9c9a-8ed1f6b06b27` | 2026-08-22T17:56:04.732Z | FAILURE/red_test | incident=`e2e72be3-2cdf-4af5-97a3-46b7a4377bb0` | lesson_key=`survey-p1-adversarial-closure` | event_sha256=`f23e3fd50283eed84d8bdb5d79b324d32806d14b897a42e3bdea268989e0ffc2`
- #3: `7c1e5a9b-4d2f-46a8-9b30-5e7d1c2f8a64` | 2026-08-22T18:04:30.117Z | GATE/survey_correctness_focused_green | incident=`a4d7f2c9-6e1b-48a3-9c50-7b2d5f8e1a63` | lesson_key=`survey-correctness-focused-green` | event_sha256=`d6e5bd9f8577d0675dc750bc40c30efc1c2608c036c0aa23f205c2c2ca19c2ef`
- #4: `d7a2f5c9-1e64-4b80-9a3f-6c2e8d5b7f10` | 2026-08-22T18:06:56.850Z | STATE_CHANGE/survey_correctness_line_completed | incident=`e4b7c2f9-6d1a-48e0-9c35-7a2d5f8b1e64` | lesson_key=`survey-correctness-line-completion` | event_sha256=`7473180e92b76cafa9cc53fd495dc0b614d9df3490b4776a19f18ed2817d4537`
