# Retrospective — v1-8-9-hardening-integration

## Goal

# Workbench v1.8.9 Hardening Integration Objective  ## Objective  Create a new candidate from the exact C3 baseline \`05362b5697e10eb25fd219da003641f96eeec082\` and serially integrate only reviewed v1.8.9 hardening lines. The candidate must preserve the C0 contract lock and C3 Agent/Notebook/Report cutover while adding the P0 evidence/Report identity hardening, P0 legacy/resume authority hardening, P1 data consumer, P1 classification production protocol, and reviewed survey extension. The result must be bound to one exact SHA and re-tested across backend, frontend, catalog, formal, and candidate-bound acceptance boundaries.  ## Required outcomes  1. Report facts are produced only from an authoritative, run-bound, artifact-bound and hash-verified typed evidence projection. Foreign artifact/envelope pairs and mixed-identity multi-artifact projections fail closed. 2. Historical Agent and Notebook confirmation paths use the server-owned compiler/admission boundary. Resume rebinds persisted completions, artifacts, output bindings, lineage and model branches before callbacks or new writes. 3. Data consumer operations expose typed profile/metadata/missing/filter/sort/split/recode and preview-confirm-child-lineage semantics. Supported interchange formats round-trip through real readers/writers; unavailable native formats remain explicitly typed unavailable. 4. Classification ML uses explicit task-aware split/CV, fold-local preprocessing, declared weight semantics, holdout/evidence status, and safe explainability/threshold/calibration projections. Unsupported or unverifiable behavior is fail closed. 5. Survey extensions use the existing variance engine and family adapters; no naive model result may be labelled as survey output, and unsupported design fields fail closed. 6. The final candidate has fresh exact-SHA focused regressions, frontend/typecheck, catalog/coverage, formal verification and candidate-bound acceptance evidence. Browser, external provider and release claims remain separately recorded and \`NOT VERIFIED\` until actually run.  ## Exact baseline  - baseline SHA: \`05362b5697e10eb25fd219da003641f96eeec082\` - branch: \`workbench-v1.8.9-hardening-integration\` - worktree: \`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration\`  ## Merge inputs  - P0 evidence/report hardening: \`da8b3e9d785df1c74b49da9a17ad80cb1e7841f8\` - P0 legacy/resume hardening: \`f1451c58a0a6e6a8f3577060016f62ebb694240a\` - P1 data consumer: \`f1519a42b8d9e147278028d02916cbeade6f7a06\` - P1 classification production: \`d429ed1564bbbe36983bb411497c1b60040a32eb\` - P1 survey extension: pending review-approved tip - acceptance harness: \`753f5405089aa8c88ee6f28cb16b2c47021e2618\`, sidecar/test owner only  ## Safety boundaries  - Do not modify root \`main\`, protected C3 candidate, or any feature branch. - Do not resolve statistical, evidence, identity, or runtime behavior conflicts inside Integration; return them to the owning line. - Do not merge a line with an open spec or code-quality review finding. - Do not claim browser, external-provider, host full-gate, merge, push, tag or release acceptance from package-local tests. - Do not add a second Agent/Notebook semantic engine or a fixed operation-specific dispatcher.

## Final status

STARTED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `bc82316b-d4c5-45df-a8a0-5244c8d48a15` | 2026-08-19T17:30:00.340Z | STATE_CHANGE/line_started | incident=`74a38c16-3233-470a-9dc0-0cdc90788a2a` | lesson_key=`frozen-context-before-start` | event_sha256=`6378cb5ac10e34e0aaa53f003d9065a49a32891e3d498f83c05460b6eddf790e`
