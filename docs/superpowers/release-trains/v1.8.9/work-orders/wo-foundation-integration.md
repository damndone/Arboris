# Work Order — v1.8.9 Foundation Integration

work_package: v1-8-9-foundation-integration
lane: foundation-integration
baseline_commit: f3836408cf15c3e7380823e5c1b303b4467c7aec
formal_line: v1-8-9-foundation-integration
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-foundation-integration

## Merge inputs

| input | exact SHA | role |
|---|---|---|
| C0 Contract Lock | `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749` | frozen contracts/catalog baseline |
| P0 Agent Compiler | `8017f6ae6c59a35851a315c3e6a5806c52367f74` | server-owned plan/compiler boundary |
| P0 legacy cutover | `fd54600ed726ed6896c7d13b19e7924320d5c8b8` | retire local compilation authority |
| P0 Evidence Core | `9db6815768f881c31928bf5e8cc8c1bac688ed73` | evidence authority/transport/persistence |
| P0 Workflow Truth | `e7593dd5788a73ee5bae94236bbdff75bbf62349` | receipt-bound runtime/report truth |
| Evaluation Harness | `d6d94798a288e4836ebdb32ba78fcf05ee2b08b4` | candidate-bound independent evaluation |

## Owned paths

- `backend/workbench/qa/v189_foundation_acceptance.py`
- `scripts/v189_foundation_acceptance_runner.py`
- `tests/test_v189_foundation_acceptance.py`
- `tests/contracts/test_v189_contract_lock.py`
- `tests/test_v189_agent_compiler.py` (compatibility-test correction only; no Agent product behavior)
- `tests/test_v189_workflow_truth.py` (declaration compatibility-test correction only; no Workflow runtime behavior)
- `backend/workbench/providers/builtin/workflow_post_estimation.json` (ProviderContributionV1 schema normalization only; no executor authority)
- `frontend/src/lineage/LineageRouteContainer.v189.test.tsx`
- `frontend/src/notebook/NotebookRouteView.v189.test.tsx`
- `frontend/src/report/ReportView.integration-v189.test.tsx`
- `docs/superpowers/release-trains/v1.8.9/locks/c1-p0.yaml`
- `docs/superpowers/release-trains/v1.8.9/locks/c2-p1.yaml`
- `docs/superpowers/release-trains/v1.8.9/locks/c3-cutover.yaml`
- `docs/superpowers/release-trains/v1.8.9/work-orders/wo-foundation-integration.md`
- `docs/superpowers/objectives/2026-08-15-v1.8.9-foundation-integration-objective.md`
- `docs/superpowers/handoff/2026-08-15-v1.8.9-foundation-integration-conductor-handoff.md`

## Protected paths

- `backend/workbench/agent`
- `backend/workbench/evidence`
- `backend/workbench/predictive_research`
- `backend/workbench/data_operations.py`
- `frontend/src/report/ReportView.tsx`
- `frontend/src/workbench/registry/sectionRegistry.ts`
- `scripts/gate.sh`

## Required gates

- C0 merge and contract-lock verification.
- P0 candidate merge with package-local focused suites and controlled host
  probes where required.
- Catalog denominator/order/digest verification after each provider contribution.
- Candidate-bound deterministic runner with clean SHA/path/dirty-state checks.
- C1/C2/C3 lock files created before their candidate commit and excluding the
  future candidate SHA and future evaluation digest.
- Browser/provider/full-gate/release states remain separate and are never
  inferred from package-local tests.
