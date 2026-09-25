# Retrospective — v1-8-9-p1-classification-correctness-central-closure

## Goal

# Workbench v1.8.9 P1 — classification correctness and central consumer closure  ## Objective  Close the remaining P1 classification-ML gaps in the candidate worktree. The production protocol must select models from the declared development OOF probabilities under the selected decision threshold, calculate probability metrics from probabilities, keep calibration and threshold scopes truthful, and produce bounded explanations when the model family supports them. Agent, Notebook, and Report must consume the same server-owned typed classification projection for a persisted run; no consumer may reconstruct classification results from generic raw-result readers.  ## Acceptance criteria  1. Model comparison uses the declared thresholded OOF predictions for metrics    whose definition is thresholded, and probability metrics use probabilities. 2. \`threshold_curve\` calculates log loss from probability columns, not hard    class labels; threshold records name the actual input scope. 3. Supported classification models emit bounded, typed explanation evidence or    a truthful unavailable/degraded reason with stable provenance. 4. Agent, Notebook, and Report central readers return the same persisted    classification projection, including status, source identity, comparison,    threshold, calibration, and explanations. 5. Holdout remains sealed until the existing explicit release boundary, and all    invalid, malformed, or unbound packets fail closed.  ## In scope  - \`backend/workbench/predictive_research/classification_protocol.py\` - \`backend/workbench/predictive_research/classification_metrics.py\` - \`backend/workbench/predictive_research/classification_explanations.py\` - \`backend/workbench/prediction.py\` - \`backend/workbench/services/classification_consumer_service.py\` - \`backend/workbench/agent/context_tools.py\` - \`backend/workbench/agent/notebook/evidence.py\` - \`tests/test_v189_classification_p1_correctness_central_closure.py\` - relevant existing classification protocol, production, and central-consumer tests  ## Out of scope / known gates  Browser acceptance, real provider execution, host-only full-gate containment, release packaging, and external benchmark parity are separate gates and must not be represented as passed by this line.  ## Safety and extensibility constraints  Keep the protocol family-agnostic and typed: use adapter capabilities and projection contracts rather than model-name branches where possible. Preserve server-owned identity and evidence provenance. Do not expose raw serialized model state, arbitrary file paths, or unbounded explanation payloads to Agent, Notebook, or Report.

## Final status

COMPLETED_WITH_KNOWN_GATES

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

- #2 2026-08-22T18:00:28.389Z `classification_p1_red_probes`; cause_status: `known`; cause: The threshold curve computes log loss from hard labels; model comparison keeps a fixed 0.5 cutoff; and the persisted threshold packet does not expose the declared development OOF scope.; resolution: `open`; lesson: Protocol tests must compare persisted thresholds, row scope, and metric semantics rather than only checking that a run completes.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `classification-p1-red-probes`: occurrences=1; cause_status: `known`; root cause: The threshold curve computes log loss from hard labels; model comparison keeps a fixed 0.5 cutoff; and the persisted threshold packet does not expose the declared development OOF scope.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `classification-p1-red-probes`: line experience occurrence(s)=1

## Future guidance

- Central consumer review must prove both positive identity sharing and negative generic-reader non-use.
- Protocol tests must compare persisted thresholds, row scope, and metric semantics rather than only checking that a run completes.

## Event index

- #1: `eef8571d-fb03-4bab-90cd-685069b7307b` | 2026-08-22T17:57:04.788Z | STATE_CHANGE/line_started | incident=`40c9c260-c919-4304-a19c-b60d94717a65` | lesson_key=`frozen-context-before-start` | event_sha256=`aac97cf7a1766ac7698f7366401f83bf0498a622066977a66b1cfa74466e3850`
- #2: `d7fef53a-1cbf-4f26-9b5c-943a3d87bf17` | 2026-08-22T18:00:28.389Z | FAILURE/classification_p1_red_probes | incident=`2bdb7d10-381e-4e64-84c8-4e4b34f0cb53` | lesson_key=`classification-p1-red-probes` | event_sha256=`a39959d967a6b35817229ab587f00e732a6c07c10f48cd6ab18f0c108e03aaf9`
- #3: `8ec5c91a-9f1a-4f08-89f0-6f1ed1a5d0c4` | 2026-08-22T18:04:24.988Z | GATE/classification_p1_correctness_green | incident=`c0a7e8f4-2d31-4b5c-9e60-71f8293a4d56` | lesson_key=`classification-p1-correctness-green` | event_sha256=`ea4917bb8aef166eabfb6212c704b836c1910d63b8bc496a435b91f5c128be81`
- #4: `2a4bf9d1-7e63-4c88-a105-9fd20e3b764a` | 2026-08-22T18:04:49.974Z | STATE_CHANGE/line_completed_with_known_gates | incident=`7c18e2f4-5b69-40ad-93e7-1f26c8d4a509` | lesson_key=`classification-p1-package-boundary-complete` | event_sha256=`952ac2a6e7c3b9f97de2763a75acb624d6d463ad89aa5a42b100b3b922f4b931`
- #5: `4d8e2f91-6a73-4b05-9c18-e2f7a4d0b563` | 2026-08-22T18:05:20.273Z | REVIEW/classification_p1_scope_review | incident=`5e9a1c73-4b82-46d0-9f15-2a7c8e4d6b10` | lesson_key=`classification-p1-boundary-review` | event_sha256=`969491802cd286cc8e16aee11e12b300ec9b7f1488d03b58016b7bd3d87f50f5`
