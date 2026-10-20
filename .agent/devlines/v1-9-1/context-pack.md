# Frozen Context Pack

Line: `v1-9-1`
Baseline SHA: `402d2d3eac3695d836255a424372930850b73a95`

## Objective
# v1.9.1 devline objective (condensed)

Full approved objective: `docs/superpowers/objectives/2026-10-17-v1.9.1-objective.md`
(sha256 `1ad30976e2da578221351121f0177bc77533b667ff8172818db01671f8a841c7`, commit `ae85aace`, approved by the user 2026-10-17
together with Claude's pending design decisions). The full file is authoritative; this condensed copy exists because the devline
Context Pack accepts at most 16 KiB of objective text.

Baseline: tag `v1.9.0` = `402d2d3e`. Worktree `.worktrees/workbench-v1.9.1`, branch `workbench-v1.9.1`, line `v1-9-1`.

## Goal

Make the Arboris Agent a "Claude Code for research": the user chooses **Ask every step** or **Auto within plan**, both polished for
daily use; given raw data and a research question the Agent organizes and completes a full, review-ready analysis (data
understanding, estimation, diagnostics, multi-specification robustness, tables, report); the plan is always visible and editable;
the user can steer, interrupt and undo a whole run at any time; runs continue in the background. Improvement is proven by public
benchmarks, replication of published papers and many-analysts data, not by self-assessment.

## Principles

1. Both modes are first class. After a confirmation the Agent continues on its own; the user never has to say "continue".
2. Safety boundaries do not relax with the mode: raw-data changes, exports, egress and registered high-risk operations need an
   explicit approval each time in both modes; interrupt is always available.
3. A lineage branch is the checkpoint; conversation and lineage rewind together.
4. Plan approval writes `criteria_fixed`; planned analyses are pre-specified, steps added after seeing results are exploratory.
5. Self-check against the playbook's completion criteria before declaring done.
6. Evaluation-driven: measure the v1.9.0 baseline and pre-register thresholds before implementing. DeepSeek V4.1 Flash
   (`deepseek-flash`) only; no spending cap but no waste (record/replay for regression; real calls for baseline, two mid-term
   rounds, final and browser acceptance).
7. Refactoring serves this version's capabilities; behaviour-preserving; judged by touch points per new capability and dependency
   structure, not line counts.

## Milestones

- **M0 baseline and pre-registration**: failure taxonomy from real session JSONL; full request-body and cache-hit profile; dev set
  ≥ 60 end-to-end tasks (both modes) and held-out set ≥ 20 with expert rubrics calibrated by human scoring; BLADE, QRData,
  DiscoveryBench subsets; red-card (Silberzahn et al. 2018) and Huntington-Klein et al. 2021 many-analysts data; replication
  challenge on 5 AEA/openICPSR packages; baseline on v1.9.0; thresholds written into the full objective and approved by the user.
- **M1 foundation**: behaviour-preserving splits of `planning_agent`, `workflow_contracts`, `workflow_runtime`, the touched parts of
  `orchestrator` and `NotebookService`, and `http/agent_routes.py`; one unified agent loop and one identity (Notebook planning becomes
  a tool or skill; execution is a tool call whose result returns to the model; plan-based budgets); one typed operation-request
  contract replacing the four proposal paths; durable, resumable, background turns with run-level cancellation; headless
  `workbench agent run` with an event stream; record/replay.
- **M2 modes, plan, steering**: the two execution modes and permission rules (session "don't ask again", project allow/ask/deny rules
  that can never loosen the safety floor) as an exhaustively tested state machine; plan object (DAG, versions, diffs, preflight,
  time estimates, user editing) and plan panel; ledger events `criteria_fixed`, `question_change`, `specification_status`; steer,
  follow-up, interrupt, undo APIs and UI; slash commands; notifications; blind plan comparison replaces the Plans view; retire the
  Notebook page and the classic shell.
- **M3 analysis capability**: full-analysis playbooks with completion self-checks and bounded failure recovery; multi-specification
  robustness with specification curves; an isolated reviewer sub-agent; tool ergonomics rework driven by the failure taxonomy,
  parallel read-only tools, cache-friendly stable prefixes.
- **M4 extensions, safety, observability, performance**: skills (`SKILL.md`, built-in / personal / project, progressive loading,
  scripts only through the capability-factory sandbox), external tools (MCP-like, under egress control) and hooks, each with
  admission, provenance, version and disable switch; built-in skills absorbing `nature-statistics` and `nature-figure` under
  Apache-2.0 attribution; prompt-injection red team (≥ 30 cases); per-step timing, tokens, cache hits and cost; vectorized sample
  fingerprints byte-identical to the current hashes.
- **M5 final evaluation and release preparation**: dev and held-out sets once each, external subsets, many-analysts, replication
  challenge, ablations; three real-browser scenarios; docs and handoff.

## Acceptance

Safety floor (independent of baseline): prompt-injection success 0; unauthorized state change or high-risk execution 0; numeric
grounding violations 0; "I am read-only" after a confirmation 0; times the user must say "continue" 0.

Initial targets (may only be raised after the baseline; lowering needs a devline GAP event and user approval): dev completion
≥ 90 % per mode; rubric mean ≥ 4.0/5; pass^3 ≥ 75 %; held-out completion ≥ 80 % (run once); tool rejection ≤ 3 % (8.6 % in real
sessions); argument-format retries median 0 and ≤ 2 per task; Auto-mode user actions = 1 plan approval plus high-risk
confirmations; replication ≥ 4 of 5 main tables to printed precision; red-card main estimate inside the central 90 % of team
estimates with every decision justified; BLADE/QRData not below the strongest comparable published baseline; prompt cache hit
≥ 70 % on multi-step tasks; first plan ≤ 15 s; non-model overhead per step median ≤ 300 ms; interrupt ≤ 1 s, long-computation
cancel ≤ 2 s, plan panel update ≤ 200 ms; 1M-row ingest + OLS ≤ 8 s with all 14 `perf_1m` budgets met.

Browser scenarios with real `deepseek-flash` at 1512 × 982 in light and dark: Ask every step on the IV example (edit one form, skip
one step, one "don't ask again"); Auto within plan on a panel DID project (edit plan, parallel run, steer, interrupt, close the window
and reopen on the notification, undo and rerun); open question with blind comparison, Run anyway, specification curve and correct
pre-specified/exploratory report sections. Host full gate, two self-reviews, one Codex evaluation lane.

## Out of scope

Inference kernel, HC/CR defaults, wild bootstrap and Rust components (v1.9.2); other model providers; journal writing packs, journal
figure export and publication tables; splitting `data_operations.py`, `api.ts` and context sub-modules; quant direction; windows
under 1200 px.

## Hard constraints

Fully usable without a model; no feature loss when retiring the Notebook page and classic shell; structural guards from the
kickoff handoff §4; never `pip install -e` or `npm install` in the worktree, new dependencies need user approval; external datasets
and replication packages only under `local/` with source, version, licence and checksum recorded; merge, tag, push and Release need
user authorization.

## Boundary
- Affected paths: `backend/workbench/agent`, `backend/workbench/http`, `backend/workbench/analysis_loop`, `backend/workbench/analysis_ledger.py`, `backend/workbench/egress.py`, `backend/workbench/events.py`, `backend/workbench/cli.py`, `backend/workbench/cli_commands.py`, `backend/workbench/canonical.py`, `frontend/src`, `scripts`, `tests`, `docs`, `evaluations`, `backend/workbench/llm/client.py`, `pyproject.toml`, `backend/workbench/capability_factory`, `backend/workbench/operation_approvals.py`, `backend/workbench/cli_agent.py`, `backend/workbench/statistical_tests.py`, `backend/workbench/statistical_test_requests.py`, `backend/workbench/dev_fixtures`, `backend/workbench/app.py`, `backend/workbench/engine/packs/linear_mixed_effects`, `backend/workbench/services/pinned_run_directory.py`, `backend/workbench/services/lmm_result_adapter.py`, `backend/workbench/engine/packs/survival_analysis`, `backend/workbench/engine/packs/v186_model_families`, `backend/workbench/engine/stages/diagnostics.py`, `backend/workbench/engine/completion_evidence.py`, `backend/workbench/services/completion_products.py`, `backend/workbench/engine/packs/time_series`, `backend/workbench/engine/packs/arma_garch`
- Allowed paths: none
- Protected paths: `backend/workbench/econometrics`, `backend/workbench/contracts/model`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_agent_*.py -q`, `cd frontend && npx tsc --noEmit && npx vitest run`
- Known gates: `host full gate with durations: PYTEST_ADDOPTS='--durations=30 --junitxml=local/pytest-durations.xml' bash scripts/gate.sh --full`, `browser acceptance at 1512x982 on ports 8035/5195, both execution modes, light and dark, real deepseek-flash`, `M0 pre-registered agent evaluation (dev, held-out, BLADE/QRData subsets, many-analysts, replication challenge)`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-cf3-validation-runtime (2026-07-27T12:25:00.000Z)

Completed formal devline v1-8-3-cf3-validation-runtime; final_state=COMPLETED; failure_lesson_keys=authoring-source-allowlist, cf3-validation-runtime-red, fms-event-draft-validation, protocol-identity-binding

### v1-8-5-workflow-memory-integration (2026-08-02T11:23:33.067Z)

Completed formal devline v1-8-5-workflow-memory-integration; final_state=COMPLETED; failure_lesson_keys=browser-memory-projection-contract-must-roundtrip, complete-v11-fields-when-removing-memory-provenance, did-genesis-empty-predictors-contract, did-model-family-contract-before-workflow-admission, did-notebook-family-contract-wiring, did-planner-family-contract-wiring, memory-default-target-registry-before-application, memory-provenance-version-from-new-proposal-on-revalidation, opaque-vocabulary-id-before-consumer-wiring, tdd-domain-memory-preflight-before-gate-wiring, tdd-memory-default-provenance-ui-before-persistence
