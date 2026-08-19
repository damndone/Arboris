# Frozen Context Pack

Line: `v1-8-9-p0-legacy-compilation-authority-cutover`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 P0 Legacy Compilation Authority Cutover Objective

Retire the publicly constructible C0 `ServerCompilationRecordIssuerV1` as a
security authority. The independent audit proved that a caller can create the
issuer, register a typed draft, compile it, issue a server reference and have
the record store resolve it without the new PlanCompiler, host authority or
supervisor. This is an open P0 bypass.

Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
Formal line: v1-8-9-p0-legacy-compilation-authority-cutover
Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-legacy-cutover

Required outcomes:

- public legacy issuer construction, registration, compile, record and issue
  paths fail closed without an authority receipt from the trusted host/compiler
  boundary; caller-supplied project/session/principal metadata is not authority;
- no public re-export or compatibility alias can silently restore the legacy
  signing path; old historical records remain readable as untrusted data but
  cannot be upgraded into a server reference;
- the new host-bound PlanCompiler integration seam is explicit and typed; no
  module-private key, environment variable, JSON, pickle, object.__new__ or
  process-local token is treated as the trust root;
- focused C0 compatibility tests are migrated to a host-backed test harness or
  explicitly marked as non-authoritative fixtures, with negative probes for
  caller-created issuer, cross-scope, serialization and fork reuse;
- valid host-backed compilation/replay remains possible through the explicit
  integration seam; production supervisor wiring remains a separate gate.

## Boundary
- Affected paths: `backend/workbench/contracts/agent/planning.py`, `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/planning_contracts.py`, `backend/workbench/agent/compilation_store.py`, `tests/contracts/test_v189_contract_lock.py`, `tests/test_v189_legacy_compilation_authority.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-legacy-compilation-authority-cutover.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-legacy-compilation-authority-cutover-handoff.md`
- Allowed paths: `backend/workbench/contracts/agent/planning.py`, `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/planning_contracts.py`, `backend/workbench/agent/compilation_store.py`, `tests/contracts/test_v189_contract_lock.py`, `tests/test_v189_legacy_compilation_authority.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-legacy-compilation-authority-cutover.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-legacy-compilation-authority-cutover-handoff.md`
- Protected paths: `backend/workbench/agent/workflow.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/notebook`, `backend/workbench/evidence`, `backend/workbench/services/results_service.py`, `backend/workbench/report_view_model.py`, `backend/workbench/predictive_research`, `frontend`, `scripts/gate.sh`, `.agent/devlines`
- Dependencies: `v1-8-9-p0-agent-compiler-remediation-5`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/contracts/test_v189_contract_lock.py ../tests/test_v189_legacy_compilation_authority.py -q`
- Known gates: `trusted host/supervisor wiring and integration with the accepted Compiler-5 implementation remain NOT VERIFIED`, `Agent/Notebook route cutover, provider, browser, full gate and release remain NOT VERIFIED`, `no commit, merge, push or tag is authorized`

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
