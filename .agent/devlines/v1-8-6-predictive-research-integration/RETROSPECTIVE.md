# Retrospective — v1-8-6-predictive-research-integration

## Goal

# Workbench v1.8.6 Predictive Research Integration Objective  从本地 checkpoint \`bfeb346\` 继续完成 Workbench v1.8.6 predictive-research correctness foundation 的 integration 收口。保留原 foundation formal line 的冻结证据，不编辑其 manifest 或历史事件。  必须完成：  1. 未声明 prediction data structure 的新 run 在拟合前以    \`PREDICTION_DATA_STRUCTURE_UNKNOWN\` 阻塞，不得进入 legacy random split；legacy    prediction 仅保留给历史 run 重放。 2. Temporal 与 panel 识别并校验必填列，但在 M0 通用 prediction 路径    \`PREDICTION_SPLIT_PROFILE_NOT_SUPPORTED\` fail-closed，不得执行随机或 temporal ML。 3. 仅为 \`frequency_weight\` 实现明确的 sklearn \`sample_weight\` 正例；sampling_weight、    analysis_weight、OLS、panel 与 econometric estimator 权重继续 fail-closed。 4. 缺少 payload contract 的历史 prediction 显示    \`legacy_random_split_v0\`、\`payload_not_evaluated\`、\`legacy_only\`，使用规定英文 UI 文案，    legacy 与 v1.8.6 Compare 以 \`PREDICTION_LEGACY_RESULT_INCOMPARABLE\` 拒绝。 5. MICE 与 prediction 同 run 时必须折内拟合，或在全表路径 fail-closed，并有诱饵测试。 6. Graph、Report、Compare、Table、Run、Agent 只读取同一经过 schema validation 的 typed    evidence；Graph 至少显示 Dataset Snapshot → Prediction Task → Split Plan → Baseline +    Candidate Models → Evaluation → Negative Controls → Result，Report 分区显示 development /    final holdout / negative-control / limitations，Compare 只接受兼容 SplitPlan。 7. 完成 focused tests、formal verification、baseline \`7e257f2\` 对照归因、quick/full gate    与 native browser evidence；不得 push、PR、merge、tag。  明确不做：PIT/Quant、实盘、自动调参、深度学习、任意 code.execute、reshape/merge、 temporal/panel prediction execution、OLS/Panel/econometric weights。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 19/33 (57.6%; 57.6 per 100 events)
- Repeat rate: 0/19 (0.0%)
- Recurrence rate: 0/19 (0.0%)
- MTTR: median=0 ms (sample=6; unresolved=13)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/5 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-02T17:26:39.000Z `tdd_red_unknown_structure_reached_legacy_prediction`; cause_status: `known`; cause: A new prediction request without data_structure still entered the legacy prediction dispatch and created prediction_results.; resolution: `open`; lesson: A contract test must exercise the real new-run dispatch seam, not only the typed entrypoint, because an unchanged legacy fallback can bypass the contract entirely.
- #3 2026-08-02T17:27:48.000Z `tdd_red_temporal_profile_still_executable`; cause_status: `known`; cause: The typed prediction entrypoint still executed a temporal split and returned a prediction packet instead of refusing the unsupported M0 profile.; resolution: `open`; lesson: A temporal split implementation must remain unreachable until its registered safety profile is complete.
- #4 2026-08-02T17:29:55.000Z `tdd_red_frequency_weight_contract_not_executed`; cause_status: `known`; cause: The OOS protocol ignored declared frequency_weight and did not reject unsupported sampling_weight or analysis_weight semantics before fitting.; resolution: `open`; lesson: Weight semantics need an executable positive path and explicit pre-fit rejection tests for every unsupported semantic.
- #5 2026-08-02T17:35:00.000Z `tdd_red_legacy_artifact_not_marked`; cause_status: `known`; cause: A historical prediction_result without payload_contract was treated as an incomplete v1.8.6 packet and raised instead of being exposed as legacy-only evidence.; resolution: `open`; lesson: Legacy compatibility must be decided from the persisted artifact contract boundary and must not fabricate a SplitPlan.
- #6 2026-08-02T17:39:00.000Z `tdd_red_legacy_ui_collapsed_to_unavailable`; cause_status: `known`; cause: The evidence card only recognized validated and unavailable states, so a readable legacy projection was rendered as contract failure.; resolution: `open`; lesson: Compatibility states need a dedicated user-visible projection with the exact comparability warning.
- #7 2026-08-02T17:43:00.000Z `tdd_red_prediction_compare_unsupported`; cause_status: `known`; cause: The durable compare service only admitted ARMA-GARCH pack IDs and had no typed predictive-research or legacy compatibility builder.; resolution: `open`; lesson: Compare compatibility must be derived from the shared persisted evidence projection before pack-specific builders are selected.
- #8 2026-08-02T17:47:00.000Z `typed_prediction_dispatch_missing_binding`; cause_status: `known`; cause: DiagnosticsStage called run_prediction_model_v186 without binding the function from the orchestrator module.; resolution: `open`; lesson: When stages preserve orchestrator monkeypatch seams, every newly dispatched callable needs an explicit local binding and a real workflow test.
- #9 2026-08-02T17:52:00.000Z `tdd_red_prediction_graph_chain_missing`; cause_status: `known`; cause: The typed prediction entrypoint persisted packets but exposed no graph recorder seam for the required user-visible prediction chain.; resolution: `open`; lesson: A persistence-only implementation is incomplete when the same evidence must be projected into lineage; test the recorder seam at the entrypoint.
- #10 2026-08-02T17:57:00.000Z `tdd_red_prediction_report_sections_missing`; cause_status: `known`; cause: The Report view had no deterministic predictive-research sections consuming the typed evidence projection.; resolution: `open`; lesson: Report integration needs an independently testable projection component before wiring it into the existing AI report flow.
- #11 2026-08-02T18:02:00.000Z `tdd_red_projection_omits_development_evidence`; cause_status: `known`; cause: The shared typed consumer projection exposed final OOS, baseline, controls, and limits but omitted persisted development CV evidence.; resolution: `open`; lesson: A consumer projection must carry every bounded report section required by the contract; consumers must not parse packets independently.
- #12 2026-08-02T18:06:00.000Z `tdd_red_prediction_compare_ui_missing`; cause_status: `known`; cause: The stored comparison drawer rendered only generic ARMA-GARCH packet fields and ignored the predictive-research compare schema.; resolution: `open`; lesson: A durable backend packet is not a user-visible capability until its dedicated consumer renders the packet contract.
- #16 2026-08-02T18:26:44.000Z `gate_regression_legacy_dispatch`; cause_status: `known`; cause: The v1.8.6 dispatch correctly stopped using the legacy prediction runner, but two existing workflow tests still patched that retired default seam and therefore lost their structured failure evidence; the new typed runner was also temporarily re-exported in the orchestrator namespace.; resolution: `resolved`; lesson: When a correctness contract removes a default path, migrate old failure-injection tests to the explicit typed seam and keep namespace compatibility deliberate.
- #17 2026-08-02T18:26:44.000Z `tdd_red_negative_control_metrics`; cause_status: `known`; cause: Negative-control packets initially contained only seeded receipts and no comparable model metrics or fold-level noise importance evidence.; resolution: `resolved`; lesson: Persist bounded control metrics, development-CV distributions, metric gaps, and model-agnostic fold permutation importance rather than receipt-only status.
- #18 2026-08-02T18:26:44.000Z `tdd_red_statistics_evidence_packet`; cause_status: `known`; cause: The independent v1.8.6 statistical operators produced typed individual results, but no versioned workbench.statistics.evidence-packet producer existed.; resolution: `resolved`; lesson: Keep independent statistical evidence in a versioned packet and explicitly preserve its non-model-selection boundary.
- #19 2026-08-02T18:26:44.000Z `temporal_protocol_reachable`; cause_status: `known`; cause: The low-level OOS protocol still accepted a temporal SplitPlan after the public entrypoint had been guarded, leaving a direct execution seam outside the M0 fail-closed boundary.; resolution: `resolved`; lesson: Repeat fail-closed profile checks at the protocol boundary and validate declared required columns before refusal.
- #21 2026-08-02T18:57:03.300Z `gate_new_run_test_not_migrated`; cause_status: `known`; cause: The full quick gate reached an existing HTTP prediction test that creates a new run without declaring prediction_data_structure; v1.8.6 correctly blocked the run as unknown instead of writing the legacy artifact.; resolution: `open`; lesson: When a new-run boundary removes a default path, migrate every real HTTP fixture that intentionally expects the old artifact, including tests outside the initial focused list.

## All errors

- None recorded.

## All gaps

- #13 2026-08-02T18:08:38.000Z `allowlist_gap_found`; cause_status: `known`; cause: The frozen Context Pack already includes the continuation file's listed HTTP, frontend API, draft, table, and API-test paths, but the current predictive compare implementation also modifies frontend/src/lineage/detail/sections files that are outside the frozen allowlist.; resolution: `open`; lesson: Audit the frozen allowlist against every changed consumer path before continuing integration work.
- #20 2026-08-02T18:26:44.000Z `sandbox_containment_gate_failure`; cause_status: `known`; cause: The agent-seatbelt full fallback reported sandbox-exec: sandbox_apply: Operation not permitted in code-execution tests; baseline attribution must still be performed on a supported host before this is classified as inherited.; resolution: `open`; lesson: Separate product regression evidence from host containment capability and compare the same gate on a supported host and exact baseline.
- #27 2026-08-03T09:32:27.000Z `existing_line_scope_drift_audit`; cause_status: `known`; cause: The completed v1.8.6 integration changes include eight paths that are not present in the currently frozen Context Pack allowlist, so the formal line scope does not faithfully describe the already committed work.; resolution: `open`; lesson: A completed commit does not prove formal scope correctness; audit the frozen allowlist against the complete diff before starting an expansion.

