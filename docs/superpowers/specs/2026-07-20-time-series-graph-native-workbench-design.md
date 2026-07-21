# Time-Series Graph-Native Workbench — Design Spec

Date: 2026-07-20 · Line: successor to `v1-8-arma-garch-runtime` · Worktree: `.worktrees/workbench-v1.8`
Status: design approved in brainstorming (direction + fork/compare topology confirmed by user).
Reference workload: the user's VIXCLS Stata Do-file (frozen ARMA(1,1)-GARCH(1,1) recipe).

## 1. Goal

Make the v1.8 ARMA–GARCH pack **fully graph-native**: every step of the reference Do-file is an
inspectable, operable node in the lineage graph; every result and operation lives in the graph node
drawer; the deprecated legacy Overview page is no longer part of the time-series path. The redesign
must reproduce the full capability set of the VIXCLS Do-file, read cleanly, and look elegant.

## 2. Current-state problems (verified in code)

1. The rich ARMA-GARCH result card (9 tabs) renders **only** inside the legacy `LegacyRunRoute`
   (`runResult.tsx:590`), an off-nav deep link (`?tab=overview`) with no way back. The graph node
   drawer shows only Ask-AI + Compare, not the result.
2. The ARMA-GARCH model node's `editable_schema` is a generic `model_options` JSON blob (derived
   from the capability `params` in `declaration.py`), so `OperationSection` cannot render a
   time-series operation form → "nodes can't do time-series operations".
3. `CompareNodesSection` is an ephemeral drawer view; it does not persist a comparison node.
4. The Workbench "Table" tab shows generic EDA figures (histograms/KDE/boxplots) and the generic
   artifact list — not a time-series view.
5. The comparison of ARMA-only vs ARMA-GARCH is modelled as a fixed backbone step, not as a
   fork-then-join, which does not match the chain-structured lineage model.

## 3. Design principles

- **Chain backbone, fork on divergence, join to compare.** The shared backbone runs only as far as
  the first point where alternatives diverge. Each distinct model is its own node (a fork). Compare
  is a node that joins ≥2 model nodes.
- **The node drawer is the single home** for both results and operations. No legacy Overview in the
  time-series path.
- **Every chart is a structured artifact** (`ts.chart.*`) rendered as inline SVG, never an opaque PNG.
- **Statistical honesty is a UI invariant.** Sequential vs joint labelled; 5% quantile never auto-
  named VaR; plug-in intervals disclaimed; trading-day units not silently converted to calendar.
- **Immutable source, frozen split before selection, child-not-overwrite on rerun** — unchanged from
  the accepted v1.8 runtime.

## 4. Target graph topology

```
VIXCLS data → Time & trading-day index → Transform → Train/Val split → ARMA mean selection
                                                                              │  (fork on divergence)
                        ┌─────────────────────────────┬───────────────────────┴───────────┐
                 Model: ARMA-only              Model: ARMA-GARCH (Normal, selected)   Model: GARCH-t (fork)
                 (variance = constant)                │                                     │
                        └──────────────┐   ┌──────────┘ → Forecast / Report                 │
                                    Compare node (joins ≥2 model nodes)  ◄──────────────────┘
```

- The backbone (data → index → transform → split → ARMA mean selection) is shared.
- **The fork point is wherever the rerun patch diverges**, not fixed at variance. Changing the
  variance model forks after ARMA mean selection; changing the transform forks further upstream
  (a new sub-tree from the transform node); changing p/q forks from ARMA mean selection.
- Each **model node** carries its own complete result: final fit, conditional series (mu/h/sd/z/z²),
  rolling one-step validation, n+1 forecast, and that model's diagnostics.
- A **compare node** is created by selecting ≥2 model nodes on the canvas; it validates
  comparability (same `analysis_view_hash` + `split_hash` + forecast origins) and renders the
  four-layer comparison.

## 5. Node inventory

