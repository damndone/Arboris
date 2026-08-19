# Frozen Context Pack

Line: `v1-8-9-foundation-integration`
Baseline SHA: `f3836408cf15c3e7380823e5c1b303b4467c7aec`

## Objective
# Workbench v1.8.9 Foundation Integration Objective

## Objective

Build one clean, candidate-bound integration line that serially assembles the
frozen Contract Lock (C0), P0 Workflow Truth, Evidence Core, Agent Compiler,
legacy compilation-authority cutover, and independent Evaluation Harness. Then
admit later P1 and Agent/Notebook cutover candidates only through explicit C1,
C2 and C3 locks. The line proves discovery, compilation, preview/confirmation,
trusted execution, persistence, evidence and declared consumers without
inventing a second semantic engine.

## Exact starting point

- Integration baseline: `f3836408cf15c3e7380823e5c1b303b4467c7aec`
- First merge input (C0):
  `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`
- P0 Agent compiler candidate:
  `8017f6ae6c59a35851a315c3e6a5806c52367f74`
- P0 legacy compilation cutover candidate:
  `fd54600ed726ed6896c7d13b19e7924320d5c8b8`
- P0 Evidence Core candidate:
  `9db6815768f881c31928bf5e8cc8c1bac688ed73`
- P0 Workflow Truth candidate:
  `e7593dd5788a73ee5bae94236bbdff75bbf62349`
- Independent Evaluation Harness candidate:
  `d6d94798a288e4836ebdb32ba78fcf05ee2b08b4`

## Scope

This line owns only integration locks, acceptance runner/tests, and the
catalog/contract-test denominator update required when declaration-only P0
providers become visible. It must not rewrite product behavior in the Agent,
Evidence, Workflow, Data Consumer, Classification ML, or Report packages.
Product defects are returned to the owning candidate line and invalidate all
downstream candidate evidence.

## Non-negotiable safety and evidence rules

- There is one active candidate SHA and one serial merge queue.
- Every merge is explicit, conflict-resolved by named paths, and followed by
  focused tests plus provider/catalog verification.
- The catalog is declaration-driven. Provider rows may expand the denominator;
  a blocked/unavailable row is evidence, not a silently skipped row.
- Evaluation manifests are immutable and must name the exact candidate SHA.
- Deterministic, independent, browser, provider, formal, host, full-gate and
  release claims remain separate. Unrun boundaries are `NOT VERIFIED`.
- No push, protected-branch merge, tag or release is authorized by this line.

## Boundary
- Affected paths: `backend/workbench/qa/v189_foundation_acceptance.py`, `scripts/v189_foundation_acceptance_runner.py`, `tests/test_v189_foundation_acceptance.py`, `tests/contracts/test_v189_contract_lock.py`, `tests/test_v189_agent_compiler.py`, `tests/test_v189_workflow_truth.py`, `backend/workbench/providers/builtin/workflow_post_estimation.json`, `frontend/src/lineage/LineageRouteContainer.v189.test.tsx`, `frontend/src/notebook/NotebookRouteView.v189.test.tsx`, `frontend/src/report/ReportView.integration-v189.test.tsx`, `docs/superpowers/release-trains/v1.8.9/locks/c1-p0.yaml`, `docs/superpowers/release-trains/v1.8.9/locks/c2-p1.yaml`, `docs/superpowers/release-trains/v1.8.9/locks/c3-cutover.yaml`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-foundation-integration.md`, `docs/superpowers/objectives/2026-08-15-v1.8.9-foundation-integration-objective.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-foundation-integration-conductor-handoff.md`
- Allowed paths: `backend/workbench/qa/v189_foundation_acceptance.py`, `scripts/v189_foundation_acceptance_runner.py`, `tests/test_v189_foundation_acceptance.py`, `tests/contracts/test_v189_contract_lock.py`, `tests/test_v189_agent_compiler.py`, `tests/test_v189_workflow_truth.py`, `backend/workbench/providers/builtin/workflow_post_estimation.json`, `frontend/src/lineage/LineageRouteContainer.v189.test.tsx`, `frontend/src/notebook/NotebookRouteView.v189.test.tsx`, `frontend/src/report/ReportView.integration-v189.test.tsx`, `docs/superpowers/release-trains/v1.8.9/locks/c1-p0.yaml`, `docs/superpowers/release-trains/v1.8.9/locks/c2-p1.yaml`, `docs/superpowers/release-trains/v1.8.9/locks/c3-cutover.yaml`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-foundation-integration.md`, `docs/superpowers/objectives/2026-08-15-v1.8.9-foundation-integration-objective.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-foundation-integration-conductor-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/evidence`, `backend/workbench/predictive_research`, `backend/workbench/data_operations.py`, `frontend/src/report/ReportView.tsx`, `frontend/src/workbench/registry/sectionRegistry.ts`, `scripts/gate.sh`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p0-workflow-truth-remediation-6`, `v1-8-9-p0-evidence-host-transport-hardening`, `v1-8-9-p0-agent-compiler-remediation-5`, `v1-8-9-p0-legacy-compilation-authority-cutover`, `v1-8-9-independent-evaluation-remediation`
- Tests: `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/test_v189_foundation_acceptance.py -q`, `cd frontend && npm test -- --run src/lineage/LineageRouteContainer.v189.test.tsx src/notebook/NotebookRouteView.v189.test.tsx src/report/ReportView.integration-v189.test.tsx && npm run typecheck`
- Known gates: `deterministic, independent, browser, provider, formal, host, full-gate and release claims remain separate`, `provider catalog denominator/order/digest must be reverified after each candidate merge`

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
