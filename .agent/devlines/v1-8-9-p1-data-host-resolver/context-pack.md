# Frozen Context Pack

Line: `v1-8-9-p1-data-host-resolver`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# v1.8.9 P1 Data Host Resolver and Consumer Wiring Objective

## Objective

Close the remaining production boundary for the v1.8.9 data-consumer capability:
install a server-owned, scope-bound resolver at runtime bootstrap and make the
data provider's Agent, Notebook, and Report projection declarations agree with
the typed data-operation output contract. The resolver must consume only
server-issued opaque identities and durable OperationRecord/output evidence;
callers must never supply project paths, rows, data frames, or caller-authored
evidence. Missing or ambiguous durable state remains unavailable rather than
being guessed or recomputed.

## Success criteria

1. Application bootstrap can install a server-owned data host resolver for one
   exact project/session scope without relying on an optional ad-hoc port.
2. The resolver rejects foreign scope, stale snapshot, unknown operation, raw
   payloads, incomplete records, and ambiguous records fail-closed.
3. A completed durable data OperationRecord is rehydrated into the exact typed
   `DataConsumerRuntimeOutputV1` contract and cannot be forged by a caller.
4. The builtin data provider declares the same typed projection for Agent,
   Notebook, and Report; catalog coverage tests prove the declarations are
   identity-bound.
5. Focused resolver/bootstrap/catalog tests pass, while browser, external
   provider, cross-process, full host, and release gates remain explicitly
   reported as not verified until separately exercised.

## Non-goals

- Do not add a raw-data escape hatch or infer a filesystem root from an HTTP
  caller.
- Do not change statistical algorithms or the existing package-local data
  operation implementation in this line.
- Do not claim browser acceptance, production deployment, or release readiness.

## Boundary
- Affected paths: `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-host-resolver-handoff.md`
- Allowed paths: `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-host-resolver-handoff.md`
- Protected paths: `.agent/devlines`, `tests/test_agent_context_tools.py`, `frontend`
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -p no:cacheprovider tests/test_v189_data_host_resolver.py tests/test_v189_data_host_port.py tests/test_v189_consumer_catalog_contract.py tests/test_v189_agent_notebook_runtime_bootstrap.py -q --disable-warnings`
- Known gates: `browser`, `provider`, `cross-process`, `full-host`, `merge`, `tag`, `release`, `deploy`

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

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-9-p0-agent-compiler-remediation-5 (2026-08-19T02:35:17.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-5; final_state=COMPLETED; failure_lesson_keys=os-boundary-probes-need-controlled-sandbox-access

### v1-8-9-p0-workflow-truth-remediation-6 (2026-08-16T16:15:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-6; final_state=COMPLETED; failure_lesson_keys=formal-output-registration-transaction, register-child-run-model-artifacts, runtime-fixture-model-preconditions, use-declared-model-minimum

### v1-8-9-p0-legacy-compilation-authority-cutover (2026-08-16T14:30:00.000Z)

Completed formal devline v1-8-9-p0-legacy-compilation-authority-cutover; final_state=COMPLETED; failure_lesson_keys=legacy-authority-red-before-implementation, legacy-cutover-keeps-host-dependency-explicit

### v1-8-9-p0-workflow-truth-remediation-5 (2026-08-16T13:35:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-5; final_state=COMPLETED; failure_lesson_keys=production-host-integration-boundary, runtime-artifact-no-follow, workflow-remediation-5-red-before-fix

### v1-8-9-p0-evidence-core-remediation-7 (2026-08-16T12:56:51.000Z)

Completed formal devline v1-8-9-p0-evidence-core-remediation-7; final_state=COMPLETED; failure_lesson_keys=evidence-host-trust-root, typed-timeout-boundary
