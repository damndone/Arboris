# Retrospective — v1-8-9-p0-evidence-core-remediation-7

## Goal

# v1.8.9 P0 Evidence Core Remediation 7 Objective  Close the remaining Evidence host-authority trust-root gap found by the remediation-6 independent review. A caller must not be able to supply the endpoint path, inode, peer identity, scope, session, secret and self-authored protocol together and obtain an Evidence registry, persistence receipt or successful projection. The package must consume only an authority handle admitted by the deployment-owned host boundary; self-attested endpoint configuration and caller-started authority servers must fail closed. Add a bounded RPC timeout so an unavailable or malicious host cannot hang the Agent or Notebook request indefinitely.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-evidence-core-remediation-7 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-evidence-core  Required outcomes:  - public Evidence admission does not accept caller-selected trust-root fields;   deployment-owned endpoint configuration and bootstrap material arrive only   from the external host/supervisor boundary, with no package-local issuance   fallback; - caller-created socket/socketpair, self-authored server/protocol, fake or   caller-selected config/FD, wrong peer/path/inode/handshake and absent host   resolver all fail closed before registry, persistence or projection success; - valid externally admitted host authority preserves scope/session/purpose   binding and all existing evidence integrity, persistence and projection   behavior; - authority RPC reads/writes have an explicit bounded timeout and return a   stable typed unavailable/timeout failure; - copy/deepcopy/pickle/JSON/object.__new__/fork and malformed authority inputs   remain fail closed; - production host resolver wiring remains an explicit integration dependency;   this line must not claim it is verified by package-local fixtures.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/6 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T12:53:59.000Z `host_trust_root_red_probe`; cause_status: `known`; cause: The remediation-7 red probe reproduced that a caller could select endpoint path, inode, peer identity, scope, session and bootstrap material together and obtain an admitted host endpoint.; resolution: `resolved`; lesson: A Python value containing endpoint identity and bootstrap material is not a deployment trust root; public admission must consume only a deployment-owned resolver seam and fail closed when it is absent.

## All errors

- #3 2026-08-16T12:54:39.000Z `timeout_error_mapping`; cause_status: `known`; cause: The first real unresponsive-host probe found that the timeout path called the typed rejection helper with the wrong argument shape and escaped as TypeError.; resolution: `resolved`; lesson: Exercise real transport timeout paths, not only mocked response paths, before declaring a typed unavailable boundary.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `evidence-host-trust-root`: occurrences=1; cause_status: `known`; root cause: The remediation-7 red probe reproduced that a caller could select endpoint path, inode, peer identity, scope, session and bootstrap material together and obtain an admitted host endpoint.; solution: `resolved`
- `typed-timeout-boundary`: occurrences=1; cause_status: `known`; root cause: The first real unresponsive-host probe found that the timeout path called the typed rejection helper with the wrong argument shape and escaped as TypeError.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `evidence-host-trust-root`: line experience occurrence(s)=1
- `typed-timeout-boundary`: line experience occurrence(s)=1

## Future guidance

- A Python value containing endpoint identity and bootstrap material is not a deployment trust root; public admission must consume only a deployment-owned resolver seam and fail closed when it is absent.
- Exercise real transport timeout paths, not only mocked response paths, before declaring a typed unavailable boundary.
- Treat host trust-root admission, transport containment and downstream success prevention as one adversarial boundary and repeat the direct probes.

## Event index

- #1: `a6eef79a-1b31-4c4d-952f-3c55151cdd17` | 2026-08-16T12:42:55.091Z | STATE_CHANGE/line_started | incident=`28a46a1c-8162-4634-84b0-6170b03177ff` | lesson_key=`frozen-context-before-start` | event_sha256=`44b05f124265b1226e6bdd613d8785dc6b7300031a322621625b3fb883881092`
- #2: `7f8a4d3e-4b2c-4c1d-9e0f-1234567890ab` | 2026-08-16T12:53:59.000Z | FAILURE/host_trust_root_red_probe | incident=`8c7d6e5f-4a3b-4c2d-9e1f-2345678901bc` | lesson_key=`evidence-host-trust-root` | event_sha256=`9ce7a01f099edc9e06306e0ea9327a9b960c47c784461566defe2d2a433dc3c1`
- #3: `3e2d1c0b-9a8f-4765-b4c3-210987654321` | 2026-08-16T12:54:39.000Z | ERROR/timeout_error_mapping | incident=`2d1c0b9a-8f7e-465b-a4c3-109876543210` | lesson_key=`typed-timeout-boundary` | event_sha256=`27e70d895161fb82251e9c2b6ecaf10d33ddb667966d2bb5f80c3e723438266f`
- #4: `4f3e2d1c-0b9a-4876-a5b4-321098765432` | 2026-08-16T12:55:31.000Z | REVIEW/authority_direct_probe_rounds | incident=`5e4d3c2b-1a0f-4987-b6c5-432109876543` | lesson_key=`evidence-authority-adversarial-rounds` | event_sha256=`9c4a99d8b9d8f3b12dde11bd22f299bb62a493c9cb1e16fac0bb4ee079f35abc`
- #5: `6a5b4c3d-2e1f-4987-b6c5-432109876543` | 2026-08-16T12:56:10.000Z | GATE/evidence_remediation_7_package_gate | incident=`7b6c5d4e-3f2a-1098-b7c6-543210987654` | lesson_key=`evidence-remediation-7-boundary-handoff` | event_sha256=`3a0b7134737b9f19bcb9fcb8d2cb4959db5c4cee7277723ebd7bd07fce8ef1bf`
- #6: `8b7a6c5d-4e3f-2109-a8b7-654321098765` | 2026-08-16T12:56:51.000Z | STATE_CHANGE/remediation_line_completed | incident=`9c8b7a6d-5e4f-3210-b9c8-765432109876` | lesson_key=`evidence-remediation-7-completion-boundary` | event_sha256=`108c2a3df4694e3e9fea366d4cc150cf470c9dc41ae6c9bf28908a5160062fbc`
