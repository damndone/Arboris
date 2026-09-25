# Frozen Context Pack

Line: `v1-8-9-p0-capability-manifest-contract`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Workbench v1.8.9 P0 Capability Manifest Contract

## Objective

Align the built-in Agent compiler manifest assertion with the published
declaration contract. A typed `compiler_receipt` fact kind is a result/evidence
declaration and must not be confused with an execution authority or client
receipt.

## Scope

- `tests/test_v189_capability_manifest.py`

## Acceptance

- The manifest test rejects execution authority fields while permitting the
  declared typed compiler evidence fact kind.

## Boundary
- Affected paths: `tests/test_v189_capability_manifest.py`
- Allowed paths: `tests/test_v189_capability_manifest.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_v189_capability_manifest.py`
- Known gates: `full backend regression and production provider/host acceptance remain separate gates`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-9-p0-agent-compiler-remediation-5 (2026-08-19T02:35:17.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-5; final_state=COMPLETED; failure_lesson_keys=os-boundary-probes-need-controlled-sandbox-access

### v1-8-9-p0-agent-compiler-legacy-cutover (2026-08-16T15:18:00.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-legacy-cutover; final_state=COMPLETED; failure_lesson_keys=compiler-os-fixture-needs-controlled-access, host-result-cross-object-binding, legacy-issuer-cutover-red-first

### v1-8-9-p0-agent-compiler-remediation-4 (2026-08-16T13:45:00.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-4; final_state=COMPLETED; failure_lesson_keys=compiler-proof-copy-must-fail-closed, compiler-remediation4-host-authority-and-fd-reservation, compiler-remediation4-red-tests-before-fix

### v1-8-9-p0-agent-compiler-remediation-3 (2026-08-16T12:20:00.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-3; final_state=COMPLETED; failure_lesson_keys=compiler-bootstrap-proof, compiler-durable-reservation, compiler-public-durable-store, compiler-sealed-scope-authority, compiler-selection-admission, discovery-server-scope-binding, legacy-c0-issuer-dependency

### v1-8-9-p0-agent-compiler-remediation-2 (2026-08-16T11:08:02.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-2; final_state=COMPLETED; failure_lesson_keys=agent-compiler-atomic-reservation, agent-compiler-effect-binding, agent-compiler-exact-connections, agent-compiler-natural-language-allowlist, agent-compiler-readonly-capabilities, agent-compiler-runtime-shadow, agent-compiler-server-scope-authority, formal-event-redaction-retry, formal-gate-enum-validation

### v1-8-9-p0-agent-compiler-remediation (2026-08-16T10:38:00.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation; final_state=COMPLETED; failure_lesson_keys=adversarial-authority-probes-before-green, discovery-budget-fails-closed, discovery-receipt-issuer-bound, exact-port-contract-before-green, registry-manifest-authority-before-compile

### v1-8-9-p0-agent-compiler-core (2026-08-16T09:55:00.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-core; final_state=COMPLETED; failure_lesson_keys=protected-provider-denominator-boundary, quality-tool-not-verified, shadow-core-not-runtime-acceptance, tdd-red-before-implementation

### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required
