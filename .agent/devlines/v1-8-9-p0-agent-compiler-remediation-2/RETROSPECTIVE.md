# Retrospective — v1-8-9-p0-agent-compiler-remediation-2

## Goal

# v1.8.9 P0 Agent Compiler Remediation 2 Objective  Close the independently reproduced Agent Compiler capability, scope and composition gaps before integration admission. The compiler must preserve the registry-declared semantic effect exactly, support every declared read-only capability, hide operations explicitly disabled for natural-language access, and require server-owned scope authority rather than trusting caller strings. Manifest shadow comparison must include executor/runtime identity; connection records must be exact rather than accepting forged extra fields; and identical semantic plans must use an atomic reservation/replay path under concurrency.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-agent-compiler-remediation-2 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-agent-compiler  Required outcomes:  - draft effect/risk/confirmation/policy/budget must equal or be safely   constrained by the registry declaration; no semantic downgrade; - read-only/none risk capabilities compile successfully where declared; - natural_language_enabled=false capabilities are not discoverable or   resolvable through Agent/Notebook natural-language paths; - scope and principal are server-resolved/bound, or compilation fails closed   when a trusted resolver/receipt is absent; - manifest shadow detects executor/reconciler/runtime identity changes; - connection schemas are exact and reject extra forged endpoints/fields; - concurrent equal intents converge on one reservation/result or a stable   replay, without duplicate compilation side effects.  Keep C0 contracts locked and the package-local boundary. Do not modify runtime cutover, central catalog, frontend, provider integration, or protected paths.

## Final status

COMPLETED

## Metrics

- Failure frequency: 9/12 (75.0%; 75.0 per 100 events)
- Repeat rate: 0/9 (0.0%)
- Recurrence rate: 0/9 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=7)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T10:56:49.000Z `semantic_effect_downgrade_red`; cause_status: `known`; cause: The red test reproduced that model.genesis accepted a model_evaluate draft effect even though the registered operation is a mutation model fit.; resolution: `open`; lesson: Bind the draft effect to a registry-declared semantic effect before compilation.
- #3 2026-08-16T10:56:50.000Z `readonly_none_risk_red`; cause_status: `known`; cause: The red test reproduced that a declared read_only and none-risk capability was rejected because the compiler did not rank none risk.; resolution: `open`; lesson: Represent every registry risk level in the compiler rank and keep read-only plans non-mutating.
- #4 2026-08-16T10:56:51.000Z `disabled_natural_language_red`; cause_status: `known`; cause: The red test reproduced that code.execute, whose natural language flag is false, still appeared in discovery results.; resolution: `open`; lesson: Apply the natural-language allowlist at both discovery and resolution boundaries.
- #6 2026-08-16T10:56:54.000Z `connection_exact_schema_red`; cause_status: `known`; cause: The red test reproduced that a connection with valid endpoints plus forged extra endpoint fields was accepted.; resolution: `open`; lesson: Use an exact connection wire shape and reject every unknown field before port compatibility checks.
- #7 2026-08-16T10:56:55.000Z `compiler_reservation_race_red`; cause_status: `known`; cause: The red concurrency test reproduced duplicate compilation side effects and idempotency conflicts after all workers observed a replay miss.; resolution: `open`; lesson: Reserve a semantic compilation key atomically before any server draft registration or compilation side effect.
- #8 2026-08-16T10:56:52.000Z `scope_authority_fail_closed_red`; cause_status: `known`; cause: The red test reproduced that compilation accepted caller-provided scope and identity strings without a server-owned authority binding.; resolution: `open`; lesson: Require a server-owned, issuer-bound scope and principal resolution before plan compilation.

## All errors

- #9 2026-08-16T10:56:56.000Z `formal_event_redaction_retry`; cause_status: `known`; cause: The first authority red event source was rejected by the formal event sanitizer because one summary phrase matched its secret-like pattern; the source was corrected and the event was appended successfully.; resolution: `resolved`; lesson: Keep formal event summaries free of secret-like vocabulary and verify the CLI result after every append.
- #11 2026-08-16T11:08:01.000Z `formal_gate_enum_retry`; cause_status: `known`; cause: The first focused gate event used a preventability value outside the formal control enum and was rejected before changing the event stream; the source was corrected and retried.; resolution: `resolved`; lesson: Validate formal event enum values before preparing a gate source.

## All gaps

- #5 2026-08-16T10:56:53.000Z `runtime_identity_shadow_red`; cause_status: `known`; cause: The red test showed that the manifest projection did not publish executor, reconciler, or runtime identity fields for shadow comparison.; resolution: `open`; lesson: Hash all server-selected runtime identities into the manifest projection used by shadow comparison.

## All waste

- None recorded.

## Root causes and solutions

