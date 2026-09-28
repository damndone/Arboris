# Work Order — v1.8.9 P1 Classification ML Core

## Objective and exact baseline

- Objective: implement a leakage-resistant, model-agnostic classification core
  with Logistic Regression and Random Forest adapters, typed evidence/artifact
  projections, and package-local provider/renderer contributions.
- Plan Lock: `f3836408cf15c3e7380823e5c1b303b4467c7aec`
- Exact C0 wave lock and current baseline: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`
- Branch: `workbench-v1.8.9-wave-a`
- Worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-wave-a`
- Formal line: `v1-8-9-p1-classification-ml-core`
- Completion handoff/report: `docs/superpowers/handoff/2026-08-15-v1.8.9-p1-classification-ml-core-handoff.md`

## Required outcomes

1. Typed classification task, class mapping, label, availability and decision
   policy contracts fail closed on incomplete information.
2. IID, group, temporal and panel split profiles enforce row/entity/time
   identities, information-set predicates, purge/embargo evidence and sealed
   holdout separation.
3. Fold-local preprocessing and training-only resampling retain fit row refs,
   recipe/schema/seed receipts and reject unsupported inputs or ignored weights.
4. Logistic Regression and Random Forest implement the same typed adapter
   contract and registry seam with explicit bounded parameters and no unknown
   model fallback.
5. Metrics, calibration, baselines, negative controls, bounded tuning,
   comparisons and DecisionPolicy selection carry denominator, oracle,
   validation and holdout-access evidence.
6. Explanations, stability, subgroup and shift diagnostics are descriptive,
   support-bounded and isolated from unauthorized holdout exploration.
7. Classification artifacts, Graph lineage, EvidenceEnvelope contribution and
   additive prediction entrypoint are persisted/projected without changing old
   regression semantics.
8. A package-local provider declaration and unmounted typed renderer prove the
   extension seam without central Agent/Notebook/Report/UI changes.

## Dependency and evidence status

- Completed dependency: `v1-8-9-contract-lock` at exact C0 tip
  `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`. The C0 handoff and generated
  retrospective were read before this order was created; catalog digest is
  `cac54a40f62620b84d288416ee09d5b04814f4dbcb2c8ee3a4595522e3e0da40`.
- Required by the plan but not materialized in this active Wave A worktree:
  `v1-8-9-p0-workflow-truth-core`, `v1-8-9-p0-evidence-core`, and
  `v1-8-9-p0-agent-compiler-core` completion SHAs/handoffs/retrospectives.
  This is a formal GAP and remains `NOT VERIFIED`; implementation may consume
  only the C0 public contract facade and must not import sibling private code or
  claim C1 compatibility/cutover.
- Sibling `v1-8-9-p1-data-consumer-core` handoff/retrospective were read. Its
  dirty product files and formal artifacts in this shared Wave A worktree are
  protected and are not owned by this line.

## Owned paths (exact)

```text
backend/workbench/predictive_research/classification_contracts.py
backend/workbench/predictive_research/classification_adapters.py
backend/workbench/predictive_research/classification_metrics.py
backend/workbench/predictive_research/classification_protocol.py
backend/workbench/predictive_research/classification_explanations.py
backend/workbench/predictive_research/schema.py
backend/workbench/predictive_research/consumer_projection.py
backend/workbench/predictive_research/graph_persistence.py
backend/workbench/predictive_research/split_kernel.py
backend/workbench/predictive_research/preprocessing.py
backend/workbench/predictive_research/persistence.py
backend/workbench/predictive_research/__init__.py
backend/workbench/prediction.py
backend/workbench/providers/builtin/classification_ml.json
frontend/src/report/ClassificationEvidence.tsx
frontend/src/report/ClassificationEvidence.test.tsx
tests/predictive_research/test_classification_contracts_v189.py
tests/predictive_research/test_classification_protocol_v189.py
tests/predictive_research/test_classification_leakage_v189.py
tests/predictive_research/test_classification_consumers_v189.py
docs/superpowers/objectives/2026-08-15-v1.8.9-p1-classification-ml-objective.md
docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-classification-ml-core.md
docs/superpowers/handoff/2026-08-15-v1.8.9-p1-classification-ml-core-handoff.md
```

Existing files in the owned list may only receive additive classification
changes; regression behavior and unrelated predictive-research contracts remain
unchanged.

## Read-only inputs and protected paths

Read-only inputs are the C0 public contract/catalog facades, the C0 manifest,
the v1.8.9 parity design/program/plans, existing regression predictive-research
semantics, and the generated Context Pack/global rules/selected retrospectives.

The following are protected and must not be modified:

```text
backend/workbench/contracts
backend/workbench/agent
backend/workbench/evidence
backend/workbench/workflow.py
backend/workbench/workflow_runtime.py
backend/workbench/providers/builtin/contract_fixture.json
backend/workbench/data_profile.py
backend/workbench/data_operation_manifest.py
backend/workbench/filter_ast.py
backend/workbench/data_operations.py
backend/workbench/metadata.py
backend/workbench/http/data_operation_routes.py
backend/workbench/data_context_egress.py
backend/workbench/providers/builtin/data_consumer.json
frontend/src/lineage/dataOperationManifest.ts
frontend/src/lineage/dataOperations.ts
frontend/src/lineage/detail/sections/DataOperationsSection.tsx
frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx
tests/test_v189_data_profile.py
tests/test_v189_data_operation_manifest.py
tests/test_v189_context_egress.py
tests/test_v189_filter_ast.py
tests/test_data_operation_routes.py
tests/contracts/test_v189_contract_lock.py
frontend/src/report/ReportView.tsx
frontend/src/workbench/registry/sectionRegistry.ts
scripts/gate.sh
```

No new dependency, provider credential, network access or raw executor path is
authorized.

## Tests, mutations and known gates

Focused backend command:

```bash
cd backend && PYTHONPATH=$PWD /Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  ../tests/predictive_research/test_classification_contracts_v189.py \
  ../tests/predictive_research/test_classification_protocol_v189.py \
  ../tests/predictive_research/test_classification_leakage_v189.py \
  ../tests/predictive_research/test_classification_consumers_v189.py -q
```

Focused frontend command:

```bash
cd frontend && npm test -- --run src/report/ClassificationEvidence.test.tsx && npm run typecheck
```

Required adversarial/mutation anchors include full-table preprocessing,
pre-split resampling, ignored weights, holdout reads/repeated release,
class-map reversal, holdout threshold selection, unknown availability
promotion, interval/purge/embargo/entity-overlap bypasses, unknown adapter
fallback and provider contract/effect/path bypasses. Restore every mutation
before proceeding and record material results through the formal CLI.

Known gates and explicit non-claims:

- Only Logistic Regression and Random Forest are completion adapters.
- C1 P0 dependency completion SHAs/handoffs are not present in this worktree;
  C1 compatibility is `NOT VERIFIED`.
- Agent/Notebook production cutover, Context Compiler routing, ReportView and
  section registry mount, real browser acceptance, external provider benchmark,
  performance certification, full release gate, merge, push and tag are
  `NOT VERIFIED`/not performed.
- Formal verification/retrospective proves process control only; it does not
  replace numerical, leakage, provider, browser or release evidence.

## Rollback and closeout

Rollback means removing only the files in this line's owned path list while
preserving the pre-existing Data Consumer changes; no `git reset --hard`, broad
cleanup or worktree deletion is permitted. Closeout requires focused tests,
compile/typecheck/diff checks, exact-scope check, formal `verify`, CLI-generated
retrospective and the completion handoff with implemented/tested versus
`NOT VERIFIED` evidence separated. No commit, merge, push or tag is allowed.
