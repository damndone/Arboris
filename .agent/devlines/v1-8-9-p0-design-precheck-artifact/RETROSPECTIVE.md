# Retrospective — v1-8-9-p0-design-precheck-artifact

## Goal

# Workbench v1.8.9 P0 design-precheck artifact objective  ## Objective  Close the exact-baseline workflow evidence regression at \`01d746658eaccaadc4fcd0ee85f7a15fa1bbf225\`: the workflow emits a typed \`design_precheck\` artifact, but the canonical repository artifact vocabulary does not admit that type. As a result, model estimation can complete while the formal artifact index is rejected as invalid.  ## Required behavior  - \`design_precheck\` is admitted by the same closed canonical artifact   vocabulary used by the repository reader. - The reader still rejects unknown artifact types and malformed records. - Add a regression probe against the real canonical record validator. - Re-run the affected workflow truth tests to prove model results and evidence   can be consumed after the index is validated. - Do not loosen path, digest, required-field, or result-evidence checks.  ## Scope  Allowed product/test/document paths:  - \`backend/workbench/repository/run_repository.py\` - \`tests/test_v189_artifact_contracts.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-design-precheck-artifact-objective.md\` - \`docs/superpowers/plans/2026-08-20-design-precheck-artifact.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-design-precheck-artifact-handoff.md\`  Protected paths include model estimators, Survey engine, central Agent/ Notebook/Report cutover, other worktrees, and release/merge/tag/push machinery.  ## Baseline, dependency, and gates  - Exact baseline: \`01d746658eaccaadc4fcd0ee85f7a15fa1bbf225\`. - Dependency: \`v1-8-9-p0-survey-absence-boundary\`. - Required checks: TDD RED before production edits, focused artifact contract   tests, affected workflow truth tests, compileall, \`git diff --check\`, formal   verify, and retrospective. - Browser, provider, host, full gate, central candidate, release, merge, tag,   and push remain \`NOT VERIFIED\`.  ## Completion target  The line is complete only when \`design_precheck\` is admitted without admitting arbitrary unknown types, and an affected workflow truth test proves the model artifact can be read through the canonical index.

## Final status

STARTED

## Metrics

- Failure frequency: 1/3 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T08:31:29.467Z `design_precheck_artifact_tdd_red`; cause_status: `known`; cause: The canonical artifact reader rejects the real design_precheck artifact type emitted by the estimation pipeline.; resolution: `open`; lesson: Every artifact type emitted by an estimation stage must be registered in the same closed vocabulary used by the canonical reader.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `design-precheck-artifact-contract-red`: occurrences=1; cause_status: `known`; root cause: The canonical artifact reader rejects the real design_precheck artifact type emitted by the estimation pipeline.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `design-precheck-artifact-contract-red`: line experience occurrence(s)=1

## Future guidance

- Every artifact type emitted by an estimation stage must be registered in the same closed vocabulary used by the canonical reader.

## Event index

- #1: `74932e4f-421b-415a-80ed-6982450f6eae` | 2026-08-20T08:26:13.199Z | STATE_CHANGE/line_started | incident=`24189062-a264-45ff-a08e-0d5fe4ad78a5` | lesson_key=`frozen-context-before-start` | event_sha256=`afadd502d9957c65cf5d96dfb5de2068528c6f0a0430ed1e85fbb3e7917a6bd3`
- #2: `7d2a9f41-5c68-4b03-8e17-6a2d9c5f804b` | 2026-08-20T08:31:29.467Z | FAILURE/design_precheck_artifact_tdd_red | incident=`9e4c1a72-6b35-48d0-f7a3-2c8e5b1d9046` | lesson_key=`design-precheck-artifact-contract-red` | event_sha256=`3804ea290b2366c6539b4870905c1dc6ca46d162501bb38d05b1e688f9c3fc0a`
- #3: `8e3f2a71-5c94-4d60-b8e1-7f2a6c5d9034` | 2026-08-20T08:35:47.981Z | GATE/design_precheck_artifact_focused_gate | incident=`9e4c1a72-6b35-48d0-f7a3-2c8e5b1d9046` | lesson_key=`design-precheck-artifact-green` | event_sha256=`6951a3eeb8f0a42f94bfd1f4f2ea71bed658d082026cc05225ce318007fab3a9`
