# Frozen Context Pack

Line: `v1-8-9-p0-evidence-host-transport-hardening`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# Workbench v1.8.9 — Evidence Host Transport Hardening Objective

## Objective

Harden the deployment-only Evidence host bootstrap transport after independent
adversarial review. The bootstrap must remain fail-closed while guaranteeing
ownership and cleanup of every duplicated control descriptor and every
`SCM_RIGHTS` descriptor on all parse, timeout, ancillary, wrapping and
admission failures. It must explicitly make received authority sockets
non-inheritable and accept bounded, correctly framed Unix stream control
messages without treating a single `recvmsg()` call as a message boundary.

Extend the existing direct probes to cover fragmented control frames, extra
frames, unsupported ancillary data after received rights, descriptor cleanup,
close-on-exec, and typed timeout/unavailable failures. Preserve the existing
endpoint path/inode/peer/handshake binding and one-shot semantics.

This line does not claim that the real supervisor launch configuration,
Workbench startup lifecycle, or a separate host process has been wired. Those
remain explicit integration gates. The same-process untrusted-plugin threat
also remains blocked at the deployment/startup architecture boundary until
the application invokes bootstrap before loading untrusted extensions.

## In scope

- `backend/workbench/evidence/deployment_authority.py`
- `backend/workbench/evidence/authority.py` only for descriptor lifecycle,
  non-inheritable channel state, and strict RPC frame consumption
- `tests/test_v189_evidence_host_bootstrap.py`
- `tests/test_v189_evidence_envelope.py` only where the FD lifecycle probe
  exercises the shared admission helper
- this line's handoff and formal evidence

## Out of scope

- production app startup wiring or supervisor implementation
- changing endpoint authority semantics, scope/session policy, or provider
  behavior
- Agent/Notebook route cutover, browser/provider acceptance, release, merge,
  push, or tag

## Acceptance criteria

- all newly identified FD-leak probes fail before the fix and pass after it;
- control frames may be split across bounded stream reads but extra bytes or
  extra frames are rejected and all received descriptors are closed;
- received control and endpoint descriptors are non-inheritable before any
  admitted handle is returned;
- control timeout and transport-unavailable failures use the existing typed
  Evidence error vocabulary;
- the complete Evidence focused suite, compileall, diff check, and three
  consecutive direct-probe rounds pass;
- the handoff distinguishes package-local transport completion from the
  unverified production startup and deployment gates.

## Known gates

- real supervisor-owned resolver and FD handoff: `NOT VERIFIED`
- Workbench startup lifecycle before untrusted extensions: `NOT VERIFIED`
- separate supervisor/host process topology: `NOT VERIFIED`
- real provider, browser, full gate, release and merge: `NOT VERIFIED`

## Boundary
- Affected paths: `backend/workbench/evidence/deployment_authority.py`, `backend/workbench/evidence/authority.py`, `tests/test_v189_evidence_host_bootstrap.py`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-host-transport-hardening-handoff.md`
- Allowed paths: `backend/workbench/evidence/deployment_authority.py`, `backend/workbench/evidence/authority.py`, `tests/test_v189_evidence_host_bootstrap.py`, `tests/test_v189_evidence_envelope.py`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-evidence-host-transport-hardening-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/app.py`, `frontend/src`
- Dependencies: `v1-8-9-p0-evidence-core-remediation-7`
- Tests: `tests/test_v189_evidence_host_bootstrap.py`, `tests/test_v189_evidence_envelope.py`, `compileall`, `git-diff-check`
- Known gates: `real-supervisor-wiring-not-verified`, `startup-before-untrusted-extensions-not-verified`, `separate-supervisor-host-topology-not-verified`, `browser-provider-full-gate-release-not-verified`

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
