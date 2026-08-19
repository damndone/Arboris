# Frozen Context Pack

Line: `v1-8-9-p0-agent-compiler-remediation-3`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 P0 Agent Compiler Remediation 3 Objective

Close the remaining Agent Compiler authority and multi-worker gaps before
integration admission. Scope/principal/session binding must be issued by a
server-owned authority that a caller cannot construct or re-issue from JSON;
the public Agent/Notebook compiler path must not accept the historical
ServerCompilationRecordIssuer bypass; and identical semantic intents must
converge across independent compiler/store instances, not only within one
Python process. Discovery and direct typed-draft entry must share the same
natural-language eligibility and scope authority checks.

Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
Remediation line: v1-8-9-p0-agent-compiler-remediation-3
Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-agent-compiler

Required outcomes:

- caller-created or deserialized ScopeAuthorityResolver/binding cannot issue
  arbitrary scope, principal, session or project authority;
- Agent/Notebook public compilation accepts only a new compiler-issued,
  server-bound plan; historical C0 issuer/compiled aliases cannot bypass the
  manifest, authority, policy and evidence gates. If the locked C0 contract
  itself must change, record that as a separate contract dependency rather
  than silently editing it;
- identical intents across independent stores/processes have one durable
  reservation/result or a stable conflict, never two server identities;
- discovery and direct typed draft compilation both enforce
  natural_language_enabled and the same server scope selection;
- reconstructed JSON bindings, references, aliases and legacy objects fail
  closed before compilation or runtime-visible persistence.

Keep C0 contract files locked in this package-local line. Do not modify
runtime cutover, central catalog, frontend, provider integration, or protected
paths.

## Boundary
- Affected paths: `backend/workbench/agent/capability_discovery.py`, `backend/workbench/agent/capability_manifest.py`, `backend/workbench/agent/compilation_store.py`, `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/failure_contract.py`, `backend/workbench/agent/planning_contracts.py`, `backend/workbench/agent/port_types.py`, `backend/workbench/providers/builtin/agent_compiler.json`, `tests/test_v189_agent_compiler.py`, `tests/test_v189_capability_manifest.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-compiler-remediation-3.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-agent-compiler-remediation-3-handoff.md`
- Allowed paths: `backend/workbench/agent/capability_discovery.py`, `backend/workbench/agent/capability_manifest.py`, `backend/workbench/agent/compilation_store.py`, `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/failure_contract.py`, `backend/workbench/agent/planning_contracts.py`, `backend/workbench/agent/port_types.py`, `backend/workbench/providers/builtin/agent_compiler.json`, `tests/test_v189_agent_compiler.py`, `tests/test_v189_capability_manifest.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-compiler-remediation-3.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-agent-compiler-remediation-3-handoff.md`
- Protected paths: `backend/workbench/contracts`, `backend/workbench/agent/operations.py`, `backend/workbench/data_operations.py`, `backend/workbench/evidence`, `backend/workbench/services/results_service.py`, `backend/workbench/report_view_model.py`, `backend/workbench/predictive_research`, `frontend`, `scripts/gate.sh`, `.agent/devlines`
- Dependencies: `v1-8-9-p0-agent-compiler-remediation-2`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_agent_compiler.py ../tests/test_v189_capability_manifest.py -q`
- Known gates: `C0 legacy contract issuer changes are outside this line and must be a separately admitted contract decision if unavoidable`, `runtime cutover, provider execution, browser, full gate and release remain NOT VERIFIED`, `no commit, merge, push or tag is authorized`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-5-b3-recipe-default-materialization (2026-08-01T20:48:00.000Z)

Completed formal devline v1-8-5-b3-recipe-default-materialization; final_state=COMPLETED; failure_lesson_keys=external-memory-projection-utf8-budget, generic-memory-omissions-must-fit-context-contract, memory-payload-budget-is-utf8-bytes, memory-projection-budget-must-cover-envelope, recipe-default-bridge-currentness-and-omission-budget, recipe-default-groups-must-be-budget-atomic, recipe-default-materialization-before-provider-choice, recipe-default-truncation-must-fail-closed, recipe-defaults-not-generic-provider-hints

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity
