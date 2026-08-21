# Retrospective — v1-8-9-c2-classification-projection-adapter

## Goal

# Workbench v1.8.9 C2 Classification Projection Adapter Objective  ## Objective  把 classification provider catalog 中声明的 Agent、Notebook、Report \`projection_ref\`、policy 和 renderer 与实际消费适配器做精确的 server-owned join，并让 Report 优先读取中央 classification projection， 不再把原始 artifact 作为 Report 的结果来源。此线只做消费层、catalog 绑定和渲染注册，不重新拟合模型、不重新计算指标、不改变已有的 artifact/receipt/C0 校验。  ## Required behavior  - projection adapter 必须按 \`(provider_id, exposure_path, consumer_id)\` 精确   解析 catalog 声明；不能按 consumer 名称、renderer 名称或任意 caller   supplied projection ref 猜测。 - classification 的 projection、policy、renderer、evidence contract 和   exposure path 必须来自同一份 server-owned catalog，并验证 ref identity、   digest、预算、敏感度和 coverage 状态。 - Agent、Notebook、Report 的中央 classification projection 必须携带已绑定   的 projection identity；缺失、错配、篡改或未声明时 fail closed，并保留   \`validated\`、\`degraded\`、\`unavailable\` 与阻断原因。 - Report renderer 只能从闭合的 renderer registry 解析声明，不允许把未知   renderer ref 当作 React 组件，也不能回退到 raw JSON。 - Report 使用 server-owned classification projection 展示已验证的任务、   split、metrics、calibration、comparison、explanations、stability、shift   和 holdout 边界；旧 artifact 下载路径只能作为诊断/兼容路径，不得成为   Report 结果 authority。 - 通用 numeric evidence projection 的现有消费行为必须保持兼容；新的   provider-scoped registry 必须支持未来模型族以同样方式接入，不能写成   classification 专用的死流程。  ## Explicit non-goals  - 不修改分类 estimator、split/CV/holdout/calibration/threshold/SHAP 语义。 - 不新增模型族，不扩展复杂抽样、SEM、survival 或其他 P2 模型。 - 不实现浏览器、真实 provider、跨进程 authority、发布、merge、push、tag。 - 不把 central projection 伪装成 generic numeric envelope，也不把未验证   的 artifact 重新提升为可引用证据。  ## Acceptance evidence  - TDD RED probes first cover exact provider/path/consumer joins, wrong ref,   wrong renderer, missing declaration, forged catalog and unavailable states. - Backend tests prove central classification Agent/Notebook/Report projections   carry the catalog-bound identity and coverage reports no longer confuse a   provider-specific projection with the generic consumer projection. - Frontend tests prove Report consumes the server projection through the closed   renderer registry, rejects unknown/mismatched identities, and never renders   raw classification JSON. - Existing classification central/production/consumer suites, compileall,   frontend tests and diff check pass. Browser/provider/full/release remain   separate claims until independently verified.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/18 (16.7%; 16.7 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #13 2026-08-20T22:41:54.109Z `c2_registry_digest_order_mismatch`; cause_status: `known`; cause: The first exact registry issuance comparison hashed catalog bindings in catalog iteration order while the sealed registry exposed canonical key order.; resolution: `resolved`; lesson: Registry authority comparisons must canonicalize the complete binding set independent of loader iteration order.
- #14 2026-08-20T22:43:02.915Z `c2_sandbox_unix_socket_permission`; cause_status: `external`; cause: The non-escalated sandbox could not create the local Unix socket used by the generic evidence boundary suite.; resolution: `accepted`; lesson: Keep sandbox capability failures separate from product correctness results and rerun the exact suite at the host boundary.

## All errors

- None recorded.

## All gaps

- #17 2026-08-20T22:43:22.033Z `c2_external_acceptance_not_verified`; cause_status: `external`; cause: The current C2 worktree has no completed browser, real-provider, cross-process identity, full-repository, or release acceptance run.; resolution: `accepted`; lesson: Do not promote a package-local or targeted green result to release readiness until host, browser, provider, full-tree, and release gates run.

## All waste

- None recorded.

## Root causes and solutions

- `canonicalize-registry-binding-digest`: occurrences=1; cause_status: `known`; root cause: The first exact registry issuance comparison hashed catalog bindings in catalog iteration order while the sealed registry exposed canonical key order.; solution: `resolved`
- `retain-unverified-external-boundaries`: occurrences=1; cause_status: `external`; root cause: The current C2 worktree has no completed browser, real-provider, cross-process identity, full-repository, or release acceptance run.; solution: `accepted`
- `separate-sandbox-boundary-from-product-gate`: occurrences=1; cause_status: `external`; root cause: The non-escalated sandbox could not create the local Unix socket used by the generic evidence boundary suite.; solution: `accepted`

