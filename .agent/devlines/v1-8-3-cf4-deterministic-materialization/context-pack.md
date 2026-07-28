# Frozen Context Pack

Line: `v1-8-3-cf4-deterministic-materialization`
Baseline SHA: `c0289afd460919397fc047274ad4b9248144e982`

## Objective
# Workbench v1.8.3 Execution Control Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` for the two independent lanes, or `executing-plans` when continuing one lane serially. Execute only one formal development line per worker.

**Goal:** Deliver the approved Capability Factory and opt-in two-layer domain memory with the fewest independently useful work units, while preserving isolation, reproducibility, statistical evidence, Graph-first execution, and user authorization.

**Architecture:** `B0` is the small authority/verifier trust core and `CORE` is the independent local identity foundation. After both are accepted into one clean foundation baseline, B1 native containment and CF1 resolution may proceed on disjoint paths; CF3 cannot start until both the capability path and B1 are accepted. One Memory worker may use the second slot whenever it does not displace a dependency-critical Capability task. The main agent alone integrates shared Trace, Context Compiler, application mounting, Notebook surface, and cross-lane acceptance.

**Tech Stack:** Python 3, FastAPI, append-only and content-addressed stores, existing Workbench Graph/Run/Artifact/Core Trace contracts, React/TypeScript, pytest, Vitest, browser QA, formal development-line CLI.

---

## 1. Planning authority and non-negotiable boundaries

These are the only retained human-facing implementation plans for v1.8.3:

- this execution-control plan;
- `2026-07-25-v1.8.3-capability-lane.md`;
- `2026-07-25-v1.8.3-memory-lane.md`.

Semantic authority remains:

- `docs/superpowers/specs/2026-07-25-v1.8.3-custom-capability-runtime-design.md`;
- `docs/superpowers/specs/2026-07-25-v1.8.3-capability-factory-design.md`;
- `docs/superpowers/specs/2026-07-25-v1.8.3-domain-memory-design.md`.

Design corrections through commit `ac93be4159a0fcf874dfe77884dc84fa1af6b272`
are incorporated into those live authority files; the files, not that historical commit, govern implementation.

Hard boundaries:

- Never dynamically install dependencies into the Workbench host environment.
- Never execute untrusted capability code with network, host filesystem, main-process, or user-file access.
- Never treat Python module privacy, canonical hashes, or B0 unit tests as native containment evidence.
- Never expose a product issuer, signer, test key, unsigned attestation path, or caller-controlled trust/eligibility constructor.
- Agent-authored self-tests are not independent evidence.
- Memory may affect retrieval and inspection plans only; it cannot raise evidence, change admission, select a unique winner, authorize, or run.
- Consumer support is explicit. A custom model never inherits OLS diagnostics, reports, plots, or comparison semantics by accident.
- Do not introduce exercise-specific names, dataset columns, fixed years, or hidden compatibility writes.
- Do not push, open a PR, merge, tag, promote, or release without explicit user authorization.

## 2. Real concurrency model

```text
Plan commit
   |
   +--> B0 verifier -------+
   |                       |
   +--> CORE identity -----+--> clean foundation baseline
                                  |
                                  +--> B1 native containment --------------------------+
                                  |                                                     |
                                  +--> Capability: CF1 -> CF2 ----------------+         |
                                  |                                           +--> CF3 -> CF3B -> CF4 --+
                                  +--> Memory: MEM1 -> MEM2 -> MEM3 -------------------------------+
                                                                                      |
                                                                                 Integration
```

Rules:

- Use at most two implementation subagents at once.
- A subagent must not create more subagents, broaden its allowlist, or edit another lane.
- B1 and CF1 may run in parallel only after B0 is frozen because they own disjoint packages and consume the same immutable attestation contracts.
- The Capability phases are serial because they share registry, stores, validity, evidence, and admission state.
- The Memory phases are serial because they share one candidate/content/approval store.
- CF3 waits for both accepted CF2 and accepted B1; no validation run may use a mock containment claim as product evidence.
- The main agent reviews focused test evidence and the exact diff at each line boundary.
- Accepted foundation and lane commits are combined locally in deterministic order by the main agent; no remote action is implied.

## 3. Shared integration seam

Lane workers must not modify these shared files:

- `backend/workbench/app.py`;
- `backend/workbench/agent/trace.py`;
- `backend/workbench/agent/context_compiler.py`;
- `frontend/src/notebook/NotebookSurface.tsx`;
- `frontend/src/notebook/notebook.css`.

