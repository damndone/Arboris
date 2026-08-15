# Work Order — v1.8.9 Contract Lock C0

```yaml
work_package: v1-8-9-contract-lock
lane: contract-lock
release_baseline_commit: f564de63b2ca901bc76360e9ace62e89992670d3
repository_main_at_kickoff: 376fe4e202e25d77ca62a6aa214c25032a8e103c
pre_plan_design_commit: 167481748097e64a08896853a59fa0efe0f77bef
plan_lock_commit: f3836408cf15c3e7380823e5c1b303b4467c7aec
integration_base_commit: f3836408cf15c3e7380823e5c1b303b4467c7aec
branch_start_commit: f3836408cf15c3e7380823e5c1b303b4467c7aec
branch: workbench-v1.8.9-contract-lock
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-contract-lock
formal_line: v1-8-9-contract-lock

owned_files:
  - backend/workbench/contracts/common/contract_ref.py
  - backend/workbench/contracts/common/foundation_status.py
  - backend/workbench/contracts/common/provider.py
  - backend/workbench/contracts/workflow/state.py
  - backend/workbench/contracts/agent/planning.py
  - backend/workbench/contracts/agent/execution_admission.py
  - backend/workbench/contracts/agent/context_egress.py
  - backend/workbench/contracts/evidence/envelope.py
  - backend/workbench/contracts/evidence/persistence.py
  - backend/workbench/contracts/prediction/holdout.py
  - backend/workbench/providers/catalog.py
  - backend/workbench/providers/builtin/contract_fixture.json
  - tests/contracts/test_v189_contract_lock.py
  - tests/fixtures/contracts/v189/**
  - docs/superpowers/release-trains/v1.8.9/contract-lock-manifest.yaml
  - docs/superpowers/release-trains/v1.8.9/work-orders/wo-contract-lock.md
  - docs/superpowers/handoff/2026-08-15-v1.8.9-contract-lock-handoff.md

read_only_contracts:
  - backend/workbench/canonical.py
  - backend/workbench/contracts/common/envelope.py
  - backend/workbench/contracts/model/result_envelope.py
  - backend/workbench/contracts/model/validation_levels.py
  - backend/workbench/agent/capability_contract.py
  - backend/workbench/agent/workflow_contracts.py
  - backend/workbench/agent/workflow_capability_registry.py
  - backend/workbench/agent/workflow_capability_adapters.py

forbidden_files:
  - backend/workbench/agent/workflow.py
  - backend/workbench/agent/workflow_runtime.py
  - backend/workbench/agent/orchestrator.py
  - backend/workbench/agent/operations.py
  - backend/workbench/agent/notebook/**
  - backend/workbench/graph_store.py
  - backend/workbench/predictive_research/**
  - frontend/**
  - scripts/gate.sh
  - tests/test_honest_did_adversarial.py
  - tests/test_honest_did_sd_adversarial.py

consumes:
  - canonical_json_v1 and sha256_canonical from backend/workbench/canonical.py
  - existing CapabilityContract and workflow registry as read-only runtime truth
  - v1.8.9 Plan Lock spec and implementation program

produces:
  - strict ContractRefV1 and shared foundation status contracts
  - workflow, planning, admission, egress, evidence and holdout public schemas
  - deterministic repository-local ProviderContribution catalog inputs
  - canonical producer, consumer, legacy and corrupt fixture packets
  - non-self-referential Contract Lock manifest and evidence-layered handoff

focused_tests:
  - "cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/contracts/test_v189_contract_lock.py -q"

baseline_evidence:
  command: "PYTHONPATH=$PWD/backend .venv/bin/python -m pytest tests/contracts/test_v181_contract_lock.py tests/contracts/test_v183_contract_lock.py tests/test_workflow_contracts_v186.py tests/test_workflow_capability_registry.py -q"
  observed_result: "137 passed in 11.58s"

mutation_requirements:
  - duplicate resolver mutation must fail
  - validation-level promotion mutation must fail
  - authority/hash weakening mutations must fail
  - path-like executor and provider-order mutations must fail

known_gates:
  - focused Contract Lock tests do not prove feature behavior
  - browser acceptance is NOT VERIFIED
  - real provider behavior is NOT VERIFIED
  - full release gate is NOT VERIFIED
  - merge, push, tag and release are not authorized

rollback:
  - abandon the isolated branch/worktree; do not rewrite Plan Lock or main
```

## Acceptance

- Every owned schema has strict round-trip behavior and stable error codes.
- Duplicate, unresolved, unknown-major, digest-mismatched, malformed and
  path-like declarations fail closed.
- Catalog order and digest are deterministic, and current live runtime
  operation identities remain unchanged.
- Canonical fixtures cover valid, legacy, unavailable, blocked, corrupt and
  adversarial packets without becoming product routing logic.
- Formal scope, events, verification and retrospective are produced only by
  `scripts/devline_control.py`.

## Non-goals

- Product capability implementation or runtime cutover.
- Statistical estimator, Graph, Notebook, Report or frontend changes.
- Arbitrary Python, shell, network or external plugin execution.
- Browser/provider/full-gate/release evidence.
