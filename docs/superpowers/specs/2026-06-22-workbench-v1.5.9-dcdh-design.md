# Workbench v1.5.9 — de Chaisemartin–D'Haultfœuille (dCDH) DID estimator — Design

**Date:** 2026-06-22
**Status:** Approved (brainstorm complete)
**Base:** origin/main `fc22964` (tag `v1.5.8`)
**DID Layer:** 3 (final piece, after honest-DID v1.5.7/v1.5.7.1, Sun-Abraham v1.5.8)
**Worktree:** `.worktrees/workbench-v1.5.9` off `fc22964`

---

## 1. Thesis & scope

dCDH (`DIDmultiplegtDYN`) is the **only** workbench estimator that handles **non-absorbing
/ switching** treatment — treatment that can turn on and off over time, with not-yet-switched
units as controls. Callaway-Sant'Anna (v1.5.6) and Sun-Abraham (v1.5.8) both *require*
absorbing staggered adoption. dCDH therefore fills a genuine capability gap, not "a third
estimator for a filled niche."

Its estimand/sample/influence-function do **not** map onto the `(g,t)` cell
`EffectEstimateBundle` that CS and SA share — dCDH produces a **dynamic event-study directly**
(effects + placebos by relative period). So this version **breaks the bundle** and introduces a
new, narrower cross-estimator contract: `EventStudyBundle`.

### In scope (minimal faithful, v1.5.9)

- **Binary non-absorbing** treatment `D_it ∈ {0,1}`, path may rise and fall.
- **Analysis sample = baseline=0 units whose FIRST switch is `0→1` ("first-up switchers").**
  Event origin is unambiguously an up-switch. After the first `0→1`, the unit's path may go
  `1→0` again and it **stays in the sample** (event_time keeps counting from the first up-switch)
  — this is the genuinely non-absorbing part that distinguishes dCDH from CS/SA.
