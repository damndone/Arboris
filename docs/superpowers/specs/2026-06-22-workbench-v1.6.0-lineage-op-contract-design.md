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

## North-star framing

The lineage graph is **not a visualization DAG**. It is an **immutable-run +
editable-operation operating system**. Slice 1 lays the spine:

```text
Upload (content-addressable, by sha256)
  │
  ▼
Immutable Run ──────────────► Lineage Graph
  │                                  │
  │                                  ▼
  │                        Editable Operation Node  (stage → op_type → schema_id)
  │                                  │
  │                                  ▼
  │                          Override Contract  (op_overrides + override_hash)
  │                                  │
  ▼                                  ▼
Immutable Child Run  ◄──── rerun_of / from_node / rerun_reason
  │
  ▼
Future slices: Incremental Execution · AI Agent (v1.7) · Report Composer · Code Sandbox
```

Everyone downstream (including the v1.7 AI agent) addresses nodes by **`node_id` +
`op_type` + `schema_id`** — never by label/title/display name.

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
  `editable_stages` list, each schema carrying a stable `schema_id`.
- **B. Run-input persistence + content-addressable uploads** — each run writes
  `run_inputs.json` (full form bag, addressed-by-sha256 upload, lineage fields), written
  outside the engine (golden-safe); uploads live in a content-addressable store.
- **C. Generic node-rerun endpoint** — `POST /runs/{run_id}/rerun` with
  `{from_node, op_overrides, rerun_reason}` → structural validation against the manifest →
  new immutable run (`rerun_of` parent), reuses the parent upload by sha256, full-pipeline
  re-execution.
- **Serve-layer `editable_schema` annotation** — `GET /runs/{id}/graph` decorates
  editable nodes at response time (never written back to `graph.json`).

### 2.2 Explicitly out of scope (deferred roadmap)

Each is its own future version (incremental, golden-safe, never big-bang):

1. **Graph node-edit UI** (next slice) — make `OperationSection` editable + light up
   `rerunFromNode`, consuming `editable_schema`, calling `/rerun`.
