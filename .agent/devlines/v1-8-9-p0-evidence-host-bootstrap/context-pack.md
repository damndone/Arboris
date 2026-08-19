# Frozen Context Pack

Line: `v1-8-9-p0-evidence-host-bootstrap`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 Evidence Host Bootstrap Objective

Add the deployment-only bootstrap transport needed by Evidence Core.  The
package-local Evidence authority protocol already verifies a host endpoint;
this line supplies the missing supervisor-owned control channel that delivers
one endpoint descriptor and one passed client FD to the Workbench process.
No request, public resolver, environment-selected path or caller-created
configuration may become the Evidence trust root.

Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
Development line: v1-8-9-p0-evidence-host-bootstrap
Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core

Required outcomes:

- receive a bounded canonical control frame and exactly one endpoint FD from a
  supervisor-owned inherited control descriptor;
- validate the control peer against the Workbench parent process and bind the
  received endpoint config to that peer before invoking the existing Evidence
  admission/handshake;
- reject missing or malformed control frames, missing/multiple FDs, wrong peer,
  endpoint replacement, replay and fork reuse before registry success;
- keep the existing public caller-selected configuration rejection and the
  package-local test resolver seam unchanged; do not claim production
  supervisor launch verification from a same-process fixture;
- expose only a startup/bootstrap function with no request configuration
  argument; application lifecycle wiring belongs to the later single-owner
  integration cutover.

Owned paths:

- backend/workbench/evidence/deployment_authority.py
- backend/workbench/evidence/__init__.py
- tests/test_v189_evidence_host_bootstrap.py
- docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-host-bootstrap-handoff.md

Tests and gates:

- red tests before implementation;
- focused bootstrap tests and the existing Evidence envelope suite;
- compileall and git diff --check;
- formal verification and retrospective generation;
- real deployment supervisor, browser/provider/full-gate and release evidence
  remain separate and are NOT VERIFIED by this line.

## Boundary
- Affected paths: `backend/workbench/evidence/deployment_authority.py`, `backend/workbench/evidence/__init__.py`, `tests/test_v189_evidence_host_bootstrap.py`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-host-bootstrap-handoff.md`
- Allowed paths: `backend/workbench/evidence/deployment_authority.py`, `backend/workbench/evidence/__init__.py`, `tests/test_v189_evidence_host_bootstrap.py`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-host-bootstrap-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/app.py`, `frontend/src`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p0-evidence-core-remediation-7`
- Tests: `cd backend && PYTHONPATH=$PWD /Users/jiayuanren/项目规划/.venv/bin/python -m pytest ../tests/test_v189_evidence_host_bootstrap.py -q`, `cd backend && PYTHONPATH=$PWD /Users/jiayuanren/项目规划/.venv/bin/python -m pytest ../tests/test_v189_evidence_envelope.py -q --disable-warnings`
- Known gates: `supervisor launch and OS peer identity remain separate deployment evidence`, `browser/provider/full-gate/release claims remain NOT VERIFIED`

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
