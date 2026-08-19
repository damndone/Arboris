# Retrospective — v1-8-9-p0-agent-compiler-remediation-4

## Goal

# v1.8.9 P0 Agent Compiler Remediation 4 Objective  Replace compiler-local proof objects and path-based reservation ownership with an explicit host authority boundary. The remediation-3 review showed that module-private compiler proof values, selection issuer tokens and ScopeAuthorityResolver bootstrap helpers can be imported and used to mint arbitrary authority. It also showed that replacing a durable reservation root path can create two owners. The public compiler must consume a host-issued authority handle, verify the reservation domain by stable FD/inode identity, and reject caller-created or reconstructed selection/scope proofs before compilation.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-agent-compiler-remediation-4 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-agent-compiler  Required outcomes:  - compiler authority and capability-selection proofs come from a host   authority channel/handle outside compiler module globals; - imported internal tokens, \`_from_server_snapshots\`, \`_issue\`, copy/pickle,   JSON reconstruction and object.__new__ cannot mint scope, selection or   disabled-NL bypass authority; - durable reservation is bound to an admitted root FD/inode and root-path   replacement cannot create a second owner; - malformed proof failures are stable typed compiler failures; - valid host-issued compile/replay still preserves effect/risk/port/NL and   cross-process idempotency behavior.  The locked C0 ServerCompilationRecordIssuer remains a separate contract/cutover dependency; do not modify C0 contract files in this package-local line. If the legacy issuer remains callable, keep it explicitly OPEN/NOT VERIFIED rather than claiming the public product path is fully closed.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/7 (42.9%; 42.9 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: N/A (sample=0; unresolved=3)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T12:30:00.000Z `remediation4_adversarial_review_red`; cause_status: `known`; cause: The remediation-3 adversarial review showed that compiler module proof globals, caller-reachable bootstrap helpers, imported selection tokens and replaceable reservation paths can mint authority or create two durable owners.; resolution: `open`; lesson: Public compiler authority must be issued by the host through an unforgeable channel and durable reservation must bind to stable admitted storage identity.
- #3 2026-08-16T12:38:00.000Z `remediation4_red_tests`; cause_status: `known`; cause: Compiler4 red tests reproduced acceptance of an imported selection token, internal disabled-natural-language bypass, and caller-reachable snapshot bootstrap.; resolution: `open`; lesson: Red tests must exercise the actual public compiler and host bootstrap boundary before implementing the authority-channel repair.
- #4 2026-08-16T13:12:00.000Z `proof_copy_red`; cause_status: `known`; cause: The adversarial copy probe showed that an otherwise valid CapabilitySelection proof remained shallow-copyable even though host validation blocked field tampering.; resolution: `open`; lesson: Fail closed on proof serialization and copying; replay must use the host-issued opaque identifier through the host channel.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `compiler-proof-copy-must-fail-closed`: occurrences=1; cause_status: `known`; root cause: The adversarial copy probe showed that an otherwise valid CapabilitySelection proof remained shallow-copyable even though host validation blocked field tampering.; solution: `open`
- `compiler-remediation4-host-authority-and-fd-reservation`: occurrences=1; cause_status: `known`; root cause: The remediation-3 adversarial review showed that compiler module proof globals, caller-reachable bootstrap helpers, imported selection tokens and replaceable reservation paths can mint authority or create two durable owners.; solution: `open`
- `compiler-remediation4-red-tests-before-fix`: occurrences=1; cause_status: `known`; root cause: Compiler4 red tests reproduced acceptance of an imported selection token, internal disabled-natural-language bypass, and caller-reachable snapshot bootstrap.; solution: `open`

## Added tests

- `tests/test_v189_agent_compiler.py`
- `tests/test_v189_agent_compiler.py::test_host_handle_and_selection_proofs_cannot_be_copied_or_reconstructed`

## New rules

- `compiler-proof-copy-must-fail-closed`: line experience occurrence(s)=1
- `compiler-remediation4-host-authority-and-fd-reservation`: line experience occurrence(s)=1
- `compiler-remediation4-red-tests-before-fix`: line experience occurrence(s)=1

## Future guidance

- Fail closed on proof serialization and copying; replay must use the host-issued opaque identifier through the host channel.
- Keep host-issued proof validation and durable reservation identity as separate, directly probed trust boundaries.
- Public compiler authority must be issued by the host through an unforgeable channel and durable reservation must bind to stable admitted storage identity.
- Red tests must exercise the actual public compiler and host bootstrap boundary before implementing the authority-channel repair.

## Event index

- #1: `941ed3a1-2cac-4f02-9ed4-d5bc8bc6d7cd` | 2026-08-16T11:49:07.717Z | STATE_CHANGE/line_started | incident=`506a5830-0fbb-4966-a7a9-d5e9e65d3179` | lesson_key=`frozen-context-before-start` | event_sha256=`2cc618cbe8608202855ef60f90873742ffa07ca12cf77c808f0f70c839b62b47`
- #2: `0b1c2d3e-4f50-6789-abcd-000000000021` | 2026-08-16T12:30:00.000Z | FAILURE/remediation4_adversarial_review_red | incident=`0b1c2d3e-4f50-6789-abcd-000000000031` | lesson_key=`compiler-remediation4-host-authority-and-fd-reservation` | event_sha256=`e1c89ae864f98e3c881d08a29c331dafa87fc3d3f9fd2e162ffce01b32c222b3`
- #3: `0b1c2d3e-4f50-6789-abcd-000000000022` | 2026-08-16T12:38:00.000Z | FAILURE/remediation4_red_tests | incident=`0b1c2d3e-4f50-6789-abcd-000000000032` | lesson_key=`compiler-remediation4-red-tests-before-fix` | event_sha256=`9436c1868f8f3c30d07130e4324d9ae8a725620231faacb05fbe4f525888525d`
- #4: `0b1c2d3e-4f50-6789-abcd-000000000023` | 2026-08-16T13:12:00.000Z | FAILURE/proof_copy_red | incident=`0b1c2d3e-4f50-6789-abcd-000000000033` | lesson_key=`compiler-proof-copy-must-fail-closed` | event_sha256=`c992028d3faf907e87f638381277606126570ffb5dace311810435c11adb5a53`
- #5: `0b1c2d3e-4f50-6789-abcd-000000000024` | 2026-08-16T13:35:00.000Z | REVIEW/remediation4_authority_boundary_self_review | incident=`0b1c2d3e-4f50-6789-abcd-000000000034` | lesson_key=`compiler-remediation4-boundary-self-review` | event_sha256=`6397bdff05c439569338a1b6eec1e62b2ee641d767ec2905548eff35df4da959`
- #6: `0b1c2d3e-4f50-6789-abcd-000000000025` | 2026-08-16T13:40:00.000Z | GATE/remediation4_focused_and_adversarial_gate | incident=`0b1c2d3e-4f50-6789-abcd-000000000035` | lesson_key=`compiler-remediation4-package-gate-separate-from-integration` | event_sha256=`829ea41900c2621a07f367532826fd33904b16f6ba8410cdc4dfee92ff6b79af`
- #7: `0b1c2d3e-4f50-6789-abcd-000000000026` | 2026-08-16T13:45:00.000Z | STATE_CHANGE/remediation4_package_local_completed | incident=`0b1c2d3e-4f50-6789-abcd-000000000036` | lesson_key=`compiler-remediation4-scoped-closeout` | event_sha256=`f1ea00121a9587125682cd4fa9fb84ff5e51cc43b593b8981ba142a00d5ca71a`
