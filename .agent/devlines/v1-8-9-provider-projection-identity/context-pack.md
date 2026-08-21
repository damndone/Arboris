# Frozen Context Pack

Line: `v1-8-9-provider-projection-identity`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 provider projection identity objective

## Objective

Create a read-only identity sentinel for the provider catalog's consumer
projection declarations. Every declared row must preserve the exact tuple
`(provider_id, exposure_path, consumer_id, projection_ref)` and remain
auditable without silently rewriting package-owned projection references.

This line does not change runtime adapters, provider manifests, coverage
semantics, or central Agent/Notebook/Report mounts. It proves the current
catalog denominator and makes the next central consumer integration line safe
to implement in disjoint, package-owned steps.

## Required outcomes

1. Load the repository builtin catalog through the server-owned loader.
2. Assert the current declaration counts are explicit: 7 providers, 15 rows,
   12 composable paths, and 3 direct paths.
3. Assert every row's provider, path, consumer, and projection reference is
   unique and internally stable; provider identity must not be inferred from a
   consumer-only registry key.
4. Preserve the current status split as evidence: 5 covered and 10 blocked
   `projection_ref_mismatch` rows. The test must not turn blocked rows into
   coverage by changing refs.

## Boundary

Only the sentinel test and this line's objective/plan/handoff are owned. No
product runtime, provider manifest, frontend, central consumer, or release
artifact may be changed.

## Acceptance

Run the sentinel test, the existing catalog/coverage focused tests, Python
compileall for the touched test module, `git diff --check`, and formal devline
verification. Browser, provider, host, full-gate, merge, push, tag, and release
remain unverified.

## Boundary
- Affected paths: `tests/test_v189_provider_projection_identity.py`
- Allowed paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-provider-projection-identity-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-provider-projection-identity-plan.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-provider-projection-identity-handoff.md`, `tests/test_v189_provider_projection_identity.py`
- Protected paths: `backend/workbench/evidence`, `backend/workbench/providers`, `frontend`, `.agent/devlines`
- Dependencies: `v1-8-9-consumer-projection-core`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_provider_projection_identity.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_consumer_coverage.py tests/test_v189_consumer_projection.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q tests/test_v189_provider_projection_identity.py`, `git diff --check`
- Known gates: `browser-NOT-VERIFIED`, `provider-NOT-VERIFIED`, `host-full-gate-NOT-VERIFIED`, `no-merge-push-tag`

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