## Added tests

- `frontend focused C2 classification/report tests`
- `tests/test_v189_classification_projection_adapter.py`
- `tests/test_v189_evidence_report_boundary.py`

## New rules

- `canonicalize-registry-binding-digest`: line experience occurrence(s)=1
- `retain-unverified-external-boundaries`: line experience occurrence(s)=1
- `separate-sandbox-boundary-from-product-gate`: line experience occurrence(s)=1

## Future guidance

- A catalog-bound result must bind both the declaration and the actual source receipt; private naming is not an authority boundary, and every unavailable branch must use the same typed identity envelope.
- A closed projection boundary needs an independent review of both positive paths and forged or unavailable inputs.
- Do not promote a package-local or targeted green result to release readiness until host, browser, provider, full-tree, and release gates run.
- Keep sandbox capability failures separate from product correctness results and rerun the exact suite at the host boundary.
- Registry authority comparisons must canonicalize the complete binding set independent of loader iteration order.
- Treat provider/path/consumer identity, policy, evidence refs, budgets, sensitivity, and ordering as one executable server-owned admission contract; do not close a consumer adapter line on shape-only tests.

## Event index

- #1: `3c1fe39a-0154-4c09-b974-9add772bb748` | 2026-08-20T20:55:03.303Z | STATE_CHANGE/line_started | incident=`a1cfc973-f9db-43dc-a6f9-bf8291684e01` | lesson_key=`frozen-context-before-start` | event_sha256=`5e69d83626d0ad5cbddeb9aa5d84dfd3df7936c6af119412347a9339c79ea6f2`
- #2: `ecc67237-7213-4ff4-af9d-1b6de178dcf2` | 2026-08-20T21:15:12.011Z | STATE_CHANGE/context_rescope_required | incident=`74e0d5c0-92df-404a-91a7-dc629752febb` | lesson_key=`context-pack-rescope` | event_sha256=`f6bbf711186b0ca994cd0c158a1d0bd1780811a5dfc3584e5cf2484526c7bf76`
- #3: `b6413b9b-6ef2-452b-9b5f-6e5d5e74653d` | 2026-08-20T21:15:12.015Z | STATE_CHANGE/context_rescoped | incident=`13fd361f-1a4e-458a-b1de-f59b075ce5e8` | lesson_key=`context-pack-rescope` | event_sha256=`af6d1522f5419e943dc2ec59d70c48684e70ea23577062dc0f8b23e6c61fee7b`
- #4: `e460cc69-4571-4a01-ad34-61b955ba1001` | 2026-08-20T21:17:01.835Z | STATE_CHANGE/context_rescope_required | incident=`a96fdce5-4414-4706-97cd-f1240e851b4f` | lesson_key=`context-pack-rescope` | event_sha256=`15527b517da069d317bf6b1c787b359b6b7e418df2470f488ca254627356a50b`
- #5: `4caaa055-6250-4b03-ba81-38ea53c3d73d` | 2026-08-20T21:17:01.841Z | STATE_CHANGE/context_rescoped | incident=`e3d609a1-a70a-403f-8417-3c1a21da12fa` | lesson_key=`context-pack-rescope` | event_sha256=`2ed97022e9a953a0550a5bcc272ba6406fa7510f438e4bc0aaa22bbf677bd48d`
- #6: `ce0e8252-aa8b-4179-ab21-bee774f49963` | 2026-08-20T21:26:14.800Z | STATE_CHANGE/context_rescope_required | incident=`adf2cb2b-bc80-4e2f-8461-f3081caa4d68` | lesson_key=`context-pack-rescope` | event_sha256=`7de0fba0f227122e1b0d11d90e72294c9e34e0e90096899a1a9d8fb0d3d8d73f`
- #7: `e13d6f86-1d8e-417b-8220-0300ab4b4596` | 2026-08-20T21:26:14.805Z | STATE_CHANGE/context_rescoped | incident=`c4f75c0d-a257-4511-a8c0-fe7edb0b0a57` | lesson_key=`context-pack-rescope` | event_sha256=`fddc39117ea5c584876ae9de5bb42863f5a2c15098b7aaf584bcdaf35060abf9`
- #8: `4e1b8a3d-7c92-4f65-a0d1-9b2e6c8f4a17` | 2026-08-20T21:36:45.719Z | REVIEW/c2_spec_review_required_changes | incident=`b7c3e9f1-2a64-4d80-9e15-6f8b0c2d4a73` | lesson_key=`c2-catalog-bound-admission` | event_sha256=`35be97ccde4453a2bf8d07a03b9277b21710396ddf0f3967be19902d344638f7`
- #9: `9f3c6a1e-5b72-4d80-a9c4-2e7f1b6d8a35` | 2026-08-20T21:57:34.728Z | REVIEW/c2_second_review_p1_identity_gaps | incident=`2d8f4b1a-7c63-4e90-b5a2-9f1d6c8e3b74` | lesson_key=`c2-source-receipt-identity` | event_sha256=`b75a4d97ce42b688b52eaa45f49a40a4d8fbed2514c40e8d65fd76d7b21f1cfd`
- #10: `d6a1b4f9-0c72-4c63-8e1a-2f9b7d5c4a10` | 2026-08-20T22:01:49.644Z | GATE/c2_frontend_unavailable_identity_green | incident=`f4c2a8e1-6b93-4d70-9a15-3e7c0b2d8f64` | lesson_key=`c2-frontend-unavailable-identity` | event_sha256=`5d36b23c06eb4815df929a8217a08317d2b13b780edbce04bd76e1cc5c9f485f`
- #11: `90edc630-803c-415e-8d66-680ff665a4b1` | 2026-08-20T22:19:11.040Z | STATE_CHANGE/context_rescope_required | incident=`309eba2e-773d-42ae-bd8b-fbc7a62a2495` | lesson_key=`context-pack-rescope` | event_sha256=`91d870984a78812633f746ebc89687f5a84ab0eadbeee94fce59f37faab325b1`
- #12: `27c7bb25-8856-4f04-b702-ea9a8c92ad9d` | 2026-08-20T22:19:11.047Z | STATE_CHANGE/context_rescoped | incident=`5ed4dd24-742d-4a4e-a220-4e6985a8fd30` | lesson_key=`context-pack-rescope` | event_sha256=`b309330b9d1fc85d8a070df4723727a47ad8235a8f60972a5a300f854ed734b7`
- #13: `a2c9f7d1-6b4e-4f18-9d20-3e8a1c5b7f62` | 2026-08-20T22:41:54.109Z | FAILURE/c2_registry_digest_order_mismatch | incident=`a6f0a7f1-6b4e-4f18-9d20-3e8a1c5b7f62` | lesson_key=`canonicalize-registry-binding-digest` | event_sha256=`cf667ab93bb43fc2a9f87e40162452f9c110449442bfe4517a842f5df3356e51`
- #14: `b3d0a8e2-7c51-4f29-9a64-1d8e2b7c5f30` | 2026-08-20T22:43:02.915Z | FAILURE/c2_sandbox_unix_socket_permission | incident=`c4e1f9a2-7b53-4d80-9e16-2f8a6c0b5d41` | lesson_key=`separate-sandbox-boundary-from-product-gate` | event_sha256=`f4479e7426c615e2e853c8e90370cc9eed0b66c0c2b6e044f9d8163d3fc0e268`
- #15: `d4e1a9b3-8c62-4f30-9a75-2e8f3b7c6d41` | 2026-08-20T22:43:15.790Z | REVIEW/c2_final_review_pass | incident=`e5f2a0c4-9d73-4f41-a8b6-3c9e7d1b5f20` | lesson_key=`review-positive-and-forged-projection-paths` | event_sha256=`b303296880343ca83117dbf5f653f579e5f0cb24157989158c92bc2315cb9e92`
- #16: `e5f2b0c4-9d73-4f41-a8b6-3c9e7d1b5f20` | 2026-08-20T22:43:18.961Z | GATE/c2_final_backend_frontend_green | incident=`f6a3b1d5-0e84-4f52-b9c7-4d0a8e2b6f31` | lesson_key=`separate-targeted-gate-from-external-acceptance` | event_sha256=`7521f9d18301c2e55617009245a68804d7bcf61c14a927c625e1f1a280a1a678`
- #17: `f6a3c1d5-0e84-4f52-b9c7-4d0a8e2b6f31` | 2026-08-20T22:43:22.033Z | GAP/c2_external_acceptance_not_verified | incident=`a7b4c2e6-1f95-4063-8ad0-5e1b9f3c7d42` | lesson_key=`retain-unverified-external-boundaries` | event_sha256=`0b0e798a83c6c8dd27eaa8e9be93a1b1974b2c0bb4fe774b5cbcb5366ebdee4d`
- #18: `a7b4d2e6-1f95-4063-8ad0-5e1b9f3c7d42` | 2026-08-20T22:43:59.987Z | STATE_CHANGE/c2_line_completed | incident=`b8c5e3f7-2a06-4174-9be1-6f2c0a4d8e53` | lesson_key=`close-with-targeted-and-release-boundaries` | event_sha256=`a364e7117a09f4f103082125d790a02b225395ecec839d79e6ae4274817a9e28`
