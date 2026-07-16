# V1.5.4.4 — IV/2SLS Done Right + Debt Cleanup — Design

**Date:** 2026-06-11
**Status:** Design (awaiting plan)
**Theme:** Wire the last stranded estimator (`run_iv_2sls`) end-to-end to the GUI and make it professionally *trustworthy* — not merely runnable — by shipping the standard IV diagnostic trio, fail-loud input validation, and a foolproof role-assignment input UI. Dogfood the V1.5.4.3 `rerun_actions` socket with the first real consumer. Clear the V1.5.4.3 debt backlog.

**Behavior-freeze guarantee:** `iv_2sls` is an explicit-only model that CORE_PACK did not previously expose. Every change is gated so that runs NOT selecting `iv_2sls` produce byte-identical output → golden 0-drift.

---

## 1. Background & Motivation

`backend/workbench/econometrics/runner.py:366` already implements a complete, tested IV/2SLS estimator:

```python
run_iv_2sls(frame, y, exog, endog, instruments, model_id, covariance="robust")
  -> (normalized_result_dict, fitted)   # formula: y ~ exog [endog ~ instruments]
```

It is **stranded**: not registered in `CORE_PACK` (`estimation.py` exposes only panel_ols/probit/negative_binomial/glm/logit/poisson/ols), not reachable through the engine pipeline, absent from the capabilities manifest, and invisible to the frontend. This was the last of the three stranded capability families identified in the V1.5.4.2 audit (prediction/ML and panel entity-time were wired in V1.5.4.2).

IV/2SLS is the first new capability that touches the **engine model registry** — which is exactly why V1.5.4.3 hardened that surface (fail-loud `register_pack`, explicit `StageInsertion`, `RerunAction` wiring, frontend type gate, extracted RunForm). This version is the first real consumer of that hardened foundation.

**Distinctive challenge:** IV needs **three column-group inputs** (`exog` controls, `endog` endogenous regressors, `instruments`) where every prior model took a single `x` list, and the three must form a strict partition (no column in two roles) with the identification order condition `#instruments ≥ #endog` satisfied.

---

## 2. Scope

### In scope
1. **IV backend wiring** — register `run_iv_2sls` into `CORE_PACK` via a `_fit_iv_2sls(ctx, env)` adapter; `iv_2sls` is **explicit-only** (never auto-routed), y_type `continuous`.
2. **IV input fail-loud validation** — order condition, three-bucket non-overlap, non-empty endog/instruments, exclusion of `y` → structured `FailureCard`.
3. **IV diagnostic trio** — weak-instrument first-stage F (per endogenous regressor), Wu-Hausman endogeneity, Sargan overidentification (only when over-identified) — wired into `DiagnosticsStage`, gated on `model_type == "iv_2sls"`, each with a plain-language verdict.
4. **Frontend** — when `iv_2sls` is selected, reuse `x` as exog and reveal a **role-assignment** control (each candidate column assigned exactly one role: exogenous control / endogenous / instrument / unused) with a live identification badge; result card gains an IV diagnostics block (expanded by default, statistics + verdicts both).
5. **IV covariance selector** — expose robust/clustered/unadjusted for IV by reusing the existing panel covariance control (`run_iv_2sls` already accepts `covariance`).
6. **rerun_actions dogfood** — the IV pack declares `RerunAction`(s) so that on IV failure (under-identified / spec incomplete) the `FailureCard` offers a one-click "switch to OLS" recovery, exercising the V1.5.4.3 socket in production.
7. **Capabilities manifest 4-way sync (G0-5)** — backend key, drift-guard test, frontend type, contract schema + sample.
8. **Canonical IV example + how-to** — one textbook IV dataset in `examples/` plus a short doc, because valid instruments are hard for users to supply ad hoc.
9. **V1.5.4.3 debt cleanup** — `RERUN_ACTION_REGISTRY` key-dedup guard; `REGISTERED_PACKS` restore fixture for the new pack tests; `tsconfig` coverage of root config files.

### Explicitly out of scope (deferred)
- **Full `orchestrator.py` decomposition** → V1.5.4.5. This version does only the **minimal dispatch-seam touch** that adding IV forces, no broader split.
- **OLS-vs-IV side-by-side comparison** — needs two estimations per run, breaks the one-model-per-run pipeline assumption → its own feature.
- **Full first-stage regression display** — the trio already reports the decision-relevant first-stage F; dumping the entire `endog ~ instruments` regression is data, not decision, and grows the golden surface.
- **CLI/config path for IV** — consistency item that forks into config parsing; evaluate separately.
- Other unwired pack slots (`diagnostics`/`report_blocks`/`interpretation_restrictions`) remain alarmed-but-unwired → V1.5.6+.
- Agent Harness → separate architecture brainstorm.

