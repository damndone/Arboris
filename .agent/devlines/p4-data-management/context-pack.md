# Frozen Context Pack

Line: `p4-data-management`
Baseline SHA: `ebba33f18037d3569f3d39dae8773b21a870e6e5`

## Objective
# P4 Data Management Objective

At baseline `ebba33f18037d3569f3d39dae8773b21a870e6e5`, make the existing typed
data-management executors reachable through the server-owned
`operation.multi_step@v1` contract seam, with one live `OperationDefinition` per
transformation and one shared feature-recipe definition.

The delivered scope is:

- `data.merge`, `data.append`, `data.reshape`, and `data.subset` as typed,
  closed workflow-step proposals;
- the five registered feature recipes through `data.feature_recipe`;
- `data.dedupe`, `data.rename`, `data.aggregate`, `data.fill_missing`,
  `data.tsset`, and `data.lag` as new closed workflow-step operations;
- the closed subset operators `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `in`,
  `not_in`, `between`, `is_missing`, and `not_missing`, while retaining the
  legacy `equals` form;
- the chain-scoped, read-only `list_project_datasets` tool, which returns only
  real `(run_id, node_id, artifact_id)` identities resolved from graph and
  artifact-index state and never invents an identity;
- declaration-driven proposal/editable schemas, vocabulary, capability
  inventory, source/producer projections, validation, execution, graph child,
  `node_index`, and lineage evidence;
- a real workflow path in which a data transformation or recipe is followed by
  `model.genesis` and the model reads the persisted transformed dataset.

Preserve the P0–P3 source commitment, fail-closed dependency, fingerprint, and
capability semantics. Use one generic workflow-runtime data-operation executor
selected by the trusted declaration seam; do not add an operation-specific
four-way manual dispatch table to the orchestrator. Keep `data.sort`, arbitrary
code execution, `model.custom`, frontend changes, browser/P7 work, push, PR,
merge, tag, and release integration out of this line.

Evidence required before close: focused red-to-green TDD tests, declaration
injection tests, hard-coded-replacement mutation failures, focused and relevant
backend regressions, a fresh repository-root backend suite with only the two
valid DID ignores, formal event verification and retrospective regeneration,
and a local English commit.

## Boundary
- Affected paths: `backend/workbench/data_operations.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/context_tools.py`, `tests/test_agent_data_management_p4.py`, `tests/test_data_operations_v186.py`, `tests/test_agent_capabilities.py`, `tests/test_capability_inventory.py`, `tests/test_agent_context_tools.py`, `tests/test_workflow_seam.py`
- Allowed paths: `backend/workbench/data_operations.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/context_tools.py`, `tests/test_agent_data_management_p4.py`, `tests/test_data_operations_v186.py`, `tests/test_agent_capabilities.py`, `tests/test_capability_inventory.py`, `tests/test_agent_context_tools.py`, `tests/test_workflow_seam.py`
- Protected paths: `frontend`, `docs/superpowers/handoff/2026-08-08-codex-implementer-protocol.md`, `docs/superpowers/roadmap/2026-08-08-remaining-phase-goals.md`, `docs/superpowers/specs/2026-08-07-v1.8.8-data-management-in-natural-language-design.md`, `docs/superpowers/plans/2026-08-07-v1.8.8-p0-composition-seam.md`, `docs/superpowers/plans/2026-08-07-v1.8.8-p1-capability-contract.md`, `docs/superpowers/plans/2026-08-08-v1.8.8-p2-reachability-guard.md`, `docs/superpowers/plans/2026-08-08-v1.8.8-p3-capability-registration.md`, `docs/superpowers/plans/2026-08-08-v1.8.8-p3-capability-registration-objective.md`
- Dependencies: `p0-composition-seam`, `p1-capability-contract`, `p2-reachability-guard`, `p3-capability-registration`
- Tests: `focused P4 data-management pytest slices`, `relevant backend regression suites`, `repository-root pytest tests with only tests/test_cs_did_oracle.py and tests/test_cs_did_clustering.py ignored`
- Known gates: `bash scripts/gate.sh --full in the host terminal`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none

### wo-a-live-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-live-agent; final_state=CLOSED; failure_lesson_keys=none
