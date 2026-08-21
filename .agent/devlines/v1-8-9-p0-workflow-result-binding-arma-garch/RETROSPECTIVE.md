# Retrospective — v1-8-9-p0-workflow-result-binding-arma-garch

## Goal

# Workbench v1.8.9 P0 workflow result-binding objective  ## Objective  Close the workflow truth boundary exposed by the real ARMA/GARCH workflow. The estimation stage must not apply the coefficient-only OLS binding contract to a model family whose authoritative result is an artifact-backed time-series packet. Every admitted model family must declare a typed result-binding strategy, and an undeclared or incomplete strategy must fail closed.  The implementation must remain extensible: adding a model family should add a validated binding adapter and its contract tests, not modify a fixed sequence of estimator-specific branches. No coefficient values may be invented merely to satisfy a legacy binding shape.  ## Required outcomes  1. Preserve the existing strict coefficient binding for coefficient-based    families, including source IDs, input identity, bounded fields, and payload    digest. 2. Add a typed artifact-backed binding strategy for    \`time_series.arma_garch\` that binds the model result to its declared    artifact references, production child, validation summary, input IDs and    model identity without manufacturing \`coefficients\`. 3. Reject an unknown model result shape, missing required artifact reference,    foreign model identity, malformed child/validation metadata, or an    undeclared family strategy with \`MODEL_RESULT_INVALID\` and no persisted    model-result fallback. 4. Prove the strategy through a direct RED/GREEN contract test and the real    orchestrator ARMA/GARCH report-admission regression. Existing diagnostics,    lineage and Report evidence must continue to consume the authoritative    family result. 5. Keep the change limited to result-binding and its tests. Do not weaken    server-owned evidence, Report ownership, Agent/Notebook authority,    statistical estimators, or release gates.  ## Acceptance boundary  Focused package tests, the real ARMA/GARCH workflow regression, compileall, diff check and formal devline verification are required. Browser, external provider, multi-worker, host identity, full repository gate, merge, push, tag and release remain explicit follow-up gates.

## Final status

COMPLETED_WITH_LIMITS

## Metrics

