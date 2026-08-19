# Frozen Context Pack

Line: `v1-8-9-p0-evidence-core-remediation-2`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 P0 Evidence Core Remediation 2 Objective

Close the independently reproduced Evidence Core persistence and provenance
gaps before integration admission. The persistence layer must remain safe when
multiple store instances write the same project, must bind commit identity to
an immutable trusted admission rather than merely matching two mutable files,
and must reject path-like structured references at every nested provenance
boundary. Public projection and persistence-admission value construction must
not provide a success or write capability that bypasses the server-owned
factory/receipt boundary.

Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
Remediation line: v1-8-9-p0-evidence-core-remediation-2
Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core

Required outcomes:

- cross-instance and cross-process concurrent writes preserve every committed
  index entry or fail with a stable retryable conflict;
- commit and packet bindings cannot be changed together and remain accepted;
- ContractRef and nested provenance use one strict closed opaque-ref grammar;
- public projection values cannot be forged into a successful mutable result;
- persistence admission requires an unforgeable server-issued admission token;
- adversarial tests demonstrate each bypass fails before unsafe persistence or
  consumer-visible success.

Keep the locked C0 envelope and package-local boundary. Do not modify runtime,
consumers, central catalog, frontend, provider wiring, or protected paths.

## Boundary
- Affected paths: `backend/workbench/evidence/__init__.py`, `backend/workbench/evidence/contracts.py`, `backend/workbench/evidence/registry.py`, `backend/workbench/evidence/projection.py`, `backend/workbench/evidence/persistence.py`, `backend/workbench/providers/builtin/evidence_core.json`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core-remediation-2.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-core-remediation-2-handoff.md`
- Allowed paths: `backend/workbench/evidence/__init__.py`, `backend/workbench/evidence/contracts.py`, `backend/workbench/evidence/registry.py`, `backend/workbench/evidence/projection.py`, `backend/workbench/evidence/persistence.py`, `backend/workbench/providers/builtin/evidence_core.json`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core-remediation-2.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-core-remediation-2-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/services/results_service.py`, `backend/workbench/report_view_model.py`, `backend/workbench/predictive_research`, `frontend`, `scripts/gate.sh`, `.agent/devlines`
- Dependencies: `v1-8-9-p0-evidence-core-remediation`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_evidence_envelope.py -q`
- Known gates: `catalog denominator, consumers, browser, provider execution, full gate and release remain NOT VERIFIED`, `no commit, merge, push or tag is authorized`

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