## All waste

- None recorded.

## Root causes and solutions

- `allowlist-audit-before-integration`: occurrences=1; cause_status: `known`; root cause: The frozen Context Pack already includes the continuation file's listed HTTP, frontend API, draft, table, and API-test paths, but the current predictive compare implementation also modifies frontend/src/lineage/detail/sections files that are outside the frozen allowlist.; solution: `open`
- `audit-formal-scope-before-expansion`: occurrences=1; cause_status: `known`; root cause: The completed v1.8.6 integration changes include eight paths that are not present in the currently frozen Context Pack allowlist, so the formal line scope does not faithfully describe the already committed work.; solution: `open`
- `frequency-weight-positive-path-and-unsupported-rejections`: occurrences=1; cause_status: `known`; root cause: The OOS protocol ignored declared frequency_weight and did not reject unsupported sampling_weight or analysis_weight semantics before fitting.; solution: `open`
- `host-containment-gate-must-be-supported-host-verified`: occurrences=1; cause_status: `known`; root cause: The agent-seatbelt full fallback reported sandbox-exec: sandbox_apply: Operation not permitted in code-execution tests; baseline attribution must still be performed on a supported host before this is classified as inherited.; solution: `open`
- `independent-statistics-need-versioned-packet`: occurrences=1; cause_status: `known`; root cause: The independent v1.8.6 statistical operators produced typed individual results, but no versioned workbench.statistics.evidence-packet producer existed.; solution: `resolved`
- `legacy-prediction-artifacts-need-explicit-projection`: occurrences=1; cause_status: `known`; root cause: A historical prediction_result without payload_contract was treated as an incomplete v1.8.6 packet and raised instead of being exposed as legacy-only evidence.; solution: `open`
- `legacy-ui-state-must-not-be-unavailable`: occurrences=1; cause_status: `known`; root cause: The evidence card only recognized validated and unavailable states, so a readable legacy projection was rendered as contract failure.; solution: `open`
- `negative-controls-need-comparable-metrics`: occurrences=1; cause_status: `known`; root cause: Negative-control packets initially contained only seeded receipts and no comparable model metrics or fold-level noise importance evidence.; solution: `resolved`
- `new-run-prediction-tests-must-declare-structure`: occurrences=1; cause_status: `known`; root cause: The full quick gate reached an existing HTTP prediction test that creates a new run without declaring prediction_data_structure; v1.8.6 correctly blocked the run as unknown instead of writing the legacy artifact.; solution: `open`
- `prediction-compare-needs-evidence-compatibility`: occurrences=1; cause_status: `known`; root cause: The durable compare service only admitted ARMA-GARCH pack IDs and had no typed predictive-research or legacy compatibility builder.; solution: `open`
- `prediction-compare-packet-needs-dedicated-renderer`: occurrences=1; cause_status: `known`; root cause: The stored comparison drawer rendered only generic ARMA-GARCH packet fields and ignored the predictive-research compare schema.; solution: `open`
- `prediction-evidence-must-enter-lineage-graph`: occurrences=1; cause_status: `known`; root cause: The typed prediction entrypoint persisted packets but exposed no graph recorder seam for the required user-visible prediction chain.; solution: `open`
- `prediction-report-needs-four-evidence-sections`: occurrences=1; cause_status: `known`; root cause: The Report view had no deterministic predictive-research sections consuming the typed evidence projection.; solution: `open`
- `retired-dispatch-seams-need-test-migration`: occurrences=1; cause_status: `known`; root cause: The v1.8.6 dispatch correctly stopped using the legacy prediction runner, but two existing workflow tests still patched that retired default seam and therefore lost their structured failure evidence; the new typed runner was also temporarily re-exported in the orchestrator namespace.; solution: `resolved`
- `shared-projection-must-carry-development-evidence`: occurrences=1; cause_status: `known`; root cause: The shared typed consumer projection exposed final OOS, baseline, controls, and limits but omitted persisted development CV evidence.; solution: `open`
- `temporal-profile-must-be-guarded-at-protocol-boundary`: occurrences=1; cause_status: `known`; root cause: The low-level OOS protocol still accepted a temporal SplitPlan after the public entrypoint had been guarded, leaving a direct execution seam outside the M0 fail-closed boundary.; solution: `resolved`
- `temporal-profile-must-fail-closed-in-m0`: occurrences=1; cause_status: `known`; root cause: The typed prediction entrypoint still executed a temporal split and returned a prediction packet instead of refusing the unsupported M0 profile.; solution: `open`
- `typed-prediction-dispatch-binding-required`: occurrences=1; cause_status: `known`; root cause: DiagnosticsStage called run_prediction_model_v186 without binding the function from the orchestrator module.; solution: `open`
- `unknown-structure-must-block-new-run-dispatch`: occurrences=1; cause_status: `known`; root cause: A new prediction request without data_structure still entered the legacy prediction dispatch and created prediction_results.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `allowlist-audit-before-integration`: line experience occurrence(s)=1
- `audit-formal-scope-before-expansion`: line experience occurrence(s)=1
- `frequency-weight-positive-path-and-unsupported-rejections`: line experience occurrence(s)=1
- `host-containment-gate-must-be-supported-host-verified`: line experience occurrence(s)=1
- `independent-statistics-need-versioned-packet`: line experience occurrence(s)=1
- `legacy-prediction-artifacts-need-explicit-projection`: line experience occurrence(s)=1
- `legacy-ui-state-must-not-be-unavailable`: line experience occurrence(s)=1
- `negative-controls-need-comparable-metrics`: line experience occurrence(s)=1
- `new-run-prediction-tests-must-declare-structure`: line experience occurrence(s)=1
- `prediction-compare-needs-evidence-compatibility`: line experience occurrence(s)=1
- `prediction-compare-packet-needs-dedicated-renderer`: line experience occurrence(s)=1
- `prediction-evidence-must-enter-lineage-graph`: line experience occurrence(s)=1
- `prediction-report-needs-four-evidence-sections`: line experience occurrence(s)=1
- `retired-dispatch-seams-need-test-migration`: line experience occurrence(s)=1
- `shared-projection-must-carry-development-evidence`: line experience occurrence(s)=1
- `temporal-profile-must-be-guarded-at-protocol-boundary`: line experience occurrence(s)=1
- `temporal-profile-must-fail-closed-in-m0`: line experience occurrence(s)=1
- `typed-prediction-dispatch-binding-required`: line experience occurrence(s)=1
- `unknown-structure-must-block-new-run-dispatch`: line experience occurrence(s)=1