- `agent-compiler-atomic-reservation`: occurrences=1; cause_status: `known`; root cause: The red concurrency test reproduced duplicate compilation side effects and idempotency conflicts after all workers observed a replay miss.; solution: `open`
- `agent-compiler-effect-binding`: occurrences=1; cause_status: `known`; root cause: The red test reproduced that model.genesis accepted a model_evaluate draft effect even though the registered operation is a mutation model fit.; solution: `open`
- `agent-compiler-exact-connections`: occurrences=1; cause_status: `known`; root cause: The red test reproduced that a connection with valid endpoints plus forged extra endpoint fields was accepted.; solution: `open`
- `agent-compiler-natural-language-allowlist`: occurrences=1; cause_status: `known`; root cause: The red test reproduced that code.execute, whose natural language flag is false, still appeared in discovery results.; solution: `open`
- `agent-compiler-readonly-capabilities`: occurrences=1; cause_status: `known`; root cause: The red test reproduced that a declared read_only and none-risk capability was rejected because the compiler did not rank none risk.; solution: `open`
- `agent-compiler-runtime-shadow`: occurrences=1; cause_status: `known`; root cause: The red test showed that the manifest projection did not publish executor, reconciler, or runtime identity fields for shadow comparison.; solution: `open`
- `agent-compiler-server-scope-authority`: occurrences=1; cause_status: `known`; root cause: The red test reproduced that compilation accepted caller-provided scope and identity strings without a server-owned authority binding.; solution: `open`
- `formal-event-redaction-retry`: occurrences=1; cause_status: `known`; root cause: The first authority red event source was rejected by the formal event sanitizer because one summary phrase matched its secret-like pattern; the source was corrected and the event was appended successfully.; solution: `resolved`
- `formal-gate-enum-validation`: occurrences=1; cause_status: `known`; root cause: The first focused gate event used a preventability value outside the formal control enum and was rejected before changing the event stream; the source was corrected and retried.; solution: `resolved`

## Added tests

- `tests/test_v189_agent_compiler.py and tests/test_v189_capability_manifest.py`
- `tests/test_v189_agent_compiler.py::test_compiler_concurrent_identical_requests_have_one_compilation_reservation`
- `tests/test_v189_agent_compiler.py::test_compiler_fails_closed_without_server_scope_authority`
- `tests/test_v189_agent_compiler.py::test_compiler_rejects_forged_connection_fields`
- `tests/test_v189_agent_compiler.py::test_compiler_rejects_semantic_effect_downgrade_for_model_genesis`
- `tests/test_v189_agent_compiler.py::test_compiler_supports_declared_read_only_none_risk_capability`
- `tests/test_v189_agent_compiler.py::test_disabled_natural_language_capability_is_not_queryable_or_resolvable`
- `tests/test_v189_agent_compiler.py::test_manifest_exposes_runtime_identity_for_shadow_comparison`

## New rules

- `agent-compiler-atomic-reservation`: line experience occurrence(s)=1
- `agent-compiler-effect-binding`: line experience occurrence(s)=1
- `agent-compiler-exact-connections`: line experience occurrence(s)=1
- `agent-compiler-natural-language-allowlist`: line experience occurrence(s)=1
- `agent-compiler-readonly-capabilities`: line experience occurrence(s)=1
- `agent-compiler-runtime-shadow`: line experience occurrence(s)=1
- `agent-compiler-server-scope-authority`: line experience occurrence(s)=1
- `formal-event-redaction-retry`: line experience occurrence(s)=1
- `formal-gate-enum-validation`: line experience occurrence(s)=1

## Future guidance

- Apply the natural-language allowlist at both discovery and resolution boundaries.
- Bind the draft effect to a registry-declared semantic effect before compilation.
- Hash all server-selected runtime identities into the manifest projection used by shadow comparison.
- Keep formal event summaries free of secret-like vocabulary and verify the CLI result after every append.
- Represent every registry risk level in the compiler rank and keep read-only plans non-mutating.
- Require a server-owned, issuer-bound scope and principal resolution before plan compilation.
- Reserve a semantic compilation key atomically before any server draft registration or compilation side effect.
- Use an exact connection wire shape and reject every unknown field before port compatibility checks.
- Validate formal event enum values before preparing a gate source.

## Event index

