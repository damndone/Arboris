# Retrospective — v1-8-5-a5-model-packet-lineage-label

## Goal

# Workbench v1.8.5 A5 — model packet lineage label correctness  ## Objective  Ensure the shared estimation-to-lineage boundary derives the model identity from the authoritative public result payload when a model pack returns a packet envelope. A packed time-series result must never be displayed as the legacy \`ols (primary)\` label in Graph, Table, Report, or downstream evidence.  ## Scope  Allowed implementation paths:  - \`backend/workbench/engine/stages/estimation.py\` - \`tests/engine/test_lmm_execution_admission.py\` - this objective document  The change is limited to the existing \`_result_for_downstream\` boundary and its regression tests. It must preserve the LMM packet contract and the direct result shape of built-in handlers.  ## Acceptance  - A packet whose authoritative nested \`result.model_type\` is   \`time_series.ets\` is exposed to legacy downstream stages with that model   type, so RecordingStage cannot fall back to OLS. - The existing LMM unwrapping behavior remains unchanged. - Direct result payloads remain unchanged. - Focused backend tests and TypeScript/diff checks pass. - No browser claim is made by this line; browser acceptance remains separate.  ## Non-goals  - No model-specific label map in the frontend. - No special case for ETS. - No change to result persistence, model selection, or statistical semantics.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=240000 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-01T22:20:00.000Z `tdd_red_model_packet_downstream_unwrap`; cause_status: `known`; cause: The shared estimation-to-downstream boundary returned the ETS packet envelope instead of its authoritative nested result payload.; resolution: `open`; lesson: Every model packet envelope must be unwrapped at the shared legacy-consumer boundary by authoritative nested model type, not by model-specific frontend labels.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `model-packet-downstream-boundary`: occurrences=1; cause_status: `known`; root cause: The shared estimation-to-downstream boundary returned the ETS packet envelope instead of its authoritative nested result payload.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `model-packet-downstream-boundary`: line experience occurrence(s)=1

## Future guidance

- Every model packet envelope must be unwrapped at the shared legacy-consumer boundary by authoritative nested model type, not by model-specific frontend labels.
- Use one server-side packet-to-legacy projection boundary for model identity; do not repair model labels in the frontend.

## Event index

- #1: `5b5e4631-b471-4e70-8224-277160f60151` | 2026-08-01T22:16:10.264Z | STATE_CHANGE/line_started | incident=`3906831f-57d2-4c3b-ac57-0a777c4e2bbb` | lesson_key=`frozen-context-before-start` | event_sha256=`b2395024e38b5762ae47ec578d30c47df7b77ea47866fbe47a0ff0c2746fd741`
- #2: `2e9f7920-2a06-4c94-9441-0c72042e5f47` | 2026-08-01T22:20:00.000Z | FAILURE/tdd_red_model_packet_downstream_unwrap | incident=`2e9f7920-2a06-4c94-9441-0c72042e5f47` | lesson_key=`model-packet-downstream-boundary` | event_sha256=`550fdcc84b07747341db50cd2eaaca0141dbc8777ffd248579b8270f483d82b4`
- #3: `4c67f2fa-32bb-479f-b3d1-eac10dcae8f7` | 2026-08-01T22:24:00.000Z | REVIEW/a5_model_packet_boundary_verified | incident=`2e9f7920-2a06-4c94-9441-0c72042e5f47` | lesson_key=`model-packet-downstream-boundary` | event_sha256=`b88c1b47305912fcc457b1952be043c2514eee9ec37a381a77f738d8166d1462`
- #4: `6c9e5d83-5f64-4e66-b67b-26fbe9de4c75` | 2026-08-01T22:24:00.000Z | GATE/a5_model_packet_boundary_gate_passed | incident=`2e9f7920-2a06-4c94-9441-0c72042e5f47` | lesson_key=`model-packet-downstream-boundary` | event_sha256=`a59f4540665fb4b23d5c0164018b052658a521f0264ec9bb48d6be99c4e9f20a`
- #5: `8f434e33-051d-4384-82b4-1d08e37cbb2a` | 2026-08-01T22:24:00.000Z | STATE_CHANGE/a5_model_packet_lineage_label_completed | incident=`2e9f7920-2a06-4c94-9441-0c72042e5f47` | lesson_key=`model-packet-downstream-boundary` | event_sha256=`c51f326b0b85a5e406afd32a039fd480f4a1d5fe3d041c817b13d1cbe1d1b9fc`
