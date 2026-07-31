# Retrospective — v1-8-4-model-term-reuse

## Goal

v1.8.4 Model Term Reuse  Objective  Let a declared polynomial term reuse a persisted derived column when that column provably is the requested term, matching the semantics categorical expansion already applies to persisted indicators. A workflow that composes a model on a dataset already carrying a derived power column from an earlier composed workflow currently fails before fitting, even when the existing column holds exactly the requested power of exactly the requested source.  Reuse is admitted only after an explicit value comparison against the server-derived term: identical missing-value positions, and finite values equal within a strict floating-point tolerance that admits a serialization round trip while rejecting any difference of analytical consequence. Any other same-named column is refused, so the workflow fails closed rather than silently overwriting a column or fitting against a term it did not derive.  Non-goals  No change to categorical reuse, which already compares values. No formula evaluator, no relaxation of the collision rule for columns that do not match, and no reuse based on name equality alone. No change to how derived columns are named or persisted.  Acceptance  Focused tests prove that an exactly equal persisted power column is reused, that a same-named column whose values differ fails closed, that a column differing only by serialization round trip is still reused, and that mismatched missing-value positions are refused. Existing categorical reuse behaviour is unchanged and the full gate stays green.

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
- Gate waste rate: 0/2 (0.0%)
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

- #1: `bc48937c-1ac6-4717-be24-19ba4e6ee688` | 2026-07-31T01:12:48.613Z | STATE_CHANGE/line_started | incident=`ac530d9f-4fa4-4e84-9910-56c2b7f65904` | lesson_key=`frozen-context-before-start` | event_sha256=`b1c8bb882790157749f54e9ae0a152c07c3da7541bf613231bc8cb4d59e57c89`
- #2: `3228c018-cdeb-47c3-959c-d6a8742eb773` | 2026-07-31T05:30:00.000Z | GATE/polynomial_term_reuse_implemented | incident=`7634938a-b26e-4c46-9e18-02190ee73632` | lesson_key=`verified-categorical-indicator-reuse` | event_sha256=`d89db2b285d978c983690ea187fd7798aab10c014af39afa0a2cfde2dd8a4830`
- #3: `95cdcee2-1e37-4805-8647-d5804105d88b` | 2026-07-31T02:40:00.000Z | GATE/v1_8_4_release_gate | incident=`53eae867-ca1f-401f-b1da-b8804ee373f4` | lesson_key=`v1-8-4-release-gate` | event_sha256=`e6b150615b3d750dbb7a5f9d695b014712060f9babab88c81ebe9b09cc8c13a6`
- #4: `15618dc5-d5f3-4588-922a-bdc5f1f5a607` | 2026-07-31T02:50:00.000Z | STATE_CHANGE/model_term_reuse_completed | incident=`c27a6557-1387-4d84-baee-479cfa71e7b5` | lesson_key=`derived-column-reuse-requires-value-identity` | event_sha256=`b4c763f097269d2af1c5705126c1b802309b51b3003e0cc5ed8108f1bf6df259`
