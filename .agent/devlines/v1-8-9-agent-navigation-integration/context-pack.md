# Frozen Context Pack

Line: `v1-8-9-agent-navigation-integration`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 Agent navigation integration objective

## Objective

Close the current C3 integration regression without weakening the server-owned
proposal boundary. Existing Agent navigation tests must create durable records
through the admitted proposal capability and the shared operation lifecycle;
they must not regain raw `ProposalStore` mutation or the retired
`WorkbenchOrchestrator.confirm_proposal` execution authority. Read-only graph
navigation over a project with no Workbench storage must return an unavailable
projection, not leak a filesystem capability error or create storage.

## Baseline

- Worktree: `workbench-v1.8.9-hardening-integration`
- Exact baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`
- Existing dirty v1.8.9 changes are in scope and must be preserved.

## In scope

- `backend/workbench/agent/navigation.py` read-only unavailable boundary.
- `tests/test_agent_navigation.py` migration to the server-owned proposal and
  operation lifecycle.
- `tests/test_agent_routes.py` fixture migration or explicit fail-closed
  assertions where the historical route lacks a persisted server compilation.
- This objective, work order, handoff, and focused contract/acceptance tests.

## Out of scope

- Removing or weakening `ProposalStoreCapabilityV1` admission.
- Reintroducing `WorkbenchOrchestrator.confirm_proposal` as an execution path.
- Estimator, data-consumer, classification, survey, Report, or Notebook
  implementation changes.
- Browser, external provider, cross-process, full-host, full-repository,
  merge, tag, release, or root-main synchronization.

## Required outcomes

1. Navigation fixtures use an admitted server capability and a durable
   `ProposalConfirmation` → `OperationRecord` lifecycle.
2. Missing Workbench storage is represented as an unavailable read projection;
   no directory is created as a side effect.
3. Historical Agent routes without a server-owned compilation remain typed
   fail-closed; tests do not silently accept their old execution semantics.
4. Focused Agent/Notebook C3 tests and the affected route/navigation tests pass.

## Known gates

Production host identity/data/evidence injection, browser acceptance, external
provider execution, cross-process authority, full host/repository gate, and
release readiness remain unverified.

## Boundary
- Affected paths: `backend/workbench/agent/navigation.py`, `tests/test_agent_navigation.py`, `tests/test_agent_routes.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-agent-navigation-integration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-agent-navigation-integration.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-agent-navigation-integration-handoff.md`
- Allowed paths: `backend/workbench/agent/navigation.py`, `tests/test_agent_navigation.py`, `tests/test_agent_routes.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-agent-navigation-integration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-agent-navigation-integration.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-agent-navigation-integration-handoff.md`
- Protected paths: `backend/workbench/agent/proposals.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/http/agent_routes.py`
- Dependencies: `v1-8-9-central-evidence-consumer-mount`, `v1-8-9-agent-notebook-runtime-bootstrap`
- Tests: `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_agent_navigation.py tests/test_agent_routes.py -q --disable-warnings`, `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_agent_notebook_cutover.py tests/test_v189_artifact_integrity.py -q --disable-warnings`
- Known gates: `Production host identity/data/evidence injection, browser, external provider, cross-process, full host/repository, and release remain unverified`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-9-p0-agent-compiler-remediation-5 (2026-08-19T02:35:17.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-5; final_state=COMPLETED; failure_lesson_keys=os-boundary-probes-need-controlled-sandbox-access

### v1-8-9-p0-workflow-truth-remediation-6 (2026-08-16T16:15:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-6; final_state=COMPLETED; failure_lesson_keys=formal-output-registration-transaction, register-child-run-model-artifacts, runtime-fixture-model-preconditions, use-declared-model-minimum

### v1-8-9-p0-legacy-compilation-authority-cutover (2026-08-16T14:30:00.000Z)

Completed formal devline v1-8-9-p0-legacy-compilation-authority-cutover; final_state=COMPLETED; failure_lesson_keys=legacy-authority-red-before-implementation, legacy-cutover-keeps-host-dependency-explicit

### v1-8-9-p0-workflow-truth-remediation-5 (2026-08-16T13:35:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-5; final_state=COMPLETED; failure_lesson_keys=production-host-integration-boundary, runtime-artifact-no-follow, workflow-remediation-5-red-before-fix
