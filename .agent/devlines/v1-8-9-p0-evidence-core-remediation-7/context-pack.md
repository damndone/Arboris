# Frozen Context Pack

Line: `v1-8-9-p0-evidence-core-remediation-7`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 P0 Evidence Core Remediation 7 Objective

Close the remaining Evidence host-authority trust-root gap found by the
remediation-6 independent review. A caller must not be able to supply the
endpoint path, inode, peer identity, scope, session, secret and self-authored
protocol together and obtain an Evidence registry, persistence receipt or
successful projection. The package must consume only an authority handle
admitted by the deployment-owned host boundary; self-attested endpoint
configuration and caller-started authority servers must fail closed. Add a
bounded RPC timeout so an unavailable or malicious host cannot hang the Agent
or Notebook request indefinitely.

Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
Remediation line: v1-8-9-p0-evidence-core-remediation-7
Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core

Required outcomes:

- public Evidence admission does not accept caller-selected trust-root fields;
  deployment-owned endpoint configuration and bootstrap material arrive only
  from the external host/supervisor boundary, with no package-local issuance
  fallback;
- caller-created socket/socketpair, self-authored server/protocol, fake or
  caller-selected config/FD, wrong peer/path/inode/handshake and absent host
  resolver all fail closed before registry, persistence or projection success;
- valid externally admitted host authority preserves scope/session/purpose
  binding and all existing evidence integrity, persistence and projection
  behavior;
- authority RPC reads/writes have an explicit bounded timeout and return a
  stable typed unavailable/timeout failure;
- copy/deepcopy/pickle/JSON/object.__new__/fork and malformed authority inputs
  remain fail closed;
- production host resolver wiring remains an explicit integration dependency;
  this line must not claim it is verified by package-local fixtures.

## Boundary
- Affected paths: `backend/workbench/evidence/authority.py`, `backend/workbench/evidence/__init__.py`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core-remediation-7.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-core-remediation-7-handoff.md`
- Allowed paths: `backend/workbench/evidence/authority.py`, `backend/workbench/evidence/__init__.py`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-evidence-core-remediation-7.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-core-remediation-7-handoff.md`
- Protected paths: `backend/workbench/contracts`, `backend/workbench/agent`, `backend/workbench/data_operations.py`, `backend/workbench/services/results_service.py`, `backend/workbench/report_view_model.py`, `backend/workbench/predictive_research`, `frontend`, `scripts/gate.sh`, `.agent/devlines`
- Dependencies: `v1-8-9-p0-evidence-core-remediation-6`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_evidence_envelope.py -q`
- Known gates: `production host resolver/deployment wiring and downstream runtime cutover remain NOT VERIFIED`, `provider execution, browser, full gate and release remain NOT VERIFIED`, `no commit, merge, push or tag is authorized`

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