- Dynamic `effect_ℓ` (ℓ≥0) + `placebo_ℓ` (pre-trend) — **primary results**.
- Overall ATT — **secondary**, emitted but flagged `experimental: true`.
- Self-implemented analytic influence function; per-ℓ SE validated against `DIDmultiplegtDYN`.
- sup-t uniform bands via the existing `multiplier_bootstrap`.
- Clustering: entity-default, optional `cluster_var` (mirror SA's single-row convention + guards).

### Deferred (explicitly NOT this version)

- Continuous / multi-valued treatment intensity.
- Covariates.
- baseline=1 units; `1→0` exit effects; direction-specific event study.
- Repeated-switch dose/path interpretation beyond "first-up origin".
- Irregular / non-consecutive time grids; fine unbalanced-panel reweighting.
- **honest-DID on dCDH** — not connected this version (see §6). Placebos are the native
  pre-trend device.

---

## 2. Architecture & data flow

```
input (treatment_path) → normalize_treatment_path → TreatmentPathPanel
   → estimate_dcdh (DID_ℓ + placebo + analytic IF)  →  EventStudyBundle
        → multiplier_bootstrap(estimates, IF, cluster_ids)  →  sup-t uniform band
        → per-ℓ SE (命门, aligned to DYN)
        → overall ATT (experimental)
        → run_dcdh assembles result dict → dcdh.json
```

**New files**
- `engine/event_study.py` — the narrow cross-estimator contract `EventStudyBundle` (NOT in
  `cs_attgt.py`, to avoid it reading as a CS appendage; CS/SA may later promote their internal
  dynamic IF onto this seam).
- `engine/dcdh_spec.py` — `DCDHSpecError`, `normalize_treatment_path`, `TreatmentPathPanel`.
- `engine/dcdh_estimator.py` — `estimate_dcdh_dynamic` → `dcdh_influence` → `estimate_dcdh`.

**Modified files**
- `econometrics/runner.py` — `run_dcdh` (reuses `multiplier_bootstrap`; **does NOT call
  `_finalize_did_bundle`** — that is `(g,t)`-bundle-specific).
- `estimation.py` — explicit-only `_fit_dcdh` handler (in `MODEL_REGISTRY`, never in
  `defaults_by_y_type`).
- `orchestrator/_model_types.py` — `"dcdh" → continuous` + `_MODEL_METADATA`.
- `engine/capabilities.py` — new `"dcdh"` group (4-way sync).
- `api.py` / `_run_workflow` — new `did_treatment_path` role param threading.
- Frontend: new `runForm/DCDHControls.tsx`, `runResult/DCDHResultCard.tsx`.

**Isolation invariants**
- `_finalize_did_bundle`, `did_spec.py`, `cs_attgt.py` aggregation: **one line unchanged**.
- dCDH touches CS/SA only at `multiplier_bootstrap`, which is a **pure inference function**
  consuming `(estimates, influence_func, cluster_ids)` arrays — it must **not** depend on the
  `EventStudyBundle` type. (Already true of its current signature; spec forbids regressing this.)

---

## 3. The narrow contract: `EventStudyBundle` (`engine/event_study.py`)

A cross-estimator event-study contract. **`event_times` is the sole primary axis;** `labels`
is a derived display-only field (never a second key).

```python
@dataclass
class EventStudyBundle:
    estimates: np.ndarray        # (L,) aligned to event_times
    influence_func: np.ndarray   # (N, L) entity rows, mean-zero columns, N-scaled (see §5)
    event_times: np.ndarray      # (L,) the SOLE primary axis; negatives = placebo, ≥0 = effect
    cluster_ids: np.ndarray      # (n_clusters,) descriptive
    n_switchers: np.ndarray      # (L,) per-event-time switcher count (for display/report)
    aux: dict                    # {"n_total": N, "row_cluster": (N,)}
    diagnostics: dict = {}       # estimator-specific (risk set, excluded units, sample spec)

    @property
    def labels(self) -> list[str]:   # DERIVED ONLY
        return ["placebo" if e < 0 else "effect" for e in self.event_times]
```

`multiplier_bootstrap` is called as `multiplier_bootstrap(bundle.influence_func, B=…, alpha=…,
seed=…, estimates=bundle.estimates, clusters=bundle.aux["row_cluster"])` — raw arrays only.

---

## 4. Input model (`engine/dcdh_spec.py`)

`did_spec` is cohort/absorbing-only (even its `status` mode raises `DID_NON_ABSORBING`), so dCDH
needs its own normalizer; `did_spec` stays untouched.

`normalize_treatment_path(frame, *, entity, time, y, treatment) -> TreatmentPathPanel`

Frame-derived columns:
- `_dcdh_D` — raw per-row treatment path (may rise/fall).
- `_dcdh_baseline` — per-entity first-period status `D_1`.
- `_dcdh_first_switch` — earliest `t` with `D_t ≠ D_{t-1}`; NaN if never switches.
- `_dcdh_first_switch_direction ∈ {"up","down","none"}`.
- `_dcdh_event_time` — `time − _dcdh_first_switch`, **filled only for eligible first-up
  switchers** (baseline=0 ∧ direction=="up"); NaN otherwise.

**Eligible analysis sample** = baseline=0 ∧ first-switch direction = "up". Controls =
baseline=0 not-yet-up-switched (incl. never-switchers). baseline=1 units are **excluded from
both treatment and control** with a recorded reason.

**Validation (structured `DCDH_*` → MODEL_FIT_FAILED):**
- `DCDH_FIELDS_MISSING` / column-not-found.
- `DCDH_TOO_FEW_PERIODS` (<2 periods).
- `DCDH_NON_BINARY_TREATMENT` (treatment ∉ {0,1}; continuous deferred).
- `DCDH_DUPLICATE_OBS` (non-unique (entity,time)).
- `DCDH_IRREGULAR_TIME` (non-consecutive / non-equispaced grid; deferred).
- `DCDH_NO_SWITCHERS` (no unit changes at all).
- `DCDH_NO_ELIGIBLE_UP_SWITCHERS` (switchers exist but none are baseline=0 first-up).

---

## 5. Estimator + analytic IF (`engine/dcdh_estimator.py`) — technical core

> **Lesson carried from SA (v1.5.8): the plan's numeric pseudocode is NOT authoritative — the
> committed `DIDmultiplegtDYN` oracle is.** The sketch below pins the *contract*; exact
> construction is whatever reproduces the oracle's estimates + per-ℓ SE. Research-risk items
> have an "oracle authoritative" fallback.

**`estimate_dcdh_dynamic` (long-difference DID_ℓ):** for each first-up-switch time `F` and each
horizon ℓ≥0, compare switchers' outcome change from reference period `F−1` to `F−1+ℓ` against the
same calendar-time change for not-yet-up-switched controls; aggregate across switch times
weighted by switcher counts → `effect_ℓ`. Placebos are the symmetric pre-period long-differences
(`F−1` → `F−1−ℓ`).

### Three locked hard-contracts
1. **`ℓ=0` is `F−1 → F`** (first-up current period vs the period before), NOT a same-period
   difference. Must match the DYN oracle exactly, else the whole event axis is off by one.
2. **Horizon-specific risk set.** For each `(F, ℓ)` the control set = baseline=0, not yet
   up-switched before `F−1+ℓ`, **observed at both** the reference and the target period. Record
   `{ell, n_switchers, n_controls, dropped_reason}` per `(F, ℓ)` so the sample can't drift
   silently across ℓ.
3. **Overall ATT = secondary.** Primary = `effect_ℓ + placebo_ℓ`. Overall ATT weighting is
   oracle-aligned first; until then it is emitted with `experimental: true`.

**`dcdh_influence` (命门):** one analytic IF column per ℓ (switcher term + control term),
N-scaled so `_se(col, row_cluster, N)` and the bootstrap inputs reconstruct the per-ℓ SE. Lock
the **DYN SE口径** (cluster level = entity, the variance option, df handling) as the oracle口径,
recorded in fixture metadata — else point estimates align but SE is off.

**`estimate_dcdh` → `EventStudyBundle`:** estimates over ℓ ∈ {placebos(neg), effects(≥0)},
IF `(N,L)`, `event_times` axis, `n_switchers` column, cluster ids, `aux.n_total`,
`diagnostics` (risk set, excluded units, sample spec). Clustering mirrors SA (single-row
convention + `DCDH_CLUSTER_*` guards: missing/NaN/single-level/bad-dtype).

### Oracle risk branch (pre-written into the plan)
- **If `DIDmultiplegtDYN` exposes IF/vcov:** test `IF → SE` tight, and align to DYN vcov where
  exposed.
- **If it does NOT expose IF/vcov:** grade down — point estimates tight; per-ℓ SE near-tight;
  internal IF reconstructs *this implementation's* SE; sup-t deterministic. **Do NOT claim "IF
  matches DYN".**

---

## 6. Downstream + result dict (`run_dcdh`)

`run_dcdh(norm, *, cluster_var, seed, B, alpha)`: `estimate_dcdh` → `EventStudyBundle` →
`multiplier_bootstrap` for a sup-t uniform band over `event_times` → assemble `dcdh.json`. Does
**not** go through `_finalize_did_bundle`.

```jsonc
{ "estimator": "dcdh",
  "event_study": {                 // PRIMARY
     "event_time": [ … neg = placebo, ≥0 = effect … ],
     "estimate": [ … ], "se": [ … ],
     "pointwise_ci": [ … ], "uniform_band": [ … ], "uniform_crit": …,
     "label_kind": "event_time",
     "kind": [ … "placebo"/"effect" … ],      // derived
     "n_switchers": [ … ]                       // same length as event_time
  },
  "overall_att": { "estimate": …, "se": …, "experimental": true },
  "diagnostics": {
     "risk_set_by_ell": [ {"ell":…,"n_switchers":…,"n_controls":…,"dropped_reason":…} … ],
     "excluded_units": …, "sample": { … } },
  "honest_did": null,
  "honest_did_supported": false,              // machine-readable
  "interpretation_restrictions": [ "non-absorbing …", "baseline=1 units excluded …" ] }
```

Whole result is JSON-safe (non-finite → null, per prior versions). **Sample-accounting
invariant:** `excluded_units` + `risk_set_by_ell` + `event_study.n_switchers` are mutually
consistent (tested, §9).

---

## 7. Frontend

- **`runForm/DCDHControls.tsx`** — treatment-path role assignment (entity / time / outcome /
  **treatment column**), distinct from cohort controls. Live identification badge = eligible
  first-up switcher count + excluded (baseline=1) count. **The badge is a pre-check ESTIMATE
  only; the backend `diagnostics` is authoritative** (no FE/estimator口径 drift).
- **`runResult/DCDHResultCard.tsx`** — event-study plot (placebo pre-segment visually separated
  from effect post-segment) + sup-t band + per-event-time `n_switchers` annotation + overall ATT
  with an `experimental` badge + diagnostics (excluded units / risk set) +
  `interpretation_restrictions`. **No honest-DID block** (reads `honest_did_supported:false`).
- **Does NOT reuse** `CSControls` / `CSDiagnosticsCard` (different contract — unlike SA, which
  reused them). The dynamic event-study line sub-component is reused from the CS/SA card if
  cleanly extractable; else a minimal build (decided in planning).
- capabilities **4-way sync**: new `"dcdh"` group, `requires:["entity","time","outcome",
  "treatment_path"]`, additive — FE type + contract schema/sample both learn the new role.

---

## 8. Oracle / dependency strategy

- R **`DIDmultiplegtDYN`** (CRAN), installed once; `~/.R/Makevars` `CC=clang -std=gnu17` if
  rebuild needed. `tests/fixtures/dcdh/generate_oracle.R` produces committed JSON; **the test
  suite never calls R.**
- **Locked DYN口径 saved as fixture metadata in every oracle JSON** (not just a script header):
  `effects`, `placebos`, `same_switchers`, `cluster`, `seed`, `package_version` — guards against
  silent drift when DYN is upgraded. The Python fixture loader asserts this metadata is present
  and matches.
- **Fixtures:** ① binary non-absorbing main panel (baseline=0 first-up + not-yet-switched
  controls + at least one `0→1→0` switch-back, to genuinely exercise non-absorbing);
  ② baseline=1 / down-switcher panel (tests exclusion + `DCDH_NO_ELIGIBLE_UP_SWITCHERS`);
  ③ placebo≈0 panel (pre-trend).

---

## 9. Testing matrix

| File | Validates |
|---|---|
| `test_dcdh_spec.py` | normalize + all `DCDH_*` validations, `first_switch_direction`, baseline=1 exclusion |
| `test_dcdh_estimator.py` | `effect_ℓ`/`placebo_ℓ` point estimates vs DYN (tight), `ℓ=0` definition, risk-set counts, **IF reconstructs DYN per-ℓ SE (命门, graded per §5 risk branch)**, bundle shape, clustering |
| `test_event_study.py` | `EventStudyBundle` contract + `multiplier_bootstrap` consumes raw arrays (not the bundle type) |
| `test_run_dcdh.py` | end-to-end `dcdh.json` shape, sup-t band, `overall_att.experimental`, `honest_did_supported:false`, `n_switchers` column, JSON-safe |
| `test_dcdh_qa_edge.py` | `0→1→0` non-absorbing, `DCDH_NO_ELIGIBLE_UP_SWITCHERS`, placebo≈0, determinism, cluster guards, non-numeric y |
| `test_dcdh_wiring.py` | api/_run_workflow/estimation/capabilities wiring (goes red if wiring deleted) |
| `test_dcdh_oracle_metadata.py` | every oracle JSON carries `effects/placebos/same_switchers/cluster/seed/package_version`; loader compares metadata |
| `test_dcdh_sample_accounting.py` | `excluded_units` + `risk_set_by_ell` + `event_study.n_switchers` mutually consistent |
| `test_dcdh_no_finalize_touch.py` | `run_dcdh` does NOT call `_finalize_did_bundle` (monkeypatch it to raise) |
| golden | additive dcdh golden (seeded) + **CS/SA golden 0-drift RUN as a hard gate** (anti-touch = run the goldens, not just check files unchanged) |
| FE | `DCDHControls.test.tsx`, `DCDHResultCard.test.tsx`, capabilities incl. dcdh, **negative test: `honest_did_supported:false` → no Honest-DID block rendered** |

**Graded validation gates:** point estimates vs DYN tight (~1e-6); per-ℓ SE tight/near-tight
(§5 branch); IF reconstructs SE + sup-t input; non-absorbing `0→1→0` runs + matches; baseline=1
exclusion + `DCDH_NO_ELIGIBLE_UP_SWITCHERS`; clustering; placebo≈0; JSON-safe.

---

## 10. Process

- Own worktree `.worktrees/workbench-v1.5.9` off `fc22964`; rebuild venv full-extras + npm.
- Gate via `./scripts/gate.sh` (never bare pytest); golden 0-drift hard gate.
- Zero new Python deps (self-implement); new R dep `DIDmultiplegtDYN` (oracle-gen only, version
  pinned in fixture metadata).
- Per-task TDD + two-stage review. **Execution (accuracy-first):** mechanical/context-heavy tasks
  inline; subagents reserved for the two-role adversarial review; rate-limited mechanical tasks
  done inline rather than re-spawned. **Subagents never pass a `model` param.**
- **Every implementer prompt FORBIDS `git push`** (v1.5.7.1 incident).
- Ship: `--no-ff` merge into main + tag `v1.5.9` + empty-diff verify + **explicit per-version
  push authorization** + ask cache cleanup.

**NEXT after v1.5.9:** the proper no-never-treated SA implementation (deferred from v1.5.8;
needs a non-fixest oracle) and/or the lineage-graph operation layer.
