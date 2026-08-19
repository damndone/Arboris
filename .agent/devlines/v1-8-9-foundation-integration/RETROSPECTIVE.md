# Retrospective — v1-8-9-foundation-integration

## Goal

# Workbench v1.8.9 Foundation Integration Objective  ## Objective  Build one clean, candidate-bound integration line that serially assembles the frozen Contract Lock (C0), P0 Workflow Truth, Evidence Core, Agent Compiler, legacy compilation-authority cutover, and independent Evaluation Harness. Then admit later P1 and Agent/Notebook cutover candidates only through explicit C1, C2 and C3 locks. The line proves discovery, compilation, preview/confirmation, trusted execution, persistence, evidence and declared consumers without inventing a second semantic engine.  ## Exact starting point  - Integration baseline: \`f3836408cf15c3e7380823e5c1b303b4467c7aec\` - First merge input (C0):   \`c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749\` - P0 Agent compiler candidate:   \`8017f6ae6c59a35851a315c3e6a5806c52367f74\` - P0 legacy compilation cutover candidate:   \`fd54600ed726ed6896c7d13b19e7924320d5c8b8\` - P0 Evidence Core candidate:   \`9db6815768f881c31928bf5e8cc8c1bac688ed73\` - P0 Workflow Truth candidate:   \`e7593dd5788a73ee5bae94236bbdff75bbf62349\` - Independent Evaluation Harness candidate:   \`d6d94798a288e4836ebdb32ba78fcf05ee2b08b4\`  ## Scope  This line owns only integration locks, acceptance runner/tests, and the catalog/contract-test denominator update required when declaration-only P0 providers become visible. It must not rewrite product behavior in the Agent, Evidence, Workflow, Data Consumer, Classification ML, or Report packages. Product defects are returned to the owning candidate line and invalidate all downstream candidate evidence.  ## Non-negotiable safety and evidence rules  - There is one active candidate SHA and one serial merge queue. - Every merge is explicit, conflict-resolved by named paths, and followed by   focused tests plus provider/catalog verification. - The catalog is declaration-driven. Provider rows may expand the denominator;   a blocked/unavailable row is evidence, not a silently skipped row. - Evaluation manifests are immutable and must name the exact candidate SHA. - Deterministic, independent, browser, provider, formal, host, full-gate and   release claims remain separate. Unrun boundaries are \`NOT VERIFIED\`. - No push, protected-branch merge, tag or release is authorized by this line.

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 6/20 (30.0%; 30.0 per 100 events)
- Repeat rate: 0/6 (0.0%)
- Recurrence rate: 0/6 (0.0%)
- MTTR: median=0 ms (sample=5; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/7 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #6 2026-08-19T04:28:00.000Z `p0_composed_regression_failure`; cause_status: `known`; cause: The first serial P0 candidate bound Agent compiler and legacy compilation cutover together; the package regression exposed one stale test-double fallback and ten catalog denominator assertions using the wrong baseline.; resolution: `accepted`; lesson: When P0 contracts are composed, update compatibility tests to the new fail-closed boundary and compare injected catalog state against the same root-specific baseline.
- #10 2026-08-19T04:35:00.000Z `workflow_provider_schema_gate`; cause_status: `known`; cause: The Workflow Truth P0 merge introduced workflow_post_estimation.json under the C0 builtin provider directory, but the file uses a package-local compatibility schema instead of the locked ProviderContributionV1 manifest schema.; resolution: `accepted`; lesson: Keep package-local compatibility metadata out of the C0 builtin directory unless it is represented by the locked ProviderContributionV1 refs; a catalog failure must remain visible.
- #13 2026-08-19T04:38:00.000Z `workflow_declaration_test_failure`; cause_status: `known`; cause: After the declaration was normalized to ProviderContributionV1, one Workflow package test still asserted the retired authority/execution_authority fields instead of the locked declaration-only boundary.; resolution: `accepted`; lesson: When a package declaration adopts the shared contract, its tests must assert the shared schema and opaque executor boundary rather than retired local authority fields.
- #17 2026-08-19T05:12:00.000Z `c2_catalog_test_alignment`; cause_status: `known`; cause: The provider catalog identity-order repair was composed with C1, but the existing deterministic catalog test still asserted the retired filename-first ordering.; resolution: `resolved`; lesson: When a stable identity ordering changes, update the consumer assertion to the contract's primary key and retain the documented tie-breaker.
- #18 2026-08-19T05:13:00.000Z `c2_frontend_dependency_preflight`; cause_status: `known`; cause: The newly created Foundation worktree did not yet have the repository's shared frontend dependency link.; resolution: `resolved`; lesson: A clean worktree candidate must declare and prepare its shared dependency environment before frontend acceptance; ignored symlinks must remain outside the product commit.
- #19 2026-08-19T05:15:00.000Z `c2_restricted_host_gate`; cause_status: `known`; cause: The first P0 regression attempt ran in the restricted sandbox, which denies the host authority and Unix socket operations used by the existing P0 probes.; resolution: `resolved`; lesson: Host-bound authority tests must be classified by execution environment; a restricted sandbox failure is not a product result, but the same command must pass in the approved controlled-host boundary.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `c2-catalog-identity-order-test-alignment`: occurrences=1; cause_status: `known`; root cause: The provider catalog identity-order repair was composed with C1, but the existing deterministic catalog test still asserted the retired filename-first ordering.; solution: `resolved`
- `c2-frontend-shared-dependency-preflight`: occurrences=1; cause_status: `known`; root cause: The newly created Foundation worktree did not yet have the repository's shared frontend dependency link.; solution: `resolved`
- `c2-host-bound-p0-gate-environment`: occurrences=1; cause_status: `known`; root cause: The first P0 regression attempt ran in the restricted sandbox, which denies the host authority and Unix socket operations used by the existing P0 probes.; solution: `resolved`
- `p0-composition-test-boundary`: occurrences=1; cause_status: `known`; root cause: The first serial P0 candidate bound Agent compiler and legacy compilation cutover together; the package regression exposed one stale test-double fallback and ten catalog denominator assertions using the wrong baseline.; solution: `accepted`
- `workflow-declaration-test-alignment`: occurrences=1; cause_status: `known`; root cause: After the declaration was normalized to ProviderContributionV1, one Workflow package test still asserted the retired authority/execution_authority fields instead of the locked declaration-only boundary.; solution: `accepted`
- `workflow-provider-schema-boundary`: occurrences=1; cause_status: `known`; root cause: The Workflow Truth P0 merge introduced workflow_post_estimation.json under the C0 builtin provider directory, but the file uses a package-local compatibility schema instead of the locked ProviderContributionV1 manifest schema.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `c2-catalog-identity-order-test-alignment`: line experience occurrence(s)=1
- `c2-frontend-shared-dependency-preflight`: line experience occurrence(s)=1
- `c2-host-bound-p0-gate-environment`: line experience occurrence(s)=1
- `p0-composition-test-boundary`: line experience occurrence(s)=1
- `workflow-declaration-test-alignment`: line experience occurrence(s)=1
- `workflow-provider-schema-boundary`: line experience occurrence(s)=1

## Future guidance

- A clean worktree candidate must declare and prepare its shared dependency environment before frontend acceptance; ignored symlinks must remain outside the product commit.
- Host-bound authority tests must be classified by execution environment; a restricted sandbox failure is not a product result, but the same command must pass in the approved controlled-host boundary.
- Keep package-local compatibility metadata out of the C0 builtin directory unless it is represented by the locked ProviderContributionV1 refs; a catalog failure must remain visible.
- When P0 contracts are composed, update compatibility tests to the new fail-closed boundary and compare injected catalog state against the same root-specific baseline.
- When a package declaration adopts the shared contract, its tests must assert the shared schema and opaque executor boundary rather than retired local authority fields.
- When a stable identity ordering changes, update the consumer assertion to the contract's primary key and retain the documented tie-breaker.

## Event index

- #1: `d76c52ea-a7a7-45ca-b686-15283b8b7a22` | 2026-08-19T04:19:07.565Z | STATE_CHANGE/line_started | incident=`d937cdfb-5aff-4f12-8845-7fe055d40d50` | lesson_key=`frozen-context-before-start` | event_sha256=`1ff822a50e4f5b4bc1bb12413c1e4966c1e9392e038b48ed033233726515caff`
- #2: `b2f5e9a9-9f7d-46e7-b0d8-8df2d407da0d` | 2026-08-19T04:22:55.000Z | GATE/c0_contract_lock_merge_gate | incident=`b2f5e9a9-9f7d-46e7-b0d8-8df2d407da0d` | lesson_key=`c0-verified-before-p0-merge` | event_sha256=`90528c0452e55c9bcf54801cf6c694d5b9ab10ff12344388c20841f094028511`
- #3: `4bdcaafe-a3f9-4d4b-8b4a-40d9b9107a1a` | 2026-08-19T04:25:00.000Z | GATE/p0_legacy_cutover_merge_gate | incident=`4bdcaafe-a3f9-4d4b-8b4a-40d9b9107a1a` | lesson_key=`p0-legacy-cutover-before-agent-compiler` | event_sha256=`a0d9911f38bc4bf915d68ee0aa07a10b66bdbc3f859bf6c0dfca6080e80489a3`
- #4: `de1f23d5-02f5-4ffd-9284-3b1294fae375` | 2026-08-19T04:29:09.235Z | STATE_CHANGE/context_rescope_required | incident=`d0b6e1a0-0d86-4580-8397-12bfd81c82ab` | lesson_key=`context-pack-rescope` | event_sha256=`e3042606f5014874384eac8dd5d0131e907c9cf94703da440cdc6e98280d555a`
- #5: `c02b9b15-faff-4a6c-9cfc-ea8da012e36c` | 2026-08-19T04:29:09.239Z | STATE_CHANGE/context_rescoped | incident=`ac3a279b-a2d7-482b-8c63-9e71df4c37e4` | lesson_key=`context-pack-rescope` | event_sha256=`0b594036addf1e648c2ff41e31486b17c7ac5c67f9193a2da14477a11b5a59ec`
- #6: `6a6e92ec-9ad7-4fef-9cc6-a687026acfa9` | 2026-08-19T04:28:00.000Z | ERROR/p0_composed_regression_failure | incident=`6a6e92ec-9ad7-4fef-9cc6-a687026acfa9` | lesson_key=`p0-composition-test-boundary` | event_sha256=`bfd2acdc514f9efc04813d9c70078f69358099fe48db8d4895969b0ff40dd372`
- #7: `7c1ef2af-14f9-4f2d-9e7d-2dd24d58f0d9` | 2026-08-19T04:33:11.000Z | GATE/p0_evidence_core_merge_gate | incident=`7c1ef2af-14f9-4f2d-9e7d-2dd24d58f0d9` | lesson_key=`provider-catalog-gate-before-next-merge` | event_sha256=`a00624b42782ac9825813575f19cc563b85c03655d9541951dd0f6cee2efc771`
- #8: `ffc0c72a-0d7f-4141-9b05-beefca97b9f9` | 2026-08-19T04:35:04.870Z | STATE_CHANGE/context_rescope_required | incident=`8d8ca4ec-1074-47e5-931a-e351bf691014` | lesson_key=`context-pack-rescope` | event_sha256=`ff5b8b791c1aaec38eee6e0e28d94a8378d358a469c31e66c1dd24b366c3548a`
- #9: `95e66d23-e874-4b2d-8882-08e7ebea6dec` | 2026-08-19T04:35:04.877Z | STATE_CHANGE/context_rescoped | incident=`18a6c82f-1abe-494c-b6c0-0239314a7708` | lesson_key=`context-pack-rescope` | event_sha256=`2f7188fbde980069de3d174529e0c1141bb7e44b62184965858cd5a0c72c772f`
- #10: `9e9dc71f-1cd0-4c56-95ce-32ab60abf39e` | 2026-08-19T04:35:00.000Z | ERROR/workflow_provider_schema_gate | incident=`9e9dc71f-1cd0-4c56-95ce-32ab60abf39e` | lesson_key=`workflow-provider-schema-boundary` | event_sha256=`f2566889ef3cf956295a05e9e990ee97305e1b226e8386dfe09e2de6ef8f8715`
- #11: `190cdbf7-9cd9-4124-95e1-35468dde4286` | 2026-08-19T04:41:00.142Z | STATE_CHANGE/context_rescope_required | incident=`7b79d5fa-dbd0-4c47-9603-5e894153ec04` | lesson_key=`context-pack-rescope` | event_sha256=`abf9f587855b94282c5c8c79e660711d49aa24877d62de714c19e2f81662fec3`
- #12: `dcc7108d-0f5c-4a82-9c4d-93a5cf2702b8` | 2026-08-19T04:41:00.156Z | STATE_CHANGE/context_rescoped | incident=`641b3331-399d-45bd-9989-3556dff685ea` | lesson_key=`context-pack-rescope` | event_sha256=`623824a1dea46212b119f4bdd6eaec3b59e3ac13854d43e02fa2306b434e7b78`
- #13: `f7d6f418-0fb3-4ce6-9a8d-8f708ec17c19` | 2026-08-19T04:38:00.000Z | ERROR/workflow_declaration_test_failure | incident=`f7d6f418-0fb3-4ce6-9a8d-8f708ec17c19` | lesson_key=`workflow-declaration-test-alignment` | event_sha256=`9e3a83a155f15d528e56f0cb6ec6cad8623a74da55732ba0670184ca6d5ad0da`
- #14: `4c3b3f8a-3f99-4f98-9a1a-848bcc4e10a7` | 2026-08-19T04:45:30.000Z | GATE/p0_composed_focused_gate | incident=`6a6e92ec-9ad7-4fef-9cc6-a687026acfa9` | lesson_key=`p0-composed-gate-after-provider-expansion` | event_sha256=`083840ebe1569f840ace5cdc5a0897ece5693b0649bd82d2ea9ac4b3995558b0`
- #15: `c8a0e4e4-83de-4cae-b0d2-1a4a7842de0d` | 2026-08-19T04:45:30.000Z | GATE/workflow_provider_declaration_gate | incident=`9e9dc71f-1cd0-4c56-95ce-32ab60abf39e` | lesson_key=`workflow-provider-schema-incident-resolved` | event_sha256=`d02ce313cd07f5e7df76316eb02832b2b092285ecb9f8ef54463b838d303bb57`
- #16: `b37f41c0-51b2-4b2d-a52c-7d8b4e3a9b3d` | 2026-08-19T04:48:00.000Z | GATE/c1_lock_prepared | incident=`b37f41c0-51b2-4b2d-a52c-7d8b4e3a9b3d` | lesson_key=`c1-lock-before-candidate-sha` | event_sha256=`127691b75084f5405d4d146f43fffd83cf5378a65d5183e41c60efc8923b3a8e`
- #17: `c2c4a1e0-8b9d-4f3a-a6d2-1e7c5b9f2048` | 2026-08-19T05:12:00.000Z | ERROR/c2_catalog_test_alignment | incident=`c2c4a1e0-8b9d-4f3a-a6d2-1e7c5b9f2048` | lesson_key=`c2-catalog-identity-order-test-alignment` | event_sha256=`187a42b774d5da5d3eeebcf85b38ebb27c91d72b57a2ecfc108c894c07643aa2`
- #18: `c2f1b7e3-6d4a-48c2-9e5f-0a3d7b1c6249` | 2026-08-19T05:13:00.000Z | ERROR/c2_frontend_dependency_preflight | incident=`c2f1b7e3-6d4a-48c2-9e5f-0a3d7b1c6249` | lesson_key=`c2-frontend-shared-dependency-preflight` | event_sha256=`26b5180b6c2cdf7e9bafceb0387579c39177903eeacd1e2efeeaa0700179f056`
- #19: `c2e9a4d6-1f7b-4c3e-8a5d-0b2f6e9c1748` | 2026-08-19T05:15:00.000Z | ERROR/c2_restricted_host_gate | incident=`c2e9a4d6-1f7b-4c3e-8a5d-0b2f6e9c1748` | lesson_key=`c2-host-bound-p0-gate-environment` | event_sha256=`1d729f4ae9d7e11a84ebd1fe1648b711cce43354bf7935def26ea627bd26d067`
- #20: `c2b8d3f6-4a1e-49c7-0f5b-2d6e8a3c1749` | 2026-08-19T05:17:00.000Z | GATE/c2_p1_composed_gate | incident=`c2b8d3f6-4a1e-49c7-0f5b-2d6e8a3c1749` | lesson_key=`c2-lock-after-composed-gates` | event_sha256=`5e7353877fb8f37290ea58ef4f084b7b60e42eee09f54d32f603d76397a14e10`
