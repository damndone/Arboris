# Retrospective — v1-8-8-final-integration

## Goal

# v1.8.8 final integration and real acceptance objective  ## Objective  Create one locally integrated v1.8.8 tree from the verified P3 baseline and the completed P4, P5, P6, and P7 work. Preserve the declaration-driven workflow seam, typed statistical contracts, proposal confirmation boundary, fail-closed error behavior, and provenance. Then close the remaining real-consumer gates: Report, Notebook, the declaration-derived 64-operation acceptance matrix, and the final host full gate.  The P7 multivariate worktree is based on an older divergent snapshot. Its statistical pack contents are already present in the P6 adoption snapshot (\`b418db5\`) and must be verified by live registry and file-hash checks before any P7 material is selected. Do not merge a divergent branch in a way that deletes P3/P4/P5/P6 integration files or historical control records.  ## Inputs and fixed references  - Integration baseline: \`ebba33f18037d3569f3d39dae8773b21a870e6e5\`   (\`workbench-v1.8.8\`, completed P3). - P4 source: \`e0c347b0430fd11befe050d66f43859cf064aed8\`. - P5 source: \`d9fdac91a411383b2f119af4c302059f275489d6\`. - P6/P7 adoption and Agent hardening source:   \`3285bc6d5c609bdae80cf1adfa38d9dcfd51fafc\`. - P7 pack source evidence: \`b418db540c5b37af68b478339d869b1722ada49e\`,   with final extension source \`5df5686\` and freeze records \`33da187\` and   \`0ef1110\` checked against the integrated tree.  ## Boundaries  - Keep P0/P1/P2 contracts and the P3 declaration seam intact. - Do not add one orchestrator branch per operation. - Do not silently retry, drop provider content, convert typed failures to   success, invent run/node/artifact identities, or treat coordinator-only   observations as witness-attested. - Batch acceptance must derive its denominator and operation inputs from the   live registry/declarations. It may classify explicit typed optional-   dependency blocks, but it may not hide failures or replace human evidence. - A real witness claim requires a configured independent provider. If none is   available, record \`NOT VERIFIED\`; never manufacture a local attestation. - No push, pull, PR, remote merge, tag, or release.  ## Acceptance evidence  - P4, P5, P6, and the adopted P7 code are present in one clean integration   tree; the live registry and declaration-derived schemas contain the expected   operations without duplicated or deleted capabilities. - Focused P4/P5/P6/P7, Report, Notebook, and frontend regressions pass from   the integrated tree. - Report has one complete browser-produced, saved, exportable,   provenance-backed result. A provider prose response, retry log, or unit test   is not sufficient. - Notebook latest-chain acceptance has no undeclared-artifact warning and the   persisted artifact manifest is scoped to the option-owned contract. - The 64-operation batch runner produces one durable terminal outcome per live   operation: accepted result or explicit typed optional-dependency/fail-closed   outcome. It must not silently omit or downgrade a result. - Key paths receive visible human confirmation. A witness-attested result is   claimed only when an independent provider verifies the exact challenge;   otherwise the result remains \`coordinator_only\` / \`NOT VERIFIED\`. - The host \`bash scripts/gate.sh --full\` passes after the final code changes. - Formal devline events, verification, and retrospective are generated through   \`scripts/devline_control.py\` before local commit.  ## Known gates  - Repository-root backend suite with only the two valid R-oracle ignores when   the host fixture is unavailable. - Frontend TypeScript and Vitest gates. - P7 registry/adaptor/workflow integration and declaration-derived acceptance   matrix. - Real browser/provider availability for Report, Notebook, and witness claims. - Host full gate; sandbox containment failures are environment evidence, not a   product pass.

## Final status

STARTED

## Metrics

- Failure frequency: 6/14 (42.9%; 42.9 per 100 events)
- Repeat rate: 0/6 (0.0%)
- Recurrence rate: 0/6 (0.0%)
- MTTR: median=0 ms (sample=5; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/6 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/1)

## All failures

