# LMM Agent Public-Result View Implementation Plan

Status: **revised plan pending review**. The P1 pinned-writer amendment below supersedes every
earlier LMM persistence step that passed a raw `run_root` or called `write_json` / `register_artifact`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` to execute each checkbox in order.

**Goal:** Build a read-only LMM-to-WO-A recipe view that can prove the terminal packet and execution
inputs belong to one pinned, sealed run without causing a model load or an Agent action.

**Architecture:** A scheduler-owned `LmmExecutionAdmission` anchors every LMM index/artifact/input
read and every LMM-owned write at one trusted `runs_root` capability plus a validated run ID. Before
fitting, the coordinator takes the only permitted pinned input snapshot, atomically seals the
canonical executed payload, and passes the live admission (pinned capability, writer lease, seal) to
EstimationStage and the LMM runner. The capability then owns immutable
result/diagnostic/recovery packet publication and the corresponding index update. Only then can a
read-only bridge delegate prevalidated facts to WO-A.

**Tech Stack:** Python 3.14, pytest, POSIX FD primitives, `fsync`, canonical SHA-256,
`PacketEnvelope`, `ModelOptionsBinding`, `LmmModelInput`. No model fitting policy change, dependency
change, Agent route, state write by the bridge, candidate evaluation, merge, commit, push, or release.

---

Controlling specification:
`docs/superpowers/specs/2026-07-19-lmm-agent-public-result-view-design.md`. Tasks are serial because
each establishes the trust boundary required by the next. WO-D remains the only later execution gate.

> **Current-gap warning:** the provisional implementation presently has public
> `PinnedRunDirectory.logical_path` and arbitrary-part `read_regular_snapshot(...)`. These are Task 0
> non-compliances, not completed foundation work. Task 0 must remove them and prove fixed-operation
> replacement before any production LMM wiring; the existing source/test state must never be reported
> as satisfying the pinned-capability contract.

### Task 0: Build the pinned run-directory capability and atomic execution seal

**Files:** Create `backend/workbench/services/pinned_run_directory.py`; create
`tests/test_pinned_run_directory.py`; modify `backend/workbench/lineage/run_inputs.py` only if its
existing canonicalization helpers can be reused without weakening the new protocol.

- [ ] Write RED tests for `open_pinned_run_directory(runs_root, run_id)`. Its allowed ID grammar is
  `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`; reject every other value before filesystem access. Reject a
  missing/symlinked `runs_root`, missing/symlinked/replaced child, closed capability reuse, direct or
  nested symlink, non-regular target, malformed/duplicate-key/nonfinite JSON, and over-1-MiB input.
- [ ] Write RED tests for the **private** descriptor-relative snapshot primitive as exercised through
  public fixed readers (`read_run_inputs_snapshot`, `read_lmm_index`,
  `read_lmm_terminal_packet`, and `read_execution_seal`). It must use `O_NOFOLLOW`, pre/post
  `fstat` device/inode/size/mtime_ns/ctime_ns equality, pre-reject a size above `max_bytes`, and do
  exactly one `read(pre_fstat_size + 1)`. Assert `len(bytes) == pre_fstat_size`: inject a short valid
  JSON prefix and require `PINNED_SNAPSHOT_SHORT_READ`; inject a tail after pre-`fstat` and require
  `PINNED_SNAPSHOT_SIZE_CHANGED`; inject mutation/replacement and require a closed error. Assert no
  retry, partial JSON, or raw path escape.
- [ ] Add RED parametrized tests that every relative component independently rejects empty string,
  `.`, `..`, slash, backslash, and NUL before `openat`/mkdir/link/unlink. Cover caller parts, fixed
  `artifacts/execution/executed_input_v1.json` parts, and generated temp names; spy that no descriptor
  syscall is reached after rejection.
- [ ] Write RED tests for `seal_executed_input_v1(pinned_run, representation)`: canonical JSON bytes
  at `artifacts/execution/executed_input_v1.json`; a first seal fsyncs file then atomically renames and
  fsyncs pinned parent; identical retry returns the original without rewrite; divergent competing seal
  fails; symlink/rename anomaly fails; and post-seal byte mutation is detected by
  `verify_sealed_execution_input`.
- [ ] Add RED publication tests: safe `renameat2(RENAME_NOREPLACE)` never overwrites; fallback uses
  `linkat(temp, final)` then `unlinkat(temp)` and an `EEXIST` final is reopened through the anchored FD
  for exact-byte identical success or `EXECUTED_INPUT_SEAL_DIVERGENCE`; unavailable safe primitives
  fail closed. Cover a clean new run with absent `artifacts`/`execution`: creation is allowed only by
  anchored parent-FD mkdir, parent fsync, O_NOFOLLOW reopen, and directory fstat verification. Cover
  post-create replacement/symlink/mode error/race plus failures during temp publication, fsync, and
  re-read.
- [ ] Implement `PinnedRunDirectory` as a context manager retaining only private child directory-FD
  state and validated ID. Close every nested FD after use and the root FD exactly once on exit; methods
  reject use after close. Public consumers receive only fixed named readers/writers, never
  `logical_path`, `run_root`, `Path`, raw FD, arbitrary components, or a public generic snapshot
  method. Implement private literal descriptor-relative reads, one exact-size bounded snapshot, and
  closed error codes without raw paths/parser text. Document that before/after identity checks catch
  testable replacement/mutation but do not prove absolute same-UID immutability. Validate every
  component before every descriptor-relative syscall; no joined-path shortcut is permitted.
- [ ] Implement the seal as a dedicated protocol, never `update_run_inputs_metadata`: compare exact
  existing canonical bytes through the capability; otherwise create all `artifacts/execution`
  directories for a clean new run one component at a time via anchored parent `dir_fd` mkdir, fsync
  each parent, O_NOFOLLOW reopen, and fstat verification; any later replacement/symlink/mode/race fails
  closed. Then exclusive-create a validated temp there, fsync it, publish strictly with
  `renameat2(RENAME_NOREPLACE)` or tested `linkat+unlink`, fsync the same pinned parent, and reverify.
  No overwrite rename or path-based creation/re-read is permitted.
  Return only `SealedExecutionInput(run_id, canonical_bytes, digest)`.
- [ ] Run
  `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/test_pinned_run_directory.py -q`.
  Expected: all tests pass. Obtain spec and quality review before Task 0A.

### Task 0A: Build an unreachable, private P1 durable-writer primitive

This task intentionally creates no production-reachable writer. `PinnedRunDirectory` remains a
read/seal capability and has no `persist_*` surface. Until Task 0B has anchored a live
admission/lease in `run_service._bg_run`, no runner, EstimationStage, workflow, or public service may
import or call the internal admission-gated facade. The RED tests in this task exercise it only via an
explicit test-only live-admission factory. This order prevents a correct-looking file writer from
becoming a second, uncoordinated production authority.

**Files:** Modify `backend/workbench/services/pinned_run_directory.py`; modify
`tests/test_pinned_run_directory.py`; create
`tests/models/linear_mixed_effects/test_pinned_persistence.py`; do **not** modify
`backend/workbench/engine/packs/linear_mixed_effects/runner.py` until Task 0B; do **not** modify
`backend/workbench/artifacts.py` in this task.

- [ ] **Step 1: Write RED terminal-publication tests.** In
  `tests/models/linear_mixed_effects/test_pinned_persistence.py`, create a valid open
  `PinnedRunDirectory`, an exact sealed execution input, a private live
  `LmmExecutionAdmission`, and a valid terminal C1 result envelope. Assert that the private
  `_persist_lmm_terminal_packet(admission=..., packet=...)` facade call creates only
  `artifacts/model_results/linear_mixed_effects_1.result.json`, returns an opaque receipt whose
  internal facts produce the exact indexed `ArtifactRecord.to_dict()` without exposing a path, FD,
  record, or digest attribute to callers, and produces exactly one `model_result_packet`. Repeat with
  the same canonical packet and
  assert an idempotent receipt; repeat with changed bytes, a pre-existing slot, a duplicate terminal
  record, a wrong `artifact_type`, and a same ID/path with one changed record field, and assert a
  stable closed conflict. The test must prove no LMM call reaches `write_json` or
  `register_artifact` by monkeypatching both to raise.

  Add RED authority cases before any storage spy is allowed to observe a call: direct
  `pinned_run.persist_lmm_terminal_packet` / any equivalent writer attribute is absent or rejects;
  a foreign admission (including another open admission for the same run), forged admission, closed
  admission, or admission with a detached/replaced lease rejects with the specified stable code before
  descriptor traversal, temporary creation, packet write, or index update. The public
  `PinnedRunDirectory` API must offer no lease-attach/setter/getter or writer-facade accessor.

- [ ] **Step 2: Run the terminal test and observe RED.**

  Run:

  ```bash
  PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
    tests/models/linear_mixed_effects/test_pinned_persistence.py -q
  ```

  Expected: FAIL because the capability has no durable packet writer and the runner still uses a raw
  `run_root` persistence path.

- [ ] **Step 3: Write RED companion-packet and separation tests.** Add tests that a valid
  `LmmInputBlockedAdmission` writes one immutable content-addressed `lmm_diagnostic_packet`, has no terminal receipt
  and no `model_result_packet`; a complete/failed terminal may write a diagnostic companion; a failed
  terminal and an input-blocked diagnostic reject recovery publication; and only a valid same-open-
 capability terminal receipt plus the locked recovery envelope writes one immutable
  `lmm_recovery_packet`. Assert diagnostic/recovery records have digest-derived paths, distinct
  non-model types, and cannot be read by `read_lmm_public_results_from_pinned_run`.

  Add receipt-capability RED cases: pickle/JSON serialization and direct construction fail; a forged
  object, receipt from a second open capability for the same run, and a receipt used after close each
  return `LMM_PERSISTENCE_RECEIPT_INVALID`; recovery derives (rather than trusts) the exact terminal
  packet digest and fixed terminal identity into its durable audit reference. If the existing
  `ArtifactRecord` schema cannot store that durable dependency, persistence must reject pending a
  separately versioned record extension.

- [ ] **Step 4: Write RED descriptor/race/cleanup tests.** In
  `tests/test_pinned_run_directory.py`, inject a symlink, directory replacement, regular-file
  substitution, post-open mutation, `EEXIST`, partial-write, fsync, rename/link, re-read, and cleanup
  failure at each controlled parent, temp, packet, lock, and index operation. Assert rejection with a
  non-disclosing stable code, no path escape, no partial receipt, no final overwrite, and closure of
  every nested FD. Add a crash-shaped test that creates the final terminal file before index update;
  prove the next call only reconciles the exact same bytes/digest into one missing record and never
  deletes or replaces the orphan. Add a token-contention test: a pre-existing private admission token
  yields `LMM_PERSISTENCE_BUSY`, is not automatically reaped, and leaves final/index unchanged.

  Add RED single-writer and outcome-table tests: a pinned-run scheduler lease denies a legacy writer
  dispatch with `LMM_LEGACY_WRITER_FORBIDDEN`; missing/unprovable topology denies admission with
  `LMM_SINGLE_WRITER_REQUIRED`; an injected raw legacy index mutation between snapshot and
  revalidation returns `LMM_LEGACY_WRITER_CONFLICT` and refuses reconciliation except exact orphan
  recovery. Cover each persistence outcome from the controlling design: packet-before-index failure,
  input-blocked diagnostic failure, required terminal-companion failure, token-release/fsync failure,
  and exact retry/reconciliation. Assert run state, receipt/index existence, safe structured code,
  and absence of any legacy/OLS/in-memory-success fallback for every row.

- [ ] **Step 5: Implement private FD helpers and opaque receipts.** In
  `backend/workbench/services/pinned_run_directory.py`, add a non-serializable, non-publicly-
  constructible `PinnedArtifactReceipt` with an admission/facade nonce and per-receipt nonce. Store
  its facts only in the admission facade's private table and invalidate all receipts at admission
  close. Implement only these private facade methods; they take the exact live
  `LmmExecutionAdmission` (which privately owns its non-exported `LmmRunWriteLease`) and are never
  methods of `PinnedRunDirectory`:

  ```python
  def _persist_lmm_terminal_packet(
      self, *, admission: LmmExecutionAdmission, packet: Mapping[str, object]
  ) -> PinnedArtifactReceipt: ...

  def _persist_lmm_diagnostic_packet(
      self, *, admission: LmmExecutionAdmission, packet: Mapping[str, object],
      terminal: PinnedArtifactReceipt | None
  ) -> PinnedArtifactReceipt: ...

  def _persist_lmm_recovery_packet(
      self, *, admission: LmmExecutionAdmission, packet: Mapping[str, object],
      terminal: PinnedArtifactReceipt
  ) -> PinnedArtifactReceipt: ...
  ```

  Do not expose arbitrary `parts`, filenames, raw directory paths, raw FDs, or receipt internals to
  callers. Before any storage operation, each method proves the exact active admission/facade object,
  non-exported live lease, open state, and any receipt provenance; a foreign, forged, closed, or
  lease-replaced admission fails without an FD operation. Build private
  component-validation, `mkdirat`/no-follow traversal, exclusive-temp, immutable publication,
  bounded snapshot, index-snapshot, and descriptor-close helpers. Validate exact envelope contract
  and derive diagnostic/recovery names from canonical-byte SHA-256 internally. The terminal writer
  must call `verify_sealed_execution_input` immediately before publication.

- [ ] **Step 6: Implement immutable packet and index publication.** Publish packet bytes first with
  `renameat2(RENAME_NOREPLACE)` or tested `linkat+unlink`; fsync the destination parent and re-read
  exact bytes/digest through the pinned FD. Acquire a private `O_CREAT|O_EXCL|O_NOFOLLOW` admission
  token before the one-snapshot index read-modify-write. Validate every existing and candidate
  `ArtifactRecord.to_dict()` value, enforce duplicate and fixed-terminal identity rules, write a
  complete replacement index via exclusive temp, atomic same-directory replacement, parent fsync,
  and pinned re-read. Do not claim multi-file atomicity: on a post-packet index failure, return a
  closed `LMM_PERSISTENCE_IO_FAILED` outcome with no receipt, mark the run
  `PERSISTENCE_INCOMPLETE`, and permit only coordinator-mediated exact later reconciliation. A
  terminal packet that is indexed but whose required diagnostic/recovery companion fails remains
  durable but is also `PERSISTENCE_INCOMPLETE`; return its structured companion failure rather than
  silently declaring full success. Never automatically delete an existing token or final artifact.

- [ ] **Step 7: Keep the writer unreachable.** Do not modify the LMM runner, EstimationStage,
  workflow, or service dispatch in this task. Assert by import/spy tests that no production LMM path
  can call the writer and that private writer tests require an explicit test-only capability factory.
  Runner wiring is deferred to Task 0B after the concrete `_bg_run` admission/lease lifecycle is
  implemented and reviewed.

- [ ] **Step 8: Run the focused persistence gate.**

  Run:

  ```bash
  PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
    tests/test_pinned_run_directory.py \
    tests/models/linear_mixed_effects/test_pinned_persistence.py \
    tests/models/linear_mixed_effects/test_runner.py \
    tests/test_lmm_result_adapter.py -q
  ```

  Expected: all tests pass. Run `git diff --check` and then obtain specification review followed by
  code-quality review before Task 1. The review must reject any path-based LMM write, implicit
  terminal overwrite, automatic stale-lock deletion, or claim that POSIX commits packet and index as
  one atomic transaction.

### Task 0B: Make pre-fit admission and single-writer scheduling real

**Files:** Modify the concrete existing lifecycle owner
`backend/workbench/services/run_service.py` (`_submit_run` schedules only; `_bg_run` calls new private
`_admit_lmm_execution_for_bg_run` immediately before `_run_workflow`),
`backend/workbench/orchestrator/__init__.py` (private `_run_workflow` keyword handoff only),
`backend/workbench/engine/context.py` (private `RunEnv` carrier only),
`backend/workbench/engine/stages/estimation.py`,
`backend/workbench/engine/packs/linear_mixed_effects/runner.py`, and modify
`backend/workbench/services/pinned_run_directory.py`; create
`tests/engine/test_lmm_execution_admission.py`; extend
`tests/contracts/test_lmm_error_contract.py`; add focused `run_service` lifecycle tests. Do not create
a parallel admission path.

- [ ] Write RED admission tests before modifying production code. A valid server-side LMM request must
  be admitted once by private `run_service._admit_lmm_execution_for_bg_run`, called from `_bg_run`
  immediately before `_run_workflow`, which opens the trusted run,
  acquires the scheduler's `LmmRunWriteLease`, takes the one allowed pinned run-input snapshot, proves
  its canonical model type/options/binding exactly equal the server-owned request, derives the canonical
  `{schema_version, model_type, model_options, model_options_binding}` record from that request, and seals
  it before EstimationStage starts. Assert the returned admission cannot be constructed from public
  dictionaries, paths, FDs, or serialized values. Assert `_submit_run` only schedules work and cannot
  mint a process-local lease.
- [ ] Write RED exact-handoff tests: `_bg_run` passes the exact private object by
  `_run_workflow(..., lmm_execution_admission=admission)`; `_run_workflow` installs that same object
  in a private `RunEnv` carrier; EstimationStage, handler/runner, and writer receive the same object
  by `is` identity. Assert it has no global registry/cache lookup, no late
  `open_pinned_run_directory`, no `ModelingContext` field, and no artifact/manifest/event/error
  serialization route. Patch all plausible global lookups and late-open functions to raise; the good
  path must not call them. Assert pickle, JSON/mapping conversion, shallow/deep copy, and direct
  construction all fail closed.
- [ ] Write RED entrypoint tests: direct `_run_workflow`, CLI/workflow helper, and test-only LMM
  execution calls without `lmm_execution_admission` fail before EstimationStage with
  `LMM_EXECUTION_BINDING_REQUIRED`. They must not silently create/admit/lookup/reopen a capability or
  invoke legacy persistence. Non-LMM direct workflow behavior remains unchanged.
- [ ] Write RED ownership tests: a pre-seal server validation failure creates only a private
  `LmmInputBlockedAdmission` and one diagnostic-only publication right (no seal, terminal, recovery,
  model-result index, generic index API, generic writer, or `write_json`), while the private facade
  writes exactly one matching `lmm_diagnostic_packet` index record; `EstimationStage`, direct fit, terminal failure, validation failure,
  and unexpected-fit failure reject without a live admission; LMM never calls
  `update_run_inputs_metadata` or `_persist_model_options_execution_binding`; a same-byte resume is
  coordinator-mediated and a differing second admission returns
  `LMM_EXECUTION_ADMISSION_CONFLICT`. Patch every post-fit `run_inputs` reader to raise and prove no
  LMM path invokes it.
- [ ] Write RED sealed-state transition tests: sealing starts only as `PROVISIONAL_SEALED`; the final
  input/state proof under the private `(run_id, seal_digest)` admission lock is the sole transition
  to `COMMITTED_EXECUTION`, and only that state may enter `EstimationStage`. A post-seal proof failure
  must first create `artifacts/execution/invalidated_input_v1.<seal-sha256>.json` with exact pinned
  run ID, exact seal digest, and stable `LMM_*` reason, using no-replace creation plus file/parent
  fsync and pinned re-read; only then may it atomically revoke/demote the full admission and mint one
  tombstone-bound `LmmInputBlockedAdmission`. Prove divergent/existing, symlinked, replaced, unreadable,
  or unfsynced tombstones fail closed, no fit/retry under the old run ID occurs, and a new retry uses a
  new run ID without erasing or replacing the old tombstone.
- [ ] Write RED state-recheck and reader-boundary tests: every terminal packet/index and recovery
  packet/index operation reacquires the same admission lock and rechecks exact run ID, seal digest,
  `COMMITTED_EXECUTION`, open admission, and tombstone absence before descriptor traversal or
  mutation. Concurrent/restart/orphan paths observing `INVALIDATED_INPUT_BLOCKED`, a tombstone, or a
  changed seal make no storage mutation and cannot re-admit/erase/replace the tombstone. A blocked
  capability may write only one diagnostic plus matching `lmm_diagnostic_packet` index record, never
  a terminal/recovery/model-result or generic index record; public readers ignore seal/tombstone-only
  state and expose no synthetic result.
- [ ] Write RED scheduler-topology tests. The `_bg_run` admission must mark the admitted run
  `lmm_pinned_v1`, dispatch only the pinned writer with its lease, deny generic/legacy writer requests
  for that run with `LMM_LEGACY_WRITER_FORBIDDEN`, and reject a historical/unprovable topology with
  `LMM_SINGLE_WRITER_REQUIRED`. Inject a legacy raw index mutation during pinned reconciliation and
  assert `LMM_LEGACY_WRITER_CONFLICT`, no receipt, no overwrite, and only exact orphan recovery.
- [ ] Write RED lifecycle/restart tests: worker/server loss invalidates admission/lease/receipt;
  `_mark_interrupted_if_dead` leaves the old run interrupted and never auto-resumes fitting; user retry
  goes through `_submit_run` to a new run ID; and a separately authorized reconciliation-only entry
  point can add only the one missing index record for exact pre-existing packet/seal bytes. It cannot
  fit, write a new terminal packet, reuse a prior receipt, or automatically reap a token. Until that
  explicit reconciliation boundary exists, old incomplete runs remain blocked and truthful.
- [ ] Implement the admission/lease types as process-local capabilities with private constructors and
  close/invalidation semantics. The writer validates the live lease before every packet and index
  write. Implement the exact object-identity chain `_bg_run → _run_workflow(keyword) → private RunEnv
  field → EstimationStage → handler/runner/writer`; forbid serialization, copying, public getter,
  global registry/cache, context/artifact carrier, and late reopen. Do not treat an `O_EXCL` filename
  token as scheduler authority and do not claim protection from an arbitrary same-UID writer after a
  successful return.
- [ ] Implement the sealed-state protocol under the scheduler admission lock: private-only
  `PROVISIONAL_SEALED`, `COMMITTED_EXECUTION`, and `INVALIDATED_INPUT_BLOCKED` states with no public
  enum/setter or deserializable recovery path; a descriptor-relative, anchored, no-replace run+seal
  tombstone with file/parent fsync and pinned re-read; atomic full-admission revocation before the
  restricted diagnostic capability exists; and state/tombstone rechecks before every terminal or
  recovery publication/index operation. Keep pre-seal input blocking tombstone-free. Current source
  has none of these state/tombstone/demotion/recheck guarantees, so do not describe Task 0B as
  implemented until these RED tests pass.
- [ ] Only after all prior Task 0B admission tests pass, wire the LMM runner/EstimationStage so
  `_persist_result_packets`, `_persist_input_error_packet`, `fit_linear_mixed_effects`, and
  `fit_from_context` receive only the live admission and delegate packet persistence to the private
  capability writer. Delete LMM-local raw `_write_packet`, terminal-slot checks, index initialization,
  `write_json`, and `register_artifact` calls. `_bg_run` must catch `LmmPersistenceError` separately,
  write only the stable structured error contract (never `str(exc)`), and never route LMM into its
  generic legacy error persistence fallback. Add RED tests that an admitted LMM persistence error never
  mutates generic `errors.json` or a generic manifest: only the admission-bound descriptor-relative
  `LmmLifecycleFailureSink` may persist stable non-result state; its own failure leaves
  `PERSISTENCE_INCOMPLETE` and has no fallback.
- [ ] Extend the LMM error contract with all admission, lease, receipt, legacy-writer, short-read,
  size-changed, and outcome-table codes. Assert exact code/category/retryability mappings and that
  the estimation/service boundary catches `LmmPersistenceError`, not only `ValueError`, without raw
  exception detail or a fallback result.
- [ ] Run

  ```bash
  PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
    tests/engine/test_lmm_execution_admission.py \
    tests/test_pinned_run_directory.py \
    tests/models/linear_mixed_effects/test_pinned_persistence.py \
    tests/contracts/test_lmm_error_contract.py -q
  ```

  Expected: all tests pass. Obtain specification review and code-quality review before Task 1.

### Task 1: Bind the terminal LMM packet to the pre-fit sealed execution input

**Files:** Modify `backend/workbench/contracts/model/linear_mixed_effects.py`,
`backend/workbench/engine/stages/estimation.py`,
`backend/workbench/engine/packs/linear_mixed_effects/runner.py`, `result.py`, `packets.py`, and
`backend/workbench/services/lmm_result_adapter.py`, `backend/workbench/services/pinned_run_directory.py`; modify
`tests/models/linear_mixed_effects/test_runner.py`, `tests/test_lmm_extension_seams.py`, and
`tests/test_lmm_result_adapter.py`; update the public-result-adapter design/plan.

- [ ] Write RED ordering tests: before `handler.fit(ctx, env)`, the coordinator's one live
  `LmmExecutionAdmission` has already derived the canonical
  `{schema_version, model_type, model_options, model_options_binding}` record from its one permitted
  pinned snapshot and sealed it. EstimationStage passes that same admission/seal unchanged to the LMM
  handler. Different second admission fails, identical coordinator-mediated resume does not rewrite,
  and handler/terminal packet binding is byte-identical for complete and unexpected-fit-failed
  outcomes.
- [ ] Add RED regression tests around `EstimationStage`'s current
  `_persist_model_options_execution_binding`: for LMM it is forbidden, not merely bypassed after fit.
  Mutate form/executable/confirmed inputs, generic `run_inputs` metadata, or `ctx` options/binding
  after admission and assert terminal persistence rejects rather than re-reading/rebinding; otherwise
  assert exact canonical equality among sealed record, admission handoff, direct runner, and terminal
  payload.
- [ ] Write RED runner tests: patch any post-fit run-input reader to raise; no runner path may invoke
  it. `fit_linear_mixed_effects` must reject a missing/mere-dictionary binding with
  `LMM_EXECUTION_BINDING_REQUIRED`, and reject a supplied seal not reverified against its live
  `PinnedRunDirectory` with `LMM_EXECUTION_BINDING_INVALID` before terminal persistence. A changed seal
  after fit but before packet write must reject.
- [ ] Write RED adapter tests for the exact packet `execution_binding` and detached outer public field.
  Add `read_lmm_public_results_from_pinned_run(pinned_run)` tests proving index and terminal packet use
  the same capability: replace `runs_root/run_id` after open, or mutate/symlink index/packet, and prove
  no redirected/partial result is returned.
- [ ] Implement the exact LMM payload binding and public projection. The coordinator admits and seals
  before `handler.fit`; `fit_from_context`, direct fit, `_fit_and_build_terminal_result`, result
  builders, and packet persistence accept/pass the live admission explicitly. Immediately before
  terminal write, the capability re-verifies the seal through the same FD and owns all packet/index
  persistence. For LMM, post-fit `_persist_model_options_execution_binding` is forbidden; no code may
  re-read mutable `run_inputs.json`, rebind options, write a generic executed-payload sibling after
  fit, receive a raw `run_root` for LMM artifact persistence, or continue after a structured
  persistence failure.
- [ ] Refactor only the strict LMM reader into `read_lmm_public_results_from_pinned_run`; it must read
  `artifacts_index.json` and the controlled terminal path through `PinnedRunDirectory`, never call
  `Path.resolve`, `Path.read_bytes`, `glob`, or generic path-based `read_model_results` first. Keep a
  separate compatibility wrapper only where non-bridge legacy HTTP needs it; the bridge must never use
  that wrapper.
- [ ] Run
  `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/test_pinned_run_directory.py tests/models/linear_mixed_effects/test_runner.py tests/test_lmm_result_adapter.py tests/test_lmm_extension_seams.py -q`.
  Expected: all selected tests pass. Obtain spec and quality review before Task 2.

### Task 2: Bring in hardened WO-A and non-loading contract helpers

**Files:** Add from candidate tip `a450822` only:
`backend/workbench/agent/recipes/lmm_explanation.py`,
`backend/workbench/agent/recipes/repeated_measures.py`,
`tests/agent/test_repeated_measures_recipe.py`, and
`tests/agent/test_repeated_measures_recovery.py`; modify
`backend/workbench/contracts/model/linear_mixed_effects.py`,
`backend/workbench/agent/recipes/__init__.py`, and `tests/contracts/test_lmm_contracts.py`.

- [ ] Verify `git diff 0251f0a..a450822 -- <each selected file>` contains no registry, route, storage,
  operation, execution, Pack, UI, or Compare change. Add candidate files without changing their old
  source-based public signatures or the locked recovery patch.
- [ ] Write RED tests for `validate_lmm_executed_options_v1` and
  `lookup_registered_lmm_contract_without_bootstrap`. Require exact canonical binding plus four locked
  owner literals; availability is false when no matching handler is already loaded. Snapshot
  `MODEL_REGISTRY` mapping and every handler object identity before/after calls.
- [ ] Extract `build_lmm_explanation_from_validated_facts` and
  `build_repeated_measures_recipe_from_validated_facts` from the candidate's shared construction logic.
  Their inputs are `LmmModelInput` plus `tuple[LmmDiagnostic, ...]`; they may not call
  `validate_lmm_source`, `verify_binding_owner_for_model_type`, a loader, or registry. Preserve the
  old wrappers for candidate compatibility.
- [ ] Implement the pure direct-literal owner validator and read-only already-loaded registry lookup.
  It must not call `_resolve_model_options_handler`, `bootstrap_builtin_packs`, or an estimation import.
- [ ] Run
  `PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest tests/agent/test_repeated_measures_recipe.py tests/agent/test_repeated_measures_recovery.py tests/contracts/test_lmm_contracts.py -q`.
  Expected: all selected tests pass.

### Task 3: Write failing bridge tests

**Files:** Create `tests/agent/test_lmm_public_result_view.py`.

- [ ] Construct a valid `runs_root/run_id` with a sealed pre-fit execution representation, a strict
  terminal LMM packet with the same binding, and index records. Call the bridge only as
  `build_repeated_measures_recipe_from_run(runs_root, run_id)`; never inject a path/result/options.
- [ ] Add a good-path test whose only proposal is the locked confirmation-bound
  `model.rerun` random-slope removal. Assert its existing plan-diff text and three-key output shape.
- [ ] Add parametrized exact-neutral tests for invalid ID, missing/symlinked/replaced run directory,
  closed capability, missing/malformed/duplicate-key/oversized/mutated sealed execution record,
  divergent/mutated seal,
  run-A terminal packet replayed in separately valid run B, wrong public model/contract/producer,
  plural result, bad binding/options/fit/random-effect agreement, failed/blocked/unknown diagnostics,
  and unavailable non-loading registry contract.
- [ ] Add no-side-effect tests: patch `ProposalStore.create`, `OperationRegistry.require`,
  `AgentRecipeRegistry.register`, `subprocess.Popen`, and every Pack loader to raise. Snapshot the
  registry, seal bytes, index, and packet bytes; good/neutral calls must leave all unchanged. Patch
  every generic `run_inputs` reader to raise: neither bridge path may call one.
- [ ] Run the focused test. Expected: FAIL because the bridge module does not exist.

### Task 4: Implement the read-only bridge

**Files:** Create `backend/workbench/agent/recipes/lmm_public_result_view.py`; modify its package
`__init__.py` only for direct exports; modify the Task 3 test only for helper defects.

- [ ] Implement this boundary skeleton:

  ```python
  def build_repeated_measures_recipe_from_run(
      runs_root: Path, run_id: str
  ) -> dict[str, object]:
      try:
          with open_pinned_run_directory(runs_root, run_id) as pinned_run:
              result = _select_verified_lmm_result(
                  read_lmm_public_results_from_pinned_run(pinned_run)
              )
              sealed_record = pinned_run.read_execution_seal()
              model_input, diagnostics = _verify_bound_current_run(
                  result, pinned_run, sealed_record
              )
              recipe = build_repeated_measures_recipe_from_validated_facts(
                  model_input, diagnostics
              )
      except _NeutralEvidence:
          return _neutral_recipe()
      return recipe if _is_recipe_shape(recipe) else _neutral_recipe()
  ```

- [ ] `_verify_bound_current_run` requires exact outer/nested identity, contract/version/producer,
  complete/converged state, public execution binding run ID/digest, current sealed-record equality
  through the same capability, sealed-record digest equality, pure owner/options validation, already-loaded
  availability, fit-method/random-effects agreement, and whole-list diagnostic validation. Translate
  only closed expected boundary errors; never log raw bytes/paths or fall back to another input field.
- [ ] Run Task 3 focused tests. Expected: PASS.

### Task 5: Regress boundaries and preserve WO-D gate

**Files:** Test all Task 0–4 paths plus `tests/contracts/test_lmm_error_contract.py` and
`tests/test_lmm_extension_seams.py`.

- [ ] Assert a valid proposal is only a plain dictionary—no proposal ID, confirmation record,
  execution key, child run ID, callable, or containment capability. Missing WO-D capability cannot
  trigger a fallback; real dispatch remains a future WO-D-gated task.
- [ ] Run the focused suite:

  ```bash
  PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
    tests/test_pinned_run_directory.py \
    tests/models/linear_mixed_effects/test_runner.py \
    tests/test_lmm_result_adapter.py \
    tests/test_lmm_extension_seams.py \
    tests/contracts/test_lmm_contracts.py \
    tests/contracts/test_lmm_error_contract.py \
    tests/agent/test_repeated_measures_recipe.py \
    tests/agent/test_repeated_measures_recovery.py \
    tests/agent/test_lmm_public_result_view.py -q
  ```

  Expected: all selected tests pass.
- [ ] Run `git diff --check`. Prove no diff in Agent orchestrator/operations/execution, HTTP routes,
  frontend, Compare, or protected Honest-DiD tests. Do not stage, commit, merge, execute a candidate,
  or claim release acceptance.

Every task receives specification-compliance review followed by code-quality review. A later task may
consider recipe registration only after those reviews and accepted WO-D Frozen Containment evidence;
nothing here authorizes a `model.rerun` dispatch.
