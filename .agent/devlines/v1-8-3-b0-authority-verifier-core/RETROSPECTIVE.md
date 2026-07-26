# Retrospective — v1-8-3-b0-authority-verifier-core

## Goal

v1.8.3 B0 authority/verifier core implementation  Implement the revised B0 boundary from the existing v1.8.3 runtime design: immutable generic attestation contracts, canonical encoding/digests, trusted authority/key-provider interfaces, and a fail-closed verifier. B0 must not execute code, access host files or capability inputs, open network connections, persist application facts, compute statistical evidence, or implement native containment.  The implementation must bind invocation/result claims to capability revision, operation, input, policy, backend subject, attempt, output digest, protocol revisions, validity cursors, expiry, revocation and replay state. It must not export an issuer, signer, test key, unsigned fallback, runner, sandbox, model fields, dataset fields, column names, or fixed-year compatibility path.  Modify only the B0 package and its three focused test files listed in the allowlist. No product integration, B1 containment, Agent, registry, workflow, dependency, or UI changes.

## Final status

STARTED

## Metrics

- Failure frequency: 2/5 (40.0%; 40.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-07-26T09:17:00.000Z `wire_claim_contract_gap`; cause_status: `known`; cause: The first green attempt did not yet parse canonical wire timestamps or enforce SHA-256 shape for generic digest bindings.; resolution: `resolved`; lesson: Test the wire representation and identity shape, not only in-memory dataclass construction.

## All errors

- None recorded.

## All gaps

- #2 2026-07-26T09:17:00.000Z `managed_darwin_native_sandbox_unavailable`; cause_status: `known`; cause: The managed host rejects sandbox-exec with sandbox_apply: Operation not permitted before the existing sandboxed child starts.; resolution: `open`; lesson: Keep host-native containment acceptance separate from a pure protocol/verifier line and report managed-host failures as environment gaps.

## All waste

- None recorded.

## Root causes and solutions

- `managed-host-containment-gap-is-not-verifier-regression`: occurrences=1; cause_status: `known`; root cause: The managed host rejects sandbox-exec with sandbox_apply: Operation not permitted before the existing sandboxed child starts.; solution: `open`
- `wire-contracts-must-roundtrip-and-bind-digests`: occurrences=1; cause_status: `known`; root cause: The first green attempt did not yet parse canonical wire timestamps or enforce SHA-256 shape for generic digest bindings.; solution: `resolved`

## Added tests

- `tests/test_custom_capability_contracts.py`
- `tests/test_custom_capability_verifier.py`
- `tests/test_sandbox.py`

## New rules

- `managed-host-containment-gap-is-not-verifier-regression`: line experience occurrence(s)=1
- `wire-contracts-must-roundtrip-and-bind-digests`: line experience occurrence(s)=1

## Future guidance

- Keep host-native containment acceptance separate from a pure protocol/verifier line and report managed-host failures as environment gaps.
- Keep the B0 surface small and validate the frozen order, stable failures, complete bindings, and no-execution boundary before moving to containment or product integration.
- Test the wire representation and identity shape, not only in-memory dataclass construction.

## Event index

- #1: `b5263660-5874-489e-8419-5124606b3d34` | 2026-07-26T09:09:49.133Z | STATE_CHANGE/line_started | incident=`64a42962-6d64-4f1c-a06d-68244cabda7e` | lesson_key=`frozen-context-before-start` | event_sha256=`9731312258b21cf322c8909fba7655129c124bb9cf6cd137f491af173f68153b`
- #2: `84527a43-f617-4da9-882c-5f6c840530ff` | 2026-07-26T09:17:00.000Z | GAP/managed_darwin_native_sandbox_unavailable | incident=`e4655551-8d77-45d5-a944-f5c428d0ccec` | lesson_key=`managed-host-containment-gap-is-not-verifier-regression` | event_sha256=`904f71afbebfed23b0610ef8e7033d3ecb885cc4ac3a7216f77e35bc847bc986`
- #3: `ff88eb97-e0c4-42d3-a304-e43dc074694c` | 2026-07-26T09:17:00.000Z | FAILURE/wire_claim_contract_gap | incident=`b5e9b007-3244-49b4-899b-98cab042e116` | lesson_key=`wire-contracts-must-roundtrip-and-bind-digests` | event_sha256=`f6c5dd5f357539a1c5a9187c95e69d576c860fe76e30a6e13f67820d7e7bf19a`
- #4: `2b4c4b8a-0a3b-4adf-8f36-4f4a0da4bd41` | 2026-07-26T09:35:00.000Z | REVIEW/b0_compact_core_review_passed | incident=`b9e71364-4020-42d0-949c-00354e6698f3` | lesson_key=`b0-compact-core-review` | event_sha256=`bb60e42562eb6de634cca0caa4b334ed0f2dae8a187d2239bdc90ae2fa705b9a`
- #5: `c5e4cb88-3f31-4fb4-a9d7-35bdece98b91` | 2026-07-26T09:40:00.000Z | GATE/b0_authority_verifier_gate_passed | incident=`414dedeb-8c3d-42de-a377-0b291c75b0c1` | lesson_key=`separate-b0-protocol-gate-from-runtime-acceptance` | event_sha256=`9e22e7027df8578adfcbbfd4aa04233a3347ac48350ccf8672fb14b6ecf3a44a`