- #2 2026-08-10T13:48:49.000Z `integration_boundary_failure`; cause_status: `known`; cause: The P6 merge exposed two real generic-workflow boundary defects: an ARMA-GARCH temporary run lacked its artifact index and optional P7 options were not projected as nullable in the closed workflow schema.; resolution: `resolved`; lesson: A generic adapter must initialize every pack-owned durable boundary and project optional-value semantics identically into runtime validation and published closed schemas.
- #4 2026-08-10T14:57:00.000Z `report_deadline_real_qa`; cause_status: `known`; cause: The first real browser Report attempt used DeepSeek V4 without the shared bounded request policy and returned LLM_REPORT_DEADLINE_EXCEEDED after the shared 300-second deadline.; resolution: `resolved`; lesson: Provider-specific reasoning and output controls must be centralized at the wire adapter and reused by every long-form consumer.
- #5 2026-08-10T15:01:00.000Z `report_contract_real_qa`; cause_status: `known`; cause: A second real browser Report attempt reached the provider but all correction rounds returned prose missing the required Limitations section, so the evidence contract rejected it with LLM_RESPONSE_CONTRACT_INVALID.; resolution: `resolved`; lesson: Real-provider report QA must exercise both transport latency and contract correction paths; a green unit contract test is not sufficient evidence of provider completion.
- #6 2026-08-10T14:42:00.000Z `notebook_recipe_preflight_real_qa`; cause_status: `known`; cause: The real upload-only Notebook path reached confirmation with a short ETS proposal before the shared Recipe input gate was wired into admission; the server correctly exposed ETS_INSUFFICIENT_OBSERVATIONS instead of executing it.; resolution: `resolved`; lesson: The owner Recipe input contract must run read-only during both planning admission and option materialization, before any draft or execution record is written.

## All errors

- None recorded.

## All gaps

- #7 2026-08-10T14:46:00.000Z `notebook_upload_workflow_planner_gap`; cause_status: `known`; cause: After the first Notebook correction, upload-only planning had no server-pinned workflow source for operation.multi_step and the planner surfaced that boundary instead of inventing one.; resolution: `resolved`; lesson: Planner correction must distinguish an unavailable workflow source from an unavailable capability and offer a contractible alternative without fabricating a result.
- #10 2026-08-10T15:15:00.000Z `p7_batch_witness_boundary`; cause_status: `external`; cause: The final-tree registry-derived runner covered all 64 P7 operations across 18 families, but no external browser witness provider was configured, so the runner correctly stopped every admission before provider or browser confirmation.; resolution: `accepted`; lesson: A coordinator ledger can prove registry coverage and fail-closed witness admission, but only an external witness provider can add a browser confirmation trust level.

## All waste

- #11 2026-08-10T15:13:00.000Z `p7_runner_parallel_admission`; cause_status: `known`; cause: Starting family batches concurrently caused the runner's single active browser-attempt guard to reject 17 starts while one family was awaiting terminal confirmation.; resolution: `resolved`; lesson: Batch runner family submissions must be serialized at the ledger boundary even when independent operation execution could later be parallelized behind a witness provider.

## Root causes and solutions

- `external-witness-provider-boundary`: occurrences=1; cause_status: `external`; root cause: The final-tree registry-derived runner covered all 64 P7 operations across 18 families, but no external browser witness provider was configured, so the runner correctly stopped every admission before provider or browser confirmation.; solution: `accepted`
- `generic-adapter-boundary-contract`: occurrences=1; cause_status: `known`; root cause: The P6 merge exposed two real generic-workflow boundary defects: an ARMA-GARCH temporary run lacked its artifact index and optional P7 options were not projected as nullable in the closed workflow schema.; solution: `resolved`
- `real-provider-report-contract-qa`: occurrences=1; cause_status: `known`; root cause: A second real browser Report attempt reached the provider but all correction rounds returned prose missing the required Limitations section, so the evidence contract rejected it with LLM_RESPONSE_CONTRACT_INVALID.; solution: `resolved`
- `runner-family-lifecycle-serial`: occurrences=1; cause_status: `known`; root cause: Starting family batches concurrently caused the runner's single active browser-attempt guard to reject 17 starts while one family was awaiting terminal confirmation.; solution: `resolved`
- `shared-provider-controls-for-report`: occurrences=1; cause_status: `known`; root cause: The first real browser Report attempt used DeepSeek V4 without the shared bounded request policy and returned LLM_REPORT_DEADLINE_EXCEEDED after the shared 300-second deadline.; solution: `resolved`
- `shared-recipe-input-preflight`: occurrences=1; cause_status: `known`; root cause: The real upload-only Notebook path reached confirmation with a short ETS proposal before the shared Recipe input gate was wired into admission; the server correctly exposed ETS_INSUFFICIENT_OBSERVATIONS instead of executing it.; solution: `resolved`
- `upload-only-workflow-source-boundary`: occurrences=1; cause_status: `known`; root cause: After the first Notebook correction, upload-only planning had no server-pinned workflow source for operation.multi_step and the planner surfaced that boundary instead of inventing one.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `external-witness-provider-boundary`: line experience occurrence(s)=1
- `generic-adapter-boundary-contract`: line experience occurrence(s)=1
- `real-provider-report-contract-qa`: line experience occurrence(s)=1
- `runner-family-lifecycle-serial`: line experience occurrence(s)=1
- `shared-provider-controls-for-report`: line experience occurrence(s)=1
- `shared-recipe-input-preflight`: line experience occurrence(s)=1
- `upload-only-workflow-source-boundary`: line experience occurrence(s)=1

