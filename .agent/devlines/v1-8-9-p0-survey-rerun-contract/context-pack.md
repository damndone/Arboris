# Frozen Context Pack

Line: `v1-8-9-p0-survey-rerun-contract`
Baseline SHA: `4f3ae29943feebb235ca9893186e20ae3984a2eb`

## Objective
# v1.8.9 P0 — survey rerun contract fixture

Align the Agent survey rerun end-to-end test with the current explicit survey support boundary. The survey variance engine must not silently accept finite-population correction when FPC is unsupported; the test must exercise a supported design and retain a separate assertion for the fail-closed unsupported-FPC path.

Do not expand the survey model family or change estimator behavior in this line. Preserve the existing oracle and typed design evidence assertions for the supported fields.

Acceptance: the supported rerun completes with a survey design result and the unsupported FPC declaration remains explicitly blocked; the scoped Agent reach suite and compile/diff checks pass. Browser, real Provider, external host resolver, and release gates remain explicit known gates.

## Boundary
- Affected paths: `tests/test_agent_v187_capability_reach.py`
- Allowed paths: `tests/test_agent_v187_capability_reach.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -p no:cacheprovider -q tests/test_agent_v187_capability_reach.py`
- Known gates: `browser acceptance NOT VERIFIED`, `real Provider NOT VERIFIED`, `production host resolver NOT VERIFIED`, `release merge/tag NOT AUTHORIZED`

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
