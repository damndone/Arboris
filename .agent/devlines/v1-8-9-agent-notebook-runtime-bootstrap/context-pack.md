# Frozen Context Pack

Line: `v1-8-9-agent-notebook-runtime-bootstrap`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# v1.8.9 Agent/Notebook Runtime Bootstrap Objective

## Objective

Complete the next missing C2 boundary: assemble a server-owned runtime
contribution set for the current builtin provider catalog and install the
shared Agent/Notebook compiler through an explicit application bootstrap seam.
The result must make package-local data-consumer and classification runtime
identities consumable by the same compiler without importing code from JSON,
using a client-shaped authority marker, or falling back to a weaker executor.

## Required behavior

1. Every executable declaration admitted by the production catalog has exactly
   one server-composed `ProviderRuntimeContributionV1` with matching provider,
   adapter, executor, request contract and result contract identities.
2. Data-consumer and classification contributions use their existing
   package-owned typed boundaries. They must not expose raw rows, raw model
   packets, arbitrary paths, callbacks, or caller-created evidence.
3. The application exposes an explicit bootstrap function that requires the
   server-loaded catalog, host compiler, evidence committer and exact runtime
   contribution set. Missing host authority or incomplete joins fail closed.
4. Agent and Notebook continue to use one compiler/catalog/runtime authority;
   this line does not create a second Notebook capability table or an HTTP
   execution fallback.
5. Tests prove positive composition, missing/extra/mismatched contribution
   rejection, scope binding, startup absence behavior, and a real Agent and
   Notebook compile path. Browser/provider/full-gate evidence remains separate.

## Non-goals

- No statistical formula or estimator implementation.
- No weakening of Evidence Core, context-egress, holdout, or Report authority.
- No native file-format dependency installation in this line.
- No merge, push, tag, release, or deployment mutation.

## Known gates

The line cannot by itself prove production host identity resolver, external
provider execution, browser-visible acceptance, cross-process authority, full
repository gate, or release readiness. Those remain explicit evidence layers.

## Boundary
- Affected paths: `backend/workbench/agent/provider_runtime_contributions.py`, `backend/workbench/agent/runtime_bootstrap.py`, `backend/workbench/app.py`, `backend/workbench/data_operation_manifest.py`, `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/agent/cutover_runtime.py`, `backend/workbench/contracts/agent/planning.py`, `tests/test_v189_agent_notebook_runtime_bootstrap.py`, `tests/test_v189_data_operation_manifest.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/handoff/2026-08-20-v1.8.9-agent-notebook-runtime-bootstrap-handoff.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-agent-notebook-runtime-bootstrap.md`
- Allowed paths: `backend/workbench/agent/provider_runtime_contributions.py`, `backend/workbench/agent/runtime_bootstrap.py`, `backend/workbench/app.py`, `backend/workbench/data_operation_manifest.py`, `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/agent/cutover_runtime.py`, `backend/workbench/contracts/agent/planning.py`, `tests/test_v189_agent_notebook_runtime_bootstrap.py`, `tests/test_v189_data_operation_manifest.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/handoff/2026-08-20-v1.8.9-agent-notebook-runtime-bootstrap-handoff.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-agent-notebook-runtime-bootstrap.md`
- Protected paths: `backend/workbench/evidence`, `backend/workbench/report_view_model.py`, `frontend/src`, `backend/workbench/engine`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p0-workflow-truth-core`, `v1-8-9-p0-evidence-core`, `v1-8-9-p0-agent-compiler-core`, `v1-8-9-p1-data-consumer-core`, `v1-8-9-p1-classification-ml-core`, `v1-8-9-consumer-projection-core`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_agent_notebook_runtime_bootstrap.py tests/test_v189_agent_notebook_runtime_bridge.py tests/test_v189_agent_notebook_cutover.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_data_operation_manifest.py tests/test_v189_classification_production.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `git diff --check`
- Known gates: `focused tests do not prove browser, provider, cross-process, full gate or release`

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

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-3-cf4-notebook-provider-injection (2026-07-26T22:45:00.000Z)

Completed formal devline v1-8-3-cf4-notebook-provider-injection; final_state=COMPLETED; failure_lesson_keys=formal-rescope-boundary, tdd-red-before-provider-injection
