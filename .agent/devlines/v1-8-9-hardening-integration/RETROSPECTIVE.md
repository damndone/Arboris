# Retrospective — v1-8-9-hardening-integration

## Goal

# Workbench v1.8.9 Hardening Integration Objective  ## Objective  Create a new candidate from the exact C3 baseline \`05362b5697e10eb25fd219da003641f96eeec082\` and serially integrate only reviewed v1.8.9 hardening lines. The candidate must preserve the C0 contract lock and C3 Agent/Notebook/Report cutover while adding the P0 evidence/Report identity hardening, P0 legacy/resume authority hardening, P1 data consumer, P1 classification production protocol, and reviewed survey extension. The result must be bound to one exact SHA and re-tested across backend, frontend, catalog, formal, and candidate-bound acceptance boundaries.  ## Required outcomes  1. Report facts are produced only from an authoritative, run-bound, artifact-bound and hash-verified typed evidence projection. Foreign artifact/envelope pairs and mixed-identity multi-artifact projections fail closed. 2. Historical Agent and Notebook confirmation paths use the server-owned compiler/admission boundary. Resume rebinds persisted completions, artifacts, output bindings, lineage and model branches before callbacks or new writes. 3. Data consumer operations expose typed profile/metadata/missing/filter/sort/split/recode and preview-confirm-child-lineage semantics. Supported interchange formats round-trip through real readers/writers; unavailable native formats remain explicitly typed unavailable. 4. Classification ML uses explicit task-aware split/CV, fold-local preprocessing, declared weight semantics, holdout/evidence status, and safe explainability/threshold/calibration projections. Unsupported or unverifiable behavior is fail closed. 5. Survey extensions use the existing variance engine and family adapters; no naive model result may be labelled as survey output, and unsupported design fields fail closed. 6. The final candidate has fresh exact-SHA focused regressions, frontend/typecheck, catalog/coverage, formal verification and candidate-bound acceptance evidence. Browser, external provider and release claims remain separately recorded and \`NOT VERIFIED\` until actually run.  ## Exact baseline  - baseline SHA: \`05362b5697e10eb25fd219da003641f96eeec082\` - branch: \`workbench-v1.8.9-hardening-integration\` - worktree: \`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration\`  ## Merge inputs  - P0 evidence/report hardening: \`da8b3e9d785df1c74b49da9a17ad80cb1e7841f8\` - P0 legacy/resume hardening: \`f1451c58a0a6e6a8f3577060016f62ebb694240a\` - P1 data consumer: \`f1519a42b8d9e147278028d02916cbeade6f7a06\` - P1 classification production: \`d429ed1564bbbe36983bb411497c1b60040a32eb\` - P1 survey extension: pending review-approved tip - acceptance harness: \`753f5405089aa8c88ee6f28cb16b2c47021e2618\`, sidecar/test owner only  ## Safety boundaries  - Do not modify root \`main\`, protected C3 candidate, or any feature branch. - Do not resolve statistical, evidence, identity, or runtime behavior conflicts inside Integration; return them to the owning line. - Do not merge a line with an open spec or code-quality review finding. - Do not claim browser, external-provider, host full-gate, merge, push, tag or release acceptance from package-local tests. - Do not add a second Agent/Notebook semantic engine or a fixed operation-specific dispatcher.

## Final status

CONTEXT_REFRESHED

## Metrics

- Failure frequency: 1/7 (14.3%; 14.3 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #2 2026-08-19T23:59:00.000Z `integration_merge_tree_environment`; cause_status: `known`; cause: git merge-tree dry-run could not create its temporary merge object in the managed worktree environment and returned Operation not permitted; no working tree or product file was changed.; resolution: `open`; lesson: Do not treat a failed dry-run as merge evidence; keep exact-SHA serial merge and focused tests as the acceptance boundary.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `merge-tree-managed-worktree-temp`: occurrences=1; cause_status: `known`; root cause: git merge-tree dry-run could not create its temporary merge object in the managed worktree environment and returned Operation not permitted; no working tree or product file was changed.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `merge-tree-managed-worktree-temp`: line experience occurrence(s)=1

## Future guidance

- Do not treat a failed dry-run as merge evidence; keep exact-SHA serial merge and focused tests as the acceptance boundary.
- Integrate only exact feature tips with both spec and quality approval; keep external and release gates separate.

## Event index

- #1: `bc82316b-d4c5-45df-a8a0-5244c8d48a15` | 2026-08-19T17:30:00.340Z | STATE_CHANGE/line_started | incident=`74a38c16-3233-470a-9dc0-0cdc90788a2a` | lesson_key=`frozen-context-before-start` | event_sha256=`6378cb5ac10e34e0aaa53f003d9065a49a32891e3d498f83c05460b6eddf790e`
- #2: `2e5c23d2-9a34-4f1e-8b6a-7ce2b9a4d1f0` | 2026-08-19T23:59:00.000Z | ERROR/integration_merge_tree_environment | incident=`3d4c5b6a-7e8f-4012-93a4-b5c6d7e8f901` | lesson_key=`merge-tree-managed-worktree-temp` | event_sha256=`3507a30fdfa26314c53f376ae6bef978329145fa66d7e9dae5acce59863ad21b`
- #3: `8f4e2a10-5c7b-4d9e-8a31-6b0f2c9d7e45` | 2026-08-20T06:29:38.300Z | REVIEW/reviewed_merge_inputs | incident=`7c1e9a52-4f86-4b0d-a3e7-2d5f8c1b6a90` | lesson_key=`reviewed-exact-merge-inputs` | event_sha256=`d675ddfd83dcc9a353973eed2599b61836fe1e629a490b556831ed4ff55ab2c9`
- #4: `8f3ee5d0-c058-4d6f-a4ba-9714c458aebe` | 2026-08-20T07:08:35.558Z | STATE_CHANGE/context_refresh_required | incident=`fcd9ddcd-9b13-4810-9e54-ec4bd571dd0b` | lesson_key=`context-pack-rule-drift` | event_sha256=`8b0f109e49384ed6606735fde4781eb3bc78a5c243a415280e17a237c915b52c`
- #5: `c99a5d02-eb74-462f-9aeb-f786b65b0089` | 2026-08-20T07:08:35.565Z | STATE_CHANGE/context_refreshed | incident=`d5f4c434-b0b9-400e-9c8b-5ac05778a353` | lesson_key=`context-pack-rule-drift` | event_sha256=`cfa37ed82760d9510a78f4476cc3629d09e0d0a10cafd104caddbbefd9048fd5`
- #6: `6f1a3e72-0b9c-4d8e-a5f7-2c6b1d9e4a30` | 2026-08-20T07:09:25.459Z | GATE/candidate_bound_acceptance | incident=`9c4e2a71-5b8d-43f0-a6c2-7e1d9b5a3084` | lesson_key=`candidate-bound-gate-boundaries` | event_sha256=`d3673726a47278cc7b60d6b9f800eb071c84d643cc06121a583bbaaa5344baa3`
- #7: `2d7a9c4e-6b1f-48d0-a5e3-9c2b7f1d6048` | 2026-08-20T07:28:13.608Z | GATE/controlled_host_full_gate | incident=`5e1b8c3d-7a2f-49d6-b0e4-6c9f2a7d1b58` | lesson_key=`full-gate-pre-cutover-contract-migration` | event_sha256=`6e8fee54379fbd961667ec10184e470707e6ec7b92379478202d6de35b2377c2`
