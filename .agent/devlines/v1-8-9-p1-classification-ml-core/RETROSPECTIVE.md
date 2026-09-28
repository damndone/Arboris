# Retrospective — v1-8-9-p1-classification-ml-core

## Goal

# Workbench v1.8.9 — P1 Classification ML Core Objective  Implement a model-agnostic, fail-closed classification capability and prove the extension seam with Logistic Regression and Random Forest adapters. The core must make class mapping, information-set availability, IID/group/temporal split safety, fold-local preprocessing, isolated holdout evaluation, metrics, calibration, baselines, controls, explanations and decision policy explicit typed artifacts. It must preserve provenance and evidence boundaries so a consumer can report facts without recomputing or turning model ranking into a decision.  This is a package-local Wave B contribution. It may use only public Contract Lock facades and must not modify central Agent/Notebook routing, the central Report mount, the section registry, or any sibling line's private modules. Provider and renderer declarations are contributions only; discovery and natural-language Agent/Notebook cutover belong to the later single-writer cutover line.  ## Safety and correctness requirements  - Unknown feature availability, unsupported structure, invalid label mapping,   insufficient class/group/period support and unjustified temporal safety fail   closed with typed reasons. - Learned preprocessing, resampling, calibration, threshold selection and   tuning are fold-local and cannot inspect sealed holdout labels or predictions. - Holdout access is one-time, predeclared and auditable; DecisionPolicy is   separate from model selection and unknown costs produce scenarios only. - Metrics preserve denominator, weighting, sample scope, numerical method,   evaluation design, uncertainty and validation level. Undefined values are   unavailable/insufficient, never zero-filled. - Explanations are predictive/descriptive, not causal; subgroup and shift   claims remain bounded by support and the release plan. - Logistic and Random Forest share one adapter/protocol. Adding a fixture model   must not require compiler/runtime/consumer family branches.  ## Explicit non-goals and gates  - No central Agent/Notebook/Report/UI mount or route cutover. - No online scoring service or external provider benchmark. - C1 P0 package integration, real supervisor wiring, browser acceptance, full   release gate, merge, push and tag are \`NOT VERIFIED\` for this line.

## Final status

STARTED

## Metrics

- Failure frequency: 22/36 (61.1%; 61.1 per 100 events)
- Repeat rate: 0/22 (0.0%)
- Recurrence rate: 0/22 (0.0%)
- MTTR: median=0 ms (sample=14; unresolved=8)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/8 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T16:05:00.000Z `tdd_red_classification_adapter_seam`; cause_status: `known`; cause: The classification adapter, metric and explanation modules were intentionally absent when the new known-answer contract tests were first collected.; resolution: `accepted`; lesson: Freeze known-answer adapter, metric and explanation contracts before implementing the model family seam.
- #4 2026-08-16T16:02:00.000Z `classification_protocol_tdd_red`; cause_status: `known`; cause: The protocol boundary tests were added before the sealed-holdout orchestration module existed.; resolution: `open`; lesson: Define the holdout seal and protocol orchestration as a typed seam before exposing the result to consumers.
- #5 2026-08-16T15:56:48.000Z `classification_tdd_red`; cause_status: `known`; cause: The new classification tests first referenced absent typed contracts, the safe split manifest builder, and the fold-local classification preprocessor.; resolution: `resolved`; lesson: Keep classification contract and leakage tests red before adding the implementation surface.
- #6 2026-08-16T15:57:32.000Z `classification_edge_case_red`; cause_status: `known`; cause: Mutation-style edge tests exposed a datetime interval arithmetic assumption, missing-column misclassification, and empty decision costs being treated as invalid instead of unknown scenarios.; resolution: `resolved`; lesson: Exercise date-like intervals, missing columns, and unknown policy inputs explicitly before declaring the typed core green.
- #13 2026-08-16T16:10:00.000Z `classification_row_index_alignment`; cause_status: `known`; cause: The fold-local preprocessing numeric helper returned a RangeIndex series and pandas aligned it against server row IDs during assignment.; resolution: `resolved`; lesson: Information-set row identity must be preserved through every pandas transform; add a non-default-index regression probe.
- #17 2026-08-16T16:20:00.000Z `classification_multiclass_metric_averaging`; cause_status: `known`; cause: The first multiclass protocol path called the metric bundle without an explicit macro or weighted averaging policy.; resolution: `resolved`; lesson: Multiclass metrics must carry an explicit averaging policy at every fold, OOF, holdout and baseline evaluation.
- #18 2026-08-16T16:40:00.000Z `classification_unknown_cost_scenario_regression`; cause_status: `known`; cause: The new expected-utility validation applied required cost keys to an empty cost mapping, although an empty mapping is the existing typed representation for unknown costs.; resolution: `resolved`; lesson: Unknown policy inputs must retain their explicit scenarios-only state; only non-empty malformed declarations should fail closed.
- #20 2026-08-16T17:05:00.000Z `classification_temporal_warmup_oof`; cause_status: `known`; cause: The temporal rolling split includes a development warm-up period without a validation fold, but the first protocol treated every development row as an OOF row.; resolution: `resolved`; lesson: OOF evidence is exactly the development rows assigned to validation folds; warm-up and purged rows must never enter OOF metrics or threshold selection.
- #23 2026-08-16T16:19:51.000Z `classification_temporal_panel_split_correctness`; cause_status: `known`; cause: The classification split manifest did not expose a forward-only training role for temporal validation folds and did not reject a panel_known_entity_future holdout entity absent from development.; resolution: `resolved`; lesson: Ordered split manifests must materialize auditable historical training row refs per fold and enforce the entity-set contract before execution.
- #33 2026-08-16T18:00:00.000Z `metric_evidence_red_test`; cause_status: `known`; cause: The new metric evidence assertions initially failed because metric_definition, structured denominator, weighted status, and evidence_basis were absent.; resolution: `resolved`; lesson: Write and observe evidence-semantic red tests before extending metric receipts.
- #34 2026-08-16T18:05:00.000Z `out_of_scope_classification_baseline`; cause_status: `known`; cause: The full two-file classification suite retained three pre-existing diagnostics/import failures outside the metric evidence subtask.; resolution: `accepted`; lesson: Keep out-of-scope protocol and diagnostics failures separate from focused metric evidence acceptance.

