# Retrospective — v1-8-9-p1-classification-search-threshold-alignment

## Goal

# Objective: v1.8.9 P1 classification search threshold alignment  ## Objective  Make bounded classification model search score every candidate with the same development-only decision rule used by the production classification protocol. The search must not rank candidates with a hidden fixed 0.5 threshold when the declared decision policy selects a different OOF threshold. The change must preserve holdout sealing, typed evidence, bounded receipts, and fail-closed behavior.  ## Acceptance criteria  - A production bounded-search trial derives its threshold from that trial's   development OOF probabilities using the declared decision policy. - Search and final model comparison expose the same primary-metric value for   the same candidate and immutable split. - Threshold scope remains development-only and no holdout labels or   probabilities enter the search evaluator. - Generic \`run_bounded_search\` callers remain backward compatible: the   evaluator still supplies a typed development OOF metric bundle. - Regression tests cover max-F1 and precision-constrained threshold policies,   and the existing classification/search suites remain green.  ## Boundaries  In scope: the production classification search evaluator and its tests. Out of scope: new model families, provider startup, browser acceptance, and release/tag operations.  ## Known gates  Browser acceptance, real provider acceptance, host/full gate, merge/tag, and release readiness are not verified by this objective.

## Final status

COMPLETED_WITH_KNOWN_GATES

## Metrics

- Failure frequency: 1/7 (14.3%; 14.3 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=2192636 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-22T18:13:41.085Z `classification_search_threshold_alignment_red`; cause_status: `known`; cause: Production bounded-search trials score thresholded metrics at a fixed 0.5 cutoff, while the final model comparison uses the declared development OOF threshold selected by the decision policy.; resolution: `open`; lesson: Search evaluators must consume the same typed threshold policy and development OOF scope as the final model comparison.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `classification-search-threshold-alignment-red`: occurrences=1; cause_status: `known`; root cause: Production bounded-search trials score thresholded metrics at a fixed 0.5 cutoff, while the final model comparison uses the declared development OOF threshold selected by the decision policy.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `classification-search-threshold-alignment-red`: line experience occurrence(s)=1

## Future guidance

- Close a RED incident on its original incident identity after the matching regression evidence passes.
- Search evaluators must consume the same typed threshold policy and development OOF scope as the final model comparison.
- Treat search receipts as a typed projection of the same family-specific decision contract, not as a second scoring implementation.

## Event index

- #1: `3cd77567-2f1c-4509-9f39-277e629d1d4a` | 2026-08-22T18:12:16.738Z | STATE_CHANGE/line_started | incident=`c05f8c01-44e3-47c8-9c85-39e97477eb30` | lesson_key=`frozen-context-before-start` | event_sha256=`5e7b82c783be4101fbffba07f7fa44f302a7dc7ac65a398a803dc5ced1594f7e`
- #2: `d6f4c3b2-a190-4e87-9f65-2c1b0a8d7e43` | 2026-08-22T18:13:41.085Z | FAILURE/classification_search_threshold_alignment_red | incident=`c7e6d5f4-a3b2-4c19-8d7e-6f5a4b3c2d10` | lesson_key=`classification-search-threshold-alignment-red` | event_sha256=`9606dcd2361747ea22b7c6dca3d7663abc4845bf7de928814e654281f23a6a9b`
- #3: `b8c2e6f1-4a7d-49c3-8e15-2f6b0a9d7c34` | 2026-08-22T18:18:31.896Z | GATE/classification_search_threshold_alignment_green | incident=`c4e8a1d7-9b52-46f0-8c3a-7e1d5b9a2f64` | lesson_key=`classification-search-threshold-alignment` | event_sha256=`6cadaf12edccbf0c3f597bae1354e2df8f5920d77008129961ee6a9dece708dd`
- #4: `e5c4b3a2-9180-4f76-9e5d-3c2b1a0f8d64` | 2026-08-22T18:20:05.171Z | GATE/classification_search_threshold_alignment_green | incident=`f8e7d6c5-b4a3-4f29-8e7d-6c5b4a3d2f10` | lesson_key=`classification-search-threshold-alignment-green` | event_sha256=`4cdd94f455a81d080a81cbf644afa80f5805944adb06dcd34950a747d983ffe4`
- #5: `a1b2c3d4-e5f6-4789-9abc-d1e2f3a4b5c6` | 2026-08-22T18:21:26.687Z | REVIEW/classification_search_threshold_alignment_review | incident=`b2c3d4e5-f6a7-4890-abcd-e2f3a4b5c6d7` | lesson_key=`classification-search-threshold-alignment-review` | event_sha256=`2a0abce79ddc62bb945fed3fee5991a309917d350bfc3e726624ee209fe4aaab`
- #6: `c3d4e5f6-a7b8-4901-bcde-f3a4b5c6d7e8` | 2026-08-22T18:21:46.479Z | STATE_CHANGE/line_completed_with_known_gates | incident=`d4e5f6a7-b8c9-4012-cdef-a4b5c6d7e8f9` | lesson_key=`classification-search-package-boundary-complete` | event_sha256=`190fe7463524bb99e9a0572664e89d663e7e5d587afdbbdd52c9222f2da292d8`
- #7: `a4b5c6d7-e8f9-4012-3a4b-5c6d7e8f9012` | 2026-08-22T18:50:13.721Z | REVIEW/classification_search_threshold_alignment_incident_resolved | incident=`c7e6d5f4-a3b2-4c19-8d7e-6f5a4b3c2d10` | lesson_key=`classification-search-threshold-alignment-red` | event_sha256=`1e587ebae480e770341eaf4e19b27a30148038f4cd1456740832736d6dfc09fa`