---

## 3. Architecture & Data Flow

The wiring mirrors the established panel-entity/prediction parameter-threading pattern from V1.5.4.2.

### 3.1 Parameter threading (request → estimator)
```
POST /runs (api.py)  — new optional Form fields: iv_endog, iv_instruments
                       (exog reuses existing x; covariance reuses existing field)
  → _bg_run → run_workflow → _run_workflow
  → ctx.artifacts["_iv_endog"]        = [normalized endog cols]
    ctx.artifacts["_iv_instruments"]  = [normalized instrument cols]
    (exog = ctx.artifacts["_normalized_x"]; covariance = ctx.artifacts["_covariance"])
```
Endogenous/instrument column names are normalized to cleaned column names with the same `normalize_column_name` helper panel entity/time uses (so headers like "Mother Educ" resolve).

### 3.2 Estimation (`estimation.py`)
Add to `CORE_PACK.model_handlers`:
```python
ModelHandler("iv_2sls", "iv_2sls_1", ("continuous",), _fit_iv_2sls)
```
Adapter (same `(ctx, env) -> (model_id, result, fitted)` contract as the other `_fit_*`):
```python
def _fit_iv_2sls(ctx, env):
    return _orch().run_iv_2sls(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        exog=ctx.artifacts["_normalized_x"],
        endog=ctx.artifacts["_iv_endog"],
        instruments=ctx.artifacts["_iv_instruments"],
        model_id="iv_2sls_1",
        covariance=ctx.artifacts.get("_covariance") or "robust",
    )
```
`iv_2sls` is registered as an explicit alias only — `resolve()` must NOT auto-select it for any y_type (it can never be inferred from data; endogeneity is a modeling assumption). The fitted object lands in `ctx.artifacts["_fitted_models"]["iv_2sls_1"]` via the existing EstimationStage loop — no change to that loop.

### 3.3 Diagnostics (`diagnostics.py`)
`DiagnosticsStage.run` already reads `_fitted_models` and `model_type`. Add a guarded branch:
```python
if model_type == "iv_2sls":
    fitted = fitted_models["iv_2sls_1"]
    # weak instruments: fitted.first_stage.diagnostics  (per-endog F, partial R²)
    # endogeneity:      fitted.wu_hausman()
    # overid (only if #instruments > #endog): fitted.sargan
    # → write iv_diagnostics artifact with stats + plain-language verdicts
```
Because the branch only fires for `iv_2sls` (a model no prior run could request), all existing golden runs skip it → 0-drift. The diagnostics artifact is registered like other diagnostic artifacts (lineage parent = the IV model result).

**Verdict semantics (must be direction-correct):**
- Weak instruments: first-stage F per endog; `F > 10` (rule-of-thumb) → "instruments strong"; else "weak — interpret with caution". Always label the threshold as a rule of thumb, not a guarantee.
- Wu-Hausman: `p < 0.05` → "endogeneity confirmed, IV warranted"; `p ≥ 0.05` → "no endogeneity detected — OLS is consistent and more efficient".
- Overidentification: when **just-identified** (`#instruments == #endog`), Sargan is **not computable** — render "not applicable (just-identified)", never fake or hide it. When over-identified, `p < 0.05` → "instruments' exogeneity rejected (suspect)"; else "exogeneity not rejected".

### 3.4 Validation & failure path
Input validation runs before estimation (a small pure helper, e.g. `validate_iv_spec(exog, endog, instruments, y)`), raising a structured failure mapped to the existing `MODEL_FIT_FAILED`/IV failure card:
- `endog` empty or `instruments` empty → spec incomplete
- `#instruments < #endog` → under-identified (order condition)
- any column in ≥2 of {exog, endog, instruments}, or any equal to `y` → invalid partition

The IV pack declares `RerunAction(key="rerun_ols", label="Switch to OLS", param_overrides={"model_type": "ols"})` (and, where meaningful, an "edit instruments" hint), so these failures surface a one-click recovery via the V1.5.4.3 `rerun_actions` → `FailureCard.form_overrides` path. (The success-path "OLS would suffice" message from a non-rejected Wu-Hausman is plain verdict text, not a button — the rerun socket is failure-only.)