## All errors

- #9 2026-08-16T16:25:00.000Z `parallel_sibling_gate_intermediate_state`; cause_status: `known`; cause: The package-wide classification regression was run while the separate first worker was still writing shared classification protocol and leakage-test files; the observed failures were an intermediate OOF assertion and then a duplicate keyword syntax error in that sibling scope.; resolution: `accepted`; lesson: Run cross-line regression only after each parallel writer has reached a stable syntax and protocol checkpoint; keep its intermediate failures separate from the non-overlapping seam gate.
- #12 2026-08-16T16:12:00.000Z `classification_eager_import_cycle`; cause_status: `known`; cause: The new package exports eagerly imported artifact-backed consumer helpers while workbench.artifacts was still importing the schema registry.; resolution: `resolved`; lesson: Artifact-backed extensions must be lazy package exports so the existing artifact module remains acyclic.
- #25 2026-08-16T18:10:00.000Z `classification_holdout_refactor_baseline_scope`; cause_status: `known`; cause: Moving baseline computation into the one-shot holdout release callback left packet assembly reading majority_label and baseline_probability_matrix from the old outer scope.; resolution: `resolved`; lesson: When evidence is moved behind a release capability, every downstream field must consume the released typed bundle rather than the pre-refactor lexical scope.

## All gaps

- #8 2026-08-16T15:58:52.000Z `legacy_prediction_boundary_blocked`; cause_status: `external`; cause: The v1.8.6 prediction boundary regression imports artifacts before a pre-existing dirty predictive_research __init__.py; that unrelated package export imports consumer_projection and creates an artifacts circular import.; resolution: `accepted`; lesson: Separate an out-of-scope dirty baseline import failure from the classification kernel gate and do not alter unowned files to force green.
- #16 2026-08-16T16:35:00.000Z `classification_policy_cost_capacity_unused`; cause_status: `known`; cause: The first protocol version treated a non-empty cost matrix and capacity as sufficient for threshold selection but delegated selection to max_f1 without applying the declared policy semantics.; resolution: `resolved`; lesson: Decision policy fields must either affect the typed selection algorithm or fail closed; cost/utility and capacity semantics must be recorded in the threshold receipt.
- #19 2026-08-16T16:50:00.000Z `classification_negative_control_receipt_only`; cause_status: `known`; cause: The first protocol packet declared a shuffle-target control but did not execute a target permutation through the shared fold-local adapter path.; resolution: `resolved`; lesson: A control is evidence only when it runs on the declared exchangeability unit, split manifest and development-only scope; unsupported temporal/panel units must be unavailable rather than row-shuffled.
- #24 2026-08-16T16:19:51.000Z `classification_protocol_calibrator_regression`; cause_status: `known`; cause: The relevant classification protocol regression suite expects fit_probability_calibrator, but the current P1 classification_metrics module does not expose it.; resolution: `open`; lesson: Report split correctness separately from unrelated protocol implementation gaps; do not widen a scoped split fix to repair another package boundary.
- #26 2026-08-16T19:05:00.000Z `classification_packet_identity_missing_model_policy`; cause_status: `known`; cause: The packet identity initially included dataset, task, and split only, so changing the candidate model or DecisionPolicy could reuse an evidence artifact identity even though the result changed.; resolution: `resolved`; lesson: Typed evidence identity must bind every decision-relevant input, not only the data and split snapshots.
- #27 2026-08-16T17:00:03.000Z `classification_entrypoint_external_gap`; cause_status: `external`; cause: The full persistence and Graph subset reached the existing typed classification entrypoint, which fails in classification_metrics.py because development_calibration_eval is rejected as a calibrator transform scope.; resolution: `open`; lesson: Keep persistence hardening evidence separate from unrelated classification protocol or metrics failures outside the authorized boundary.
- #28 2026-08-16T17:01:21.000Z `classification_multiclass_calibration_gap`; cause_status: `external`; cause: The full classification consumer suite fails in classification_protocol.py for two multiclass cases because the calibration branch raises on incomplete OOF probability refs before any persistence consumer runs.; resolution: `open`; lesson: Do not widen a persistence hardening change to repair an unrelated multiclass protocol calibration boundary.
- #31 2026-08-16T18:35:00.000Z `classification_blocked_projection_model_metrics`; cause_status: `known`; cause: The blocked consumer projection redacted evaluation, baseline, control, comparison, and explanation sections but still forwarded candidate models containing development metrics and selection scores.; resolution: `resolved`; lesson: Fail-closed projections must audit every route by which formal numeric evidence can escape, including candidate lists and policy metadata.