They may implement and test unmounted route modules, package-local trace contracts, pure context projections, and independent UI components. The final Integration line owns:

- route and startup registration in `app.py`;
- registration of all package-local event catalogs in Core Trace;
- Context Compiler injection order, budgets, fallback, and provenance;
- mounting Capability and Memory UI into the shared Notebook surface;
- cross-lane contract locks, browser QA, full gate, and release-quality evidence.

## 4. Formal development-line sequence

| Wave | Line ID | Owner | Baseline requirement |
|---|---|---|---|
| 1 | `v1-8-3-b0-authority-verifier-core` | Capability worker | clean revised-plan commit |
| accepted | `v1-8-3-core1-local-identity` | Identity worker | retained accepted CORE1 commit |
| 2 | `v1-8-3-b1-native-containment` | Containment worker | clean B0 + CORE1 foundation baseline |
| 2 | `v1-8-3-cf1-capability-resolution` | Capability worker | same clean foundation baseline |
| 2 | `v1-8-3-cf2-dependency-bundles` | Capability worker | accepted CF1 |
| 3 | `v1-8-3-cf3-adapter-validation` | Capability worker | accepted CF2 plus accepted B1 |
| 3 | `v1-8-3-cf3b-bundle-admission` | Capability worker | accepted CF3 |
| 3 | `v1-8-3-cf4-model-custom-integration` | Capability worker | accepted CF3B |
| 2 | `v1-8-3-mem1-project-context-index` | Memory worker | clean foundation baseline |
| 2 | `v1-8-3-mem2-domain-memory` | Memory worker | accepted MEM1 |
| 2 | `v1-8-3-mem3-memory-curator` | Memory worker | accepted MEM2 |
| 4 | `v1-8-3-integration-acceptance` | main agent | accepted CF4 plus accepted MEM3 |

For every line:

- [ ] Confirm the intended baseline checkout is clean and resolve its full commit SHA.
- [ ] Create one temporary repository-relative objective from the relevant phase section in the retained lane plan.
- [ ] Run only `scripts/devline_control.py start` with exact affected paths, allowlist, protected paths, dependencies, tests, and known gates.
- [ ] Delete the temporary objective after start; the generated Context Pack retains the frozen objective.
- [ ] Read the generated `context-pack.md`, `.agent/development/global_rules.md`, and selected retrospectives before product edits.
- [ ] Use TDD and append material `FAILURE`, `ERROR`, `GAP`, `WASTE`, `REVIEW`, `GATE`, and `STATE_CHANGE` events through the CLI.
- [ ] Verify the event stream, regenerate `RETROSPECTIVE.md`, close the line, and commit before a dependent phase starts.

Never hand-create or edit `.agent/devlines`. Scope corrections use only formal `rescope-context` or `refresh-context`.

## 5. Scientific acceptance gates

Every relevant phase must prove negative and positive behavior:

- [ ] Identity and hashes bind exact immutable inputs, implementation, environment, protocol, and output schema.
- [ ] B0 rejects forged, stale, expired, revoked, replayed, kind-escalated, weak-authentication, and incompletely bound attestations without executing code.
- [ ] Statistical validation uses registered protocols, bounded attempts, holdouts, and independent oracles for E2+ evidence.
- [ ] E0/E1 implementations remain experimental and `source_eligible=false`.
- [ ] Reproducibility profiles distinguish exact, numeric, and statistical claims; fixed seeds do not stand in for numerical determinism.
- [ ] B1 containment tests include filesystem, network, subprocess tree, environment, resource limit, timeout, cleanup, authenticated broker reporting, and unsupported-host failures.
- [ ] B0, B1, statistical validation, browser acceptance, and release acceptance remain separate evidence claims.
- [ ] Resolver tests cover unavailable, invalid, stale, incomparable, tied, and no-dominant-candidate outcomes.
- [ ] Memory tests prove default-off use/iteration, scope isolation, provenance, stale/conflict/revocation, and no authority escalation.
- [ ] No test asserts one preferred result merely because it matches a fixture; tests validate contracts and invariants across generated or parameterized cases.

## 6. Efficiency rules

- [ ] Do not create additional planning files or per-phase objective files in advance.
- [ ] Do not start another general review cycle after an accepted phase unless a failing test, security boundary, statistical validity issue, or user-requested scope change requires it.
- [ ] Keep one worker on each lane across its serial phases to retain context.
- [ ] Stop and ask only when scope or authority must materially expand; otherwise implement and verify.
- [ ] Run focused tests during phases; reserve `bash scripts/gate.sh`, combined browser QA, and full integration contracts for Wave 4.

