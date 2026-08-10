# Frozen Context Pack

Line: `v1-8-8-final-integration`
Baseline SHA: `ebba33f18037d3569f3d39dae8773b21a870e6e5`

## Objective
# v1.8.8 final integration and real acceptance objective

## Objective

Create one locally integrated v1.8.8 tree from the verified P3 baseline and the
completed P4, P5, P6, and P7 work. Preserve the declaration-driven workflow
seam, typed statistical contracts, proposal confirmation boundary, fail-closed
error behavior, and provenance. Then close the remaining real-consumer gates:
Report, Notebook, the declaration-derived 64-operation acceptance matrix, and
the final host full gate.

The P7 multivariate worktree is based on an older divergent snapshot. Its
statistical pack contents are already present in the P6 adoption snapshot
(`b418db5`) and must be verified by live registry and file-hash checks before
any P7 material is selected. Do not merge a divergent branch in a way that
deletes P3/P4/P5/P6 integration files or historical control records.

## Inputs and fixed references

- Integration baseline: `ebba33f18037d3569f3d39dae8773b21a870e6e5`
  (`workbench-v1.8.8`, completed P3).
- P4 source: `e0c347b0430fd11befe050d66f43859cf064aed8`.
- P5 source: `d9fdac91a411383b2f119af4c302059f275489d6`.
- P6/P7 adoption and Agent hardening source:
  `3285bc6d5c609bdae80cf1adfa38d9dcfd51fafc`.
- P7 pack source evidence: `b418db540c5b37af68b478339d869b1722ada49e`,
  with final extension source `5df5686` and freeze records `33da187` and
  `0ef1110` checked against the integrated tree.

## Boundaries

- Keep P0/P1/P2 contracts and the P3 declaration seam intact.
- Do not add one orchestrator branch per operation.
- Do not silently retry, drop provider content, convert typed failures to
  success, invent run/node/artifact identities, or treat coordinator-only
  observations as witness-attested.
- Batch acceptance must derive its denominator and operation inputs from the
  live registry/declarations. It may classify explicit typed optional-
  dependency blocks, but it may not hide failures or replace human evidence.
- A real witness claim requires a configured independent provider. If none is
  available, record `NOT VERIFIED`; never manufacture a local attestation.
- No push, pull, PR, remote merge, tag, or release.

## Acceptance evidence

- P4, P5, P6, and the adopted P7 code are present in one clean integration
  tree; the live registry and declaration-derived schemas contain the expected
  operations without duplicated or deleted capabilities.
- Focused P4/P5/P6/P7, Report, Notebook, and frontend regressions pass from
  the integrated tree.
- Report has one complete browser-produced, saved, exportable,
  provenance-backed result. A provider prose response, retry log, or unit test
  is not sufficient.
- Notebook latest-chain acceptance has no undeclared-artifact warning and the
  persisted artifact manifest is scoped to the option-owned contract.
- The 64-operation batch runner produces one durable terminal outcome per live
  operation: accepted result or explicit typed optional-dependency/fail-closed
  outcome. It must not silently omit or downgrade a result.
- Key paths receive visible human confirmation. A witness-attested result is
  claimed only when an independent provider verifies the exact challenge;
  otherwise the result remains `coordinator_only` / `NOT VERIFIED`.
- The host `bash scripts/gate.sh --full` passes after the final code changes.
- Formal devline events, verification, and retrospective are generated through
  `scripts/devline_control.py` before local commit.

## Known gates

- Repository-root backend suite with only the two valid R-oracle ignores when
  the host fixture is unavailable.
- Frontend TypeScript and Vitest gates.
- P7 registry/adaptor/workflow integration and declaration-derived acceptance
  matrix.
- Real browser/provider availability for Report, Notebook, and witness claims.
- Host full gate; sandbox containment failures are environment evidence, not a
  product pass.

## Boundary
- Affected paths: `backend/workbench/agent`, `backend/workbench/contracts/model`, `backend/workbench/engine/packs`, `backend/workbench/engine/replicate_combine`, `backend/workbench/engine/stages`, `backend/workbench/imputation.py`, `backend/workbench/http`, `backend/workbench/lineage/pipeline_drafts.py`, `backend/workbench/llm`, `backend/workbench/orchestrator`, `backend/workbench/report_contract.py`, `backend/workbench/report_quality.py`, `backend/workbench/report_view_model.py`, `backend/workbench/services`, `backend/workbench/statistical_tests.py`, `scripts/p7_acceptance_runner.py`, `frontend/src/lineage/drafts`, `frontend/src/notebook`, `frontend/src/report`, `frontend/src/runForm`, `frontend/src/workbench`, `tests`, `docs/superpowers/objectives/2026-08-10-v1.8.8-final-integration-objective.md`
- Allowed paths: `backend/workbench/agent`, `backend/workbench/contracts/model`, `backend/workbench/engine/packs`, `backend/workbench/engine/replicate_combine`, `backend/workbench/engine/stages`, `backend/workbench/imputation.py`, `backend/workbench/http`, `backend/workbench/lineage/pipeline_drafts.py`, `backend/workbench/llm`, `backend/workbench/orchestrator`, `backend/workbench/report_contract.py`, `backend/workbench/report_quality.py`, `backend/workbench/report_view_model.py`, `backend/workbench/services`, `backend/workbench/statistical_tests.py`, `scripts/p7_acceptance_runner.py`, `frontend/src/lineage/drafts`, `frontend/src/notebook`, `frontend/src/report`, `frontend/src/runForm`, `frontend/src/workbench`, `tests`, `docs/superpowers/objectives/2026-08-10-v1.8.8-final-integration-objective.md`
- Protected paths: `backend/workbench/agent/capability_contract.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/orchestrator`
- Dependencies: none
- Tests: `tests/test_agent_data_management_p4.py`, `tests/test_p5_reachability_gaps.py`, `tests/test_p7_adoption_calls.py`, `tests/test_p7_adoption_registry.py`, `tests/test_p7_workflow_integration.py`, `tests/test_workflow_capability_adapters.py`, `tests/test_workflow_capability_registry.py`, `tests/test_workflow_capability_runtime.py`, `tests/test_workflow_seam.py`, `tests/test_capability_inventory.py`, `tests/test_report_contract.py`, `tests/test_report_quality.py`, `tests/test_llm_chat.py`, `tests/test_notebook_artifact_contract.py`, `tests/test_notebook_routes.py`, `tests/test_notebook_planning_agent.py`, `tests/test_notebook_graph_projection.py`, `tests/test_p7_acceptance_matrix.py`, `tests/test_qa_witness.py`, `frontend/src/lineage/drafts/GenesisWizard.test.tsx`, `frontend/src/notebook/NotebookSurface.notebook.test.tsx`, `frontend/src/report/reportClient.test.ts`
- Known gates: `repository-root backend suite with only the two valid DID oracle ignores`, `frontend TypeScript and Vitest`, `host bash scripts/gate.sh --full`, `in-app browser Report and Notebook acceptance`, `independent witness provider availability`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### v1-8-3-cf3-validation-runtime (2026-07-27T12:25:00.000Z)

Completed formal devline v1-8-3-cf3-validation-runtime; final_state=COMPLETED; failure_lesson_keys=authoring-source-allowlist, cf3-validation-runtime-red, fms-event-draft-validation, protocol-identity-binding

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget
