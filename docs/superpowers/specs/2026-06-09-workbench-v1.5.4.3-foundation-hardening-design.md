# V1.5.4.3 — Foundation Hardening (Design)

- **Date:** 2026-06-09
- **Status:** Approved (brainstorming) — pending spec review
- **Branch (to create):** `workbench-v1.5.4.3`
- **Worktree (to create):** `.worktrees/workbench-v1.5.4.3`
- **Base:** `main` head (includes shipped `v1.5.4.2`, `eaaedd8`)
- **Theme:** Turn silent failure modes into loud, gated ones. No new user-facing econometrics — pure guardrails/structure so later versions (IV, feature packs, agent) build on solid ground.

## 1. Problem & Motivation

The post-v1.5.4.2 extensibility audit (`docs/architecture/2026-06-09-extensibility-assessment-and-antifragility-guide.md`) found two foundation-level fragilities plus latent structural debt:

1. **AnalysisPack "declared-but-not-wired" extension points** (`engine/pack.py`). `register_pack()` consumes only `model_handlers` + `defaults_by_y_type`. The fields `stages`, `diagnostics`, `report_blocks`, `recommended_actions`, `interpretation_restrictions`, `rerun_actions` are declared on the dataclass but **silently ignored**. A future pack that populates one gets no effect and no error — the classic extensibility trap, and this is the spine of the planned feature-pack roadmap.
2. **Frontend has zero type checking.** No `frontend/tsconfig.json`; `package.json` scripts are `dev` + `test` only; vitest/esbuild transpiles without type-checking. The capability-manifest-driven UI relies on `api.ts ↔ capabilities/types.ts ↔ components` types staying in sync, with no gate enforcing it.
3. **Process footguns from the v1.5.4.2 build:** bare `.venv/bin/pytest` silently breaks `tests.contracts` imports (3 collection errors masquerading as a red baseline); a Task-2 regression was only caught by the full suite, not a per-task subset. These lessons are documented but not *enforced*.
4. **`App.tsx` (939 lines)** is a god-component owning project state + the entire run form + submission + validation. Closing the frontend type gate is the right moment to split it (tsc becomes the safety net), and it de-risks the IV work (V1.5.4.4) by giving it clean components to extend.

## 2. Goals / Non-Goals

**Goals:**
- Make `register_pack()` **fail loudly** when a pack declares a not-yet-wired field.
- Give `stages` an **explicit-insertion API** so packs splice into the PIPELINE by declared position (real near-term consumer: DID/RDD/TimeSeries packs).
- Wire **`rerun_actions`** end-to-end as the reference "this socket is live" implementation, reusing the existing V1.5.4.1 rerun mechanism.
- Keep the still-unwired sockets **declared + alarmed + annotated** with their planned version.
- Add **`frontend/tsconfig.json` + `tsc --noEmit`**, fix **all** existing type errors (hard zero-error gate — no baseline), and add the typecheck to the gate.
- Split the run form out of `App.tsx` into focused components (behavior-frozen).
- Codify the antifragility gates into a single **gate script**, and **kill the bare-`pytest` footgun** so both `python -m pytest` and bare `pytest` work.

**Non-Goals (YAGNI):**
- Wiring `diagnostics` / `report_blocks` / `recommended_actions` / `interpretation_restrictions` (alarmed + annotated only; wired when a real consumer arrives).
- Splitting `orchestrator.py` (the 1344-line file split is golden-sensitive → isolated as **V1.5.4.5**).
- IV/2SLS (V1.5.4.4). Any new estimation path or model.

## 3. Scope

| # | Item | Layer | Risk |
|---|------|-------|------|
| a1 | `register_pack` fail-loud on unwired fields | backend | low |
| a2 | `stages` explicit-insertion API (declared position → spliced into PIPELINE; bad position errors) | backend | med |
| a3 | `rerun_actions` reference wiring (reuses V1.5.4.1 rerun path; CORE_PACK ships one real example) | backend (+ thin FE if surfaced) | med |
| a4 | Annotate reserved sockets with planned version | backend | trivial |
| b | Frontend type gate: tsconfig + fix all errors + `tsc --noEmit` zero-error into gate | frontend | low-med |
| B | `App.tsx` run-form componentization (behavior-frozen) | frontend | med |
| C | Gate script + bare-`pytest` footgun fix | tooling | low |

## 4. Design

### 4.1 (a1) Fail-loud registration
`register_pack()` checks each not-yet-wired field; if non-empty, raise a `PackContractError` (new, subclass of `ValueError`) naming the field and its planned version, e.g. `"AnalysisPack.diagnostics is declared but not wired (planned: V1.5.6). Remove it or wire it before registering."` Wired fields after this version: `model_handlers`, `defaults_by_y_type`, `stages`, `rerun_actions`. Alarmed fields: `diagnostics`, `report_blocks`, `recommended_actions`, `interpretation_restrictions`. Safe because the only existing pack (CORE_PACK) populates none of the alarmed fields → golden 0-drift.

### 4.2 (a2) `stages` explicit-insertion API
Add an insertion-position declaration to the stage contribution — a pack declares each added stage with an anchor, e.g. `StageInsertion(stage=MyStage(), after="estimation")` (or `before=`). `register_pack()` splices declared stages into the live PIPELINE at the anchor. An anchor naming a stage not in the PIPELINE raises `PackContractError`. PIPELINE stays a single ordered list; insertion is deterministic and explicit (no implicit auto-append). CORE_PACK does **not** add stages (keeps current behavior; golden 0-drift) — the API is exercised by tests with a throwaway test pack.