## Future guidance

- A coordinator ledger can prove registry coverage and fail-closed witness admission, but only an external witness provider can add a browser confirmation trust level.
- A generic adapter must initialize every pack-owned durable boundary and project optional-value semantics identically into runtime validation and published closed schemas.
- Batch runner family submissions must be serialized at the ledger boundary even when independent operation execution could later be parallelized behind a witness provider.
- Planner correction must distinguish an unavailable workflow source from an unavailable capability and offer a contractible alternative without fabricating a result.
- Provider-specific reasoning and output controls must be centralized at the wire adapter and reused by every long-form consumer.
- Real-provider report QA must exercise both transport latency and contract correction paths; a green unit contract test is not sufficient evidence of provider completion.
- The owner Recipe input contract must run read-only during both planning admission and option materialization, before any draft or execution record is written.

## Event index

- #1: `fc52b844-2ebd-4239-8916-5e3f5dc04310` | 2026-08-10T13:23:11.416Z | STATE_CHANGE/line_started | incident=`3d8d6e19-da07-47e2-a5a6-64c4722dc91d` | lesson_key=`frozen-context-before-start` | event_sha256=`2963a4258a617eb730140b5dbb45bed30d64c1c0c461157b21cd9a4d9bdae876`
- #2: `c9b1f2d1-3c79-4c73-9a8c-2d0f9f0bb2c4` | 2026-08-10T13:48:49.000Z | FAILURE/integration_boundary_failure | incident=`a6d2d0e4-4b64-4a80-9342-6f013a63f7a8` | lesson_key=`generic-adapter-boundary-contract` | event_sha256=`c7256440c54ee64289f13b46beb3d917aa4dd5cc8898c2b32b724aca05cdb83b`
- #3: `d73d9ebc-5ea9-4bca-a4d6-9a0b6d153ba8` | 2026-08-10T14:35:38.000Z | GATE/host_full_gate_passed | incident=`2e4dcff4-9f85-4c3d-8516-6f04f2fbc9d9` | lesson_key=`host-final-gate-evidence` | event_sha256=`8b1af3fe31aa5e9e10308c994d7d04177c7b7497a89c0bf41a5fc3f0cbd452b5`
- #4: `11b7d3d7-6b9d-4b8f-a117-ccf2b9f6c81f` | 2026-08-10T14:57:00.000Z | FAILURE/report_deadline_real_qa | incident=`5fd6e02f-c857-450b-b51d-2eb2f56bd9de` | lesson_key=`shared-provider-controls-for-report` | event_sha256=`87aca2dda0857e86ac278d34531589880231733b19f0e0654626b0565f0b35c7`
- #5: `f36b8a5e-0c7e-44c8-80a0-f6e0fd9c2e61` | 2026-08-10T15:01:00.000Z | FAILURE/report_contract_real_qa | incident=`92a31c57-8ed7-4bad-a4b5-cf82726f02f2` | lesson_key=`real-provider-report-contract-qa` | event_sha256=`a7d80b7a82b6cd59a01273dd411383278e2d8dee178131c6c356e9e8ac4fbdd8`
- #6: `6f45d6a3-4db5-4c4a-8729-2b1f72d1d9f4` | 2026-08-10T14:42:00.000Z | FAILURE/notebook_recipe_preflight_real_qa | incident=`fe7eac89-1f90-4f3c-a3fb-fd5eb3d0d0f8` | lesson_key=`shared-recipe-input-preflight` | event_sha256=`bb0af9ceab5fc8f712a992ad39d35ea15189b377f24aaaa20543b2f6ba608e92`
- #7: `4af4dd4a-a27a-46cd-81b8-4ee95d95b2a0` | 2026-08-10T14:46:00.000Z | GAP/notebook_upload_workflow_planner_gap | incident=`a7807d2a-6c88-4b41-9b1b-091bf50d868d` | lesson_key=`upload-only-workflow-source-boundary` | event_sha256=`b01513727c6ee5f5b63aef9dbaf4ce8587f09ade4ea691088cb536ccadcbaa65`
- #8: `f9d18716-dfc0-4f67-a7ed-c1f7fd1a1c5f` | 2026-08-10T15:10:00.000Z | GATE/notebook_real_chain_passed | incident=`6bb76347-6530-466b-9fef-9f8813573ba4` | lesson_key=`notebook-receipt-artifact-gate` | event_sha256=`4e1a559a036c6f7890b49aba4914c3cae44cf0a3e979d01a482ae3d5c55134b5`
- #9: `a1b8c780-7e2b-4a9a-87fb-09d6dd6fe3ad` | 2026-08-10T15:11:00.000Z | GATE/report_real_chain_passed | incident=`a0c05c65-0f89-4cc7-aa72-75d9e2c53d19` | lesson_key=`report-browser-contract-save-gate` | event_sha256=`5008fa1519ed2328da339b3daaf542a88664ef6d481fc8583a22f727d45e98f4`
- #10: `e3fd3d6f-0f8c-4b27-a29a-5de9bf6e08f4` | 2026-08-10T15:15:00.000Z | GAP/p7_batch_witness_boundary | incident=`dcf7f30b-23d9-4a43-a8a5-4e27b584b66c` | lesson_key=`external-witness-provider-boundary` | event_sha256=`2c43e176ff31ac1f9a1d15b7cae57aaba4c351c6e3cdc8f5cbb2f6d687e8e21e`
- #11: `9e11989e-8a8d-4f4f-a9e1-7b3fd7f6e5e5` | 2026-08-10T15:13:00.000Z | WASTE/p7_runner_parallel_admission | incident=`e401c3dd-7cc9-4f49-94a2-9e0c4e6030c7` | lesson_key=`runner-family-lifecycle-serial` | event_sha256=`42e545bd2899cfef7942845a7ff12cbd14f3ac96489453ff49b2f98b51f721d7`
- #12: `b8c1162b-50a9-4e11-a4bf-1e8f29fbe72d` | 2026-08-10T15:27:00.000Z | GATE/host_full_gate_final_tree | incident=`17c6cf12-36e9-4e0e-8e20-5d0cc6de36d4` | lesson_key=`final-host-gate-evidence` | event_sha256=`df6aefaa85c9d221184cc70bd2718c84d061f79cb7de2779b82a419fdd8c0f6f`
- #13: `b2eb7b27-f74b-4c34-a11d-67d6cf8fbbe5` | 2026-08-10T20:56:06.000Z | GATE/notebook_planning_recovery_actions | incident=`31c6b1f7-b6e5-44be-9c64-73a5f2de0e4d` | lesson_key=`notebook-planning-recovery-surface` | event_sha256=`bca44f2c15f0d699d9c6c83ddc5fbc235e23cc52af73c8a97ee6984e07663ca2`
- #14: `d1ce71f2-32ad-4ee6-9ce0-1b9075f9b2db` | 2026-08-10T22:10:00.000Z | GATE/p7_generic_batch_execution | incident=`4a40b8d7-b9cf-43fd-b52a-f5cbca8cc6db` | lesson_key=`p7-generic-batch-execution` | event_sha256=`9302f5fcbcbaf37c5985aa2ae06afece90a448542410cf665f05b6ace89a409e`