- Failure frequency: 5/21 (23.8%; 23.8 per 100 events)
- Repeat rate: 1/5 (20.0%)
- Recurrence rate: 1/4 (25.0%)
- MTTR: median=423558 ms (sample=2; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T12:29:18.377Z `artifact_result_binding_red`; cause_status: `known`; cause: The new artifact-backed result-binding contract test failed at the missing result_binding module before the adapter existed.; resolution: `resolved`; lesson: Run a direct result-shape RED probe before implementing a family-specific binding adapter.
- #8 2026-08-20T12:42:42.674Z `artifact_binding_review_red`; cause_status: `known`; cause: Independent review probes for malformed nested metadata, missing indexed artifacts, and mixed coefficient shape did not fail closed under the first adapter implementation.; resolution: `open`; lesson: An artifact-backed result must validate nested types and bind every declared reference to the server artifact index and content digest.

## All errors

- #9 2026-08-20T12:56:49.790Z `runtime_schema_mismatch`; cause_status: `known`; cause: The first real ARMA-GARCH admission run rejected the runtime flat refit_summary.parameters shape because the adapter expected grouped parameter mappings.; resolution: `resolved`; lesson: Validate against the producer's real artifact payload before tightening a typed binding schema.

## All gaps

- #7 2026-08-20T12:35:53.404Z `ets_wiring_circular_import`; cause_status: `known`; cause: The existing ETS wiring checks hit an orchestrator statistical_tests circular import before capability assertions; the result-binding diff does not touch that import path.; resolution: `open`; lesson: Keep result-binding acceptance separate from pre-existing orchestrator import-cycle gates and do not claim pack wiring from a partial test run.
- #10 2026-08-20T12:57:19.445Z `unix_socket_sandbox_boundary`; cause_status: `known`; cause: The first in-sandbox real ARMA-GARCH report-admission invocation could not create the existing Unix-domain authority socket.; resolution: `accepted`; lesson: Treat Unix-domain socket permission failures as an execution-environment boundary, then rerun outside the nested sandbox.

## All waste

- None recorded.

## Root causes and solutions

- `artifact-binding-adversarial-red`: occurrences=1; cause_status: `known`; root cause: Independent review probes for malformed nested metadata, missing indexed artifacts, and mixed coefficient shape did not fail closed under the first adapter implementation.; solution: `open`
- `result-binding-shape-red`: occurrences=1; cause_status: `known`; root cause: The new artifact-backed result-binding contract test failed at the missing result_binding module before the adapter existed.; solution: `resolved`
- `runtime-artifact-schema-first`: occurrences=2; cause_status: `known`; root cause: The first real ARMA-GARCH admission run rejected the runtime flat refit_summary.parameters shape because the adapter expected grouped parameter mappings.; solution: `resolved`
- `separate-result-binding-gate`: occurrences=1; cause_status: `known`; root cause: The existing ETS wiring checks hit an orchestrator statistical_tests circular import before capability assertions; the result-binding diff does not touch that import path.; solution: `open`

## Added tests

- `tests/models/ets/test_ets_pack_runtime.py and tests/test_ets_wiring.py`
- `tests/test_v189_evidence_envelope.py`
- `tests/test_v189_evidence_report_boundary.py`
- `tests/test_v189_workflow_result_binding.py`
- `tests/test_v189_workflow_result_binding.py tests/test_auto_infer_batch.py::test_y_auto_infers_model_type tests/test_advanced_econometrics.py`
- `tests/test_v189_workflow_result_binding.py::test_auto_workflow_does_not_ols_fallback_after_result_binding_admission_failure`

## New rules

- `artifact-binding-adversarial-red`: line experience occurrence(s)=1
- `result-binding-shape-red`: line experience occurrence(s)=1
- `runtime-artifact-schema-first`: line experience occurrence(s)=2
- `separate-result-binding-gate`: line experience occurrence(s)=1

## Future guidance

- A green adapter test is insufficient when workflow error envelopes and nested evidence semantics can still lose identity or bounds.
- Adversarial extension tests must reach the extension seam, and every untrusted registry key must be type-validated before lookup.
- An artifact-backed result must validate nested types and bind every declared reference to the server artifact index and content digest.
- Every result adapter invocation must carry a handler-owned identity allowlist, normalize serialization failures, and require the primary family identity in any alias set.
- Extension safety needs independent exception-shape tests and final evidence recorded in the formal line.
- Keep result-binding acceptance separate from pre-existing orchestrator import-cycle gates and do not claim pack wiring from a partial test run.
- Result-binding admission failures are correctness failures, not ordinary fit warnings; classify them before any model fallback branch.
- Result-family correctness must be reviewed at the extension seams and at the real producer report-admission boundary, not only through nominal adapter unit tests.
- Run a direct result-shape RED probe before implementing a family-specific binding adapter.
- Treat Unix-domain socket permission failures as an execution-environment boundary, then rerun outside the nested sandbox.
- Validate against the producer's real artifact payload before tightening a typed binding schema.

## Event index

- #1: `ba08e857-6d2e-45c2-a729-d88fb762910b` | 2026-08-20T12:26:04.636Z | STATE_CHANGE/line_started | incident=`de8059f5-8bbc-41ea-b396-5390a8b3591e` | lesson_key=`frozen-context-before-start` | event_sha256=`bd59d9fdd8d591d0d75f087459b8e09fad0623be6ad094ef74686b233772ab62`
- #2: `b3c4d5e6-f7a8-49b0-c1d2-e3f4a5b6c7d8` | 2026-08-20T12:29:18.377Z | FAILURE/artifact_result_binding_red | incident=`c4d5e6f7-a8b9-40c1-d2e3-f4a5b6c7d8e9` | lesson_key=`result-binding-shape-red` | event_sha256=`11d5d03fc8ca31b67393fc7f4117bb40608682f4ad1749b57adcf8290cf62dc4`
- #3: `06b4439e-a797-4679-b5a2-d99971fd88e0` | 2026-08-20T12:33:48.218Z | STATE_CHANGE/context_rescope_required | incident=`36c45dc4-aada-43ed-a9f6-f2b54d8ed8f6` | lesson_key=`context-pack-rescope` | event_sha256=`32e6737705f7fe2c48593d0769eef09d6a2abf339b33a4cb6d5bc386f5d0468f`
- #4: `68bcd599-b0ef-4ac7-936d-25bf56a7f0e8` | 2026-08-20T12:33:48.222Z | STATE_CHANGE/context_rescoped | incident=`e04b32b5-f1b9-43b6-8da6-1ad1f2678a58` | lesson_key=`context-pack-rescope` | event_sha256=`07ef18bae41211ebee8e5f581adcb9e14eb459e967d3b984f4b868127922b194`
- #5: `23b837ff-df2c-41bb-b76c-ace3e27bf78f` | 2026-08-20T12:35:20.850Z | STATE_CHANGE/context_rescope_required | incident=`e9aac178-3657-463c-b1d5-1a62f64fbdab` | lesson_key=`context-pack-rescope` | event_sha256=`a2c419a4684d02d8ae01372e14bb152442b33b3720f8af607097df545fa7d303`
- #6: `0da67b14-e8c9-4f4f-8611-29e31463d87e` | 2026-08-20T12:35:20.854Z | STATE_CHANGE/context_rescoped | incident=`633067b7-2410-478e-b792-09637c17e4f8` | lesson_key=`context-pack-rescope` | event_sha256=`5df90c0dc48d11ab090f1c618877111572351232d629b311f9202272c08e3435`
- #7: `f7a8b9c0-d1e2-43f4-a5b6-c7d8e9f0a1b2` | 2026-08-20T12:35:53.404Z | GAP/ets_wiring_circular_import | incident=`a8b9c0d1-e2f3-44a5-b6c7-d8e9f0a1b2c3` | lesson_key=`separate-result-binding-gate` | event_sha256=`4241a5b649866f3511a24fcef5526d9dc8bcad85442cde948f14e5e5b26888c6`
- #8: `a9b0c1d2-e3f4-45a6-b7c8-d9e0f1a2b3c4` | 2026-08-20T12:42:42.674Z | FAILURE/artifact_binding_review_red | incident=`b0c1d2e3-f4a5-46b7-c8d9-e0f1a2b3c4d5` | lesson_key=`artifact-binding-adversarial-red` | event_sha256=`53cc6d1b575023c7570e7d94f06ab221372f922d8370c8f4412b17118ae40cc7`
- #9: `dc881cb1-2d8d-4069-a704-94edb241c49b` | 2026-08-20T12:56:49.790Z | ERROR/runtime_schema_mismatch | incident=`b0c1d2e3-f4a5-46b7-c8d9-e0f1a2b3c4d5` | lesson_key=`runtime-artifact-schema-first` | event_sha256=`c2fd79ecbe7582ef889c0ab117b7aca325e1df94e2f322aabd9ea486b2bea3bd`
- #10: `562ca278-af83-4633-b25b-822ac9f311e1` | 2026-08-20T12:57:19.445Z | GAP/unix_socket_sandbox_boundary | incident=`b0c1d2e3-f4a5-46b7-c8d9-e0f1a2b3c4d5` | lesson_key=`runtime-artifact-schema-first` | event_sha256=`fe7418b7ef814ed93fd39e805b8f0f573c3d22849d06445d805a54650e2216cb`
- #11: `647d27d8-0309-46cf-9afd-3e7cb2d6a337` | 2026-08-20T12:57:42.274Z | GATE/result_binding_verification | incident=`b0c1d2e3-f4a5-46b7-c8d9-e0f1a2b3c4d5` | lesson_key=`runtime-artifact-schema-first` | event_sha256=`55afacf9e89d09bc57216707b6b4688aa95a31c3ab8ccb67ac3cb081e3ed0b10`
- #12: `38720894-8d09-400e-8249-5dac41a19449` | 2026-08-20T13:08:48.336Z | STATE_CHANGE/context_rescope_required | incident=`3bc4533d-28d9-47ed-b423-ddd086118cef` | lesson_key=`context-pack-rescope` | event_sha256=`1ce806b61591fa1d4b6eb888a9bc30611b4e0b9421f666501f3dd6177dd705c5`
- #13: `fab54995-1dad-4730-9983-44f6f9623b74` | 2026-08-20T13:08:48.343Z | STATE_CHANGE/context_rescoped | incident=`1cf9f0e5-f7ed-4cfe-8b41-940ebcc518d0` | lesson_key=`context-pack-rescope` | event_sha256=`f3a5cbd76b93298660bc5566e2a212cb9dd2714bf0e6634124e1b0a7772d9e78`
- #14: `a7cae792-881e-4e0b-9df0-0a7f7d273d51` | 2026-08-20T13:52:06.609Z | REVIEW/result_binding_spec_not_ready | incident=`9a1a0ee4-3c26-4f13-9f3f-e0f8b4b6d9dd` | lesson_key=`result-binding-nested-contract` | event_sha256=`f2ff2795d7483d54351a0ea83e4c0e18a3df82620086452545121638c4a88026`
- #15: `b24f1a80-05cb-4e4e-9a85-4f6ef3bb9db1` | 2026-08-20T14:01:39.593Z | REVIEW/result_binding_quality_not_ready | incident=`0c89ed60-3d4b-4c64-a95e-61c6a2e0d074` | lesson_key=`adapter-exception-boundary` | event_sha256=`3d50e9d3208567d7987c293b7785ba6bc5f803fcd9cb226878eecd7420a638cc`
- #16: `6e01c5b2-7f3a-4d91-bc27-8a6e4f2d1c90` | 2026-08-20T14:14:03.261Z | REVIEW/result_binding_auto_fallback_fixed | incident=`0d7f4b2a-9c61-4e35-b8a2-6f0c1d9e7b54` | lesson_key=`result-binding-fail-closed-auto` | event_sha256=`da11cb053a50df62a625091ba8f22d7b2cc285091ac2593db762d68d3f9389e4`
- #17: `3f1a8d7c-6b5e-4a2f-90d1-c8e7b4a6f2d3` | 2026-08-20T14:33:54.497Z | REVIEW/result_binding_identity_and_egress_review | incident=`2f0e6d4c-5b3a-4978-91e2-f7d6c4b8a0e1` | lesson_key=`result-binding-identity-and-serialization` | event_sha256=`cdb192819c8bdffdec337ee1d753fba9bb79d060f8c4e03abd8a3a6f4ce0f3c9`
- #18: `7b2e9d4f-6a1c-48f0-b3d7-5e8a2c9f1b6d` | 2026-08-20T14:42:43.040Z | REVIEW/result_binding_exception_and_key_review | incident=`4c8e1a6f-2b9d-47e3-a0f5-6d7c9b1e2a8f` | lesson_key=`result-binding-adapter-seam-reachability` | event_sha256=`a110cbdf0c9273ff3f33eb4f63a951a999d270d5667c133df70eecb69d89dc58`
- #19: `c7e2a9f4-1b63-48d0-5e27-8a0f3d6b9c14` | 2026-08-20T15:09:30.379Z | REVIEW/result_binding_final_review | incident=`d9b4f0a7-2c85-4e16-9a30-6f1d8c3b5e72` | lesson_key=`result-binding-final-review` | event_sha256=`7d719787d86abb635ca6337b37c43d45b46424d1718d1605f96ad9f2e2560c94`
- #20: `e8b3f0a6-2c71-49d5-8f04-6a1c7e9b2d53` | 2026-08-20T15:09:56.540Z | GATE/result_binding_verification | incident=`f1c6a9e3-4b82-5d07-9e15-2a7f0c6b8d34` | lesson_key=`result-binding-bounded-gate` | event_sha256=`a585754d8dff7ff3b68b59a505de1ca0fa9876fa4908a3b5e4baca6991378f24`
- #21: `f9c4e1a7-3b82-4d06-8f15-2a7e0c6b5d93` | 2026-08-20T15:10:20.897Z | STATE_CHANGE/bounded_line_complete | incident=`a2d7f0c5-9b14-4e83-6f20-1c8a5d3b7e94` | lesson_key=`bounded-line-closeout` | event_sha256=`ee9660cb8a93139d77027aeb3fa8fe9c0cc790e302ec4c8899e0ce1f96e05b89`
