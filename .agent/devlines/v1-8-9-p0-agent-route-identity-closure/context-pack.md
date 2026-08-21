# Frozen Context Pack

Line: `v1-8-9-p0-agent-route-identity-closure`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P0 Agent route identity closure

## Objective

Close the remaining Agent/Notebook route identity seam in which a direct
route-function call with `request=None` can currently treat caller-supplied
actor, session, and project values as if they were server-owned identity.
Natural-language preview, confirmation, execution, and evidence paths must
all require the same server-bound identity contract. A missing request or
missing deployment-bound resolver must fail closed before compiler, proposal,
provider, repository, or evidence side effects.

Preserve the real HTTP path and its typed unavailable responses. If a test
needs a direct route call, it must use an explicit server-owned test harness
that supplies a typed host binding; no boolean, arbitrary callback, raw
mapping, or caller assertion may become an authority substitute.

## Required evidence

- RED probes showing `request=None` cannot reach an authority or execution
  side effect;
- GREEN for the affected Agent route and Agent/Notebook cutover suites;
- positive HTTP/typed-host harness coverage remains valid;
- compileall and `git diff --check`;
- formal verification and generated retrospective;
- real supervisor/provider, browser, multi-worker, full-host, merge, tag, and
  release gates remain separate `NOT VERIFIED` evidence.

## Boundary
- Affected paths: `backend/workbench/http/agent_routes.py`, `tests/test_agent_routes.py`, `tests/test_v189_agent_route_identity_boundary.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p0-agent-route-identity-closure-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-route-identity-closure.md`
- Allowed paths: `backend/workbench/http/agent_routes.py`, `tests/test_agent_routes.py`, `tests/test_v189_agent_route_identity_boundary.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p0-agent-route-identity-closure-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-route-identity-closure.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/evidence`, `backend/workbench/providers`, `backend/workbench/engine`, `frontend`, `.agent/devlines`
- Dependencies: `v1-8-9-p0-deployment-authority-adapter`
- Tests: `PYTHONPATH=backend:tests .venv/bin/python -m pytest tests/test_v189_agent_route_identity_boundary.py tests/test_agent_routes.py tests/test_v189_agent_natural_language_route.py tests/test_v189_agent_notebook_cutover.py -q --disable-warnings`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/http/agent_routes.py tests/test_agent_routes.py tests/test_v189_agent_route_identity_boundary.py`, `git diff --check`
- Known gates: `real-supervisor-provider`, `browser`, `multi-worker`, `full-host-gate`, `merge-tag-release`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none