| Node | Purpose | Operable? | Result surface (drawer) |
| --- | --- | --- | --- |
| **Data** | immutable VIXCLS source | read-only | source hash, row count, provenance |
| **Time & trading-day index** | date parse, drop non-trading, `t=_n` observation-order | confirm time column + semantics | time audit (parsed/invalid/dup/gap, inferred freq, lag unit) |
| **Transform** | level / log / diff_1 / log_return_pct (=100·Δln) | pick + confirm transform | per-transform profile: eligibility, n_effective, ADF, ACF decay, recommendation + reason |
| **Train/Val split** | freeze holdout before selection | set validation_n, refit_every | split index/hash, train/val counts, role = evaluation-after-selection |
| **ARMA mean selection** | bounded search, IC table | auto or manual p/q/const | candidate table (AIC/AICc/BIC/Δ), selected mean, roots, convergence |
| **Model node (per variance/dist/strategy)** | final ARMA±GARCH fit | rerun/fork (see §7) | **the result dashboard** (§6) |
| **Compare node** | join ≥2 model nodes | pick partners | four-layer compare + PI panels + width/coverage/pinball (§8) |
| **Forecast / Report** | n+1 + answer-first report | read-only | next mean/vol, PI, 5% quantile; report sections |

Mean diagnostics (resid ACF/PACF, Ljung–Box, squared-resid ACF, ARCH-LM) attach to the ARMA mean
selection node and to each model node's dashboard (standardized-residual versions).

## 6. Node-drawer result dashboard (replaces the 9 pills)

A single vertical, scrollable dashboard rendered by a new section-registry entry for
`kind==model && model_type==time_series.arma_garch`:

1. **Verdict header** — model title (`ARMA(1,1)-GARCH(1,1)`), meta line (strategy · distribution ·
   transform · trading-day index; the honest "reference = directional/workflow parity" note when
   applicable), and the **six acceptance dimensions as inline status chips** (data / mean /
   volatility / distribution / forecast / value-added) — all visible at once, no tab-hunting.
2. **Stat tiles** — persistence (α+β), half-life (trading days), 95% coverage (+ n), 5% pinball
   (vs ARMA), next conditional mean/vol.
3. **Inline mini-charts** (SVG from `ts.chart.*`): conditional volatility, rolling 95% PI band with
   exceptions, standardized-residual² ACF, QQ. Additional charts (series/transform, ACF/PACF,
   residual series, model comparison) available in a collapsible "all charts" strip.
4. **Candidate tables** — ARMA and variance candidates (incl. ARCH(0)=constant-variance baseline),
   sortable by AICc/BIC/param-count, filterable success/failed, failure reasons shown.
5. **Operation form** (§7).

Rendering must degrade gracefully in the drawer width (2-col grid collapses to 1-col); model nodes
may request a wider drawer. All numbers finite-JSON, no NaN/Inf.

## 7. Operation model (graph-native rerun/fork)

- Define a **structured operation schema** for the pack (replacing the opaque `model_options` JSON):
  transform, arma.p, arma.q, constant_mode, variance.model, arch/garch orders, innovation_distribution,
  estimation_strategy, validation_n, refit_every — each with kind/options/server caps. This drives
  `OperationSection` so the node renders a real time-series form. Server hard-caps (AR/MA/ARCH ≤ 10,
  GARCH p/q ≤ 5) still apply.
- Every operation is `model.rerun` / `graph.fork` → **a new child model node**; never overwrites the
  source. The fork attaches at the correct upstream node based on which fields changed.
- q>0 + joint stays blocked (`UNSUPPORTED_JOINT_ARMA_GARCH`); Normal→Student-t is a one-click fork
  offered as a recommended action when tails misbehave.

## 8. Compare node (new: persisted, not a view)

- Selecting ≥2 model nodes materializes a **persisted compare node** in the graph (extends the
  current ephemeral `CompareNodesSection` into a real node with its own lineage edges to its inputs).
- The compare node **validates comparability**: same transform, `analysis_view_hash`, `split_hash`,
  forecast origins, refit cadence. If they differ, it surfaces a blocking/warning diagnostic instead
  of a misleading comparison.
- Drawer content: parameter diff, data/sample diff, metric diff (MAE/RMSE/coverage/width/5% pinball),
  diagnostic diff (residual ARCH gone?), conclusion + "which is more trustworthy and why", and the
  ARMA-only-vs-GARCH PI panels + interval-width difference.

## 9. Chart artifacts → inline SVG

