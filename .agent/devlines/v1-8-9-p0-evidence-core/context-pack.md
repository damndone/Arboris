# Frozen Context Pack

Line: `v1-8-9-p0-evidence-core`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 P0 Evidence Core Objective

Build the package-local evidence registry and projection kernel against the locked EvidenceEnvelopeV1 contract. Preserve family semantics and existing validators. Do not modify workflow runtime, services, Agent, Notebook, Report, frontend or consumer coverage; never infer missing facts, trust loose files, or report unavailable/blocked evidence as success.

Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
Branch: workbench-v1.8.9-p0-evidence-core
Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core
Formal line: v1-8-9-p0-evidence-core

Required outcomes:
- Strict facade, registry, projection and persistence preserve EvidenceEnvelopeV1 semantics.
- Missing, corrupt, unavailable, blocked, tampered and cross-scope evidence fail closed.
- Artifact identity and content hash are verified before projection.
- Mutation, replay and consumer-side guessing are covered by focused tests.

Boundaries: no workflow runtime, results service, Agent, Notebook, Report, frontend, classification or data-consumer changes; no loose-file trust, dynamic imports, network execution or release claims. Formal state is managed only by scripts/devline_control.py.

## Boundary
- Affected paths: `backend/workbench/evidence/__init__.py`, `backend/workbench/evidence/contracts.py`, `backend/workbench/evidence/registry.py`, `backend/workbench/evidence/projection.py`, `backend/workbench/evidence/persistence.py`, `backend/workbench/providers/builtin/evidence_core.json`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-p0-evidence-core-handoff.md`
- Allowed paths: `backend/workbench/evidence/__init__.py`, `backend/workbench/evidence/contracts.py`, `backend/workbench/evidence/registry.py`, `backend/workbench/evidence/projection.py`, `backend/workbench/evidence/persistence.py`, `backend/workbench/providers/builtin/evidence_core.json`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-p0-evidence-core-handoff.md`
- Protected paths: `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/services/results_service.py`, `backend/workbench/agent/notebook`, `backend/workbench/report_view_model.py`, `backend/workbench/predictive_research`, `frontend`
- Dependencies: `v1-8-9-contract-lock`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_evidence_envelope.py -q`
- Known gates: `evidence core does not prove persistence wiring, consumers, path coverage, browser, provider, full gate or release`

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
