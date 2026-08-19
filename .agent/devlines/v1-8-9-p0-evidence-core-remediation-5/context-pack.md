# Frozen Context Pack

Line: `v1-8-9-p0-evidence-core-remediation-5`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 P0 Evidence Core Remediation 5 Objective

Replace in-process module secrets with an explicit host-authority boundary.
The remediation-4 review proved that Python private names are not an
authority boundary: a same-process caller can import construction keys,
HMAC secrets and proof classes. Evidence must therefore accept a
server-issued external authority handle (for example an admitted FD or an
authority-channel response) and verify it without creating a trust root from
caller-provided scope or module globals. Registry, persistence and projection
proofs must all derive from that host authority; copying, pickle, JSON
reconstruction, object.__new__, or importing implementation symbols must not
create a valid proof.

Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
Remediation line: v1-8-9-p0-evidence-core-remediation-5
Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core

Required outcomes:

- a public factory without a host-issued authority handle fails closed;
- the host authority channel is outside Evidence module globals and binds
  scope, root FD/inode, owner, session and proof purpose;
- registry/persistence/projection can only consume a valid host handle and
  cannot mint or verify success using module constants;
- pickle/JSON/copy/object.__new__ handles fail closed with stable typed errors;
- same-process and forked malicious probes cannot create registry, write
  evidence, or manufacture `success=True`; valid host-issued flows retain all
  previous concurrency/path/orphan guarantees.

If the current host runtime lacks the authority channel, record that as an
explicit integration dependency and keep the public product path fail closed.
Do not modify C0 contracts, runtime consumers, central catalog, frontend,
provider wiring, or protected paths in this package-local line.

## Boundary
- Affected paths: `backend/workbench/evidence/__init__.py`, `backend/workbench/evidence/authority.py`, `backend/workbench/evidence/contracts.py`, `backend/workbench/evidence/registry.py`, `backend/workbench/evidence/projection.py`, `backend/workbench/evidence/persistence.py`, `backend/workbench/providers/builtin/evidence_core.json`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core-remediation-5.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-core-remediation-5-handoff.md`
- Allowed paths: `backend/workbench/evidence/__init__.py`, `backend/workbench/evidence/authority.py`, `backend/workbench/evidence/contracts.py`, `backend/workbench/evidence/registry.py`, `backend/workbench/evidence/projection.py`, `backend/workbench/evidence/persistence.py`, `backend/workbench/providers/builtin/evidence_core.json`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core-remediation-5.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-core-remediation-5-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/services/results_service.py`, `backend/workbench/report_view_model.py`, `backend/workbench/predictive_research`, `frontend`, `scripts/gate.sh`, `.agent/devlines`
- Dependencies: `v1-8-9-p0-evidence-core-remediation-4`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_evidence_envelope.py -q`
- Known gates: `host runtime authority-channel wiring, catalog denominator, consumers, browser, provider execution, full gate and release remain NOT VERIFIED`, `no commit, merge, push or tag is authorized`

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