## All waste

- None recorded.

## Root causes and solutions

- `classification-blocked-projection-total-redaction`: occurrences=1; cause_status: `known`; root cause: The blocked consumer projection redacted evaluation, baseline, control, comparison, and explanation sections but still forwarded candidate models containing development metrics and selection scores.; solution: `resolved`
- `classification-contract-first`: occurrences=1; cause_status: `known`; root cause: The classification adapter, metric and explanation modules were intentionally absent when the new known-answer contract tests were first collected.; solution: `accepted`
- `classification-controls-are-executed-or-unavailable`: occurrences=1; cause_status: `known`; root cause: The first protocol packet declared a shuffle-target control but did not execute a target permutation through the shared fold-local adapter path.; solution: `resolved`
- `classification-edge-cases-before-green`: occurrences=1; cause_status: `known`; root cause: Mutation-style edge tests exposed a datetime interval arithmetic assumption, missing-column misclassification, and empty decision costs being treated as invalid instead of unknown scenarios.; solution: `resolved`
- `classification-exports-stay-acyclic`: occurrences=1; cause_status: `known`; root cause: The new package exports eagerly imported artifact-backed consumer helpers while workbench.artifacts was still importing the schema registry.; solution: `resolved`
- `classification-focused-gate-separation`: occurrences=1; cause_status: `known`; root cause: The full two-file classification suite retained three pre-existing diagnostics/import failures outside the metric evidence subtask.; solution: `accepted`
- `classification-metric-evidence-semantics`: occurrences=1; cause_status: `known`; root cause: The new metric evidence assertions initially failed because metric_definition, structured denominator, weighted status, and evidence_basis were absent.; solution: `resolved`
- `classification-multiclass-averaging-is-explicit`: occurrences=1; cause_status: `known`; root cause: The first multiclass protocol path called the metric bundle without an explicit macro or weighted averaging policy.; solution: `resolved`
- `classification-oof-excludes-warmup`: occurrences=1; cause_status: `known`; root cause: The temporal rolling split includes a development warm-up period without a validation fold, but the first protocol treated every development row as an OOF row.; solution: `resolved`
- `classification-ordered-splits-materialize-history-and-entity-set`: occurrences=1; cause_status: `known`; root cause: The classification split manifest did not expose a forward-only training role for temporal validation folds and did not reject a panel_known_entity_future holdout entity absent from development.; solution: `resolved`
- `classification-packet-identity-binds-decision-inputs`: occurrences=1; cause_status: `known`; root cause: The packet identity initially included dataset, task, and split only, so changing the candidate model or DecisionPolicy could reuse an evidence artifact identity even though the result changed.; solution: `resolved`
- `classification-policy-fields-are-executable`: occurrences=1; cause_status: `known`; root cause: The first protocol version treated a non-empty cost matrix and capacity as sufficient for threshold selection but delegated selection to max_f1 without applying the declared policy semantics.; solution: `resolved`
- `classification-protocol-seam-first`: occurrences=1; cause_status: `known`; root cause: The protocol boundary tests were added before the sealed-holdout orchestration module existed.; solution: `open`
- `classification-release-bundle-consumer-scope`: occurrences=1; cause_status: `known`; root cause: Moving baseline computation into the one-shot holdout release callback left packet assembly reading majority_label and baseline_probability_matrix from the old outer scope.; solution: `resolved`
- `classification-row-identity-survives-transform`: occurrences=1; cause_status: `known`; root cause: The fold-local preprocessing numeric helper returned a RangeIndex series and pandas aligned it against server row IDs during assignment.; solution: `resolved`
- `classification-split-verification-keeps-protocol-gap-separate`: occurrences=1; cause_status: `known`; root cause: The relevant classification protocol regression suite expects fit_probability_calibrator, but the current P1 classification_metrics module does not expose it.; solution: `open`
- `classification-tdd-red-before-implementation`: occurrences=1; cause_status: `known`; root cause: The new classification tests first referenced absent typed contracts, the safe split manifest builder, and the fold-local classification preprocessor.; solution: `resolved`
- `classification-unknown-policy-stays-scenarios`: occurrences=1; cause_status: `known`; root cause: The new expected-utility validation applied required cost keys to an empty cost mapping, although an empty mapping is the existing typed representation for unknown costs.; solution: `resolved`
- `out-of-scope-baseline-gap-separate`: occurrences=1; cause_status: `external`; root cause: The v1.8.6 prediction boundary regression imports artifacts before a pre-existing dirty predictive_research __init__.py; that unrelated package export imports consumer_projection and creates an artifacts circular import.; solution: `accepted`
- `persistence-gate-keeps-external-classification-gap-separate`: occurrences=1; cause_status: `external`; root cause: The full persistence and Graph subset reached the existing typed classification entrypoint, which fails in classification_metrics.py because development_calibration_eval is rejected as a calibrator transform scope.; solution: `open`
- `persistence-suite-keeps-multiclass-gap-separate`: occurrences=1; cause_status: `external`; root cause: The full classification consumer suite fails in classification_protocol.py for two multiclass cases because the calibration branch raises on incomplete OOF probability refs before any persistence consumer runs.; solution: `open`
- `stable-sibling-checkpoint-before-regression`: occurrences=1; cause_status: `known`; root cause: The package-wide classification regression was run while the separate first worker was still writing shared classification protocol and leakage-test files; the observed failures were an intermediate OOF assertion and then a duplicate keyword syntax error in that sibling scope.; solution: `accepted`

