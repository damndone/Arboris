# Frozen Context Pack

Line: `v1-8-9-consumer-catalog-contract`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 consumer catalog contract objective

## Objective

Replace the refs-only consumer catalog seam with a versioned provider-owned
declaration contract. A consumer projection row must declare which evidence
and envelope contracts it accepts, which fact kinds it may select, its policy,
renderer identity, budgets, ordering, and whether coverage is required or
explicitly exempt. The shared projection registry must read those declarations
and fail closed when a required declaration is missing or inconsistent.

This is a contract and wiring slice, not a claim that every package projection
is already executable. Package-specific rows may remain blocked until their
runtime adapter is registered; the catalog must make that state explicit.

## Required outcomes

1. Add a typed, immutable `ConsumerProjectionDeclarationV1` to the provider
   contract and persist it in every builtin manifest.
2. Validate declaration identity against the owning exposure path and its
   projection ref, policy/renderer refs, evidence refs, budgets, ordering,
   fact kinds, and explicit required/exempt coverage ownership.
3. Make the core consumer projection registry derive its policy, renderer,
   budgets, sensitivity and ordering from the server-owned catalog declaration;
   no consumer-side fallback defaults may create a covered row.
4. Keep package-specific projection refs blocked when no runtime adapter is
   registered. Do not rewrite real provider refs to the core projection ref.
5. Prove malformed, missing, duplicate, mismatched and exempt declarations
   fail closed through direct contract and catalog integration tests.

## Acceptance boundary

Required: RED/GREEN contract tests, builtin catalog loading, projection
registry/coverage sentinel tests, compileall and diff check. Browser, real
provider, host identity, full repository gate, merge, push, tag and release
remain follow-up gates.

## Boundary
- Affected paths: `tests/contracts/test_v189_contract_lock.py`
- Allowed paths: `backend/workbench/contracts/common/provider.py`, `backend/workbench/providers/catalog.py`, `backend/workbench/providers/builtin/agent_compiler.json`, `backend/workbench/providers/builtin/classification_ml.json`, `backend/workbench/providers/builtin/consumer_projection.json`, `backend/workbench/providers/builtin/contract_fixture.json`, `backend/workbench/providers/builtin/data_consumer.json`, `backend/workbench/providers/builtin/evidence_core.json`, `backend/workbench/providers/builtin/workflow_post_estimation.json`, `backend/workbench/evidence/consumer_adapters.py`, `tests/test_v189_consumer_catalog_contract.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-consumer-catalog-contract-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-consumer-catalog-contract-plan.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-consumer-catalog-contract.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-consumer-catalog-contract-handoff.md`, `backend/workbench/data_operation_manifest.py`, `tests/fixtures/contracts/v189/provider_contribution.json`, `tests/contracts/test_v189_contract_lock.py`, `tests/test_v189_data_operation_manifest.py`
- Protected paths: `backend/workbench/agent`, `frontend`, `backend/workbench/engine`, `backend/workbench/predictive_research`
- Dependencies: `v1-8-9-consumer-projection-core`, `v1-8-9-provider-projection-identity`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_consumer_catalog_contract.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_provider_projection_identity.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench`, `git diff --check`
- Known gates: `browser-NOT-VERIFIED`, `real-provider-NOT-VERIFIED`, `host-identity-NOT-VERIFIED`, `full-repository-gate-NOT-VERIFIED`, `no-merge-push-tag`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-9-contract-lock (2026-08-16T04:25:00.000Z)

Completed formal devline v1-8-9-contract-lock; final_state=COMPLETED; failure_lesson_keys=catalog-normalized-name-fixture-portability, formal-cli-command-surface-task2, formal-event-cli-generated-hash, formal-event-preventability-vocabulary, formal-event-source-repository-relative, formal-event-supported-stage, linked-worktree-git-index-permission, resolver-authority-slot-red, resolver-module-registry-red, shared-worktree-git-lock-permission, shared-worktree-git-staging-permission-repeat, task3-authority-slot-replacement-red, task3-compiled-projection-provenance-red, task3-failure-class-spec-red, task3-failure-vocabulary-red, task3-internal-snapshot-reflection-red, task3-reflection-provenance-hardening-red, task3-synchronized-authority-red, task4-catalog-spec-gap-red, task4-provider-contract-red, task5-compatibility-red, task5-formal-event-schema, task5-projection-contract-red, task5-projection-slot-shape-red, task5-quality-review-red, task5-slots-mutation-red, task5-timing-wrapper, task5-tuple-backed-red, v189-contract-ref-duplicate-mutation, v189-contract-ref-tdd-red, v189-duplicate-oracle-identity-mutation, v189-evidence-contract-quality-red, v189-evidence-contract-task2-red, v189-evidence-portable-integer-recursion-red, v189-evidence-public-shape-context, v189-fixture-command-error, v189-nested-evidence-portable-integer-red, v189-quality-fix-linked-worktree-index-permission, v189-semver-oversized-component-red, v189-task3-allowlist-assertion-alignment, v189-task3-capability-test-alignment, v189-task3-commit-index-lock-sandbox, v189-task3-commit-index-lock-sandbox-retry, v189-task3-compilation-capability-reflection-red, v189-task3-contract-red, v189-task3-durable-option-allowlist-assertion-alignment, v189-task3-durable-option-allowlist-compatibility, v189-task3-durable-option-allowlist-red, v189-task3-egress-selected-ref-error-vocabulary, v189-task3-egress-unknown-key-red, v189-task3-field-specific-ref-prefix, v189-task3-final-authority-and-field-kind-red, v189-task3-final-review-opaque-ref-private-issue-red, v189-task3-fourth-security-rereview-red, v189-task3-full-allowlist-assertion-alignment, v189-task3-git-index-sandbox-error, v189-task3-git-stage-sandbox-permission, v189-task3-holdout-capability-bypass-red, v189-task3-holdout-initial-state-compatibility, v189-task3-init-whitespace-check, v189-task3-opaque-prefix-binding-red, v189-task3-opaque-ref-camelcase-red, v189-task3-planning-cycle-error, v189-task3-public-wire-promotion-red, v189-task3-review-b-remaining-boundaries-red, v189-task3-second-security-focused-compatibility-failure, v189-task3-second-security-rereview-red, v189-task3-security-rereview-red, v189-task3-third-security-rereview-adversarial-red, v189-task3-typed-value-sensitive-red, v189-task3-validation-seam-implementation-gap, v189-validation-promotion-mutation
