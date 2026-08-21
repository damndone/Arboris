# Retrospective — v1-8-9-fms-structural-and-retrospective-contract

## Goal

# Workbench v1.8.9 Formal Control Contract Alignment  Resolve full-regression failures in the formal structural guard and retrospective contract without hiding new server-owned evidence reads or weakening event integrity. If a new intentional authority read is required, encode it explicitly in the structural guard with a narrow allowlist and rationale.  Scope: backend/workbench/agent/workflow_runtime.py, tests/test_context_compiler_entry_point.py, tests/test_devline_control_retrospective.py.  Acceptance: focused structural/retrospective tests pass; compiler-owned source boundaries remain explicit; formal line verification and retrospective are completed.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/8 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=125504 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/4 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T07:14:26.810Z `structural_guard_stale_allowlist`; cause_status: `known`; cause: The structural compiler-source guard treated an intentional server-owned workflow_runtime artifact-index read as an unapproved compiler bypass.; resolution: `open`; lesson: Keep structural source-read exemptions narrow by module and canonical source, with the safety guard retained.
- #3 2026-08-21T07:14:44.664Z `retrospective_mttr_contract_stale`; cause_status: `known`; cause: The retrospective test expected caller-supplied historical timestamps, but append_event now assigns server-owned strictly increasing timestamps.; resolution: `open`; lesson: Derive retrospective metric expectations from server-owned event timestamps rather than caller-supplied timestamp requests.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `retrospective-uses-server-owned-event-time`: occurrences=1; cause_status: `known`; root cause: The retrospective test expected caller-supplied historical timestamps, but append_event now assigns server-owned strictly increasing timestamps.; solution: `open`
- `structural-guard-narrow-source-allowlist`: occurrences=1; cause_status: `known`; root cause: The structural compiler-source guard treated an intentional server-owned workflow_runtime artifact-index read as an unapproved compiler bypass.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `retrospective-uses-server-owned-event-time`: line experience occurrence(s)=1
- `structural-guard-narrow-source-allowlist`: line experience occurrence(s)=1

## Future guidance

- Derive retrospective metric expectations from server-owned event timestamps rather than caller-supplied timestamp requests.
- Keep structural source-read exemptions narrow by module and canonical source, with the safety guard retained.

## Event index

- #1: `4064851d-9478-45be-a317-924e91093d1c` | 2026-08-21T07:06:47.846Z | STATE_CHANGE/line_started | incident=`4573762d-da69-4d65-8492-6a466af98628` | lesson_key=`frozen-context-before-start` | event_sha256=`e492112fe414f191c9459f225fed782148e3faf07af4cd04423f6cd349574280`
- #2: `0d4e8f3a-1c72-4b8a-9f52-6a31d7c0e942` | 2026-08-21T07:14:26.810Z | FAILURE/structural_guard_stale_allowlist | incident=`3e9a1c74-5b62-4f80-9d31-7c2e6a8b0549` | lesson_key=`structural-guard-narrow-source-allowlist` | event_sha256=`90f12da6f1d78061d606be20bcee4bb51bd803c08c3813a2d16339965033d55d`
- #3: `2b7f4e91-8a63-4c0d-b5e2-19f6a7d3c804` | 2026-08-21T07:14:44.664Z | FAILURE/retrospective_mttr_contract_stale | incident=`5f1b8d36-2c74-4a90-be61-9e3d7c0a2854` | lesson_key=`retrospective-uses-server-owned-event-time` | event_sha256=`da5bfcc6018442dbc53a1c87a972f053f5c50a0a399a923d7260ef3a451127b4`
- #4: `4c8d1e72-5a63-4b90-a7f1-2d6c9e0b3845` | 2026-08-21T07:16:32.263Z | GATE/structural_contract_focused_green | incident=`3e9a1c74-5b62-4f80-9d31-7c2e6a8b0549` | lesson_key=`structural-guard-narrow-source-allowlist` | event_sha256=`9c6e56cf7b1d856bd7d071c657113289da2592ff1036898419d1e03b37cb3745`
- #5: `6e2f9a14-7b80-4c53-bd91-5a3e8f0c2764` | 2026-08-21T07:16:50.219Z | GATE/retrospective_contract_focused_green | incident=`5f1b8d36-2c74-4a90-be61-9e3d7c0a2854` | lesson_key=`retrospective-uses-server-owned-event-time` | event_sha256=`1a021ac00dbdc864b9fd3d437cc6c0b0420a2884cd48ab401c6e453731c757e7`
- #6: `7a3e9c16-4b82-5d70-1f64-8e2a0c5b9376` | 2026-08-21T07:17:07.371Z | GATE/compile_diff_checks_passed | incident=`8c4f2a71-6d90-4b35-a8e2-5f1c7d0b9463` | lesson_key=`focused-contract-gates-before-close` | event_sha256=`fddf21cbfd73f36d0efa055f410deda58dccce2b998cf3bc5d87d53e51f25cb7`
- #7: `ab7d3f19-5c82-4e60-a1f7-9d2c6b0e8435` | 2026-08-21T07:17:53.456Z | GATE/formal_verify_retrospective_passed | incident=`c6a2f8d0-4b71-5e93-a6c2-8f1d0b7459e3` | lesson_key=`formal-verify-before-retrospective-close` | event_sha256=`8bd9a3255892ca30e5dc57aa7df6c3c3c6b2233380302f12877c47df93cc9548`
- #8: `9e5a3c71-8b24-4d60-a2f7-6c1e0b9385a4` | 2026-08-21T07:18:30.705Z | STATE_CHANGE/fms_contract_completed | incident=`ab6d2f90-4c71-5e83-b1a6-9d0f2c7485e6` | lesson_key=`fms-structural-retrospective-contract-completed` | event_sha256=`9fc6ce5955b354c1312ab4c3e325c17daf419741cf5b24a9c2e0b4f98bf9e12e`
