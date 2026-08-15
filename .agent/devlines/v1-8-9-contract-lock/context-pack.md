# Frozen Context Pack

Line: `v1-8-9-contract-lock`
Baseline SHA: `f3836408cf15c3e7380823e5c1b303b4467c7aec`

## Objective
# v1.8.9 Contract Lock Objective

## Objective

Create the minimal versioned public contracts, deterministic builtin provider
catalog, canonical fixtures and compatibility tests required for parallel P0/P1
development. Preserve the existing runtime registries as authority until the
explicit cutover line. Do not add product capabilities, switch execution,
modify statistical results, open third-party discovery, install dependencies,
or claim browser/provider/release evidence.

## Baseline

- Plan Lock: `f3836408cf15c3e7380823e5c1b303b4467c7aec`
- Branch: `workbench-v1.8.9-contract-lock`
- Worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-contract-lock`
- Formal line: `v1-8-9-contract-lock`

## Required outcomes

- Versioned public refs and schemas have strict canonical serialization,
  semantic-version and digest validation, and stable fail-closed reason codes.
- Provider declarations compose contract refs without importing or executing
  feature code, and the builtin catalog is deterministic and repository-local.
- Canonical valid, legacy, blocked, unavailable and corrupt packets prove
  producer/consumer compatibility without changing current runtime authority.
- Focused tests and mutation anchors prove duplicate, unresolved, incompatible,
  path-like and authority-bypass inputs are rejected.
- The non-self-referential C0 manifest and handoff separate implementation,
  tests, formal verification and all unperformed acceptance layers.

## Boundaries

- No changes to runtime, orchestrator, Notebook, Graph, frontend, release gate
  or statistical implementation paths.
- No dynamic imports, third-party manifest discovery, dependency installation,
  shell/network execution or implicit compatibility coercion.
- No browser, provider, full-gate, merge, push, tag or release claims.
- All formal state is managed only through `scripts/devline_control.py`.

## Boundary
- Affected paths: `backend/workbench/contracts/common/contract_ref.py`, `backend/workbench/contracts/common/foundation_status.py`, `backend/workbench/contracts/common/provider.py`, `backend/workbench/contracts/workflow/state.py`, `backend/workbench/contracts/agent/planning.py`, `backend/workbench/contracts/agent/execution_admission.py`, `backend/workbench/contracts/agent/context_egress.py`, `backend/workbench/contracts/evidence/envelope.py`, `backend/workbench/contracts/evidence/persistence.py`, `backend/workbench/contracts/prediction/holdout.py`, `backend/workbench/providers/catalog.py`, `backend/workbench/providers/builtin/contract_fixture.json`, `tests/contracts/test_v189_contract_lock.py`, `tests/fixtures/contracts/v189`, `docs/superpowers/release-trains/v1.8.9/contract-lock-manifest.yaml`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-contract-lock.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-contract-lock-handoff.md`
- Allowed paths: `backend/workbench/contracts/common/contract_ref.py`, `backend/workbench/contracts/common/foundation_status.py`, `backend/workbench/contracts/common/provider.py`, `backend/workbench/contracts/workflow/state.py`, `backend/workbench/contracts/agent/planning.py`, `backend/workbench/contracts/agent/execution_admission.py`, `backend/workbench/contracts/agent/context_egress.py`, `backend/workbench/contracts/evidence/envelope.py`, `backend/workbench/contracts/evidence/persistence.py`, `backend/workbench/contracts/prediction/holdout.py`, `backend/workbench/providers/catalog.py`, `backend/workbench/providers/builtin/contract_fixture.json`, `tests/contracts/test_v189_contract_lock.py`, `tests/fixtures/contracts/v189`, `docs/superpowers/release-trains/v1.8.9/contract-lock-manifest.yaml`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-contract-lock.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-contract-lock-handoff.md`
- Protected paths: `frontend`, `scripts/gate.sh`
- Dependencies: none
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/contracts/test_v189_contract_lock.py -q`
- Known gates: `Contract Lock is process and schema evidence; it does not prove feature, browser, provider, full-gate or release acceptance`

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
