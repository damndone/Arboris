# Frozen Context Pack

Line: `v1-8-9-p0-evidence-core-remediation-4`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 P0 Evidence Core Remediation 4 Objective

Close the final public-construction and proof-forgery gaps found by the
remediation-3 adversarial review. EvidenceRegistry construction must be
server-factory-only and its durable namespace must be bound to a
server-issued authority proof; object.__new__ or a caller-created registry
must not make hand-built packet/commit/index artifacts loadable. Persistence
admission must validate a non-reconstructible server proof, and projector
success must require a non-reconstructible receipt rather than a recomputable
summary hash. Invalid proof objects must fail with stable typed errors before
reading or writing durable evidence.

Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
Remediation line: v1-8-9-p0-evidence-core-remediation-4
Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core

Required outcomes:

- public `EvidenceRegistryV1()` and caller-created registries cannot admit or
  load durable evidence; only the server factory can issue the registry proof;
- object.__new__/field-forged `EvidencePersistenceAdmissionV1` cannot write;
- fake/recomputed projector receipts cannot create a consumer-visible success;
- malformed, cross-owner and cross-process proofs fail with typed,
  deterministic errors before packet/index reads;
- existing 68 focused cases plus direct construction, proof forgery and
  no-read/no-write probes remain green.

Keep the C0 contracts and package-local boundary. Do not modify runtime,
consumers, central catalog, frontend, provider wiring, or protected paths.

## Boundary
- Affected paths: `backend/workbench/evidence/__init__.py`, `backend/workbench/evidence/contracts.py`, `backend/workbench/evidence/registry.py`, `backend/workbench/evidence/projection.py`, `backend/workbench/evidence/persistence.py`, `backend/workbench/providers/builtin/evidence_core.json`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core-remediation-4.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-core-remediation-4-handoff.md`
- Allowed paths: `backend/workbench/evidence/__init__.py`, `backend/workbench/evidence/contracts.py`, `backend/workbench/evidence/registry.py`, `backend/workbench/evidence/projection.py`, `backend/workbench/evidence/persistence.py`, `backend/workbench/providers/builtin/evidence_core.json`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core-remediation-4.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-core-remediation-4-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/services/results_service.py`, `backend/workbench/report_view_model.py`, `backend/workbench/predictive_research`, `frontend`, `scripts/gate.sh`, `.agent/devlines`
- Dependencies: `v1-8-9-p0-evidence-core-remediation-3`
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