## Added tests

- `tests/predictive_research/test_classification_consumers_v189.py`
- `tests/predictive_research/test_classification_protocol_v189.py`
- `tests/predictive_research/test_classification_protocol_v189.py::test_known_answer_binary_metrics_keep_denominators_and_calibration_evidence`

## New rules

- `classification-blocked-projection-total-redaction`: line experience occurrence(s)=1
- `classification-contract-first`: line experience occurrence(s)=1
- `classification-controls-are-executed-or-unavailable`: line experience occurrence(s)=1
- `classification-edge-cases-before-green`: line experience occurrence(s)=1
- `classification-exports-stay-acyclic`: line experience occurrence(s)=1
- `classification-focused-gate-separation`: line experience occurrence(s)=1
- `classification-metric-evidence-semantics`: line experience occurrence(s)=1
- `classification-multiclass-averaging-is-explicit`: line experience occurrence(s)=1
- `classification-oof-excludes-warmup`: line experience occurrence(s)=1
- `classification-ordered-splits-materialize-history-and-entity-set`: line experience occurrence(s)=1
- `classification-packet-identity-binds-decision-inputs`: line experience occurrence(s)=1
- `classification-policy-fields-are-executable`: line experience occurrence(s)=1
- `classification-protocol-seam-first`: line experience occurrence(s)=1
- `classification-release-bundle-consumer-scope`: line experience occurrence(s)=1
- `classification-row-identity-survives-transform`: line experience occurrence(s)=1
- `classification-split-verification-keeps-protocol-gap-separate`: line experience occurrence(s)=1
- `classification-tdd-red-before-implementation`: line experience occurrence(s)=1
- `classification-unknown-policy-stays-scenarios`: line experience occurrence(s)=1
- `out-of-scope-baseline-gap-separate`: line experience occurrence(s)=1
- `persistence-gate-keeps-external-classification-gap-separate`: line experience occurrence(s)=1
- `persistence-suite-keeps-multiclass-gap-separate`: line experience occurrence(s)=1
- `stable-sibling-checkpoint-before-regression`: line experience occurrence(s)=1

## Future guidance