### 3.5 Frontend
- **Input (RunForm / new `IVControls`):** when `model_type === "iv_2sls"`, reuse the `x` field as exogenous controls and render a role-assignment table — each candidate column gets a single-select role (`exogenous control` / `endogenous` / `instrument` / `unused`). Overlap is structurally impossible. A live badge computes identification status (`under` → blocked with message / `just` / `over`) from the role counts. The constant is implicit; `y` is excluded from the candidate list.
- **Result (`runResult` IV diagnostics block):** reuse the existing result-card skeleton; add an IV diagnostics block below the coefficient table (endogenous coefficient highlighted). Block shows the identification badge and the trio, each row = statistic(s) + plain-language verdict. Expanded by default; statistics and verdicts shown together.
- **Wire format:** `iv_endog` / `iv_instruments` sent as JSON arrays (mirroring how panel/prediction extras are threaded via `RunExtraParams`); empty when not IV.

### 3.6 Capabilities manifest (G0-5 four-way sync)
`build_capabilities()` adds `iv_2sls` to the model-type set (and, if needed, marks it as requiring endog/instruments so the frontend can drive the role UI). The four synchronized points: backend `_SUPPORTED_*` / manifest key, the drift-guard test pinning the manifest to the backend set, the frontend `Capabilities` type, and the contract schema + sample.

---

## 4. Debt cleanup (V1.5.4.3 follow-ups)
1. **`RERUN_ACTION_REGISTRY` key-dedup guard** — `register_pack` raises (fail-loud, consistent with the V1.5.4.3 philosophy) if two registered rerun actions share a `key`. Now actually exercised because the IV pack is the first real registrant.
2. **`REGISTERED_PACKS` restore fixture** — the new pack tests (`test_pack_contract`, `test_pack_stage_insertion`, `test_pack_rerun_actions`) gain a fixture restoring `REGISTERED_PACKS` for symmetry, removing the latent order-dependence noted in the V1.5.4.3 final review.
3. **`tsconfig` root-config coverage** — bring `vite.config.ts` / `vitest.setup.ts` under the type gate (where `@types/node` actually earns its place), or document the deliberate exclusion.

---

## 5. Testing & Antifragility Gates

Every backend task carries a **golden 0-drift** step (`test_engine_golden.py` + invariants + behavior-snapshot). Specific gates:
- **G0-1** full suite via `.venv/bin/python -m pytest` (and bare `pytest`, now that the footgun is fixed) + `./scripts/gate.sh` green.
- **G0-2** golden 0-drift: an IV run is additive; no existing run selects `iv_2sls`, so registry/PIPELINE/diagnostics output for all current goldens is byte-identical.
- **G0-3** wiring tests must go red if the wiring is deleted: capture real `run_iv_2sls` kwargs (spy/monkeypatch asserting exog/endog/instruments/covariance, not just completion); diagnostics tests assert the computed statistic values; the rerun_actions dogfood test asserts the "Switch to OLS" action reaches the failure card and disappears if the registry entry is removed.
- **G0-5** manifest four-way sync for `iv_2sls`.
- New golden(s): add an IV characterization snapshot (a fixed IV run with known instruments) so IV's own output is locked going forward.
- IV diagnostics correctness: a small fixture with a known weak/strong instrument exercises the verdict thresholds and the just-identified "not applicable" overid path.
- Input validation: under-identified / overlapping-partition / empty-bucket each produce the structured failure with the expected recovery action.

---

## 6. Phasing (for the plan)

Each phase independently golden-verified and bisectable:

| Phase | Content | golden-sensitive |
|---|---|---|
| A | `validate_iv_spec` pure helper + structured IV failure (fail-loud, no estimation yet) | no |
| B | IV backend wiring: `_fit_iv_2sls` + `CORE_PACK` handler + `iv_2sls` explicit-only routing + param threading (incl. minimal dispatch-seam touch) | **yes** |
| C | IV diagnostic trio in `DiagnosticsStage` (guarded on `iv_2sls`), plain-language verdicts | **yes** |
| D | Capabilities 4-way sync + frontend `IVControls` (role-assignment + identification badge) + covariance selector + result-card diagnostics block | no |
| E | rerun_actions dogfood (IV pack `RerunAction` → FailureCard "Switch to OLS") + RERUN key-dedup guard | no |
| F | Canonical IV example dataset + how-to doc | no |
| G | Debt cleanup (REGISTERED_PACKS fixture, tsconfig root coverage) + final gate + release notes | no |

---

## 7. Behavior-Freeze Summary

`iv_2sls` is explicit-only and new; the validation helper, estimation handler, diagnostics branch, rerun action, and manifest entry are all inert unless a run requests `iv_2sls`. The only existing-path change is the IV pack registration (additive to `CORE_PACK`, raising only on duplicate keys, which none of the current handlers have). Production output for every current golden is byte-identical. Deferred items (full orchestrator split, OLS-vs-IV, full first-stage, CLI path) are explicitly untouched.
