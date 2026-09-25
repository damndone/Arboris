# Frozen Context Pack

Line: `v1-8-9-p0-consumer-authority-harness`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Workbench v1.8.9 P0 Consumer Authority Harness

## Objective

Make the external evidence-authority test harness robust when the full v1.8.9
suite temporarily replaces or closes its shared Unix socket. Consumer
projection tests must always obtain a live external authority in the current
process, while production remains dependent on deployment-owned authority.

## Scope

- `tests/test_v189_consumer_projection.py`
- `tests/test_v189_evidence_envelope.py`
- `tests/test_v189_central_evidence_consumer_mount.py`

## Acceptance

- The consumer projection suite passes alone and after the authority-mount
  suite in the same process.
- The harness never falls back to an in-process or caller-owned authority.
- Production evidence code is unchanged.

## Boundary
- Affected paths: `tests/test_v189_consumer_projection.py`, `tests/test_v189_evidence_envelope.py`, `tests/test_v189_central_evidence_consumer_mount.py`
- Allowed paths: `tests/test_v189_consumer_projection.py`, `tests/test_v189_evidence_envelope.py`, `tests/test_v189_central_evidence_consumer_mount.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_v189_central_evidence_consumer_mount.py tests/test_v189_consumer_projection.py`
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
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-9-p0-evidence-host-transport-hardening (2026-08-16T15:41:00.000Z)

Completed formal devline v1-8-9-p0-evidence-host-transport-hardening; final_state=COMPLETED; failure_lesson_keys=fd-transport-red-probes

### v1-8-9-p0-evidence-core-remediation-6 (2026-08-16T14:15:00.000Z)

Completed formal devline v1-8-9-p0-evidence-core-remediation-6; final_state=COMPLETED; failure_lesson_keys=evidence-host-endpoint-identity

### v1-8-9-p0-evidence-core-remediation-7 (2026-08-16T12:56:51.000Z)

Completed formal devline v1-8-9-p0-evidence-core-remediation-7; final_state=COMPLETED; failure_lesson_keys=evidence-host-trust-root, typed-timeout-boundary

### v1-8-9-p0-evidence-core-remediation-5 (2026-08-16T12:01:29.000Z)

Completed formal devline v1-8-9-p0-evidence-core-remediation-5; final_state=COMPLETED; failure_lesson_keys=evidence-external-channel-not-structural, evidence-host-authority-red-boundary

### v1-8-9-p0-evidence-core-remediation-3 (2026-08-16T11:12:00.000Z)

Completed formal devline v1-8-9-p0-evidence-core-remediation-3; final_state=COMPLETED; failure_lesson_keys=evidence-remediation-3-authority-transaction-boundary, evidence-remediation-3-lint-boundary