## 7. Shared commands

Run Python commands under the repository path with:

```bash
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q <focused-tests>
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python scripts/devline_control.py verify --line <line-id>
git diff --check
```

Run TypeScript without piping so its real exit status is preserved:

```bash
npx tsc --noEmit
```

At Wave 4, after confirming no Vite/Vitest process is active:

```bash
bash scripts/gate.sh
```

FMS verification is process evidence only. It does not replace containment, numerical/statistical, browser, performance, or release acceptance.

## 8. Wave 4 Integration acceptance

**Line:** `v1-8-3-integration-acceptance`

**Shared files:**

- `backend/workbench/app.py`
- `backend/workbench/agent/trace.py`
- `backend/workbench/agent/context_compiler.py`
- `frontend/src/notebook/NotebookSurface.tsx`
- `frontend/src/notebook/notebook.css`
- `tests/contracts/test_v183_integration_contract_lock.py`
- `tests/fixtures/contracts/v183-integration/`
- `tests/test_v183_trace_catalog_integration.py`
- `tests/test_v183_context_capability_memory_integration.py`
- `tests/test_v183_notebook_capability_memory_integration.py`
- `frontend/src/notebook/v183.integration.notebook.test.tsx`

- [ ] Join the exact accepted CF4 and MEM3 commits in a clean Integration worktree.
- [ ] Register all package-local trace catalogs and reject event name/schema collisions.
- [ ] Mount identity, capability, and memory routes/services once in application startup.
- [ ] Inject project index before approved domain memory with deterministic budgets, provenance, omission, and fallback.
- [ ] Mount both lane UIs into the shared Notebook surface without changing confirmation or authorization semantics.
- [ ] Lock cross-lane wire contracts and prove memory cannot alter capability evidence, admission, authorization, or dispatch.
- [ ] Run focused cross-lane tests, all retained regressions, `npx tsc --noEmit`, `bash scripts/gate.sh`, and browser-visible acceptance.
- [ ] Record browser, containment, statistical, performance, and FMS evidence as separate claims.

## 9. Immediate start sequence

- [x] Close the original superseded `v1-8-3-b0-runtime-implementation` through formal CLI evidence.
- [x] Accept CORE1 on its independent branch without integrating it into the released or main worktree.
- [x] Stop B0-R2 after quality review found caller-minting, incomplete input/output identity, and statistical-protocol binding gaps; retain it only as non-integrated historical evidence.
- [ ] Close/supersede the B0-R2 formal line without merging its product implementation.
- [ ] Implement the revised B0 authority/verifier core from the exact clean revised-plan baseline.
- [ ] After focused review and gates, combine only accepted B0 and CORE1 commits into one clean foundation baseline.
- [ ] Start B1 and CF1 from that same foundation baseline; use the second worker slot for Memory only when dependency-critical Capability work is not waiting.

## Boundary
- Affected paths: `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/services/draft_materialization.py`, `backend/workbench/lineage/pipeline_drafts.py`, `tests/test_notebook_materialization.py`, `tests/test_pipeline_drafts_store.py`
- Allowed paths: `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/services/draft_materialization.py`, `backend/workbench/lineage/pipeline_drafts.py`, `tests/test_notebook_materialization.py`, `tests/test_pipeline_drafts_store.py`
- Protected paths: `backend/workbench/agent/notebook/service.py`, `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/app.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/http/drafts_routes.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/agent/trace.py`, `backend/workbench/agent/context_compiler.py`, `frontend/src/notebook/NotebookSurface.tsx`
- Dependencies: `docs/superpowers/specs/2026-07-25-v1.8.3-capability-factory-design.md`, `docs/superpowers/specs/2026-07-25-v1.8.3-custom-capability-runtime-design.md`, `docs/superpowers/plans/2026-07-25-v1.8.3-capability-lane.md`, `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/lineage/pipeline_drafts.py`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_notebook_materialization.py tests/test_pipeline_drafts_store.py tests/test_pipeline_drafts_genesis.py tests/test_capability_execution_authorization.py tests/test_no_exercise_specific_naming.py`
- Known gates: `new worktree dependencies must be linked with bash scripts/link-shared-deps.sh <absolute-worktree-path>`, `caller-supplied ids must be path-safe, deterministic, and same-id same-executable-content idempotent`, `no external Run, process, network, or dispatcher side effect in this line`, `native containment remains host-capability evidence and is not claimed on this macOS host`, `full gate must be run without piping tsc output to tail`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
