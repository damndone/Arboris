# Retrospective — v1-8-9-p0-evidence-host-transport-hardening

## Goal

# Workbench v1.8.9 — Evidence Host Transport Hardening Objective  ## Objective  Harden the deployment-only Evidence host bootstrap transport after independent adversarial review. The bootstrap must remain fail-closed while guaranteeing ownership and cleanup of every duplicated control descriptor and every \`SCM_RIGHTS\` descriptor on all parse, timeout, ancillary, wrapping and admission failures. It must explicitly make received authority sockets non-inheritable and accept bounded, correctly framed Unix stream control messages without treating a single \`recvmsg()\` call as a message boundary.  Extend the existing direct probes to cover fragmented control frames, extra frames, unsupported ancillary data after received rights, descriptor cleanup, close-on-exec, and typed timeout/unavailable failures. Preserve the existing endpoint path/inode/peer/handshake binding and one-shot semantics.  This line does not claim that the real supervisor launch configuration, Workbench startup lifecycle, or a separate host process has been wired. Those remain explicit integration gates. The same-process untrusted-plugin threat also remains blocked at the deployment/startup architecture boundary until the application invokes bootstrap before loading untrusted extensions.  ## In scope  - \`backend/workbench/evidence/deployment_authority.py\` - \`backend/workbench/evidence/authority.py\` only for descriptor lifecycle,   non-inheritable channel state, and strict RPC frame consumption - \`tests/test_v189_evidence_host_bootstrap.py\` - \`tests/test_v189_evidence_envelope.py\` only where the FD lifecycle probe   exercises the shared admission helper - this line's handoff and formal evidence  ## Out of scope  - production app startup wiring or supervisor implementation - changing endpoint authority semantics, scope/session policy, or provider   behavior - Agent/Notebook route cutover, browser/provider acceptance, release, merge,   push, or tag  ## Acceptance criteria  - all newly identified FD-leak probes fail before the fix and pass after it; - control frames may be split across bounded stream reads but extra bytes or   extra frames are rejected and all received descriptors are closed; - received control and endpoint descriptors are non-inheritable before any   admitted handle is returned; - control timeout and transport-unavailable failures use the existing typed   Evidence error vocabulary; - the complete Evidence focused suite, compileall, diff check, and three   consecutive direct-probe rounds pass; - the handoff distinguishes package-local transport completion from the   unverified production startup and deployment gates.  ## Known gates  - real supervisor-owned resolver and FD handoff: \`NOT VERIFIED\` - Workbench startup lifecycle before untrusted extensions: \`NOT VERIFIED\` - separate supervisor/host process topology: \`NOT VERIFIED\` - real provider, browser, full gate, release and merge: \`NOT VERIFIED\`

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-16T15:36:56.000Z `transport_hardening_red_suite`; cause_status: `known`; cause: The new direct probes initially reproduced eight failures: duplicate control FD cleanup, rights cleanup after unsupported ancillary and timeout restore, control non-inheritance, typed timeout/unavailable mapping, and endpoint non-inheritance.; resolution: `resolved`; lesson: For FD-passing transports, write direct failure probes before implementation so cleanup and inheritance bugs cannot hide behind happy-path protocol tests.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `fd-transport-red-probes`: occurrences=1; cause_status: `known`; root cause: The new direct probes initially reproduced eight failures: duplicate control FD cleanup, rights cleanup after unsupported ancillary and timeout restore, control non-inheritance, typed timeout/unavailable mapping, and endpoint non-inheritance.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `fd-transport-red-probes`: line experience occurrence(s)=1

## Future guidance

- A green protocol suite is not enough for a descriptor-passing boundary; exercise ownership, inheritance, stream framing and real failure cleanup with direct probes before integration claims.
- Close a transport hardening line only when source ownership review, complete regression tests and repeated direct probes agree, while retaining deployment lifecycle gaps as explicit gates.
- For FD-passing transports, write direct failure probes before implementation so cleanup and inheritance bugs cannot hide behind happy-path protocol tests.

## Event index

- #1: `2ac352f6-5b63-4b56-9c1e-7f5f39eb9e44` | 2026-08-16T15:27:55.643Z | STATE_CHANGE/line_started | incident=`0b44b0ca-a8f9-4943-ade8-938d1dab4937` | lesson_key=`frozen-context-before-start` | event_sha256=`3dcd4dc89920c41c7612a73df1d5c0b10c497973cd0c2e663e40eb9cc71488d4`
- #2: `8a6b4c2d-1e0f-4a9b-7c6d-5432109876fe` | 2026-08-16T15:29:10.000Z | REVIEW/independent_transport_security_review | incident=`5e4d3c2b-1a0f-4987-b6c5-4321098765fe` | lesson_key=`transport-boundary-direct-probes` | event_sha256=`28e1e8ab71172c0050e4253631f59f3d6217cf42f59e38b524e4ae907d6c6008`
- #3: `9b7c5d3e-1f0a-4b8c-6d5e-4321098765fe` | 2026-08-16T15:36:56.000Z | FAILURE/transport_hardening_red_suite | incident=`6d5e4c3b-2a1f-0987-6e5d-4321098765ab` | lesson_key=`fd-transport-red-probes` | event_sha256=`4286284f27141341dc5212d01e8fc90116b83eab62b2cc8d48b767b2c9d5c008`
- #4: `0c9e7a5b-3d1f-4b2a-6c8e-5432109876ab` | 2026-08-16T15:40:25.000Z | REVIEW/transport_hardening_bounded_review | incident=`7b6a5c4d-3e2f-1098-7654-3210fedcba98` | lesson_key=`transport-review-and-deployment-gates` | event_sha256=`566a0508a0c1c77a7d9299ea13b2bcfff2efc6449770f3f3e60c28d05452639a`
- #5: `1d0f9e8c-7b6a-4c5d-3e2f-1098765432ab` | 2026-08-16T15:41:00.000Z | STATE_CHANGE/transport_hardening_package_completed | incident=`8c7b6a5d-4e3f-2109-a8b7-6543210fedcb` | lesson_key=`transport-package-completion-boundary` | event_sha256=`7ffb9d90fceb3908623fd2e8d3b2dc4c41d91eeee47e2d711a7e659a2c551a80`
