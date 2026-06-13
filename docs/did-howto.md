# Difference-in-Differences — How-To

## What it's for

Difference-in-differences (DID) estimates the **average treatment effect on the
treated (ATT)** from panel data: the same entities observed over time, where
some become treated and others do not. Under **two-way fixed effects** (TWFE) —
absorbing entity-level and period-level shocks — DID identifies the causal
effect by comparing the *change* in treated units' outcomes to the *change* in
comparison units' outcomes, on the **parallel-trends** assumption: absent
treatment, the treated and comparison groups would have moved in lockstep.

This is **Layer 1** (classic TWFE DID). It is explicit-only; auto mode never
picks it.

## The three input modes

Pick the mode that matches how your treatment timing is recorded. Every mode
needs an **entity** column and a **time** column (set via `entity_col` /
`time_col`); `y` is the outcome.

- **`cohort`** — staggered adoption. One column holds each entity's
  **first-treatment period** (`did_cohort_col`). Never-treated units use `0` or
  a blank/empty value. The engine derives the 0/1 treatment indicator and event
  time per row. Use this when different entities switch on in different periods.
- **`two_by_two`** — the canonical 2×2 design. A **treat-group** column
  (`did_treat_col`, 1 = ever-treated group) and a **post-period** column
  (`did_post_col`, 1 = post-treatment periods); treatment = treat × post. Use
  this when there is a single common treatment date.
- **`status`** — a per-row **0/1 treatment indicator** (`did_status_col`,
  `D_it`). The status must be **absorbing**: once an entity turns on it stays on
  (no switching back off). Use this when you already have the indicator built.

## Running it (API / GUI)

DID is driven through the **web UI** or the **`POST /runs`** API. The CLI
(`workbench run`) does **not** thread DID parameters today — it only exposes
`--y`, `--x`, `--mode`, `--model-type`, `--imputation` — so use the API or GUI
for DID. (CLI support for DID params is a possible follow-up.)

**GUI:** select model **Difference-in-Differences**, pick the **DID mode**, and
use the role controls to assign the entity, time, outcome, and the
mode-specific column(s) (cohort, or treat + post, or status).

**API (`POST /runs`, multipart form):** set `model_type=did`, `entity_col`,
`time_col`, `y`, and the DID fields for your mode:

| Mode | Form fields |
|------|-------------|
| `cohort` | `did_mode=cohort`, `did_cohort_col=<first-treat column>` |
| `two_by_two` | `did_mode=two_by_two`, `did_treat_col=<group>`, `did_post_col=<post>` |
| `status` | `did_mode=status`, `did_status_col=<0/1 D_it column>` |

## Reading the outputs

- **ATT** — the headline estimate (estimate / SE / p-value / confidence
  interval). This is the average effect on treated entity-periods.
- **Event study** — a coefficient per event time relative to treatment.
  **Pre-period leads ≈ 0** is the visual evidence *for* parallel trends;
  **post-period lags** trace the dynamic effect path (build-up, decay, etc.).
  The event study is **skipped / "not identified"** for a single cohort or when
  the reference period is absent (there is no clean baseline to difference
  against).
- **Parallel-trends test** — a joint F-test that all pre-treatment leads equal
  zero. **Rejected (`p < 0.05`) ⇒ the identifying assumption is suspect**: the
  groups were already diverging before treatment, so the ATT is unreliable.
- **Goodman-Bacon decomposition** — under staggered adoption, TWFE is a weighted
  average of all 2×2 comparisons, *including the forbidden "later-vs-earlier"
  comparisons that use already-treated units as controls*. A **high weight** on
  those forbidden comparisons means **TWFE may be biased** — prefer **Layer 2
  (Callaway-Sant'Anna)**. The decomposition requires a **balanced panel** and is
  **skipped otherwise**.

## The staggered-adoption caveat

When treatment timing varies across entities and effects are dynamic (change
over time since treatment), classic TWFE DID can be biased — the Goodman-Bacon
forbidden comparisons contaminate the estimate. Treat a high forbidden-weight as
a signal to move to **Layer 2 (Callaway-Sant'Anna)**, which estimates clean
group-time ATTs and aggregates them without the forbidden comparisons.

## Worked example

`examples/datasets/did_staggered_adoption.csv` is a 36-row simulated panel: six
entities (`A`–`F`) observed 2017–2022, with a constructed treatment effect of
**+2.0**. Two entities adopt in 2019, two in 2021, and two are never treated
(`first_treat = 0`). Set it up in **`cohort`** mode:

| Field | Value |
|-------|-------|
| model | Difference-in-Differences |
| DID mode | `cohort` |
| entity | `id` |
| time | `year` |
| y | `y` |
| cohort column | `first_treat` (never-treated = `0`) |

Because two distinct adoption cohorts (2019, 2021) coexist, the event study is
identified and the Goodman-Bacon decomposition runs (the panel is balanced). The
ATT should land near the constructed **+2.0**, the pre-period leads should sit
near zero (parallel trends not rejected), and the Goodman-Bacon output lets you
inspect how much weight the forbidden later-vs-earlier comparisons carry.