- A control is evidence only when it runs on the declared exchangeability unit, split manifest and development-only scope; unsupported temporal/panel units must be unavailable rather than row-shuffled.
- A green seam review is not an integration claim; preserve the later protocol, evidence consumer and host/provider gates as separate acceptance boundaries.
- Artifact-backed extensions must be lazy package exports so the existing artifact module remains acyclic.
- Correctness review must probe the order and identity of real data consumption, not only the shape of a final packet; remaining browser, provider, and central cutover gates stay separate.
- Decision policy fields must either affect the typed selection algorithm or fail closed; cost/utility and capacity semantics must be recorded in the threshold receipt.
- Define the holdout seal and protocol orchestration as a typed seam before exposing the result to consumers.
- Do not widen a persistence hardening change to repair an unrelated multiclass protocol calibration boundary.
- Exercise date-like intervals, missing columns, and unknown policy inputs explicitly before declaring the typed core green.
- Fail-closed projections must audit every route by which formal numeric evidence can escape, including candidate lists and policy metadata.
- Freeze known-answer adapter, metric and explanation contracts before implementing the model family seam.
- Green package tests are not sufficient when they do not probe information order, metric direction, policy status, class-column identity, or actual holdout release ordering.
- Holdout subgroup and shift evidence must be an exact, immutable, predeclared section with a self-contained plan and descriptive-only statistics.
- Information-set row identity must be preserved through every pandas transform; add a non-default-index regression probe.
- Keep classification contract and leakage tests red before adding the implementation surface.
- Keep out-of-scope protocol and diagnostics failures separate from focused metric evidence acceptance.
- Keep persistence hardening evidence separate from unrelated classification protocol or metrics failures outside the authorized boundary.
- Multiclass metrics must carry an explicit averaging policy at every fold, OOF, holdout and baseline evaluation.
- OOF evidence is exactly the development rows assigned to validation folds; warm-up and purged rows must never enter OOF metrics or threshold selection.
- Ordered split manifests must materialize auditable historical training row refs per fold and enforce the entity-set contract before execution.
- Report split correctness separately from unrelated protocol implementation gaps; do not widen a scoped split fix to repair another package boundary.
- Review safety predicates and evidence boundaries separately from model-family expansion and central cutover.
- Run cross-line regression only after each parallel writer has reached a stable syntax and protocol checkpoint; keep its intermediate failures separate from the non-overlapping seam gate.
- Separate an out-of-scope dirty baseline import failure from the classification kernel gate and do not alter unowned files to force green.
- Typed evidence identity must bind every decision-relevant input, not only the data and split snapshots.
- Unknown policy inputs must retain their explicit scenarios-only state; only non-empty malformed declarations should fail closed.
- When evidence is moved behind a release capability, every downstream field must consume the released typed bundle rather than the pre-refactor lexical scope.
- Write and observe evidence-semantic red tests before extending metric receipts.

## Event index

