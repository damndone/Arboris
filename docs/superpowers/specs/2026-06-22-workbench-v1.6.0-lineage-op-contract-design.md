# Workbench v1.6.0 — Lineage Operation Layer, Slice 1: the editable-op backend contract

> **Date:** 2026-06-22
> **Status:** Design approved (brainstorm), pending spec review → writing-plans
> **Base:** origin/main `1f1bc8f` (tag `v1.5.9`)
> **Worktree/branch:** `.worktrees/workbench-v1.6.0` / `workbench-v1.6.0`
> **Program:** v1.6 = lineage-graph operation layer (multi-version). This spec is **Slice 1** only.
> Agent Harness shifts to v1.7 (was V1.6). This slice is the Agent Harness prerequisite.

## One-line definition

**Slice 1 delivers the "editable-op backend contract": every editable node can be
resolved to a schema, can produce a new immutable run via overrides while preserving
lineage; execution is still a full re-run, UI and incremental execution are deferred.**

---

## 1. Background & motivation

### 1.1 The north-star (handoff `prototype.html`, v0.1 2026-05-22)

The original design treats **every DAG node as an editable operator**, not just the
model. Each node carries `{op, editable_schema, code}`; the interaction loop is:

> edit a node's op-controls (or its Python `code`) → "提交并重跑" → **rerun from that
> node downstream**, streaming to a run-log terminal; plus node-scoped AskAI and a
> cite-chip report composer.

`uiux/augment.js` attaches a per-node `editable` schema (e.g. `clean_winsorize` →
method radio + lower/upper sliders; `model_ols` → SE select + formula + interactions
toggle). The prototype's `handleRerun` is a **log simulation** — it executes nothing.

### 1.2 The gap to current reality (verified at `1f1bc8f`)

1. **Nodes are records, not re-executable parameterized operators.** The backend is a
   *linear, atomic 16-stage pipeline* (`orchestrator.PIPELINE`); the lineage graph is an
   *output artifact* (`graph.json`, served by `GET /runs/{id}/graph`). There is no
   per-node `op` you can `PATCH` and re-run from.
2. **Only model + imputation inputs are user-parameterized today.** Winsorize
   thresholds, log/sqrt choice, age-bin method (editable in the prototype) are **not
   backend inputs** — those stages auto-decide and record a `decision`. Making them
   editable = expanding each stage's input surface (future per-stage work).
3. **No mutation surface, no input persistence, no rerun.** Routes are read/create only
   (`/capabilities`, `/runs`, `/runs/batch`, `/runs/{id}`, artifacts, `/report`,
   `/graph`, `/events`). No `/runs/{id}/rerun`, no `/llm`. The run manifest persists only
   `y`/`x`/`requested_model_type`/`mode`/`lineage`/`model_routing` — **not** the full
   input bag, so a rerun cannot reconstruct inputs.
4. **The FE op surface is scaffolded but empty.** `actionRegistry.ts` has
   `rerunFromNode`/`askAiAboutNode`/`rerun` registered **disabled** ("lands in V1.5.3");
   `OperationSection.tsx` renders `node.editableSchema` **read-only**, but **nothing ever
   populates `editableSchema`**. `GraphViewNode.editableSchema` (and the OpenAPI
   `Node.editable_schema`) have been declared-but-empty since V1.5.2.

Full Vision 2 (every op editable + incremental hash-skip rerun + node-edit UI + AI proxy
+ report composer + sandboxed code execution) is the largest architectural program in the
project's history. Doing it big-bang would shred golden, violating the standing roadmap
law *"incremental, do-it-where-you-work, never big-bang."*

### 1.3 What Slice 1 does

Lay the **contract foundation at op-node granularity** (so it grows cleanly toward
per-op editing + incremental execution), honest about which nodes are editable on day one
(**only `model` and `imputation`** — the nodes already backed by real inputs). No graph
UI, no AI, no incremental execution in this slice. The hard constraint
(**manifest-driven, never per-estimator**) is honored: the operation layer reads a
manifest and contains zero per-estimator branches.

