# Retrospective — v1-8-8-planner-evaluation-quality

## Goal

# v1.8.8 planner evaluation and quality closeout objective  ## Objective  Add a declaration-derived natural-language planner evaluation system that measures ordinary prompts without turning a fixed prompt corpus into product logic. Cover normal, ambiguous, missing-input, false-causal, and prompt- injection cases; score typed operation choice, bindings, options, refusal reasons, and invented identities. Keep deterministic structural checks in CI and run stochastic provider benchmarks as a separate release gate with an overall correctness threshold of 95% and a dangerous-request safe-refusal threshold of 100%.  Close three adjacent v1.8.8 quality gaps in the same source tree:  - add a convergent Hurdle negative-binomial generic-workflow fixture while   retaining the existing non-convergence safety fixture; - replace P7 family-internal operation branches with declaration-keyed handler   maps without adding orchestrator dispatch; - remove Workbench-owned React \`act(...)\`, dependency-deprecation, and   avoidable statistical numerical warnings, while classifying rather than   suppressing warnings owned by third-party libraries or intentionally   degenerate safety fixtures.  ## Boundaries  - Evaluation cases and expected identities derive from live declarations. - Prompt variants are data for evaluation only and never enter production   routing, keyword rules, or hard-coded model selection. - Hidden/holdout variants must differ from public examples and must not be read   by the planner under evaluation. - Provider output is admitted only through the existing typed planner and   contract boundaries; the evaluator does not repair malformed output. - No warning is globally ignored. Statistical warnings are either converted   into explicit typed evidence/rejection or retained with a documented owner. - Do not weaken P0/P1/P2/P3 contracts, user confirmation, provenance, or   fail-closed behavior. - No external witness provider, push, PR, merge, tag, or release.  ## Acceptance  - A registry mutation automatically changes the planner-evaluation denominator   and generated case inventory without editing a second ID list. - Every live reachable capability receives all five scenario classes, with   holdout variation and leakage checks. - The deterministic evaluator rejects wrong operations, malformed bindings or   options, unsafe causal claims, unsafe injection compliance, and invented   run/node/artifact IDs. - The provider benchmark reports per-capability and per-scenario results,   confidence intervals, exact provider/model/configuration, immutable input and   output digests, and exits nonzero below the approved thresholds. - Browser confirmation remains limited to representative high-risk paths. - Hurdle negative-binomial has both one successful persisted generic workflow   outcome and one explicit non-convergence outcome. - P7 handler maps are declaration-derived and mutation-proven; unknown IDs fail   closed and no orchestrator dispatch file changes. - Workbench-owned warnings targeted by this line are absent from focused tests;   remaining upstream or intentional warnings are explicitly inventoried. - Focused backend/frontend tests, typecheck, formal verification, 64-operation   batch execution, and the host full gate pass on the final source commit.

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

- #1: `d933a7b2-1906-4434-98be-921f72615861` | 2026-08-13T11:05:37.685Z | STATE_CHANGE/line_started | incident=`bb0ada79-42a0-4a3a-bd94-9a1c489a2adb` | lesson_key=`frozen-context-before-start` | event_sha256=`c670a0620be05077ea74370f2b861b824f9653651f906f06f8ce4ad3ddd9f7ac`
