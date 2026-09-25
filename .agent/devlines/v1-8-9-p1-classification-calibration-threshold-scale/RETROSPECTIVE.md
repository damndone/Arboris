# Retrospective — v1-8-9-p1-classification-calibration-threshold-scale

## Goal

# Objective: v1.8.9 P1 classification calibration/threshold scale  ## Objective  Make classification threshold evidence truthful when probability calibration is enabled. The development OOF threshold used for model comparison and search must remain distinct from the operational threshold consumed against calibrated holdout probabilities. No released prediction may compare calibrated probabilities with a raw-probability threshold.  ## Acceptance criteria  - \`selection_threshold\` is explicitly bound to the full development OOF raw   probability scope and remains the score used for model comparison/search. - \`threshold\` is explicitly bound to the disjoint development calibration   evaluation scope and the probability scale consumed at final holdout. - The selected operational threshold and its precision constraint are computed   on the same calibrated probability scale as final holdout predictions. - Threshold row identities, scopes, source labels, release-plan hashes, and   Agent/Notebook/Report projections remain typed and provenance-bound. - Holdout remains sealed until the existing C0 release boundary; malformed or   unavailable calibration/threshold evidence fails closed.  ## Boundaries  In scope: production classification threshold/calibration evidence and its tests. Out of scope: new model families, provider startup, browser acceptance, and release/tag operations.  ## Known gates  Browser acceptance, real provider acceptance, host/full gate, merge/tag, and release readiness are not verified by this objective.

## Final status

COMPLETED_WITH_KNOWN_GATES

## Metrics

- Failure frequency: 1/6 (16.7%; 16.7 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=544246 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-22T18:41:09.475Z `classification_calibration_threshold_scale_red`; cause_status: `known`; cause: The persisted operational threshold is labeled development_oof while final holdout predictions are transformed by the fitted calibrator; selection and operational threshold evidence are not separated by probability scale.; resolution: `open`; lesson: Every threshold record must name the probability scale, sample scope, and row identity consumed by the final decision.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `classification-calibration-threshold-scale-red`: occurrences=1; cause_status: `known`; root cause: The persisted operational threshold is labeled development_oof while final holdout predictions are transformed by the fitted calibrator; selection and operational threshold evidence are not separated by probability scale.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `classification-calibration-threshold-scale-red`: line experience occurrence(s)=1

## Future guidance

- Close a calibration incident only when final predictions and threshold evidence are proven to share one declared probability scale.
- Every threshold record must name the probability scale, sample scope, and row identity consumed by the final decision.
- Evidence should name both sample scope and probability scale so Agent, Notebook, Report, and final execution cannot silently mix calibrated and raw values.

## Event index

- #1: `22bc2840-9bff-4e59-a094-4603ec5d9d23` | 2026-08-22T18:40:34.297Z | STATE_CHANGE/line_started | incident=`2ccdccfa-81ab-4d8b-8209-c48c23ff1b57` | lesson_key=`frozen-context-before-start` | event_sha256=`26a6c5ebc79298c3eef4f4340c072376aaefb75e0bf06d0839065a63be22ef45`
- #2: `d7e6f5a4-b3c2-4910-8f7e-6d5c4b3a2e19` | 2026-08-22T18:41:09.475Z | FAILURE/classification_calibration_threshold_scale_red | incident=`e8f7d6c5-b4a3-2910-8f7e-6d5c4b3a2e19` | lesson_key=`classification-calibration-threshold-scale-red` | event_sha256=`5c0365a9287c00ae70b9dd428ce7a39299514bc14db3f72075d16ca9774a30f5`
- #3: `f6e5d4c3-b2a1-4908-7f6e-5d4c3b2a1f09` | 2026-08-22T18:45:55.593Z | GATE/classification_calibration_threshold_scale_green | incident=`a7b8c9d0-e1f2-4387-9a0b-c1d2e3f4a5b6` | lesson_key=`classification-calibration-threshold-scale-green` | event_sha256=`882b743aa04372f8af7747cd3d40be40f0a86ceb8129dc952e9c73befaa0d5e3`
- #4: `b9c8d7e6-f5a4-3210-9f8e-7d6c5b4a3e21` | 2026-08-22T18:47:34.265Z | REVIEW/classification_calibration_threshold_scale_review | incident=`c0d9e8f7-a6b5-4321-0fed-cba987654321` | lesson_key=`classification-calibration-threshold-scale-review` | event_sha256=`ab7c6f84933da392dce01c9b2dec8629305e437f3de80f941f1fdd0e84c966b0`
- #5: `e1f2a3b4-c5d6-4789-0a1b-2c3d4e5f6a70` | 2026-08-22T18:48:01.299Z | STATE_CHANGE/line_completed_with_known_gates | incident=`f2a3b4c5-d6e7-4890-1a2b-3c4d5e6f7081` | lesson_key=`classification-calibration-threshold-scale-complete` | event_sha256=`d8ad416303aa473a2acb7513b4274b8623bba21d600feeb95dd6526e2a7ea3e8`
- #6: `b5c6d7e8-f9a0-4123-4b5c-6d7e8f901234` | 2026-08-22T18:50:13.721Z | REVIEW/classification_calibration_threshold_scale_incident_resolved | incident=`e8f7d6c5-b4a3-2910-8f7e-6d5c4b3a2e19` | lesson_key=`classification-calibration-threshold-scale-red` | event_sha256=`64e9b012329000dec49c952e328488e967183a24c1f6c40905e62aad99306638`
