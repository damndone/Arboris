# Frozen Context Pack

Line: `v1-8-9-p1-evidence-surface-integration`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# v1.8.9 P1 evidence-surface integration objective

## Objective

Complete the remaining central product-surface composition for the P1 evidence
layer: the Report UI must consume the server-owned data-consumer projection,
and Survey evidence must be available through the same server-owned run-detail
surface used by Agent and Notebook. Preserve fail-closed behavior: unknown,
missing, forged, stale, or unsupported evidence is typed `UNAVAILABLE` and is
never rendered from raw artifact JSON or caller-supplied paths.

## Baseline

- Integration worktree: `workbench-v1.8.9-hardening-integration`
- Exact baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`
- Existing dirty v1.8.9 changes are in scope and must be preserved.

## Boundaries

- In scope: server run-detail Survey projection, Report-side Survey and data
  consumer typed evidence state/rendering, matching contract tests, and the
  formal handoff.
- Out of scope: estimator formulas, survey variance semantics, new model
  families, browser acceptance, external providers, cross-process deployment,
  full-repository release gate, merge, tag, and release.
- No raw artifact payload, project path, or client identity may become a
  consumer authority input.

## Required outcomes

1. A run detail with a valid server-owned Survey artifact exposes one typed
   Survey projection; missing or unsupported Survey artifacts remain typed
   unavailable with bounded reasons and identity.
2. Agent, Notebook, and Report Survey reads share the same projection contract.
3. Report reads and renders the server-owned data-consumer projection, including
   status, evidence identity, lineage, and blocked/unavailable reason, without
   recomputing or accepting raw JSON.
4. Tests prove success, unavailable, identity binding, and no raw-payload
   fallback for both surfaces.

## Known gates

- Browser-visible acceptance is not yet verified.
- Real external provider, cross-process authority, full host, full-repository
  gate, merge, tag, release, and root-main synchronization are not yet
  verified.
- `.sav/.zsav/.dta` remain optional-dependency unavailable when `pyreadstat` is
  absent.

## Boundary
- Affected paths: `tests/test_v189_provider_projection_identity.py`
- Allowed paths: `tests/test_v189_provider_projection_identity.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_survey_central_consumer.py tests/test_v189_survey_authority_remediation.py -q`, `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_survey_run_detail.py -q`, `npm --prefix frontend run test -- --runInBand --testPathPattern=Report.*v189`
- Known gates: `browser-acceptance`, `external-provider`, `cross-process`, `full-repository-gate`, `release`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
