# v1.7.3 Integration Completion Plan

## Objective

Finish the contract-first LMM Wave-1 integration and establish the Failure Memory System and Development Efficiency Control System required for every development line.

## Phases

| Phase | Status | Outcome |
| --- | --- | --- |
| 0. Baseline and release ledger | complete | Exact Integration baseline, ledger, focused backend and native frontend evidence recorded. |
| 1. Failure-memory control plane | in_progress | Formal event/retrospective/promotion/Context Pack/CLI tests pass. Five canonical, in-progress formal lines were created through the CLI and backfilled only from reviewed reports/tests; their retrospectives and an empty completed-line index verify. Gate wiring and completed-line indexing remain deferred. |
| 2. WO-A trusted result persistence | in_progress | Finish the reviewed admission/pinned-writer design, implement with RED/GREEN, then independent review. |
| 3. WO-B model pack and WO-C UI | in_progress | Maintain inert Pack seam; WO-C native tests and typecheck pass, browser gate waits for assembled route. |
| 4. WO-D containment | in_progress | C1 remains fail-closed; C2 design is independently approved, but implementation and a supported-host canary are still required. |
| 5. Exact candidate assembly | pending | Assemble reviewed changes into one exact Integration candidate and record lineage/evidence. |
| 6. Release gates | pending | Backend, frontend, browser, security, performance, independent evaluation, Report/Operations evidence. |

## Non-negotiable rules

- No release, merge, tag, or passing-evidence claim without one exact reviewed Integration SHA.
- No candidate execution before WO-D C2 has a supported-host canary.
- Every formal line writes append-only `.agent/devlines/<line_id>/events.jsonl` events and ends with a generated retrospective. Pre-formal legacy lines remain quarantined and are not release evidence.
- No new line begins without a generated Context Pack, current global rules, and relevant retrospectives.

## Current blockers

1. WO-A P1 persistence design is still under final review; do not implement raw-path persistence.
2. WO-D C2 has no accepted host/canary. The approved C2 contract may be implemented, but execution must remain fail-closed until a supported-host canary exists.
3. Browser acceptance waits for a real assembled result route, not a component-only test harness.
4. The formal FMS index is intentionally empty: all five formal lines are `IN_PROGRESS`; no line may be indexed as complete before a real closing state and evidence exist.
5. Gate wiring is deferred. `scripts/gate.sh --quick` has no narrow, separately tested FMS hook; adding one now would alter release-gate behavior beyond this control-plane closeout.

## Error log

| Event | Status | Response |
| --- | --- | --- |
| Integration frontend lacked native dependencies | resolved | Offline lockfile rebuild; focused 38/38, full 1211/1211, typecheck pass. |
| Existing FailureCard assertion drifted from `0251f0a` contract | resolved | Test now asserts identity of the contract action, preserving `model_options: {}`. |
| WO-A persistence review uncovered repeated capability-boundary gaps | active | Record events; finish capability/admission contract before implementation. |