- #1: `ae7fd091-7ca7-4862-8e03-6c9b4d55e545` | 2026-08-16T15:42:22.087Z | STATE_CHANGE/line_started | incident=`067f27c5-029e-48fc-965d-a6563782597a` | lesson_key=`frozen-context-before-start` | event_sha256=`12325a9005563f2f8d3b3d170c38d27d7a833bde9904c7a42d6b4767d6113961`
- #2: `7f7d6bc4-c07f-4d36-9a54-53e4ea1d6a01` | 2026-08-16T16:05:00.000Z | FAILURE/tdd_red_classification_adapter_seam | incident=`0f5f1a1c-9ae6-4e33-9c67-ef6b9d8e7001` | lesson_key=`classification-contract-first` | event_sha256=`65ab119cc0be565f2f64bd085b0197c441227be368cc582da0a06d51abf3be57`
- #3: `f3b44f35-7f4f-4c43-8e53-3c0b0d38dd75` | 2026-08-16T15:50:00.000Z | GATE/tdd_red | incident=`a3188e11-6c33-49b6-93f6-a6b57d44a1fa` | lesson_key=`classification-consumer-tdd-red` | event_sha256=`1d67340812a7c12efa83f7950af2270aca31322bffaf3aee9a0830a04cd40718`
- #4: `65a63d9e-3a28-4800-a2da-8a7e6f12fef5` | 2026-08-16T16:02:00.000Z | FAILURE/classification_protocol_tdd_red | incident=`2e921a9f-d6e6-4f21-9ba1-3eab53985f7b` | lesson_key=`classification-protocol-seam-first` | event_sha256=`5744cea5916c948320737f14ec7f91a0200e806c41a715e63dd427e1a18d9aa3`
- #5: `9b2f5e8d-4d7f-4f3f-9dc1-3b7e9c3f8d10` | 2026-08-16T15:56:48.000Z | FAILURE/classification_tdd_red | incident=`f0a66c53-7e37-4c89-b8e3-9d6b4a2f1c80` | lesson_key=`classification-tdd-red-before-implementation` | event_sha256=`f554e6b16919549581782917df8f754752142313d1b7f0c31e31df35f83495cb`
- #6: `a4c8d2e7-1f39-4a65-9b02-6e7d3c5f8a14` | 2026-08-16T15:57:32.000Z | FAILURE/classification_edge_case_red | incident=`c3f8a2d6-9e14-4b70-8c35-1a6d7f2e9b04` | lesson_key=`classification-edge-cases-before-green` | event_sha256=`1ccfccf5979dd80dc4a1d26eec145a3de51fb58c847f813898852a8083a39449`
- #7: `d7e1a4c9-2f63-4b80-9a15-6c8d3e7f2b04` | 2026-08-16T15:58:14.000Z | GATE/classification_core_focused_green | incident=`e2c7a4d9-1f63-4b80-9a15-6c8d3e7f2b04` | lesson_key=`classification-focused-gate-separate` | event_sha256=`c9f6d4281d7bcdead63d541217981527af78d7d964dd58abae160cdf2ee8652e`
- #8: `f3a9d6e1-7c24-4b80-9f15-2d8e6a4c7b03` | 2026-08-16T15:58:52.000Z | GAP/legacy_prediction_boundary_blocked | incident=`b7e2c9a4-1f63-4d80-9b25-6c8e3a7f2d04` | lesson_key=`out-of-scope-baseline-gap-separate` | event_sha256=`dc213aa6e5da0cfbb1e00977375114acc834cdeaf844eb905b6972b051867907`
- #9: `1e3e9ce5-4f8e-4b4f-8dfd-bc5cc4c8a2c1` | 2026-08-16T16:25:00.000Z | ERROR/parallel_sibling_gate_intermediate_state | incident=`0d71bca1-7ddb-42e0-a3d9-947a16eb58b0` | lesson_key=`stable-sibling-checkpoint-before-regression` | event_sha256=`bca39d09525832d7cc6ce94e95bb64534dd8d0e35e449f51c1370032abf89313`
- #10: `c8e2a4d7-1f63-4b90-9d25-6c8e3a7f2b04` | 2026-08-16T15:59:28.000Z | REVIEW/classification_kernel_self_review | incident=`d7a4c9e2-1f63-4b80-9a25-6c8e3f7d2b04` | lesson_key=`classification-boundary-review` | event_sha256=`7aa55107e67534433cf976206630b054d20e4ff4613021374d7c7c44f1b422cc`
- #11: `e4a7c1d9-2f63-4b80-9d15-6c8e3a7f2b04` | 2026-08-16T16:00:42.000Z | GATE/classification_nonoverlap_line_final_gate | incident=`b7e2c9a4-1f63-4d80-9b25-6c8e3a7f2d04` | lesson_key=`classification-nonoverlap-gate-evidence` | event_sha256=`470c6a2b5f55f28f3d9e011b5b7b7043930622b7922274d182833fd5804fdb85`
- #12: `b8cfecfb-a864-47ef-a8c3-89b0ff4cffbc` | 2026-08-16T16:12:00.000Z | ERROR/classification_eager_import_cycle | incident=`b4f7fe5e-1d2f-4b17-94ad-ea3e9e2b8c10` | lesson_key=`classification-exports-stay-acyclic` | event_sha256=`25538b041333feb6e6fe33c76c328f10aa545b977273ca106b508c859286fa05`
- #13: `f8a4d0ca-3b5d-4a68-a1cc-286373f89df0` | 2026-08-16T16:10:00.000Z | FAILURE/classification_row_index_alignment | incident=`7e6793ed-f73c-4fcb-9daa-8ffcb01d84b2` | lesson_key=`classification-row-identity-survives-transform` | event_sha256=`1c5fe3936536ffe13ae721f54a9dcc6189b466bc93ec3ee2620f8ed97f5612ad`
- #14: `2c0dc3d7-5d94-4f5d-9db6-8d4d4e7a1a31` | 2026-08-16T16:40:00.000Z | GATE/classification_adapter_metrics_explanation_focused_gate | incident=`e4c7a7e4-8e6f-40b4-a32d-7a7a8f1c3e2d` | lesson_key=`classification-seam-focused-gate` | event_sha256=`02c717b7dadca0e4b8fa206590d1b38453a21d18744f62b8e20490a2ca7bd03a`
- #15: `4a0e65bc-cc3b-4b31-bb60-7f4ca7c2b9e1` | 2026-08-16T16:42:00.000Z | REVIEW/classification_seam_boundary_review | incident=`8f3fb2e8-0b64-4df7-a5b0-e7c47a1d9c20` | lesson_key=`classification-seam-review-separate-integration` | event_sha256=`0734a2f3a38a4cf2fde733bb32ead962878fe666710b55b3aaaae44a737e68d6`
- #16: `b4d3c218-4414-41a3-b4e0-cd1c7d6de1c5` | 2026-08-16T16:35:00.000Z | GAP/classification_policy_cost_capacity_unused | incident=`e1c35a26-8f31-4b38-a08c-6a4f8e6e45a5` | lesson_key=`classification-policy-fields-are-executable` | event_sha256=`6714b87135945b8320808c22789b6933fbdab974fd4ce47d94d9c38e91674477`
- #17: `f5578f3c-7e2d-4c4b-9aa9-bd0c61dc4f89` | 2026-08-16T16:20:00.000Z | FAILURE/classification_multiclass_metric_averaging | incident=`c5d9dd34-3d2d-4b0c-a6e6-9f77819f093b` | lesson_key=`classification-multiclass-averaging-is-explicit` | event_sha256=`2da5dfbe3c7db6722b3d8d9cb968706817409c82ac6415b5a36e4a6ff3469134`
- #18: `d3f01a29-9e2c-4cd9-86bf-6b9706f8bb63` | 2026-08-16T16:40:00.000Z | FAILURE/classification_unknown_cost_scenario_regression | incident=`2b8ce52a-15b4-43fe-aa3a-a24eecddc8a0` | lesson_key=`classification-unknown-policy-stays-scenarios` | event_sha256=`58fcdcdde2a5fb0b78664c2dc7876aa54509abd807990a46744eeeb4cc1bf45c`
- #19: `bd5d5f2e-5c41-47a2-839c-9b91788a26f7` | 2026-08-16T16:50:00.000Z | GAP/classification_negative_control_receipt_only | incident=`75a8fdbc-44e7-4f2b-a6e4-1a4b5cb5a68e` | lesson_key=`classification-controls-are-executed-or-unavailable` | event_sha256=`230e23138d71894323710e3af27171c9c2534d1d5cd9d24dc935dbe36fce05d1`
- #20: `d1d81ee7-1e3c-4a2e-8b8e-c0f8f37c9e62` | 2026-08-16T17:05:00.000Z | FAILURE/classification_temporal_warmup_oof | incident=`d13d85e7-c5d0-4d5b-a2d7-1fa1cded8a8f` | lesson_key=`classification-oof-excludes-warmup` | event_sha256=`09a623a049b61ba43d7a5fbb86a9867b0f540519bfae916a82053a15ae11e516`
- #21: `4c88d7d2-cd42-47db-b76b-6e05cb96c95b` | 2026-08-16T17:20:00.000Z | GATE/frontend_renderer_dependencies_unavailable | incident=`0a62d65f-7fda-47ed-b55e-7c772b9b5c39` | lesson_key=`classification-renderer-needs-isolated-frontend-gate` | event_sha256=`17a2d4bc56cfbfd53979913058afa0a9e272a455f75062a72a3831da41b901a4`
- #22: `a2a4f0bb-90bf-49ba-bc28-06b95c4ce1a4` | 2026-08-16T17:35:00.000Z | REVIEW/classification_adversarial_p0_gaps | incident=`f7e5513c-0d03-4588-8fc0-a1f50b60e7b1` | lesson_key=`classification-adversarial-probes-before-closeout` | event_sha256=`67c1a3659193c5fdfc73e7556973b3a0aace487914b654be6b57398772cc2c01`
- #23: `6e0e5f2d-a4fb-4f3c-8f26-d5a8d37c66e3` | 2026-08-16T16:19:51.000Z | FAILURE/classification_temporal_panel_split_correctness | incident=`dcbf4f06-f6db-4d55-8b76-10f83a80d0ba` | lesson_key=`classification-ordered-splits-materialize-history-and-entity-set` | event_sha256=`a8a3926434eebc7c891049c49fefb6a87eb9d2ea2def17e1e4d8fb0b9fdcae51`
- #24: `f96bfbbe-7d37-4f6c-99b2-86e3d0a0d07f` | 2026-08-16T16:19:51.000Z | GAP/classification_protocol_calibrator_regression | incident=`9ed63fc8-9c17-4dd3-9fee-c88c20eb1b62` | lesson_key=`classification-split-verification-keeps-protocol-gap-separate` | event_sha256=`68afb377dfbdfe28503433a4c384ca6bf57378bad9cd66cd8559c73a84238f6d`
- #25: `b4a9ad2e-3c3f-4d8e-9c8a-2c1f4c6e7b90` | 2026-08-16T18:10:00.000Z | ERROR/classification_holdout_refactor_baseline_scope | incident=`f6a0d4c0-6c0c-4f8b-8a8a-9ce9d8b9b3d1` | lesson_key=`classification-release-bundle-consumer-scope` | event_sha256=`287a232d7673cc4a39a513094d49d720930ce0fb5f372c0179786a4eba28b0e3`
- #26: `d2e3f4a5-6789-4abc-8def-1234567890ab` | 2026-08-16T19:05:00.000Z | GAP/classification_packet_identity_missing_model_policy | incident=`8b7c6d5e-4f3a-2109-8fed-cba987654321` | lesson_key=`classification-packet-identity-binds-decision-inputs` | event_sha256=`c1968600aa1d9835c19f578e242b681cbca61b3c37c490e8fd63e7d9a6e17d4a`
- #27: `1e3b9f8a-87e5-4b47-9ad8-1a0d2b4c6e7f` | 2026-08-16T17:00:03.000Z | GAP/classification_entrypoint_external_gap | incident=`2f4a6c8e-1b3d-4f5a-8c7e-9a0b2d4e6f81` | lesson_key=`persistence-gate-keeps-external-classification-gap-separate` | event_sha256=`6522b4383ba4f8a632867e0f572027a1069558c585d7d339ea0dcf32891b4825`
- #28: `3c5e7a9b-1d2f-4b6c-8e0a-2f4d6b8c1e3a` | 2026-08-16T17:01:21.000Z | GAP/classification_multiclass_calibration_gap | incident=`4d6f8a0b-2c4e-6a8f-1b3d-5e7a9c0d2f4b` | lesson_key=`persistence-suite-keeps-multiclass-gap-separate` | event_sha256=`aaad4d3beb197ba7871ccabeb432103b3b7e5428f34a96a60982bbd266479fa6`
- #29: `5e7a9c0d-2f4b-6d8e-1a3c-5f7b9d0e2a4c` | 2026-08-16T17:02:04.000Z | GATE/persistence_hardening_focused_gate | incident=`6f8a0b2c-4e6d-8a1f-3b5d-7e9c0a2f4b6d` | lesson_key=`persistence-hardening-focused-gate` | event_sha256=`1cacfedf03343ffee2894ae122f5124ef0a9450cbb40f2f9d28341c7c2d28657`
- #30: `7a9c0d2f-4b6d-8e1a-3c5f-7b9d0e2a4c6f` | 2026-08-16T17:03:04.000Z | GATE/classification_consumer_final_rerun | incident=`8b0d2f4a-6c8e-1a3c-5f7b-9d0e2a4c6f81` | lesson_key=`classification-final-rerun-separate-from-history` | event_sha256=`d06338020f89a34303294ccad83718515742a4b03efce210f28cb9501c4f799c`
- #31: `c1d2e3f4-5678-49ab-8cde-0123456789ab` | 2026-08-16T18:35:00.000Z | GAP/classification_blocked_projection_model_metrics | incident=`7a9b8c6d-5e4f-4321-a098-76543210fedc` | lesson_key=`classification-blocked-projection-total-redaction` | event_sha256=`a07c603668c6e6a4cc011a5b52a5b61aeeea9088c7d0abcae72882349bb4948d`
- #32: `e7b1c2d3-4f5a-4b6c-8d7e-9012a3b4c5d6` | 2026-08-16T20:20:00.000Z | REVIEW/classification_adversarial_second_pass_hardening | incident=`f1e2d3c4-b5a6-4789-8abc-def012345678` | lesson_key=`classification-second-pass-closes-evidence-and-persistence-boundaries` | event_sha256=`3ced0e15433ebaeb6fa762f1e763dacee70af970fc17d66924cf055f9c5f8e13`
- #33: `c9f3c4ed-3e5c-4e8b-9d49-019f7d7a0001` | 2026-08-16T18:00:00.000Z | FAILURE/metric_evidence_red_test | incident=`c9f3c4ed-3e5c-4e8b-9d49-019f7d7a0002` | lesson_key=`classification-metric-evidence-semantics` | event_sha256=`81829da278a1d0eb3a0754af5a232a7ab4846df3adbe8f882acec94ead2769eb`
- #34: `c9f3c4ed-3e5c-4e8b-9d49-019f7d7a0003` | 2026-08-16T18:05:00.000Z | FAILURE/out_of_scope_classification_baseline | incident=`c9f3c4ed-3e5c-4e8b-9d49-019f7d7a0004` | lesson_key=`classification-focused-gate-separation` | event_sha256=`a66fdc1968b3ca01cb9d4c97a8fc3baf7ea076323ded6f98fe35c2626503544e`
- #35: `c4d5e6f7-8091-4a2b-9c3d-4e5f60718293` | 2026-08-16T22:30:00.000Z | REVIEW/classification_diagnostics_release_plan_hardening | incident=`d5e6f7a8-9012-4b3c-8d4e-5f60718293a4` | lesson_key=`classification-diagnostics-plan-is-immutable-and-self-describing` | event_sha256=`51df80347f2424954b6e87e0c27df2417313774b56480c7173b46419fe3348d7`
- #36: `e6f7a8b9-0123-4c5d-9e6f-708192a3b4c5` | 2026-08-16T22:45:00.000Z | GATE/classification_package_local_completion | incident=`f7a8b9c0-1234-4d6e-8f70-8192a3b4c5d6` | lesson_key=`classification-package-local-gate-separate-from-cutover` | event_sha256=`0435f948c7ca698758be0f34970a4b3534913cc5d7cd38d141bc458fa09cc340`
