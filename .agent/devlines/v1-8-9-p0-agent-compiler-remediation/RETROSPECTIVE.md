# Retrospective — v1-8-9-p0-agent-compiler-remediation

## Goal

# v1.8.9 P0 Agent Compiler Remediation Objective  Remediate independently verified compiler authority failures before cutover. Compilation must preserve registry effect/risk/confirmation policy and resource budgets, validate actual declared port identities, expose the locked C0 FailureEnvelopeV1 shape, reject forged CompilationStore results, make discovery scope and shortlist receipts explicit, make manifest ports registry-derived, and strengthen shadow equivalence beyond identifier comparison. Preserve current runtime authority and all protected paths.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-agent-compiler-remediation Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-agent-compiler  Required outcomes: adversarial safety downgrade/oversize/forged-port/forged-store/cross-scope/discovery/shadow probes fail closed; focused tests and formal handoff reflect actual evidence. Do not perform cutover or provider execution.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/10 (50.0%; 50.0 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T10:17:44.000Z `adversarial_probe_red`; cause_status: `known`; cause: Focused adversarial probes exposed compiler authority gaps in policy binding, port identity, C0 failure shape, store correspondence, discovery receipts, and shadow metadata.; resolution: `open`; lesson: A green focused suite is insufficient until authority downgrade and cross-object adversarial probes fail closed.
- #3 2026-08-16T10:24:15.000Z `adversarial_port_nullability_red`; cause_status: `known`; cause: Port compatibility accepted a nullable target mismatch instead of failing closed.; resolution: `open`; lesson: Port compatibility must compare nullable and collection attributes exactly.
- #4 2026-08-16T10:27:36.000Z `legacy_probe_expected_truncation`; cause_status: `known`; cause: The existing discovery test expected silent truncation while the remediation requires query over-budget failure.; resolution: `resolved`; lesson: Bounded discovery must reject an oversized match set rather than return an incomplete shortlist.
- #5 2026-08-16T10:30:13.000Z `forged_registry_manifest_accepted`; cause_status: `known`; cause: A recomputed manifest digest was accepted without proving the manifest remained registry-derived.; resolution: `resolved`; lesson: The compiler must pin the complete manifest digest to a fresh OperationRegistry projection.
- #6 2026-08-16T10:31:29.000Z `forged_discovery_receipt_accepted`; cause_status: `known`; cause: A public digest-only discovery result could be reconstructed and accepted as a shortlist receipt.; resolution: `resolved`; lesson: Shortlist receipts need an issuer-bound marker in addition to a content digest.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `adversarial-authority-probes-before-green`: occurrences=1; cause_status: `known`; root cause: Focused adversarial probes exposed compiler authority gaps in policy binding, port identity, C0 failure shape, store correspondence, discovery receipts, and shadow metadata.; solution: `open`
- `discovery-budget-fails-closed`: occurrences=1; cause_status: `known`; root cause: The existing discovery test expected silent truncation while the remediation requires query over-budget failure.; solution: `resolved`
- `discovery-receipt-issuer-bound`: occurrences=1; cause_status: `known`; root cause: A public digest-only discovery result could be reconstructed and accepted as a shortlist receipt.; solution: `resolved`
- `exact-port-contract-before-green`: occurrences=1; cause_status: `known`; root cause: Port compatibility accepted a nullable target mismatch instead of failing closed.; solution: `open`
- `registry-manifest-authority-before-compile`: occurrences=1; cause_status: `known`; root cause: A recomputed manifest digest was accepted without proving the manifest remained registry-derived.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `adversarial-authority-probes-before-green`: line experience occurrence(s)=1
- `discovery-budget-fails-closed`: line experience occurrence(s)=1
- `discovery-receipt-issuer-bound`: line experience occurrence(s)=1
- `exact-port-contract-before-green`: line experience occurrence(s)=1
- `registry-manifest-authority-before-compile`: line experience occurrence(s)=1

## Future guidance

- A green focused suite is insufficient until authority downgrade and cross-object adversarial probes fail closed.
- Adversarial port tests must use exact issued references before asserting direction failures.
- Bounded discovery must reject an oversized match set rather than return an incomplete shortlist.
- Keep local adversarial probes separate from runtime and release acceptance evidence.
- Port compatibility must compare nullable and collection attributes exactly.
- Shortlist receipts need an issuer-bound marker in addition to a content digest.
- The compiler must pin the complete manifest digest to a fresh OperationRegistry projection.

## Event index