---

## 2. Scope

### 2.1 In scope (A + B + C)

- **A. Op editable-schema manifest** — `capabilities.py` declares, per editable op, the
  `editable_schema` (fields the backend genuinely consumes) + a top-level
  `editable_stages` list. `schema_version` 2→3.
- **B. Run-input persistence** — each run writes `run_inputs.json` (full form bag +
  upload pointer + lineage fields), written outside the engine (golden-safe).
- **C. Generic node-rerun endpoint** — `POST /runs/{run_id}/rerun` with
  `{from_node, op_overrides}` → structural validation against the manifest → new
  immutable run (`rerun_of` parent), reuses the parent upload, full-pipeline re-execution.
- **Serve-layer `editable_schema` annotation** — `GET /runs/{id}/graph` decorates
  editable nodes at response time (never written back to `graph.json`).

### 2.2 Explicitly out of scope (deferred roadmap)

Each is its own future version (incremental, golden-safe, never big-bang):

1. **Graph node-edit UI** (next slice) — make `OperationSection` editable + light up
   `rerunFromNode`, consuming `editable_schema`, calling `/rerun`.
2. **Per-stage op parameterization** — winsorize/log/bin become editable (one version per
   stage; expands each stage's input surface).
3. **Incremental / hash-skip execution** — `from_node`-downstream + `inputs_hash`
   memoization (a performance version with its own benchmark baseline).
4. **AI backend proxy** — `/llm` backend-proxied, audited to an `llm_call` store, token
   budgets (the prototype's direct `window.claude` call is non-compliant per handoff §7).
5. **Code-edit execution** — sandbox for user-edited Python (Pyodide/docker; handoff
   §10.1 known gap; far future).
6. **Report composer** (cite-chip traceability) + **concurrency lift** (multi run-slot;
   prerequisite for multi-node rerun) + **permission matrix**.

---

## 3. Design

### 3.1 A — the op editable-schema manifest

Extend each `MODEL_UI_META` entry in `backend/workbench/engine/capabilities.py` with a
`params` list whose items mirror the FE `EditableControl`
(`key`/`kind`/`label`/`options`/`required`/`role`/`value`). Add a top-level
`editable_stages` list. Bump `schema_version` 2→3.

```python
"iv_2sls": {
  "label": "IV / 2SLS", "group": "IV", "requires": ["endog", "instruments"],
  "params": [
    {"key": "model_type",     "kind": "select",  "label": "Model",       "role": "model"},
    {"key": "iv_endog",       "kind": "columns", "label": "Endogenous",  "required": True, "role": "endog"},
    {"key": "iv_instruments", "kind": "columns", "label": "Instruments", "required": True, "role": "instruments"},
    {"key": "covariance",     "kind": "select",  "label": "Covariance",  "options": [...], "value": "robust"},
  ],
}
```

Manifest top-level adds:

```python
"editable_stages": ["model", "imputation"],
```

**Field descriptor carries only what STRUCTURAL validation needs:** `key` (the exact
`POST /runs` form-param name), `kind`/type, `options` (enum), `required`, `role` (for
column-binding fields). **No business rules** — those stay in the pipeline.

**Honesty constraint:** the schema lists **only fields the backend genuinely consumes**
(`model_type`, `covariance`, role/param fields per `model_type`, imputation `method`). The
prototype's `formula` textarea / `interactions` toggle / winsorize sliders are **NOT**
included — they require per-stage backend support (future slices).

`common_params` (top-level) holds fields shared by every model (`y`, `x`, `model_type`,
`mode`, `imputation`); per-model `params` hold estimator-specific fields.

**Extensibility invariant:** adding a future estimator = declare its handler + its
`params` *in the same place you already declare `label`/`group`/`requires`*. The operation
layer never changes.

### 3.2 Node → op_type → schema resolution (manifest-driven)

A small resolver maps a graph node to its op-type and thus its schema, with **zero
per-estimator branches**:

- `stage == "model"` → `op_type` = the run's `effective_model_type` (read from
  `run_manifest.model_routing.effective_model_type`) → schema =
  `MODEL_UI_META[op_type]["params"]`.
- imputation node → schema = the manifest's `imputation_methods`.

day-1 only these two stages have a resolver entry. **Adding an editable stage = add one
resolver entry + one manifest schema.** The control `key` *is* the `POST /runs`
form-param name, so the node→param mapping is the schema's keys — no separate mapping
table.

The resolver is **defensive**: it only resolves nodes that exist in the run's graph and
whose op-type is resolvable; otherwise the node is treated as non-editable.

### 3.3 B — run-input persistence (`run_inputs.json`)

Written by `api.py` at run creation (in the `POST /runs` path, **outside the engine** →
golden untouched):

```json
{
  "schema_version": 1,
  "form": { "model_type": "...", "y": "...", "x": "a,b", "covariance": "robust",
            "iv_endog": "[...]", "...": "... full POST /runs form bag, verbatim ..." },
  "upload": { "path": "_uploads/foo.csv", "filename": "foo.csv", "sha256": "<hex>" },
  "rerun_of": null,
  "from_node": null
}
```

- `form` is a **generic dict** (form-param name → value), not a per-estimator typed
  structure → honors the constraint; a new estimator's params land here automatically.
- **Guardrail #1 — secret redaction:** persistence runs through a **redact/allowlist
  pass**. Today the form bag has no secrets, but the layer is built so any future API
  key / connection string is stored as a reference or `***`, never raw.
- `upload.sha256` is computed at create time and recorded (consumed by the rerun
  guardrail below).
- `rerun_of` also added to `run_manifest.json` (lineage).

### 3.4 C — generic node-rerun endpoint

`POST /runs/{run_id}/rerun`, body `{ from_node: str, op_overrides: object }`:

1. **Validate `from_node`** (Guardrail #6): it MUST exist in the parent run's graph node
   set → else `422` (no arbitrary strings).
2. Read parent `run_inputs.json` → base `form` bag + `upload` pointer.
3. Resolve `from_node`'s `op_type` → manifest schema (§3.2).
4. **Schema-switching order (Guardrail #4):** if `op_overrides` includes `model_type`,
   take the **new** model's schema first; then validate required keys against
   *(parent form bag + overrides)* under the **new** schema. Never block a switch with the
   old schema.
5. **Layer-1 structural validation (Guardrail #3):** `op_overrides` keys ⊆ schema keys;
   type / enum / required checks. **Only manifest structure** — never replicate estimator
   validators here.
6. Shallow-merge `op_overrides` onto the base `form` bag (keys = form-param names).
7. **Upload reuse (Guardrail #2 + #5):** reuse **only** the parent's recorded `upload.path`
   (body may NOT supply a new path — no cross-run path injection). Recompute the file's
   sha256 and compare against the recorded `upload.sha256`; mismatch → **fail loud**
   (`422`), do not silently reuse a changed file.
8. Acquire the run slot; busy → `429` (same as create; concurrency lift deferred).
9. Create a **new immutable run**: `rerun_of` = parent, `from_node` recorded, copy the
   parent upload into the new run's `_uploads`, write a new `run_inputs.json`.
10. Dispatch via the **same `_bg_run` path** as `POST /runs` — extracted into a shared
    helper `_submit_run(form_bag, upload_path, root, *, rerun_of, from_node)` so create and
    rerun share ONE dispatch path (zero duplication, zero per-estimator code).
11. **Full-pipeline re-execution.** `from_node` is recorded only (addressing + lineage +
    forward-compat for incremental); execution re-runs the whole pipeline. Incremental
    hash-skip is a deferred performance slice.
12. **Layer-2 semantic validation stays in the pipeline:** column existence, estimability,
    role conflicts → structured `MODEL_FIT_FAILED` as today.

Response mirrors `POST /runs`: `{ run_id, status }`.

### 3.5 Serve-layer `editable_schema` annotation

`GET /runs/{id}/graph` decorates the response **at read time**:

- For each node whose `stage ∈ editable_stages` and whose op-type resolves (§3.2):
  set `editable: true` and `editable_schema` (the resolved manifest schema, with current
  values filled from the run's `run_inputs.json`).
- **Guardrail #7 — response-time only:** the decoration is NEVER written back to
  `graph.json` or any engine artifact. The engine's `graph.json` (golden) stays
  byte-identical.

This finally populates the long-dormant `GraphViewNode.editableSchema` /
OpenAPI `Node.editable_schema` field. The next slice's graph edit UI consumes it directly;
the rerun endpoint validates against the same manifest schema.

---

## 4. Guardrails (consolidated)

| # | Guardrail | Where |
|---|---|---|
| 1 | `run_inputs.json` redacts secrets (allowlist/reference, never raw) | §3.3 |
| 2 | rerun verifies upload `sha256`; mismatch → fail loud | §3.4.7 |
| 3 | two-layer validation: manifest structural here, semantic in pipeline | §3.4.5/12 |
| 4 | `model_type` schema-switching order (new schema first) | §3.4.4 |
| 5 | no cross-run path injection: reuse only parent-recorded upload path | §3.4.7 |
| 6 | `from_node` must exist in parent run's graph node set, else 422 | §3.4.1 |
| 7 | serve-layer decorate only; never write `editable_schema` to artifacts | §3.5 |

---

## 5. Testing & gates

**Gate:** `./scripts/gate.sh` green. **golden 0-drift is a hard gate** (engine unchanged;
`run_inputs.json` + serve-layer annotation are outside the engine). Manifest change goes
through **4-way sync (G0-5):** backend key (`params` / `editable_stages`) / drift-guard /
FE `Capabilities` type / contract schema+sample; `schema_version` 2→3.

**New tests (wiring tests must go red if wiring deleted — G0-3):**

- manifest `params` + `editable_stages` shape/presence; `schema_version == 3`.
- `run_inputs.json` written on create; redaction pass applied.
- node→op_type→schema resolver (model node by `effective_model_type`; imputation node;
  non-editable / unresolvable node → not annotated).
- serve-layer graph annotation: editable nodes get `editable:true`+`editable_schema`;
  non-editable nodes untouched; `graph.json` artifact byte-identical (no write-back).
- rerun round-trip: override takes effect, new run created, `rerun_of` set, parent upload
  reused.
- structural validation rejects unknown key / wrong type / bad enum / missing required.
- **schema-switching order**: `model_type` switch validates against the NEW model schema.
- **sha256 mismatch → fail loud (422)**; body-supplied upload path rejected.
- **`from_node` not in parent graph → 422.**
- busy slot → 429.
- semantic failure still surfaces as `MODEL_FIT_FAILED` from the pipeline (boundary proof).

---

## 6. File touch list (anticipated)

- `backend/workbench/engine/capabilities.py` — `params`, `editable_stages`, `schema_version` 3.
- `backend/workbench/api.py` — write `run_inputs.json` on create; `POST /runs/{id}/rerun`;
  `_submit_run` shared helper; serve-layer graph annotation.
- `backend/workbench/orchestrator/_manifest.py` — `rerun_of` in manifest; sha256 capture.
- New module(s): node→op resolver; `run_inputs.json` read/write + redaction.
- `frontend/src/capabilities/types.ts` — `Capabilities` type: `params`, `editable_stages`
  (type sync only; RunForm unchanged, no new UI this slice).
- `tests/contracts/` — capabilities schema + sample bump (schema_version 3).
- New backend test files for the above.
- `docs/` — release notes / impl notes.

## 7. Non-goals / risks

- **Not** turning the pipeline into a persistent editable-operator DAG (that's the
  multi-version program; Slice 1 is the contract substrate only).
- **Not** executing partial/incremental runs — full re-run keeps complexity down and is
  honest about current execution semantics.
- Risk: a graph snapshot/contract test may assert the served graph shape — handle the new
  `editable`/`editable_schema` fields additively and intentionally; the **engine**
  `graph.json` golden must remain byte-identical (verifies Guardrail #7).
