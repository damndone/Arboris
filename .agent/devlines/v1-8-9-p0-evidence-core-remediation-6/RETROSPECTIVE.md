# Retrospective — v1-8-9-p0-evidence-core-remediation-6

## Goal

# v1.8.9 P0 Evidence Core Remediation 6 Objective  Close the remaining host-authority impersonation gap. Remediation-5 replaced module secrets with a socket handle, but an arbitrary \`socketpair()\` plus a caller-controlled issue/validate protocol is still accepted. Evidence must recognize only a configured host authority endpoint with a stable OS identity (allowlisted Unix endpoint, peer credentials and/or admitted FD/inode), never an anonymous socket, caller-selected endpoint, or self-described protocol.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-evidence-core-remediation-6 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core  Required outcomes:  - anonymous socketpair, caller-created Unix socket, wrong peer uid/pid,   wrong endpoint, and self-authored issue/validate protocol fail closed; - host endpoint identity is supplied by trusted deployment configuration or a   pre-admitted FD, is bound to root/scope/owner/session/purpose, and cannot be   selected by untrusted request data; - no configured host endpoint means all registry/persistence/projection public   paths fail closed with typed errors; - valid endpoint flow retains remediation-5 proof, persistence, projection,   concurrency, path and orphan guarantees; - endpoint handles cannot be copied, pickled, JSON-reconstructed or reused by   a different owner/process.  Do not silently invent a host endpoint in the Evidence module. Keep C0 contracts, runtime consumers, central catalog, frontend, provider wiring and protected paths unchanged in this package-local line.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T13:20:00.000Z `host_endpoint_red_probe`; cause_status: `known`; cause: A caller-created socketpair with a self-authored issue/validate protocol is accepted as Evidence host authority.; resolution: `open`; lesson: Host authority requires configured endpoint identity and OS peer binding, not merely a live socket and self-described protocol.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `evidence-host-endpoint-identity`: occurrences=1; cause_status: `known`; root cause: A caller-created socketpair with a self-authored issue/validate protocol is accepted as Evidence host authority.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `evidence-host-endpoint-identity`: line experience occurrence(s)=1

## Future guidance

- Endpoint identity must be checked before protocol use and again on every capability operation; deployment-owned path and peer credentials are separate from protocol correctness.
- Host authority requires configured endpoint identity and OS peer binding, not merely a live socket and self-described protocol.

## Event index

- #1: `b15ad8ca-0cfb-42a4-8cab-55beabad987d` | 2026-08-16T12:07:47.953Z | STATE_CHANGE/line_started | incident=`7c59b09c-fce3-44c2-86b0-62344eca056b` | lesson_key=`frozen-context-before-start` | event_sha256=`433daa5c5c7baa768387c475192c21aab0a42cc5a758c2e0c703d75f5dd2901e`
- #2: `c64e4bb2-1a3b-4c7d-8e9f-0123456789ab` | 2026-08-16T13:20:00.000Z | FAILURE/host_endpoint_red_probe | incident=`d75f5cc3-2b4c-4d8e-9f01-123456789abc` | lesson_key=`evidence-host-endpoint-identity` | event_sha256=`82fc3570d9e0a7dec35f9532c9e240fff82b9d3248f08619a80ec73a0f23e765`
- #3: `e75f6cc3-2b4d-4e8f-9012-3456789abcde` | 2026-08-16T13:55:00.000Z | REVIEW/host_endpoint_adversarial_review | incident=`f86a7dd4-3c5e-4f90-a123-456789abcdef` | lesson_key=`evidence-endpoint-adversarial-review` | event_sha256=`db43038f0f7d39e8cae587df1c337b0a91d67b5588169e7890e943698d805b81`
- #4: `f86a7dd4-3c5e-4f90-a123-456789abcdef` | 2026-08-16T14:05:00.000Z | GATE/evidence_core_endpoint_gate | incident=`a97b8ee5-4d6f-4091-b234-56789abcdef0` | lesson_key=`evidence-remediation-6-package-gate` | event_sha256=`5f1c5cb3541a3b7579822e3fd1ae9bcea869e0a4356b06a81bccc17cf5ad0c5e`
- #5: `b08b9ee5-4d6f-4091-b234-56789abcdef0` | 2026-08-16T14:15:00.000Z | STATE_CHANGE/remediation_line_completed | incident=`c19ca0f6-5e70-41a2-c345-6789abcdef01` | lesson_key=`evidence-remediation-6-boundary-handoff` | event_sha256=`56a64afc8c4c19c7a5b0cfb76d04daffee8e1d2db93ab2bc5ac3ab95c26d508d`
