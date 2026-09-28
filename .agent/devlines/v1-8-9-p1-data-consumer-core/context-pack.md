# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer-core`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 P1 Data Consumer Objective

Expose safe, typed and composable data understanding and mutation through a
package-local provider and schema-driven UI component. Preserve immutable source
data, metadata provenance, preview/confirmation, child-node lineage and reload.
Reject arbitrary expressions, silent coercion, ambiguous joins, metadata loss
without a manifest, and raw or sensitive provider egress by default.

This line consumes the completed v1.8.9 Contract Lock foundations. It does not
replace the central Agent registry, the Notebook planner, the Context Compiler,
the existing execution runtime, or the frontend mount point. Agent/Notebook
production cutover remains a separate line with its own end-to-end evidence.

The AI-native boundary is proposal-only: descriptors and bounded context may
help an Agent explain and compose a typed data plan, but no natural-language
input can execute a mutation, mint authority, select an unbound dataset, or
send raw/sensitive values to a provider. Every mutation remains preview →
confirmation → immutable child artifact → lineage/evidence.

## Boundary
- Affected paths: `backend/workbench/data_profile.py`, `backend/workbench/data_operation_manifest.py`, `backend/workbench/filter_ast.py`, `backend/workbench/data_operations.py`, `backend/workbench/metadata.py`, `backend/workbench/http/data_operation_routes.py`, `backend/workbench/data_context_egress.py`, `backend/workbench/providers/builtin/data_consumer.json`, `frontend/src/lineage/dataOperationManifest.ts`, `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`, `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`, `frontend/src/lineage/dataOperations.ts`, `tests/test_v189_data_profile.py`, `tests/test_v189_data_operation_manifest.py`, `tests/test_v189_context_egress.py`, `tests/test_v189_filter_ast.py`, `tests/test_data_operation_routes.py`, `tests/contracts/test_v189_contract_lock.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-data-consumer-core.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-p1-data-consumer-core-handoff.md`
- Allowed paths: `backend/workbench/data_profile.py`, `backend/workbench/data_operation_manifest.py`, `backend/workbench/filter_ast.py`, `backend/workbench/data_operations.py`, `backend/workbench/metadata.py`, `backend/workbench/http/data_operation_routes.py`, `backend/workbench/data_context_egress.py`, `backend/workbench/providers/builtin/data_consumer.json`, `frontend/src/lineage/dataOperationManifest.ts`, `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`, `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`, `frontend/src/lineage/dataOperations.ts`, `tests/test_v189_data_profile.py`, `tests/test_v189_data_operation_manifest.py`, `tests/test_v189_context_egress.py`, `tests/test_v189_filter_ast.py`, `tests/test_data_operation_routes.py`, `tests/contracts/test_v189_contract_lock.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-data-consumer-core.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-p1-data-consumer-core-handoff.md`
- Protected paths: `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/workflow_capability_registry.py`, `backend/workbench/agent/workflow_capability_adapters.py`, `backend/workbench/agent/notebook`, `backend/workbench/evidence`, `backend/workbench/predictive_research`, `frontend/src/workbench/registry/sectionRegistry.ts`
- Dependencies: `v1-8-9-contract-lock`
- Tests: `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/test_v189_data_profile.py tests/test_v189_data_operation_manifest.py tests/test_v189_context_egress.py tests/test_data_operation_routes.py -q`, `cd frontend && npm test -- --run src/lineage/detail/sections/DataOperationsSection.test.tsx && npm run typecheck`
- Known gates: `core UI/provider evidence does not prove Agent/Notebook mount, real browser, provider, full gate or release`

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
