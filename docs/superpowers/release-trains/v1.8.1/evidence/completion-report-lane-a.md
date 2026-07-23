# Completion Report — Lane A (Agent: Notebook Option 生成与生命周期)

Work order: `docs/superpowers/release-trains/v1.8.1/work-orders/wo-a-agent.md`
Branch: `feat/v181-agent-notebook-options`
Resumed from WIP commit `1fdc328` (prior agent, session-limit cutoff).
Final tip: `b38fe5e`.

ADR-PD-001 §10.2 items:

## 1. 实现了什么、没有实现什么

**Resumed state:** 24 passed / 14 failed. The prior agent had already built the
full package under `backend/workbench/agent/notebook/` (store, service, freshness
gate, artifact contract, proposal, errors, vocabulary) plus all five Gate-4 test
files. The failures all traced to **two missing seams** the prior agent never
finished wiring, not to broken logic in what existed.

**Completed this session (finished the WIP):**

- `NotebookService.compile_context(notebook_id)` — the Gate-2 compilation entry
  point every test drives through. Reads the notebook's persisted premises and
  the options already stored, and delegates to the one deterministic compiler
  (`compile_notebook_planning_context`). Existing option summaries ride in the
  generation view but are deliberately **not** freshness-dependency fields, so a
  batch of siblings stays fresh (spec §4.0 self-reference 命门).
- `NotebookService.set_focus(notebook_id, user_focus=...)` — records what the
  user is looking at. Writes to the **notebook** log only, never to any option
  log, so it is a freshness dependency the confirm-time gate catches without
  perturbing an option's append-only revision history.
- `Notebook` now persists `analysis_contract`, `user_focus`,
  `available_capabilities` (with `create_notebook` accepting them as kwargs), and
  the `get_notebook` fold carries `user_focus` forward from `notebook_state`
  records. This is what makes read-time-fresh → upstream-changed → confirm-refuses
  actually reproducible.
- `_existing_option_summaries` — a deterministic, content-only (no timestamps, no
  freshness verdict) digest of stored options for the generation context.
- Added one owned test proving spec §9.1 criterion 1 positively: a **runless**
  notebook compiles a bounded context, generates an option and confirms it with
  the active head staying `null`.

**Not implemented (out of scope, unchanged):**

- `backend/workbench/http/notebook_routes.py` — listed in `owned_files` but the
  prior agent never created it and **no lane-A test requires it**. The HTTP route
  layer is not exercised by any Gate-4 acceptance test; left absent rather than
  speculatively built.
- Non-goals per work order: estimator/model (Lane B), any frontend (Lane C),
  graph-persistence changes, unconfirmed continuous branching, real LLM calls.

## 2. 精确修改的文件和提交

Commit `b38fe5e` "feat(Lane A): complete notebook context compilation + focus":

- `backend/workbench/agent/notebook/store.py` — `Notebook` gains
  `analysis_contract` / `user_focus` / `available_capabilities` fields
  (default-factory, before `schema_version`); `to_dict`/`from_dict` updated;
  `get_notebook` fold carries `user_focus`; `field` import added.
- `backend/workbench/agent/notebook/service.py` — import
  `compile_notebook_planning_context`; `create_notebook` accepts the three
  premise kwargs and stores them; new `set_focus`, `compile_context`,
  `_existing_option_summaries` methods.
- `tests/test_notebook_option_lifecycle.py` — added
  `test_a_runless_notebook_can_compile_generate_and_confirm_with_a_null_head`.

No contract file, no forbidden file, and no file outside `owned_files` was
touched.

## 3. 是否修改合同、使用哪个 lock

No contract modified. `contract_lock_commit` / `branch_start_commit` =
`481fc2e30730395093fc0f8699843e1002d64aa3` (per work order). All code consumes
`backend/workbench/contracts/agent/notebook_option.py` read-only. Producer never
sets `generation_context_hash == freshness_dependency_fingerprint` and never
passes extra keys into `NotebookOptionRevision`, so the advanced integration lock
(unknown-field rejection + hash-inequality) remains satisfied. **No Contract
Change Request.**

## 4. 执行过的命令及精确结果

```
.venv/bin/python -m pytest tests/test_notebook_option_lifecycle.py \
  tests/test_notebook_freshness_gate.py tests/test_notebook_store_append_only.py \
  tests/test_notebook_artifact_contract.py tests/test_notebook_trace_chain.py -q
→ 39 passed
```

(Before the fix, the same five files: 24 passed / 14 failed.)

```
.venv/bin/python -m pytest tests/contracts/test_v181_contract_lock.py -q
→ 18 passed
```

All runs with `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8` (中文路径要求). `scripts/gate.sh`
was NOT run (exclusive lock, other lanes may be running).

No test was weakened, deleted, or trivialized; no golden touched. No pre-existing
test required correction — every failure was a genuine implementation gap.

## 5. 已知限制、失败路径和性能观测

- Artifact validation checks identity/type/count/step only; `payload_schema` is
  explicitly `not_evaluated` and `schema_ref` is refused at build time — the
  report always names what was and was not checked (DEC-ART-001).
- The confirm-time gate is fail-closed on `freshness_dependency_fingerprint`
  only; `generation_context_hash` never gates execution (proven by
  `test_confirm_ignores_a_changed_generation_context_hash`).
- `compile_context` re-reads every option log on each call to build summaries;
  fine at the ≤3-per-batch scale this version targets, O(options) per compile.
- Test suite runs in ~1.1s; no heavy runs, no LLM calls.

## 6. 潜在集成风险、建议合并顺序和回滚方式

- **Risk:** `Notebook.to_dict` now emits three new keys. `from_dict` tolerates
  their absence, so older notebook logs replay fine; forward-compatible.
- **Risk:** `notebook_routes.py` is unimplemented. If Integration or Lane C
  expects an HTTP surface, that is a follow-up; the service API is complete and
  fully covered.
- **Merge order:** Lane A is self-contained (consumes locked contracts +
  Gate-2/3 read-only). Safe to integrate independently of B/C/D; no shared-file
  edits. Recommend after the integration lock is confirmed at `481fc2e`.
- **Rollback:** revert `b38fe5e`; the package returns to the WIP state (24/14).
  No migrations or persisted-schema changes beyond additive notebook fields.
- **§9.1 criterion 1 / xfail note:** the `xfail(strict=True)` in
  `tests/test_run_family_acceptance.py` lives on the `workbench-v1.8.1` branch and
  was **not** edited here (correct per work order). Lane A proves the criterion
  positively on its owned surface; Integration removes the xfail when merging.

## 7. 是否触碰 forbidden/protected files

**No.** No file in `forbidden_files` (orchestrator.py, operations.py, engine/**,
graph_store.py, frontend/**, scripts/gate.sh, the two honest_did adversarial
tests) and no file in `read_only_contracts` was modified. All edits are inside
`owned_files` (`backend/workbench/agent/notebook/**`, `tests/test_notebook_*.py`).