- #1: `29e83021-13b4-4519-9e25-671b800f391f` | 2026-08-16T10:51:28.070Z | STATE_CHANGE/line_started | incident=`28d74117-36cc-4bd9-b91a-9608f62952f0` | lesson_key=`frozen-context-before-start` | event_sha256=`04715f3b97698e351875c671a6b75a50c02fa328a0fa23f01468291ba2866fea`
- #2: `1d7a9d9e-6b2f-4f67-9f6f-2b8a9fba0c11` | 2026-08-16T10:56:49.000Z | FAILURE/semantic_effect_downgrade_red | incident=`e4e9f88e-64c7-4c2e-9e8e-1e9b2fdb2c12` | lesson_key=`agent-compiler-effect-binding` | event_sha256=`2f1dc59a2ff432f32a514d08f03c86e04aaed402e6c6de23507ac0ed05ffb6be`
- #3: `2d8b0eaf-7c30-4a78-a070-3c9b0aec1d22` | 2026-08-16T10:56:50.000Z | FAILURE/readonly_none_risk_red | incident=`f5fa091f-75d8-4b3f-a181-4d0acbed2e23` | lesson_key=`agent-compiler-readonly-capabilities` | event_sha256=`da1d7c8fcd73fab753af83196c2cbc529af0e5a2f0a771386a1e7b9fcee0167f`
- #4: `3e9c1fb0-8d41-4b89-b181-4e0b1bdf2e34` | 2026-08-16T10:56:51.000Z | FAILURE/disabled_natural_language_red | incident=`a6ab1a02-86e9-4c40-b292-5f1c2cef3f45` | lesson_key=`agent-compiler-natural-language-allowlist` | event_sha256=`d3f8799735ccd8a5aecedf445f12e5f61b26500a67daacf5a67cd6dc1a7e8b7e`
- #5: `5abc31c2-af63-4da1-e3b5-8c4f5bfa6278` | 2026-08-16T10:56:53.000Z | GAP/runtime_identity_shadow_red | incident=`c8cd42d0-b074-4eb2-f4c6-9d5a6c0b7389` | lesson_key=`agent-compiler-runtime-shadow` | event_sha256=`46f2bce4735eb2788f2efea541461624bf6c0675be0a2b5fca161b702a45e0cc`
- #6: `6bcd42d1-c185-4fc3-a5d7-ae6b7d1c8490` | 2026-08-16T10:56:54.000Z | FAILURE/connection_exact_schema_red | incident=`d9de53e2-c296-4ad4-b6e8-bf7c8e2d9501` | lesson_key=`agent-compiler-exact-connections` | event_sha256=`c33133acb5f7009d99c8e0327ba2cfdf753adf4ca9eb09c069e3156a99dcfae9`
- #7: `7cde53e2-d307-4be5-c7f9-c08d9f3ea612` | 2026-08-16T10:56:55.000Z | FAILURE/compiler_reservation_race_red | incident=`eae64af3-d418-4cf6-d80a-d19eaf4fb723` | lesson_key=`agent-compiler-atomic-reservation` | event_sha256=`fb726dba693222eaf8a1d5f6c0876eca45745faa370aa42ac48df7650baf2dbe`
- #8: `4fab20b1-9e52-4c90-c292-6a2d3def4056` | 2026-08-16T10:56:52.000Z | FAILURE/scope_authority_fail_closed_red | incident=`b7bc2b13-9fa3-4da1-d3a4-7b3e4efa5167` | lesson_key=`agent-compiler-server-scope-authority` | event_sha256=`944134bd7ba09b26ba656d076e87e9350538299df7efdb3d0cf2521698a2eda4`
- #9: `8def64f3-e429-4cf7-d91a-e20f6b0fb834` | 2026-08-16T10:56:56.000Z | ERROR/formal_event_redaction_retry | incident=`9ef07504-f53a-4d08-e82b-f31a7c10c945` | lesson_key=`formal-event-redaction-retry` | event_sha256=`3356bc20aef1431187b7b92f04e0f5875706160d7423fdefb585e485e254b099`
- #10: `af0865f4-f53a-4d09-e82b-f31a7c10c956` | 2026-08-16T11:08:00.000Z | GATE/compiler_focused_gate_passed | incident=`bf197605-064b-4e1a-f93c-042b8d20da67` | lesson_key=`compiler-package-gate-boundary` | event_sha256=`0ffff2313ac51f99075b54550496deb6255fc04077298311de8d1d3e011d5e04`
- #11: `c0a8b6f5-164c-4e1a-a04d-153c9e31eb78` | 2026-08-16T11:08:01.000Z | ERROR/formal_gate_enum_retry | incident=`d1b9c7a6-275d-4f2b-b15e-264d0fa2fc89` | lesson_key=`formal-gate-enum-validation` | event_sha256=`90feb408850c3b4511f83bcba2d7e5f68de457e36bb6fd6de8f0cacf597f9f73`
- #12: `e1b9c7a6-275d-4f2b-b15e-264d0fa2fc90` | 2026-08-16T11:08:02.000Z | STATE_CHANGE/line_completed | incident=`f2ca8b97-386e-4f3c-c26f-375e1fb3ad01` | lesson_key=`compiler-remediation-line-close` | event_sha256=`5b8c7d8b3ff9d54cbd008ab18ad2a1845008486105b8d1f010f5071d7eebbcc1`
