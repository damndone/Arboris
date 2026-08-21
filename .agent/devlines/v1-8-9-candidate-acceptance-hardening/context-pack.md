# Frozen Context Pack

Line: `v1-8-9-candidate-acceptance-hardening`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 Candidate Acceptance Hardening Objective

## Objective

Finish the candidate-bound acceptance boundary without changing product
behavior: derive catalog and consumer coverage inside the candidate being
evaluated, reject dirty or mutated candidates, keep sidecar evidence outside
the candidate, and keep deterministic, provider, browser, and release claims
separate.

## Scope

This line owns only the acceptance QA module, its command-line runner, the
focused acceptance tests, and this line's work order. It must not change
statistical estimators, Agent/Notebook/Report product behavior, provider
authority, or release state.

## Required behavior

- Candidate SHA, source roots, trusted interpreter, and ignored dependency
  policy are checked before any product-path command.
- Catalog, coverage, and acceptance matrix are discovered from the candidate
  interpreter/PYTHONPATH, never from the evaluator checkout.
- A missing projection remains a BLOCKED row; it is not removed from the
  denominator.
- Deterministic mode never calls a provider. Provider mode never falls back to
  deterministic success and remains NOT_VERIFIED without an authorized
  adapter.
- Candidate source state is checked after commands; generated caches are not
  accepted as clean source state.
- Sidecar output is write-once and outside the candidate worktree.

## Verification boundary

Focused acceptance tests, candidate-bound deterministic evaluation, provider
non-fallback probe, compileall and diff check only. Browser, external provider,
cross-process, full-gate, merge, tag, release and deployment remain separate.

## Boundary
- Affected paths: `backend/workbench/qa/v189_foundation_acceptance.py`, `scripts/v189_foundation_acceptance_runner.py`, `tests/test_v189_foundation_acceptance.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-candidate-acceptance-hardening-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-candidate-acceptance-hardening.md`
- Allowed paths: `backend/workbench/qa/v189_foundation_acceptance.py`, `scripts/v189_foundation_acceptance_runner.py`, `tests/test_v189_foundation_acceptance.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-candidate-acceptance-hardening-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-candidate-acceptance-hardening.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/evidence`, `backend/workbench/engine`, `frontend`
- Dependencies: `v1-8-9-p0-agent-natural-language-route`
- Tests: `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_foundation_acceptance.py -q --disable-warnings`, `candidate-owned deterministic acceptance runner with exact clean SHA`, `provider mode returns NOT_VERIFIED without deterministic fallback`, `PYTHONPATH=backend:tests .venv/bin/python -m compileall -q backend/workbench/qa/v189_foundation_acceptance.py scripts/v189_foundation_acceptance_runner.py tests/test_v189_foundation_acceptance.py`, `git diff --check`
- Known gates: `browser, external provider, cross-process, full host gate, full repository gate, merge, tag, release and deployment remain separate and NOT_VERIFIED until directly run`

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