2. **Per-stage op parameterization** — winsorize/log/bin become editable (one version per
   stage; expands each stage's input surface).
3. **Incremental / hash-skip execution** — `from_node`-downstream + `inputs_hash`
   memoization, keyed by `cache_key = (parent_run, from_node, override_hash)` (a
   performance version with its own benchmark baseline). The `override_hash` contract is
   defined now (§3.4) but caching is NOT implemented in Slice 1.
4. **AI backend proxy** — `/llm` backend-proxied, audited to an `llm_call` store, token
   budgets (the prototype's direct `window.claude` call is non-compliant per handoff §7).
   Reuses the `rerun_reason="ai_suggestion"/"agent_execution"` lane defined now.
5. **Code-edit execution** — sandbox for user-edited Python (Pyodide/docker; handoff
   §10.1 known gap; far future).
6. **Report composer** (cite-chip traceability) + **concurrency lift** (multi run-slot;
   prerequisite for multi-node rerun) + **permission matrix**.

---

## 3. Design

### 3.0 Version axes (three independent, never one number for all)

| Axis | Field | Slice-1 value | Governs |
|---|---|---|---|
| Capabilities manifest | `capabilities_schema_version` | `3` | shape of `/capabilities` |
| Run-input record | `run_input_schema_version` | `1` | shape of `run_inputs.json` |
| Per-op schema | `schema_id = "{op_type}@v{n}"` | e.g. `iv_2sls@v1` | a single op's editable schema |

These evolve independently: a single op's schema can bump `@v2` without touching the
capabilities or run-input versions.

### 3.1 A — the op editable-schema manifest

Extend each `MODEL_UI_META` entry in `backend/workbench/engine/capabilities.py` with a
`params` list whose items mirror the FE `EditableControl`
(`key`/`kind`/`label`/`options`/`required`/`role`/`value`), plus a per-op `schema_id`. Add
a top-level `editable_stages` list. Rename `schema_version` → `capabilities_schema_version`
and bump to `3`.

```python
"iv_2sls": {
  "label": "IV / 2SLS", "group": "IV", "requires": ["endog", "instruments"],
  "schema_id": "iv_2sls@v1",
  "params": [
    {"key": "model_type",     "kind": "select",  "label": "Model",       "role": "model"},
    {"key": "iv_endog",       "kind": "columns", "label": "Endogenous",  "required": True, "role": "endog"},
    {"key": "iv_instruments", "kind": "columns", "label": "Instruments", "required": True, "role": "instruments"},
    {"key": "covariance",     "kind": "select",  "label": "Covariance",  "options": [...], "value": "robust"},
  ],
}
```

Manifest top-level adds `"editable_stages": ["model", "imputation"]`.

**Field descriptor carries only what STRUCTURAL validation needs:** `key` (the exact
`POST /runs` form-param name), `kind`/type, `options` (enum), `required`, `role`. **No
business rules** — those stay in the pipeline.

**Honesty constraint:** the schema lists **only fields the backend genuinely consumes**
(`model_type`, `covariance`, role/param fields per `model_type`, imputation `method`). The
prototype's `formula` / `interactions` / winsorize sliders are **NOT** included — they
require per-stage backend support (future slices).

`common_params` (top-level) holds fields shared by every model (`y`, `x`, `model_type`,
`mode`, `imputation`); per-model `params` hold estimator-specific fields.

**Extensibility invariant:** adding a future estimator = declare its handler + its
`params`/`schema_id` *in the same place you already declare `label`/`group`/`requires`*.
The operation layer never changes.

### 3.2 Node → op_type → schema resolution (manifest-driven, label-free)

A small resolver maps a graph node to its op-type/schema, with **zero per-estimator
branches**, addressing strictly by `node_id`/`stage`/`op_type` — **never label/title**:

- `stage == "model"` → `op_type` = the run's `effective_model_type` (read from
  `run_manifest.model_routing.effective_model_type`) → schema =
  `MODEL_UI_META[op_type]["params"]`, `schema_id = MODEL_UI_META[op_type]["schema_id"]`.
- imputation node → `op_type = "imputation"`, schema = the manifest's `imputation_methods`,
  `schema_id = "imputation@v1"`.

day-1 only these two stages have a resolver entry. **Adding an editable stage = add one
resolver entry + one manifest schema.** The control `key` *is* the `POST /runs` form-param
name, so the node→param mapping is the schema's keys — no separate mapping table.

The resolver is **defensive**: it only resolves nodes that exist in the run's graph and
whose op-type is resolvable; otherwise the node is non-editable.

### 3.3 B — run-input persistence + content-addressable uploads

**Content-addressable upload store (MUST).** Upload lifecycle ≠ run lifecycle. At
`POST /runs`, the uploaded file is stored by content hash, e.g.:

```text
<project_root>/data/uploads/<sha256>            # blob, content-addressed
```

`run_inputs.json` references the upload **by sha256 only — never by path** (a rename or a
parent-run deletion must not break a rerun). A sha256→blob resolver maps the hash to the
on-disk blob.

`run_inputs.json` (written by `api.py` at run creation, **outside the engine** → golden
untouched):

```json
{
  "run_input_schema_version": 1,
  "form": { "model_type": "...", "y": "...", "x": "a,b", "covariance": "robust",
            "iv_endog": "[...]", "...": "... full POST /runs form bag, verbatim ..." },
  "upload": { "sha256": "<hex>", "filename": "foo.csv" },
  "rerun_of": null,
  "from_node": null,
  "rerun_reason": "initial",
  "override_hash": null
}
```

- `form` is a **generic dict** (form-param name → value), not a per-estimator typed
  structure → a new estimator's params land here automatically.
- **Guardrail #1 — secret redaction:** persistence runs through a **redact/allowlist
  pass**. Today the form bag has no secrets, but the layer is built so any future API key /
  connection string is stored as a reference or `***`, never raw.
- `rerun_of` also added to `run_manifest.json` (lineage).
- `rerun_reason` enum (SHOULD): `initial` | `manual_override` | `ai_suggestion` |
  `batch_experiment` | `template_apply` | `agent_execution`. Initial runs = `initial`;
  reruns default `manual_override`. Paves the v1.7 agent lane.
- `override_hash` (SHOULD): on a rerun, `sha256` of the canonicalised `op_overrides`
  (sorted keys, normalised values). `null` on initial runs. Defines the future hash-skip
  `cache_key`; **caching not implemented in Slice 1.**

### 3.4 C — generic node-rerun endpoint

`POST /runs/{run_id}/rerun`, body `{ from_node: str, op_overrides: object,
rerun_reason?: str }`:

1. **Validate `from_node`** (Guardrail #6): MUST exist in the parent run's graph node set
   → else `422` (no arbitrary strings).
2. Read parent `run_inputs.json` → base `form` bag + `upload.sha256`.
3. Resolve `from_node`'s `op_type` → manifest schema + `schema_id` (§3.2).
4. **Schema-switching order (Guardrail #4):** if `op_overrides` includes `model_type`,
   take the **new** model's schema first; then validate required keys against
   *(parent form bag + overrides)* under the **new** schema. Never block a switch with the
   old schema.
5. **Layer-1 structural validation (Guardrail #3):** `op_overrides` keys ⊆ schema keys;
   type / enum / required checks. **Only manifest structure** — never replicate estimator
   validators here.
6. Compute `override_hash` = sha256 of canonicalised `op_overrides`.
7. Shallow-merge `op_overrides` onto the base `form` bag (keys = form-param names).
8. **Upload reuse (Guardrails #2 + #5):** resolve the parent's `upload.sha256` against the
   content-addressable store. The body **cannot** supply a path or sha256 (no field exists
   → cross-run injection is structurally impossible). Re-verify the blob's content hashes
   to its key; mismatch → **fail loud** (`422`), do not silently reuse a corrupted blob.
9. Acquire the run slot; busy → `429` (concurrency lift deferred).
10. Create a **new immutable run**: `rerun_of` = parent, `from_node` recorded,
    `rerun_reason` (default `manual_override`), `override_hash` recorded; write a new
    `run_inputs.json` referencing the SAME upload sha256 (no copy needed — content-addressed).
11. Dispatch via the **same `_bg_run` path** as `POST /runs` — extracted into a shared
    helper `_submit_run(form_bag, upload_sha256, root, *, rerun_of, from_node, rerun_reason,
    override_hash)` so create and rerun share ONE dispatch path (zero duplication, zero
    per-estimator code).
12. **Full-pipeline re-execution.** `from_node` is recorded only (addressing + lineage +
    forward-compat for incremental); execution re-runs the whole pipeline. Incremental
    hash-skip is a deferred performance slice.
13. **Layer-2 semantic validation stays in the pipeline:** column existence, estimability,
    role conflicts → structured `MODEL_FIT_FAILED` as today.

Response mirrors `POST /runs`: `{ run_id, status }`.

### 3.5 Serve-layer `editable_schema` annotation

`GET /runs/{id}/graph` decorates the response **at read time**:

- For each node whose `stage ∈ editable_stages` and whose op-type resolves (§3.2), set:
  ```json
  { "node_id": "model_ols", "stage": "model", "op_type": "ols", "schema_id": "ols@v1",
    "editable": true, "editable_schema": [ ... ],
    "editable_schema_source": "capabilities" }
  ```
  `editable_schema` values are filled from the run's `run_inputs.json`.
- `editable_schema_source` (SHOULD): provenance marker for debug; future values
  `capabilities` | `agent` | `user-template`.
- **Guardrail #7 — response-time only:** the decoration is NEVER written back to
  `graph.json` or any engine artifact. The engine's `graph.json` (golden) stays
  byte-identical.

This finally populates the long-dormant `GraphViewNode.editableSchema` /
OpenAPI `Node.editable_schema` field. The next slice's graph edit UI consumes it directly;
the rerun endpoint validates against the same manifest schema.

---

## 4. Lineage DAG invariants (normative)

The run-lineage graph is a **forest of immutable runs** and MUST satisfy:

1. **Append-only.** Runs are never mutated after creation; a rerun never touches its
   parent.
2. **Exactly one child per rerun.** Each `POST /runs/{id}/rerun` creates exactly one new
   run with `rerun_of` = the parent.
3. **At most one parent.** Each run has zero (`initial`) or one (`rerun_of`) parent.
4. **Acyclic.** `A → B → A` is forbidden. Structurally guaranteed: a child is created
   *after* its parent and points *backwards* via `rerun_of`, so no run can become its own
   ancestor. `A → B`, `A → C` (siblings) is allowed.

These invariants are what make the lineage graph an operating system rather than a
mutable workflow.

---

## 5. Guardrails (consolidated)

| # | Guardrail | Where |
|---|---|---|
| 1 | `run_inputs.json` redacts secrets (allowlist/reference, never raw) | §3.3 |
| 2 | rerun re-verifies upload blob content hash; mismatch → fail loud | §3.4.8 |
| 3 | two-layer validation: manifest structural here, semantic in pipeline | §3.4.5/13 |
| 4 | `model_type` schema-switching order (new schema first) | §3.4.4 |
| 5 | no cross-run injection: upload addressed by parent sha256 only, no path/sha256 in body | §3.4.8 |
| 6 | `from_node` must exist in parent run's graph node set, else 422 | §3.4.1 |
| 7 | serve-layer decorate only; never write `editable_schema` to artifacts | §3.5 |

---

## 6. Testing & gates

**Gate:** `./scripts/gate.sh` green. **golden 0-drift is a hard gate** (engine unchanged;
`run_inputs.json`, content-addressable uploads, and serve-layer annotation are all outside
the engine). Manifest change goes through **4-way sync (G0-5):** backend key (`params` /
`editable_stages` / `schema_id`) / drift-guard / FE `Capabilities` type / contract
schema+sample; `capabilities_schema_version` 2→3.

**New tests (wiring tests must go red if wiring deleted — G0-3):**

- manifest `params` + `editable_stages` + per-op `schema_id` shape;
  `capabilities_schema_version == 3`.
- content-addressable upload: create stores blob by sha256; `run_inputs.json` references
  by sha256 only (no `path` field); `run_input_schema_version == 1`; redaction applied.
- node→op_type→schema resolver (model node by `effective_model_type`; imputation node;
  non-editable / unresolvable node → not annotated); addressing never uses label.
- serve-layer graph annotation: editable nodes get
  `editable`/`editable_schema`/`schema_id`/`editable_schema_source`; non-editable nodes
  untouched; **`graph.json` artifact byte-identical** (no write-back).
- rerun round-trip: override takes effect, new run created, `rerun_of` set, parent upload
  reused by sha256, `override_hash` + `rerun_reason` recorded.
- structural validation rejects unknown key / wrong type / bad enum / missing required.
- **schema-switching order**: `model_type` switch validates against the NEW model schema.
- **upload blob hash mismatch → fail loud (422)**; rerun body cannot carry path/sha256.
- **`from_node` not in parent graph → 422.**
- busy slot → 429.
- semantic failure still surfaces as `MODEL_FIT_FAILED` from the pipeline (boundary proof).
- **DAG invariants**: rerun does not mutate the parent run's artifacts; child carries
  exactly one `rerun_of`.

---

## 7. File touch list (anticipated)

- `backend/workbench/engine/capabilities.py` — `params`, `editable_stages`, per-op
  `schema_id`, `capabilities_schema_version` 3.
- `backend/workbench/api.py` — content-addressable upload store on create; write
  `run_inputs.json`; `POST /runs/{id}/rerun`; `_submit_run` shared helper; serve-layer
  graph annotation.
- `backend/workbench/orchestrator/_manifest.py` — `rerun_of` in manifest.
- New module(s): content-addressable upload store (sha256 read/write/resolve);
  `run_inputs.json` read/write + redaction; node→op resolver; override canonicalisation +
  hash.
- `frontend/src/capabilities/types.ts` — `Capabilities` type: `params`, `editable_stages`,
  `schema_id`, `capabilities_schema_version` (type sync only; RunForm unchanged, no new UI
  this slice).
- `tests/contracts/` — capabilities schema + sample bump (capabilities_schema_version 3).
- New backend test files for the above.
- `docs/` — release notes / impl notes.

## 8. Non-goals / risks

- **Not** turning the pipeline into a persistent editable-operator DAG (that's the
  multi-version program; Slice 1 is the contract substrate only).
- **Not** executing partial/incremental runs — full re-run keeps complexity down and is
  honest about current execution semantics.
- **Not** implementing the hash-skip cache — only the `override_hash`/`cache_key` contract
  is defined for a future perf slice.
- Risk: a graph snapshot/contract test may assert the served graph shape — handle the new
  `editable`/`editable_schema`/`schema_id` fields additively and intentionally; the
  **engine** `graph.json` golden must remain byte-identical (verifies Guardrail #7).
- Risk: content-addressable uploads change where `POST /runs` writes the upload — contained
  to the create path; existing pre-v1.6.0 runs are not retroactively rerunnable (acceptable;
  no migration).