### 4.3 (a3) `rerun_actions` reference wiring
Define a minimal `RerunAction(key, label, param_overrides: dict)`. `register_pack()` collects rerun_actions into a registry. **Reuse the existing V1.5.4.1 mechanism**: V1.5.4.1 already renders `recommended_actions` (schema `{key,label,severity,form_overrides,hint}`) on failures via `FailureCard`, and `App.onFailureAction` applies `form_overrides` + re-runs. The reference wiring makes a registered pack's `rerun_actions` surface through that **same** path (mapping `param_overrides → form_overrides`), so no new speculative UI is invented. CORE_PACK ships **one** real example (e.g. a "re-run as auto" action). End-to-end test: pack declares a rerun_action → it appears in the actionable set → executing it triggers a run with the overrides applied. Exact surface (failure-path reuse vs a thin success-path affordance) is the one detail to lock in writing-plans; default = failure-path reuse (cheapest, zero new UI).

### 4.4 (a4) Annotated reserved sockets
Each alarmed field gets an inline comment + the `PackContractError` message stating its planned version (`diagnostics`→V1.5.6, `report_blocks`→V1.5.6, `recommended_actions`→when a pack needs it, `interpretation_restrictions`→V1.5.6). The roadmap lives in the code, not just memory.

### 4.5 (b) Frontend type gate
Add `frontend/tsconfig.json` (pragmatic `strict: true`; `noEmit`; `jsx: react-jsx`; include `src`). Run `tsc --noEmit`, **fix every error** surfaced (no baseline file). Add `"typecheck": "tsc --noEmit"` to `package.json` scripts. The gate (C) runs it. Decision (user-confirmed): if many errors surface, fix them all this version — they must be fixed eventually; gate stays at hard zero.

### 4.6 (B) App.tsx run-form componentization
Extract the run form (file/preview, model/imputation/panel/prediction controls already exist as children, plus the submission handler + `validatePanelPrediction` usage + the run-form state block) out of `App.tsx` into a focused `RunForm` component (and sub-components if a natural seam appears). Behavior-frozen: existing App tests pass (relocated if needed, assertions **not** weakened); `validatePanelPrediction` stays exported/unit-tested. `tsc --noEmit` + `vitest` are the safety net proving the split didn't break types or behavior.

### 4.7 (C) Gate script + pytest footgun
- **Footgun fix:** add `pythonpath = ["."]` under `[tool.pytest.ini_options]` in `pyproject.toml` (pytest ≥7) so the repo root is on `sys.path` and `tests.contracts` imports resolve under **both** `python -m pytest` and bare `pytest`. Verify both invocations green.
- **Gate script:** `scripts/gate.sh` runs, in order, failing fast with a clear banner per step: (1) backend full suite `pytest` (from the version venv), (2) golden/invariant/snapshot subset (explicit 0-drift check), (3) frontend `vitest run`, (4) `tsc --noEmit`. Exit nonzero on any failure. This makes G0-1/G0-2 executable, not just documented.

## 5. Testing Strategy

- **a1:** registering a pack with a non-empty alarmed field raises `PackContractError` naming field + version; registering CORE_PACK does not raise; golden 0-drift.
- **a2:** a test pack with `after="estimation"` splices correctly (PIPELINE gains the stage in the right slot); a bad anchor raises `PackContractError`; CORE_PACK adds no stages → golden 0-drift. Reset/teardown so the test pack doesn't leak into other tests' PIPELINE.
- **a3:** pack declares a rerun_action → it reaches the actionable set → executing applies `param_overrides` and produces a run (end-to-end, reusing the rerun mechanism). "Delete the wiring → test goes red" reverse-check (G0-3).
- **b:** `tsc --noEmit` exits zero on the whole tree.
- **B:** all existing frontend tests pass (relocated, not weakened); `validatePanelPrediction` unit tests intact.
- **C:** both `python -m pytest` and bare `pytest` collect+pass (footgun gone); `scripts/gate.sh` runs all four steps and fails fast on an injected failure.
- **Global gates (every task):** G0-1 full suite via `python -m pytest`; G0-2 golden 0-drift + behavior-frozen; G0-3 wiring tests go red if wiring deleted; G0-5 manifest 4-way sync (n/a this version — no manifest change).

## 6. Version Discipline

- Branch `workbench-v1.5.4.3`, worktree `.worktrees/workbench-v1.5.4.3` (fresh per-version env: `~/.local/bin/python3.11 -m venv .venv`, `pip install -e ".[dev,panel,ml,imbalanced,imputation]"`, `cd frontend && npm install`).
- Ship gate = `scripts/gate.sh` green + bare-`pytest` green.
- Release topology: tag `v1.5.4.3` on branch head, merge forward into `main`, keep branch + worktree as version markers (same as v1.5.4.1/v1.5.4.2).

## 7. Roadmap Context

- **V1.5.4.3** (this) — Foundation Hardening.
- **V1.5.4.4** — IV/2SLS + run-form is now pre-split, so IV extends clean components.
- **V1.5.4.5** — `orchestrator.py` file split (behavior-frozen, golden-sensitive — isolated).
- **V1.5.5** — multi-project tabs / concurrency.
- **V1.6** — Agent Harness (provider abstraction Anthropic+OpenAI, DeepSeek for testing; main+stage sub-agents over the pipeline; own architecture brainstorm).
