# Frozen Context Pack

Line: `v1-8-9-c1-host-authority`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 C1 Trusted Host Authority Integration Objective

Close the production-boundary gap left by the package-local Evidence Core.
Workbench must have one deployment-owned, out-of-process host authority
bootstrap path that can provide the Evidence authority channel to Agent,
Notebook and Report code without allowing a request caller to select the
endpoint path, peer identity, scope, session or secret.  The package must
remain fail-closed when the deployment boundary is absent, malformed, stale,
replaced, inherited across a fork, or supplied by a self-started process.

Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
Development line: v1-8-9-c1-host-authority
Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-c1-host-authority

Required outcomes:

- define a deployment-owned host authority bootstrap contract and adapter;
  deployment identity and endpoint material arrive through a supervisor-owned
  descriptor/control channel, not a request argument, mutable module default,
  arbitrary environment path or caller-selected resolver;
- establish the authority channel from a real separate process using POSIX
  peer credentials, stable endpoint identity, owner/session binding and the
  existing Evidence handshake/proof protocol;
- wire application startup/bootstrap to install the host authority only after
  the deployment contract has been verified, and leave the product fail-closed
  when the host is unavailable or verification fails;
- prove wrong peer, endpoint replacement, malformed control data, stale/forked
  descriptor and self-authored endpoint attempts fail before an Evidence
  registry/persistence/projection success; prove a valid supervisor-hosted
  endpoint works through the same public Evidence factories;
- keep the adapter free of statistics, Agent planning and consumer semantics;
  preserve the existing package-local test seam only as test plumbing and label
  it as not production verification;
- record the unresolved production deployment prerequisites explicitly if the
  repository cannot prove supervisor launch/OS identity in this line.

Owned paths for this line:

- backend/workbench/evidence/deployment_authority.py
- backend/workbench/evidence/authority.py
- backend/workbench/app.py
- tests/test_v189_host_authority_integration.py
- docs/superpowers/handoff/2026-08-16-v1.8.9-c1-host-authority-handoff.md

Required tests and gates:

- red tests first for the public bootstrap contract and separate-process
  supervisor proof;
- focused host authority and existing Evidence envelope suites;
- compileall and git diff --check;
- formal devline verification and retrospective generation;
- host deployment wiring, browser/provider/full-gate and release claims remain
  separate evidence and must be reported as NOT VERIFIED unless directly run.

## Boundary
- Affected paths: `backend/workbench/evidence/deployment_authority.py`, `backend/workbench/evidence/authority.py`, `backend/workbench/app.py`, `tests/test_v189_host_authority_integration.py`, `docs/superpowers/handoff/2026-08-16-v1.8.9-c1-host-authority-handoff.md`
- Allowed paths: `backend/workbench/evidence/deployment_authority.py`, `backend/workbench/evidence/authority.py`, `backend/workbench/app.py`, `tests/test_v189_host_authority_integration.py`, `docs/superpowers/handoff/2026-08-16-v1.8.9-c1-host-authority-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/predictive_research`, `frontend/src`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p0-evidence-core`
- Tests: `cd backend && PYTHONPATH=$PWD /Users/jiayuanren/项目规划/.venv/bin/python -m pytest ../tests/test_v189_host_authority_integration.py -q`, `cd backend && PYTHONPATH=$PWD /Users/jiayuanren/项目规划/.venv/bin/python -m pytest ../tests/test_v189_evidence_envelope.py -q --disable-warnings`
- Known gates: `deployment supervisor launch and OS peer identity must be proven separately from package-local fixtures`, `browser/provider/full-gate/release evidence remains NOT VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-3-cf4-notebook-provider-injection (2026-07-26T22:45:00.000Z)

Completed formal devline v1-8-3-cf4-notebook-provider-injection; final_state=COMPLETED; failure_lesson_keys=formal-rescope-boundary, tdd-red-before-provider-injection