## Future guidance

- A completed commit does not prove formal scope correctness; audit the frozen allowlist against the complete diff before starting an expansion.
- A consumer projection must carry every bounded report section required by the contract; consumers must not parse packets independently.
- A contract test must exercise the real new-run dispatch seam, not only the typed entrypoint, because an unchanged legacy fallback can bypass the contract entirely.
- A durable backend packet is not a user-visible capability until its dedicated consumer renders the packet contract.
- A persistence-only implementation is incomplete when the same evidence must be projected into lineage; test the recorder seam at the entrypoint.
- A temporal split implementation must remain unreachable until its registered safety profile is complete.
- Audit the frozen allowlist against every changed consumer path before continuing integration work.
- Compare compatibility must be derived from the shared persisted evidence projection before pack-specific builders are selected.
- Compatibility states need a dedicated user-visible projection with the exact comparability warning.
- Keep independent statistical evidence in a versioned packet and explicitly preserve its non-model-selection boundary.
- Legacy compatibility must be decided from the persisted artifact contract boundary and must not fabricate a SplitPlan.
- Persist bounded control metrics, development-CV distributions, metric gaps, and model-agnostic fold permutation importance rather than receipt-only status.
- Repeat fail-closed profile checks at the protocol boundary and validate declared required columns before refusal.
- Report integration needs an independently testable projection component before wiring it into the existing AI report flow.
- Separate product regression evidence from host containment capability and compare the same gate on a supported host and exact baseline.
- Weight semantics need an executable positive path and explicit pre-fit rejection tests for every unsupported semantic.
- When a correctness contract removes a default path, migrate old failure-injection tests to the explicit typed seam and keep namespace compatibility deliberate.
- When a new-run boundary removes a default path, migrate every real HTTP fixture that intentionally expects the old artifact, including tests outside the initial focused list.
- When stages preserve orchestrator monkeypatch seams, every newly dispatched callable needs an explicit local binding and a real workflow test.

