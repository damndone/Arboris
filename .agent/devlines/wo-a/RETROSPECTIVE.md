# Retrospective — wo-a

## Goal

可信 LMM 执行绑定与 filesystem persistence

## Final status

Generated from the append-only event history; release acceptance is determined separately by the release ledger.

## Metrics

- Failure frequency: 1
- Repeat rate: 0.0%
- Recurrence rate: 0.0%
- MTTR: unknown
- Review churn: 3
- Spec churn: 0
- Plan churn: 0
- Gate waste rate: 0.0%
- Same-state retry rate: 0.0%
- Token waste: unknown

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- 2026-07-19T19:20:00Z [persistence_capability_bypass] cause: filesystem persistence capability bypass; resolution: require a private admission-gated facade with no raw path, lease, or writer escape; lesson: Filesystem persistence rules must bind seal, writer, index, and receipt to one unforgeable live admission.

## All waste

- None recorded.

## Root causes and solutions

- GAP|persistence_capability_bypass|filesystem persistence capability bypass: 1 occurrence(s); root cause: filesystem persistence capability bypass; solution: require a private admission-gated facade with no raw path, lease, or writer escape

## Added tests

- tests/test_pinned_run_directory.py

## New rules

- A sealed input is insufficient when packet and index writes retain a raw-path escape.
- Every persistence operation must prove the same live capability, not merely carry matching values.
- Do not begin filesystem persistence implementation until authority, carrier, and writer API are all non-escapable.
- Filesystem persistence rules must bind seal, writer, index, and receipt to one unforgeable live admission.

## Future guidance

- A sealed input is insufficient when packet and index writes retain a raw-path escape.
- Every persistence operation must prove the same live capability, not merely carry matching values.
- Do not begin filesystem persistence implementation until authority, carrier, and writer API are all non-escapable.
- Filesystem persistence rules must bind seal, writer, index, and receipt to one unforgeable live admission.
