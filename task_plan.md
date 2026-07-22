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

---

# v1.8 VIX Browser Reproduction Plan — 2026-07-21

## Objective

Use the in-app browser and real DeepSeek provider to run `examples/datasets/VIXCLS.csv` through the graph-native ARMA–GARCH Workbench, reproduce every supported operation in the 1013-line Stata Do-file, and preserve inspectable screenshots, run/artifact references, Agent transcripts, discrepancies, and failures.

## Phases

| Phase | Status | Outcome |
| --- | --- | --- |
| 1. Safety and launch | complete | Confirmed the v1.8 worktree boundary, launched isolated backend/frontend smoke servers, and inspected the configured DeepSeek provider without exposing its key. |
| 2. Visible dataset and five-step run | complete | Preserved the raw-data failure, then completed both the Stata-aligned manual run and the bounded automatic scan with the visible five-step form. |
| 3. Result and chart audit | complete | Inspected results, diagnostics, full-sample child, 17 structured chart artifacts, Graph stage context, Report facts, and visible screenshots. |
| 4. Natural-language Agent | complete | Ran one real bounded DeepSeek V4 Pro session; preserved prompt, transcript, event stream, provider evidence, unsupported-operation conclusion, and call-loop inefficiency. |
| 5. Do-file capability matrix | complete | Mapped the Do-file to exact/equivalent/unsupported/gap evidence and preserved the joint-MLE exclusion. |
| 6. Evidence report | complete | Wrote `docs/superpowers/handoffs/2026-07-21-v1.8-vix-browser-reproduction.md` with run IDs, values, charts, Compare evidence, defects, and minimal priorities. |

## v1.8 browser debug closure

| Phase | Status | Outcome |
| --- | --- | --- |
| 1. Reproduce and classify | complete | Reproduced missing-policy, report, Agent patch, project-fingerprint, Compare resolution, and persisted-reader defects in the visible VIX flow. |
| 2. Contract and runtime fixes | complete | Added structured missing handling, truthful tombstones, stage identity, nested patch merge, and persisted split reading with RED/GREEN tests. |
| 3. UI and evidence fixes | complete | Added essential Report facts, four sequence charts, truthful chart states, SVG export lifecycle, and nearest-ancestor Compare resolution. |
| 4. Real browser acceptance | complete | DeepSeek V4 Pro report and Agent recovery, manual run, automatic bounded scan, 17 artifacts/18 panels, and durable complete Compare all verified visibly. |
| 5. FMS, docs, and final gate | complete | Seven formal events appended; retrospective regenerated; full gate passed with backend 2940/8, golden 23 with zero drift, frontend 1288, and clean typecheck. |

## v1.8 delivery and release-truth closure

| Phase | Status | Outcome |
| --- | --- | --- |
| 1. Artifact audit | complete | Confirmed that VIX structured results exist, but run HTML/PDF are legacy summaries, `tables.xlsx` is empty for ARMA–GARCH, and Compare/Agent originals are machine-oriented. |
| 2. Documentation truth | complete | Added release notes and candidate ledger; reconciled the browser handoff, live backlog, plan and findings without claiming publication or numerical Stata parity. |
| 3. Delivery implementation | complete | Added run-owned ARMA–GARCH HTML/PDF, eight-sheet `ts.*` workbook, durable AI-report artifacts, concise Compare presentation, and read-only aggregated Agent audit exports. Real VIX run `20260722_011832_368932_550d4414` verifies the non-empty exports. |
| 4. Final candidate and independent acceptance | in_progress | The restricted full gate stops in nested sandbox tests; the same 33 sandbox/code-execute tests pass in the host environment. Commit the exact intended tree, then obtain the user-assigned Claude Step-5 acceptance before any release action. |

The earlier “final gate” row is historical browser-debug-scope evidence, not a publication sign-off for the later delivery findings. `docs/superpowers/release-trains/v1.8/release-ledger.json` is the release-status source of truth.

## Hard constraints

- Do not run full gate or another heavy suite while smoke servers or another heavy task is active.
- Do not change the estimator to joint MA–GARCH; reference semantics remain `directional_or_workflow_regression`.
- Use visible browser interaction for product behavior; do not replace the requested flow with API-only execution.
- Real DeepSeek calls are authorized, but keep prompts bounded and do not expose secrets.
- No push, PR, merge, tag, reset, rebase, stash, clean, or protected-path edits.

## Error log

| Event | Status | Response |
| --- | --- | --- |
| `.claude/launch.json` named by the handoff does not exist | recorded | Launched the documented backend and frontend entrypoints directly, on isolated ports 8018/5188. |
| Sandbox server bind failed with `EPERM` | resolved | Re-ran only the two scoped development-server launches with approved escalation. |
| Active provider model is `deepseek-v4-flash`, not the user-required Pro model | active | Do not call Agent yet; switch the model through the visible Provider UI to `deepseek-v4-pro` first. |
| Genesis ARMA-GARCH selection did not reveal the five-step operation form | investigating | Check the created Graph model node and the graph-native operation drawer before classifying this as a defect. |
| Raw VIXCLS run failed on 68 missing value rows | recorded | Preserve failed run `20260721_200829_505438_443bf21a`; reproduce Stata `drop if missing(VIXCLS)` exactly and continue with the 2,542 non-missing observations. |
| Agent cannot express row filtering or reach an ARMA-GARCH operation on the failed run | recorded | Preserve Agent session `agent_chain_9bdac9db230b4ac1873e4eb6495cfc4b`; do not spend more provider turns looping over unsupported tools. |
| Failed raw-data node shows Run code but preview/apply remain disabled | recorded | Do not use the inert control; continue with a mechanically filtered derivative of the same VIXCLS file. |
| Cross-run ARMA-GARCH Compare is blocked despite identical frozen rows | recorded | Preserved compare node `1def99e...`; root cause is split identity including the model contract plus an unrelated-run lineage guard. |