Add a frontend renderer that turns each `ts.chart.*` structured payload into inline SVG (line, band,
stem/ACF, QQ, scatter). The generic PNG figures (histograms/KDE/boxplots) are **not** shown for
time-series runs.

## 10. Table replacement

For time-series runs, the Workbench "Table" surface shows the **candidate tables + conditional-series
table** (from `ts.*` artifacts), not the generic EDA figures. The generic EDA/Table path is
suppressed when `model_type == time_series.arma_garch`.

## 11. Overview removal (scoped)

Remove the ARMA-GARCH result card from the legacy `runResult.tsx` path; time-series results are only
in the graph drawer. **Scope guard:** removing the legacy Overview for *all* model families is a
separate, larger migration and is **out of scope** here — this spec only detaches time-series from it.

## 12. VIXCLS wiring

When the user provides `VIXCLS.csv`, wire the frozen `vix_replication_profile`
(`tests/fixtures/models/arma_garch/vix_profiles.py`) through it: time=`observation_date`,
value=`vixcls`, drop non-trading rows, trading-day index, transform=log_return_pct, ARMA(1,1)
no-constant, GARCH(1,1). Because Stata's `arch` is a joint MLE with an MA term and the Workbench does
q>0 **sequentially**, acceptance asserts **directional/workflow parity** (direction, magnitude,
sample boundaries, diagnostic logic, forecast/volatility trajectories), not per-coefficient equality.
No VIX special-casing in pack code.

## 13. Capability coverage (Do-file → node/artifact)

`gen t=_n`→index node (observation_order); drop non-trading→time audit (blocking gaps, no interp);
`ln/D/dlvix100`→transform node (4 transforms + ADF/ACF evidence); `dfuller/corrgram`→transform &
diagnostics; `holdout=_N`→split node (frozen, split_hash); `8×arima`+IC→ARMA selection (AIC/AICc/BIC,
Δ); `wntestq e/e²`→mean diagnostics (Ljung–Box + squared); ARCH-LM q=10→diagnostics (F and LM=N·R²);
`arch(0..10)+garch11`→variance selection (incl. constant baseline); `predict h/z/z²`→conditional
series; `n+1 PI/fail1`→forecast node (95% coverage); rolling 20%→rolling validation (frozen spec);
`invnormal(.05)`→forecast (5% conditional quantile, not VaR); `α+β`/half-life→model node (trading-day
units); ARMA-vs-GARCH→compare node (width diff/coverage/pinball/PI panels); `qnorm/sktest/swilk`→
diagnostics (QQ + normality → Student-t recommendation); `graph export`→every chart a structured
artifact traceable to run/node/hash; legacy Overview→removed from TS path.

## 14. Scope boundaries (out of scope)

Multivariate/panel/exogenous/SARIMA/EGARCH/GJR/regime-switching; auto interpolation/fill/aggregation;
multi-step forecasts; custom joint ARMA-GARCH likelihood; removing legacy Overview for non-TS models;
downloading any external data.

## 15. Testing strategy

- Backend: structured operation-schema contract; compare-node persistence + comparability validation;
  chart-artifact schema unchanged; existing 156 focused + evaluation suite stay green.
- Frontend: dashboard section renders from `ts.*` artifacts (component tests); chart-SVG renderers;
  operation form emits schema-valid patches; compare-node view; Table suppression for TS.
- Live: the graph-native five-step flow and fork/compare exercised in the browser once file upload
  is available; VIXCLS replication when the CSV is provided.
- Full gate (`scripts/gate.sh --full`) green; golden/snapshot 0-drift; devline verify.

## 16. Risks & open questions

- Persisting a compare node touches graph-store/lineage contracts — largest blast radius; needs its
  own careful slice and golden coverage.
- Drawer width for the richer dashboard — may need a wider model-node drawer or an expand affordance.
- Structured operation schema must round-trip to the existing frozen `ArmaGarchAnalysisContract`
  without loosening server caps.

## 17. Name mapping to existing contracts

`editable_schema` (serve-layer, `op_contract.py`) → extended with structured TS params; `model.rerun`
/`graph.fork` (existing lineage ops) → per-model-node children; `CompareNodesSection` (v1.6.11) →
promoted to a persisted compare node; `ts.*` artifacts (existing) → drawer dashboard + inline SVG.
