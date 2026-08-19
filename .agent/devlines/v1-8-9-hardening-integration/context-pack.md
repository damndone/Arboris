# Frozen Context Pack

Line: `v1-8-9-hardening-integration`
Baseline SHA: `05362b5697e10eb25fd219da003641f96eeec082`

## Objective
# Workbench v1.8.9 Hardening Integration Objective

## Objective

Create a new candidate from the exact C3 baseline `05362b5697e10eb25fd219da003641f96eeec082` and serially integrate only reviewed v1.8.9 hardening lines. The candidate must preserve the C0 contract lock and C3 Agent/Notebook/Report cutover while adding the P0 evidence/Report identity hardening, P0 legacy/resume authority hardening, P1 data consumer, P1 classification production protocol, and reviewed survey extension. The result must be bound to one exact SHA and re-tested across backend, frontend, catalog, formal, and candidate-bound acceptance boundaries.

## Required outcomes

1. Report facts are produced only from an authoritative, run-bound, artifact-bound and hash-verified typed evidence projection. Foreign artifact/envelope pairs and mixed-identity multi-artifact projections fail closed.
2. Historical Agent and Notebook confirmation paths use the server-owned compiler/admission boundary. Resume rebinds persisted completions, artifacts, output bindings, lineage and model branches before callbacks or new writes.
3. Data consumer operations expose typed profile/metadata/missing/filter/sort/split/recode and preview-confirm-child-lineage semantics. Supported interchange formats round-trip through real readers/writers; unavailable native formats remain explicitly typed unavailable.
4. Classification ML uses explicit task-aware split/CV, fold-local preprocessing, declared weight semantics, holdout/evidence status, and safe explainability/threshold/calibration projections. Unsupported or unverifiable behavior is fail closed.
5. Survey extensions use the existing variance engine and family adapters; no naive model result may be labelled as survey output, and unsupported design fields fail closed.
6. The final candidate has fresh exact-SHA focused regressions, frontend/typecheck, catalog/coverage, formal verification and candidate-bound acceptance evidence. Browser, external provider and release claims remain separately recorded and `NOT VERIFIED` until actually run.

## Exact baseline

- baseline SHA: `05362b5697e10eb25fd219da003641f96eeec082`
- branch: `workbench-v1.8.9-hardening-integration`
- worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration`

## Merge inputs

- P0 evidence/report hardening: `da8b3e9d785df1c74b49da9a17ad80cb1e7841f8`
- P0 legacy/resume hardening: `f1451c58a0a6e6a8f3577060016f62ebb694240a`
- P1 data consumer: `f1519a42b8d9e147278028d02916cbeade6f7a06`
- P1 classification production: `d429ed1564bbbe36983bb411497c1b60040a32eb`
- P1 survey extension: pending review-approved tip
- acceptance harness: `753f5405089aa8c88ee6f28cb16b2c47021e2618`, sidecar/test owner only

## Safety boundaries

- Do not modify root `main`, protected C3 candidate, or any feature branch.
- Do not resolve statistical, evidence, identity, or runtime behavior conflicts inside Integration; return them to the owning line.
- Do not merge a line with an open spec or code-quality review finding.
- Do not claim browser, external-provider, host full-gate, merge, push, tag or release acceptance from package-local tests.
- Do not add a second Agent/Notebook semantic engine or a fixed operation-specific dispatcher.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-hardening-integration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-hardening-integration.md`, `docs/superpowers/release-trains/v1.8.9/locks/c4-hardening.yaml`, `docs/superpowers/release-trains/v1.8.9/evidence/c4-hardening-gate.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-hardening-integration-handoff.md`, `tests/test_v189_hardening_integration.py`
- Allowed paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-hardening-integration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-hardening-integration.md`, `docs/superpowers/release-trains/v1.8.9/locks/c4-hardening.yaml`, `docs/superpowers/release-trains/v1.8.9/evidence/c4-hardening-gate.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-hardening-integration-handoff.md`, `tests/test_v189_hardening_integration.py`
- Protected paths: `backend/workbench`, `frontend/src`
- Dependencies: none
- Tests: `candidate_bound_acceptance`, `focused_regressions`, `frontend_typecheck`, `formal_verify`
- Known gates: `browser_acceptance_NOT_VERIFIED`, `provider_acceptance_NOT_VERIFIED`, `host_full_gate_NOT_VERIFIED`, `release_tag_NOT_VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

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
