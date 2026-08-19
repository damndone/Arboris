# Retrospective — v1-8-9-p0-evidence-core-remediation-5

## Goal

# v1.8.9 P0 Evidence Core Remediation 5 Objective  Replace in-process module secrets with an explicit host-authority boundary. The remediation-4 review proved that Python private names are not an authority boundary: a same-process caller can import construction keys, HMAC secrets and proof classes. Evidence must therefore accept a server-issued external authority handle (for example an admitted FD or an authority-channel response) and verify it without creating a trust root from caller-provided scope or module globals. Registry, persistence and projection proofs must all derive from that host authority; copying, pickle, JSON reconstruction, object.__new__, or importing implementation symbols must not create a valid proof.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-evidence-core-remediation-5 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core  Required outcomes:  - a public factory without a host-issued authority handle fails closed; - the host authority channel is outside Evidence module globals and binds   scope, root FD/inode, owner, session and proof purpose; - registry/persistence/projection can only consume a valid host handle and   cannot mint or verify success using module constants; - pickle/JSON/copy/object.__new__ handles fail closed with stable typed errors; - same-process and forked malicious probes cannot create registry, write   evidence, or manufacture \`success=True\`; valid host-issued flows retain all   previous concurrency/path/orphan guarantees.  If the current host runtime lacks the authority channel, record that as an explicit integration dependency and keep the public product path fail closed. Do not modify C0 contracts, runtime consumers, central catalog, frontend, provider wiring, or protected paths in this package-local line.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/5 (40.0%; 40.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: N/A (sample=0; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T12:30:00.000Z `remediation_red_suite`; cause_status: `known`; cause: The remediation-5 red suite shows that the current public registry and persistence factories still mint authority without an external host handle, and the implementation exposes module proof keys.; resolution: `open`; lesson: External host authority must be a required input and all success proofs must be validated by that authority before implementation is considered green.
- #3 2026-08-16T12:45:00.000Z `authority_adversarial_probe`; cause_status: `known`; cause: A direct probe shows that a caller-created Python object with matching issue and validate methods is accepted as the host authority channel.; resolution: `open`; lesson: The Evidence boundary must require a real external channel capability rather than trusting caller-provided Python method shape.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `evidence-external-channel-not-structural`: occurrences=1; cause_status: `known`; root cause: A direct probe shows that a caller-created Python object with matching issue and validate methods is accepted as the host authority channel.; solution: `open`
- `evidence-host-authority-red-boundary`: occurrences=1; cause_status: `known`; root cause: The remediation-5 red suite shows that the current public registry and persistence factories still mint authority without an external host handle, and the implementation exposes module proof keys.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `evidence-external-channel-not-structural`: line experience occurrence(s)=1
- `evidence-host-authority-red-boundary`: line experience occurrence(s)=1

## Future guidance

- External host authority must be a required input and all success proofs must be validated by that authority before implementation is considered green.
- The Evidence boundary must require a real external channel capability rather than trusting caller-provided Python method shape.

## Event index

- #1: `f67f087b-24e2-4a04-96af-41f258f1ece5` | 2026-08-16T11:40:37.646Z | STATE_CHANGE/line_started | incident=`1fc5fc6d-034d-49c8-9552-ee0171eac00a` | lesson_key=`frozen-context-before-start` | event_sha256=`3cb1f29075c1d7c334faf2ab52a8b974d06bb780c8bf66a954883be3e938fb97`
- #2: `8a1b2c3d-4e5f-4678-9012-3a4b5c6d7e8f` | 2026-08-16T12:30:00.000Z | FAILURE/remediation_red_suite | incident=`9f0a3d4e-5b6c-47d8-9012-3e4f5a6b7c8d` | lesson_key=`evidence-host-authority-red-boundary` | event_sha256=`853de1ea889877156a9a07e7011a4cc6b060f6c1a7cd20c555a12490ce95babc`
- #3: `1b2c3d4e-5f67-4890-1234-5a6b7c8d9e0f` | 2026-08-16T12:45:00.000Z | FAILURE/authority_adversarial_probe | incident=`2c3d4e5f-6789-4012-3456-6a7b8c9d0e1f` | lesson_key=`evidence-external-channel-not-structural` | event_sha256=`0415ccdb349de9728f56c52fdac6c0b11eb64b1102b71882f800cab042d0ba9c`
- #4: `2c7d4e91-5a63-4f08-9b27-1e6a3d8c5f42` | 2026-08-16T12:00:35.000Z | GATE/evidence_core_host_authority_gate | incident=`3e8a5c1d-7f42-49b6-0d2e-6c9a1f5b7d34` | lesson_key=`evidence-remediation-5-host-authority-gate` | event_sha256=`aa6129bce12a79324d9ea9c0691c7b2f72b5b6485872dfbd837b116c10dd313a`
- #5: `4f1a8c6e-2d73-49b5-0e2a-7c9d3f5b1a84` | 2026-08-16T12:01:29.000Z | STATE_CHANGE/remediation_line_completed | incident=`5b2e9c7d-4f16-48a0-3d7e-1c6b9a5f2d84` | lesson_key=`evidence-remediation-5-boundary-handoff` | event_sha256=`218baad5910242bebfac672d62a081383528c1a04d4f7d01c84b8ae9a124e53e`
