# v1.8.1 Devline Consolidation Record

Date: 2026-07-24
Author: Claude (integration owner for the v1.8.1 correctness work)
Scope of this document: **records only** — it reconciles the three `.agent/devlines`
records that accumulated on the v1.8.1 integration effort. No source code and no
other session's uncommitted work is touched by writing this record.

## Conclusion up front

There is **one** legitimate development line, and it is already linear:

- **Git:** branch `integration/v1.8.1`, HEAD `e0f2094`. Every committed change
  for v1.8.1 sits on this single branch; `git log --all` has no commit after
  `e0f2094` (no divergent branch anywhere).
- The three devline *records* below are **sequential phases of that one line**,
  not competing lines. Their frozen baselines are nested ancestors of HEAD:
  `d26d079` → `dd3d2b7` → `51377a8` → `9a8a947` → `d010438` → `e0f2094`.

Nothing needed to be "merged" or "ported": the newest devline
(`v181-agent-surface-polish`) was frozen at `e0f2094`, which is the tip of all
prior work, so it already builds on 100% of it.

## The three devline records

| Devline | Frozen baseline | Owner | Status | Git record | Events |
|---|---|---|---|---|---|
| `v181-notebook-wave` | `d26d079` (07-22 19:19) | Claude | Committed through `e0f2094`; last state `CONTEXT_RESCOPED` | tracked (has uncommitted rescope on top) | 92 |
| `dc-evolution` | `dd3d2b7` (07-22 19:42) | Claude | Code committed in `9a8a947` (E1–E4, WIP); devline is a stub | tracked | 1 (`line_started`) |
| `v181-agent-surface-polish` | `e0f2094` (07-23 23:59) | Codex | Active, **uncommitted** working-tree edits | untracked | 5 |

### Phase 1 — `v181-notebook-wave` (foundation, Claude)
- **Purpose:** Gate 4/5/6 Graph-first Notebook (Option lifecycle, Execution &
  Artifact Contract, selected-text), plus the Context Compiler and Core Trace
  wiring and the ETS model pack, under ADR-PD-001.
- **Landed as commits:** `51377a8` (wave), `d010438` (review fixes F-6/F-7).
- **Scope (affected paths):** `backend/workbench/agent/notebook`,
  `contracts/agent/notebook_option.py`, `contracts/model/ets.py`,
  `agent/context_compiler.py`, `agent/trace.py`, `engine/packs/ets`,
  `services/draft_*`, `http/notebook_routes.py`, `frontend/src/notebook`,
  `frontend/src/pipelineDrafts`, `tests/**/notebook*`, `tests/evaluation/v181`, …
- **Note:** Codex later `rescope`d this line to add agent-surface files as
  *allowed paths* (see the overlap note below). Those two rescope events are
  uncommitted and belong to Codex's work, not to Phase 1.

### Phase 2 — `dc-evolution` (governance layer, Claude)
- **Purpose:** make the Failure-Memory / Development-Control systems evolve, not
  just record (E1 gate-refuses-uncovered-work, E2 severity surfacing, E3
  efficacy feedback, E4 enabled-rule markers).
- **Landed as commit:** `9a8a947` (marked **WIP** — the E1/E4 wiring into
  `scripts/gate.sh` is implemented and unit-tested but not yet connected in the
  gate script).
- **Scope (affected paths):** `backend/workbench/development_control/`,
  `scripts/gate.sh`, `scripts/devline_control.py`.
- **Record status:** the devline itself only carries `line_started`; the work
  events were never appended to it. Treat the commit `9a8a947` and its tests as
  the authoritative record; the devline is a stub.

### Phase 3 — `v181-agent-surface-polish` (UI layer, Codex — ACTIVE)
- **Purpose:** restyle the Workbench Agent surface to match a Codex composer
  reference while preserving the typed-proposal / fail-closed boundaries
  (see `docs/superpowers/specs/2026-07-24-v1.8.1-agent-surface-polish-design.md`).
- **State:** uncommitted working-tree edits (~30 files: `AgentComposer`,
  `AgentPanel`, `AgentCapabilityPopover`, `agent.css`, `GraphView`,
  `GraphCanvas`, `RunHistoryRail`, `BottomPanel`, `App.tsx`, `agent_routes.py`,
  `test_agent_routes.py`, …). Frozen baseline `e0f2094`.
- **Disjoint from Phases 1–2:** it touches none of the files changed by the
  notebook wave, the F-6/F-7 fixes, or the dc-evolution work. No conflict, no
  revert — purely additive on top of `e0f2094`.

## Relationships (one line, three phases)

```
integration/v1.8.1 (single branch)
 d26d079  ── Phase 1 baseline (v181-notebook-wave)
   │  51377a8  Notebook wave
 dd3d2b7  ── Phase 2 baseline (dc-evolution)
   │  9a8a947  dc-evolution E1–E4 (WIP)
   │  d010438  Notebook review fixes F-6/F-7
 e0f2094  ── Phase 3 baseline (v181-agent-surface-polish)  ==  HEAD
   └─ Codex agent-surface edits (uncommitted, active)
```

- Phases 1 and 2 are **complete and committed**.
- Phase 3 is **in progress** on top of them; it is the current active phase.
- There is no second line to reconcile — the appearance of "another line" was
  Codex correctly starting Phase 3 from the tip of Phases 1–2.

## Overlap to clean up (for whoever owns Phase 3)

Codex recorded its agent-surface work in **two** places:
1. by `rescope`-ing `v181-notebook-wave` to allow the agent-surface files, and
2. by creating the separate `v181-agent-surface-polish` line (scoped to
   `frontend/src/workbench/views/GraphView.tsx`).

Recommendation (a Phase-3 decision, not made here): keep the agent-surface work
under **one** devline — either finish it under `v181-agent-surface-polish` with
its affected-path scope widened to the files actually edited, or under the
rescoped `v181-notebook-wave` — and drop the duplicate framing in the other, so
the FMS record for Phase 3 has a single owner and scope.

## What this record does and does not do

- **Does:** state the single canonical line, map the three devlines to three
  sequential phases, and record their baselines, owners, scopes, and status.
- **Does not:** modify any source file, append events to any devline (in
  particular it does not touch Codex's active `v181-agent-surface-polish` chain
  or the uncommitted rescope on `v181-notebook-wave`), or move Phase-3 work.
