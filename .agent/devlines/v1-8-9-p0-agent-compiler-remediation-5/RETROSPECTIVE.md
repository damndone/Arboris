# Retrospective — v1-8-9-p0-agent-compiler-remediation-5

## Goal

# v1.8.9 P0 Agent Compiler Remediation 5 Objective  Close the remaining compiler host-authority gap found by the remediation-4 independent review. A caller-created socket or public authority-server constructor must not be able to mint compiler scope, selection, or disabled-NL authority. The public compiler must accept only a deployment-owned host endpoint or a supervisor-passed FD whose identity is bound to that configured endpoint and to OS peer credentials. It must fail closed when no trusted host endpoint is configured.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-agent-compiler-remediation-5 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-agent-compiler  Required outcomes:  - compiler authority is issued only through a deployment-owned endpoint with   configured pathname/device/inode, peer identity, purpose, scope and session   binding; the compiler does not start or trust a caller-selected authority   server; - anonymous socketpairs, caller-created sockets, wrong endpoint/path/peer,   endpoint inode replacement, wrong handshake, fake peer and no configured   endpoint fail closed before compiler capability use; - host handles, scope proofs, selection receipts and disabled-NL proofs reject   copy/deepcopy/pickle/JSON/object.__new__/fork reconstruction and malformed   values with stable typed failures; - durable compiler reservation remains bound to the admitted root FD/inode and   cannot be split by replacing its path; - valid host-issued compilation retains the existing effect/risk/port/NL,   replay and cross-process behavior; - the C0 legacy ServerCompilationRecordIssuer remains an explicit separate   contract/cutover dependency and is not claimed fixed in this package-local   line.

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
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T13:00:56.300Z `sandbox_socket_access`; cause_status: `external`; cause: The default sandbox denied binding a real pathname Unix socket needed by the remediation-5 OS peer-identity probe.; resolution: `resolved`; lesson: When acceptance depends on OS endpoint identity, record sandbox limits and use the smallest controlled elevation rather than replacing the probe with an in-process fake.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `os-boundary-probes-need-controlled-sandbox-access`: occurrences=1; cause_status: `external`; root cause: The default sandbox denied binding a real pathname Unix socket needed by the remediation-5 OS peer-identity probe.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `os-boundary-probes-need-controlled-sandbox-access`: line experience occurrence(s)=1

## Future guidance

- Carry explicit external wiring and legacy issuer dependencies into the next integration line instead of treating the local compiler gate as a release claim.
- When acceptance depends on OS endpoint identity, record sandbox limits and use the smallest controlled elevation rather than replacing the probe with an in-process fake.

## Event index

- #1: `7d219438-20f5-4410-97a9-a01b070990d1` | 2026-08-16T12:37:15.428Z | STATE_CHANGE/line_started | incident=`c907f1d3-b21a-4420-b924-071fd3a30faa` | lesson_key=`frozen-context-before-start` | event_sha256=`2c87dac7a0a328cfeba368de7e1d166d9ca19857f1c14d4bda7a8afe784ba26d`
- #2: `0b91c4a4-31e3-4a9e-9e36-6c0c9e3b1a11` | 2026-08-16T13:00:56.300Z | FAILURE/sandbox_socket_access | incident=`7f783ad0-8f2f-4d0c-bd1a-b52d0cbf4ef8` | lesson_key=`os-boundary-probes-need-controlled-sandbox-access` | event_sha256=`cc7c748fdc1403dd02429d96e21511ec09267b21dabaadcfb4a4ae45eeef5a1c`
- #3: `1a5fba40-5c0d-4a1c-93c5-4e83d8c8e7d2` | 2026-08-16T13:03:38.000Z | GATE/remediation_5_focused_gate | incident=`2b82f9d2-3e97-4f6b-9f0c-2c3e4e7c1a11` | lesson_key=`endpoint-authority-gate-is-external-and-fail-closed` | event_sha256=`6581705a3d344dc1fab67ea50613329f7a114668fb34a2054d4761a29c6b236e`
- #4: `4c6e7f80-6d1e-4f2a-9b35-7a8c9d0e1f22` | 2026-08-16T13:03:38.000Z | REVIEW/external_host_boundary_review | incident=`5d7f8091-7e2f-4a3b-8c46-8b9d0e1f2a33` | lesson_key=`separate-package-gate-from-production-wiring` | event_sha256=`d5d7bd862c0ade687c77df69c28d487c2d479fff8aa140f740255a30d31fb625`
- #5: `6e5f4d3c-2b1a-4987-9f0e-1d2c3b4a5e6f` | 2026-08-19T02:35:17.000Z | STATE_CHANGE/line_completed | incident=`7f6e5d4c-3b2a-4987-9f0e-1d2c3b4a5e6f` | lesson_key=`package-local-close-with-integration-gaps` | event_sha256=`8608f44e19af957316f759d527ea1c2e536c17afdf7399f9fd46b9399fc5770d`