- #1: `ccbad4d1-3af8-4fbc-a9ec-c863a53aba6a` | 2026-08-16T10:09:26.484Z | STATE_CHANGE/line_started | incident=`b56a3c46-7016-4833-9c38-17165ebf25ad` | lesson_key=`frozen-context-before-start` | event_sha256=`96def174dce8107d09afdf60e828c0c67ddd070e3d6c09da94d3e4e2f08f3bc5`
- #2: `3241c9e0-1ff2-4818-8a61-858cd29e67fb` | 2026-08-16T10:17:44.000Z | FAILURE/adversarial_probe_red | incident=`9271bbcf-8062-47e0-9fc9-d611f8018176` | lesson_key=`adversarial-authority-probes-before-green` | event_sha256=`4636c079111eab9a31dae18218f48414d07a6503163f470e58cfb38ac7315215`
- #3: `E2D68E15-438B-439D-803D-2FA26C752677` | 2026-08-16T10:24:15.000Z | FAILURE/adversarial_port_nullability_red | incident=`7a7be042-c3de-4c8c-8b4b-b4af1c8cb7c2` | lesson_key=`exact-port-contract-before-green` | event_sha256=`de923822917e6a8b37e5470f8db021ef60bf061c98c904a1107fa90d41d691a3`
- #4: `8912E73E-1199-4797-A381-5BC5763F08A9` | 2026-08-16T10:27:36.000Z | FAILURE/legacy_probe_expected_truncation | incident=`f22666d7-615b-46da-a0dd-25fa9c75ac36` | lesson_key=`discovery-budget-fails-closed` | event_sha256=`62de92369e493d7b9588e5c604db177c993db8db5c7f6f966b6a5e3dcc5dd4c2`
- #5: `E1F99DE3-C4C5-4B7C-9754-7E8A8B07551B` | 2026-08-16T10:30:13.000Z | FAILURE/forged_registry_manifest_accepted | incident=`4f2353a1-2df6-40ce-a25f-7ba098d7f66c` | lesson_key=`registry-manifest-authority-before-compile` | event_sha256=`4a9d4aaa32782b07d0e902cfd1448e509ec23820628d107f0c376ff3d9a0663f`
- #6: `938035CA-8C38-4ECD-BCF2-B1709EFB98BD` | 2026-08-16T10:31:29.000Z | FAILURE/forged_discovery_receipt_accepted | incident=`6e9ee67b-68f1-4235-abd0-fc3c84a3c068` | lesson_key=`discovery-receipt-issuer-bound` | event_sha256=`ce4b4a7b988b1e49bf9366af64a95743f6d20ee50351d1c53c2af36bd1d2ac40`
- #7: `7D01B33C-D780-4E93-8CE6-4445DD3F849F` | 2026-08-16T10:36:00.000Z | REVIEW/agent_compiler_remediation_review_passed | incident=`a1d0d0dd-d438-43c1-82b5-22cd1b8f09fd` | lesson_key=`separate-local-and-release-evidence` | event_sha256=`6660a63f0cbf5a52d9e7cabbdf988a6421d064a7f70758ba2b27b35d7fd13eb7`
- #8: `DC8B0617-4518-4F82-A004-16E7F5447204` | 2026-08-16T10:37:00.000Z | GATE/agent_compiler_local_gate_passed | incident=`e890fa8f-6d4e-4d71-a4dc-fbb5e4cf8c2b` | lesson_key=`local-gate-does-not-promote-runtime` | event_sha256=`eb0ba15ef2d28f1413504722588f088a730ef659efd850a6bbda4f5fed2e012c`
- #9: `5DFF22D9-7F55-40F1-BAF8-B52AB952F613` | 2026-08-16T10:38:00.000Z | STATE_CHANGE/agent_compiler_remediation_completed | incident=`2b65ba3e-0e5f-438e-bb4e-64ed0750286a` | lesson_key=`close-local-remediation-with-boundaries` | event_sha256=`8f528dbb4fac318832f7136df5bea6dfc6fd55c99079482909fa72fbb720f9f7`
- #10: `33BEB941-D880-470D-97C6-26FFF10EC714` | 2026-08-16T10:42:00.000Z | REVIEW/directional_probe_exact_ref_hardened | incident=`f035db57-f801-422d-8637-dbd9ad916978` | lesson_key=`exact-issued-port-probe` | event_sha256=`f6111dd5616c3a1072efff34b4cfa7eb0f133dee8e3d7337d91bfcf6a75ba8df`