## Event index

- #1: `845024f5-231d-489f-972f-d751ffc86f99` | 2026-08-02T17:24:55.496Z | STATE_CHANGE/line_started | incident=`7aae8c2e-4c01-489f-80c2-bbf3feda7491` | lesson_key=`frozen-context-before-start` | event_sha256=`e3df3c7e929a395c11e3d8a8815a4bfc11ee775043160e9bfcf877630a326468`
- #2: `e6f7a8b9-c0d1-4234-e567-89abcdef0123` | 2026-08-02T17:26:39.000Z | FAILURE/tdd_red_unknown_structure_reached_legacy_prediction | incident=`f7a8b9c0-d1e2-4345-f678-9abcdef01234` | lesson_key=`unknown-structure-must-block-new-run-dispatch` | event_sha256=`8ed4750bf23551be0a3bd501df37c62d1e441080dcf4d33c62ff03b706cbf965`
- #3: `a8b9c0d1-e2f3-4456-a789-0abcdef12345` | 2026-08-02T17:27:48.000Z | FAILURE/tdd_red_temporal_profile_still_executable | incident=`b9c0d1e2-f3a4-4567-b890-abcdef123456` | lesson_key=`temporal-profile-must-fail-closed-in-m0` | event_sha256=`d67447f19f63080d451aa9ce652c2c0c122378509393ccb4aeff22a39480fe72`
- #4: `c0d1e2f3-a4b5-4678-c901-23456789abcd` | 2026-08-02T17:29:55.000Z | FAILURE/tdd_red_frequency_weight_contract_not_executed | incident=`d1e2f3a4-b5c6-4789-d012-3456789abcde` | lesson_key=`frequency-weight-positive-path-and-unsupported-rejections` | event_sha256=`7fd8d1b04d90e6a30eef1c089878bf273e822702167890541682029b0a2dea0b`
- #5: `d2e3f4a5-b6c7-4890-d123-456789abcdef` | 2026-08-02T17:35:00.000Z | FAILURE/tdd_red_legacy_artifact_not_marked | incident=`e3f4a5b6-c7d8-4901-e234-56789abcdef0` | lesson_key=`legacy-prediction-artifacts-need-explicit-projection` | event_sha256=`81c058777958b3b449f732e863ff394edfc87a50b8a43143384e0a51ca76f6f4`
- #6: `f4a5b6c7-d8e9-4012-f345-6789abcdef01` | 2026-08-02T17:39:00.000Z | FAILURE/tdd_red_legacy_ui_collapsed_to_unavailable | incident=`a5b6c7d8-e9f0-4123-a456-789abcdef012` | lesson_key=`legacy-ui-state-must-not-be-unavailable` | event_sha256=`25d47c00feca1668b29789369aec9a9132ada2ead4fa2cc3b94c9c9da26c32bd`
- #7: `b6c7d8e9-f0a1-4234-b567-89abcdef0123` | 2026-08-02T17:43:00.000Z | FAILURE/tdd_red_prediction_compare_unsupported | incident=`c7d8e9f0-a1b2-4345-c678-9abcdef01234` | lesson_key=`prediction-compare-needs-evidence-compatibility` | event_sha256=`2ef471ee8ab68b4116d4d2dc1382c8d1b2cc9fda7649ae00bdcdbf2481160513`
- #8: `d8e9f0a1-b2c3-4456-d789-abcdef012345` | 2026-08-02T17:47:00.000Z | FAILURE/typed_prediction_dispatch_missing_binding | incident=`e9f0a1b2-c3d4-4567-e890-bcdef0123456` | lesson_key=`typed-prediction-dispatch-binding-required` | event_sha256=`5a3151e891655bf863171eddca1e82d336f84ee6a506f7cad3379ff727668f79`
- #9: `f0a1b2c3-d4e5-4678-f901-23456789abcd` | 2026-08-02T17:52:00.000Z | FAILURE/tdd_red_prediction_graph_chain_missing | incident=`a1b2c3d4-e5f6-4789-a012-3456789abcde` | lesson_key=`prediction-evidence-must-enter-lineage-graph` | event_sha256=`f5d05137df7de9d1d6df5c3f7fce2e3b7518260ab9dea95bc38bc962df65ba5e`
- #10: `c3d4e5f6-a7b8-4901-c234-56789abcdef0` | 2026-08-02T17:57:00.000Z | FAILURE/tdd_red_prediction_report_sections_missing | incident=`d4e5f6a7-b8c9-4012-d345-6789abcdef01` | lesson_key=`prediction-report-needs-four-evidence-sections` | event_sha256=`3ef54696d770f4c193279c71bdb83a0adfe81173ad8935b19f3d0002400f017b`
- #11: `e5f6a7b8-c9d0-4123-e456-789abcdef012` | 2026-08-02T18:02:00.000Z | FAILURE/tdd_red_projection_omits_development_evidence | incident=`f6a7b8c9-d0e1-4234-f567-89abcdef0123` | lesson_key=`shared-projection-must-carry-development-evidence` | event_sha256=`e80efbf99448fdce41a68fc3fb3ddbb08a72ad5ac2983311297517765ef394e4`
- #12: `a7b8c9d0-e1f2-4345-a678-9abcdef01234` | 2026-08-02T18:06:00.000Z | FAILURE/tdd_red_prediction_compare_ui_missing | incident=`b8c9d0e1-f2a3-4456-b789-abcdef012345` | lesson_key=`prediction-compare-packet-needs-dedicated-renderer` | event_sha256=`c0e851756696e9dac87ed3bd7c828d2f09f250a6c7ee8ad9bd26dc153c1f297c`
- #13: `b9c0d1e2-f3a4-4567-b890-cdef01234567` | 2026-08-02T18:08:38.000Z | GAP/allowlist_gap_found | incident=`c0d1e2f3-a4b5-4678-c901-23456789abcd` | lesson_key=`allowlist-audit-before-integration` | event_sha256=`ed766df4d9e1c8ddafc5536541a64665499f8aed97ab693162083bbab5ddb591`
- #14: `78778548-3f27-4ebe-8ed1-31ac29f16c29` | 2026-08-02T18:16:36.297Z | STATE_CHANGE/context_rescope_required | incident=`2320fb97-a3df-4c10-bb6a-cea1c3ea3f36` | lesson_key=`context-pack-rescope` | event_sha256=`33e24869d062943d6e2640b34f43b5d6711db37210d7eea0bc5c01d180936c7f`
- #15: `3ba08b69-da00-4b3d-90ad-575438b3285f` | 2026-08-02T18:16:36.306Z | STATE_CHANGE/context_rescoped | incident=`03e96f8e-a5a7-478d-8d0e-94dd7f2512a7` | lesson_key=`context-pack-rescope` | event_sha256=`7980300d7f28e44a8bd5d748f76c5971b678f554a59e68ecac37d59aabb85b53`
- #16: `d1e2f3a4-b5c6-4789-d012-3456789abcde` | 2026-08-02T18:26:44.000Z | FAILURE/gate_regression_legacy_dispatch | incident=`e2f3a4b5-c6d7-4890-e123-456789abcdef` | lesson_key=`retired-dispatch-seams-need-test-migration` | event_sha256=`b3ca086dd218f9055da22a86eb44743234557f75821d151daaafa06cb2c35489`
- #17: `f3a4b5c6-d7e8-4901-f234-56789abcdef0` | 2026-08-02T18:26:44.000Z | FAILURE/tdd_red_negative_control_metrics | incident=`a4b5c6d7-e8f9-4012-3456-789abcdef012` | lesson_key=`negative-controls-need-comparable-metrics` | event_sha256=`15fa47c29d2612e4e1bddb2c18d86823e61e63e7ecb426e37e3c451f33821358`
- #18: `b5c6d7e8-f901-4234-5678-9abcdef01234` | 2026-08-02T18:26:44.000Z | FAILURE/tdd_red_statistics_evidence_packet | incident=`c6d7e8f9-0123-4456-789a-bcdef0123456` | lesson_key=`independent-statistics-need-versioned-packet` | event_sha256=`204c625f54d36ff4e41ebacb8675a59848030e43d1d6e37adc6dbba6f35a02a4`
- #19: `d7e8f901-2345-4678-9abc-def012345678` | 2026-08-02T18:26:44.000Z | FAILURE/temporal_protocol_reachable | incident=`e8f90123-4567-489a-bcde-f0123456789a` | lesson_key=`temporal-profile-must-be-guarded-at-protocol-boundary` | event_sha256=`25a572f9ba6842b8b9ee6379eaa66a4ad30eb4f678723ed747c0af83e9aa31d7`
- #20: `f9012345-6789-4abc-def0-123456789abc` | 2026-08-02T18:26:44.000Z | GAP/sandbox_containment_gate_failure | incident=`01234567-89ab-4cde-f012-3456789abcde` | lesson_key=`host-containment-gate-must-be-supported-host-verified` | event_sha256=`fdaa7d4c917db56c90d14677c0fdc7b1572263362a6af1f2b0671e64adc1c964`
- #21: `23456789-abcd-4ef0-9123-456789abcdef` | 2026-08-02T18:57:03.300Z | FAILURE/gate_new_run_test_not_migrated | incident=`3456789a-bcde-4f01-9234-56789abcdef0` | lesson_key=`new-run-prediction-tests-must-declare-structure` | event_sha256=`a98f533535b965bc7cb364c0aa63f4b067b8daaacccb481f3458d369ac6df34d`
- #22: `d28af161-b27a-4b9e-9e22-8094ae319e5c` | 2026-08-02T18:59:01.740Z | STATE_CHANGE/context_rescope_required | incident=`c9c353b7-305f-4019-b69e-9d7dc6672699` | lesson_key=`context-pack-rescope` | event_sha256=`1363a4f456c84c062042a0951aaaeaf05376dc5bae889c4bd7e5d8c80fb96472`
- #23: `c96d9509-932d-4ef9-b065-881e8e6f671c` | 2026-08-02T18:59:01.752Z | STATE_CHANGE/context_rescoped | incident=`64e3290e-fc25-45c5-b38b-73ed40106a07` | lesson_key=`context-pack-rescope` | event_sha256=`fa2491c07e662c43f6e2ad643a6178de70eb04cda8afd49365621f146d654924`
- #24: `456789ab-cdef-4012-3456-789abcdef012` | 2026-08-02T19:42:57.300Z | GATE/gate_new_run_fixture_migrated | incident=`3456789a-bcde-4f01-9234-56789abcdef0` | lesson_key=`new-run-prediction-tests-must-declare-structure` | event_sha256=`3e74d20a783b8bd1a4cce7f9ae795a5f110b8d772d5d470a0cfbb1c5a79a6046`
- #25: `56789abc-def0-4123-4567-89abcdef0123` | 2026-08-02T19:42:57.300Z | GATE/baseline_and_current_full_gate_passed | incident=`6789abcd-ef01-4234-5678-9abcdef01234` | lesson_key=`baseline-gate-needs-matching-dependency-preflight` | event_sha256=`4a998b7800412305ad00f580c038004d8a6e8e39bc6b8c79ee66161a2e80e021`
- #26: `6789abcd-ef01-4234-5678-9abcdef01234` | 2026-08-02T19:42:57.300Z | GATE/sandbox_containment_supported_host_reverified | incident=`01234567-89ab-4cde-f012-3456789abcde` | lesson_key=`host-containment-gate-must-be-supported-host-verified` | event_sha256=`db46e73196e54cf01d7c7ca3b6ad79b31d75ab2cfa9494c9a6beee9115f65b2a`
- #27: `789abcde-f012-4345-6789-abcdef012345` | 2026-08-03T09:32:27.000Z | GAP/existing_line_scope_drift_audit | incident=`89abcdef-0123-4456-789a-bcdef0123456` | lesson_key=`audit-formal-scope-before-expansion` | event_sha256=`d49f3d60726a735ffc920af7ffbbeb57a974a66c47f9c6e45edf7f7c5f8c7604`
- #28: `65e32663-5c93-461b-961b-61d0cf78e01d` | 2026-08-03T09:34:15.582Z | STATE_CHANGE/context_rescope_required | incident=`dd68a654-c512-4c50-8e55-742c82b16d38` | lesson_key=`context-pack-rescope` | event_sha256=`4f0110bb4a9642cb496768e4ec84c828573655d7cf959c603554dbdb8acf3164`
- #29: `2dee7b8b-b8ff-4ab6-858a-a5ac63fa28a3` | 2026-08-03T09:34:15.597Z | STATE_CHANGE/context_rescoped | incident=`177eb231-1f50-4f24-8292-ce6a55789bab` | lesson_key=`context-pack-rescope` | event_sha256=`37b9618edff85fa96550d07195843109e35978d1d770f88973fead6e2a4e455a`
- #30: `c1d2e3f4-a5b6-4789-0123-abcdef012359` | 2026-08-03T15:21:07.000Z | GATE/prediction_api_gate_passed | incident=`d2e3f4a5-b6c7-4890-1234-abcdef012360` | lesson_key=`prediction-protocol-scope` | event_sha256=`0ce9ebc00878fe2a72cd3befe412485ecb379a02d63ddb4b073263a73a225d6c`
- #31: `edb94885-672a-49e7-85f7-ee6ba1c1fe94` | 2026-08-03T15:49:29.142Z | STATE_CHANGE/context_rescope_required | incident=`89736fe8-26f3-46f0-9fd0-c0119b195750` | lesson_key=`context-pack-rescope` | event_sha256=`1af9fd774435f868f7c8622baeaf5c84d49f493e316b5397459fd91fc876ff35`
- #32: `76390678-ddf0-405b-a007-a41d34dcbec1` | 2026-08-03T15:49:29.157Z | STATE_CHANGE/context_rescoped | incident=`2d5d33da-f71d-4edc-b922-668aaa370725` | lesson_key=`context-pack-rescope` | event_sha256=`651834f7919f424bc523e60bb598030de3d708ffad93ddc5325f56242dea3e14`
- #33: `e456789a-bcde-4f01-9234-56789abcdef0` | 2026-08-03T19:27:46.000Z | GATE/baseline_current_full_gate_attribution | incident=`f56789ab-cdef-4012-3456-789abcdef012` | lesson_key=`baseline-current-gate-attribution` | event_sha256=`51a44edde53187202aeb8ba932ab6d667da11ccae7b72e17cc1ee2d431284ff5`
