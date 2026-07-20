# LMM Agent Public-Result View Design

Date: 2026-07-19

Status: **revised proposal pending review**. This document authorizes neither a recipe registration nor an
Agent operation, rerun, candidate execution, merge, release, or browser claim.

## Purpose and Boundary

WO-A's existing candidate (`5ce9824`, hardened by `a450822`) can explain a narrowly closed set of
LMM diagnostics and can construct one confirmation-bound recovery proposal. It currently accepts a
caller-provided `source` plus diagnostics. That is useful unit-level logic, but it is not a safe
Integration boundary: a caller could pair a genuine diagnostic with invented model options, or use
a valid result from a different run.

This design adds one Integration-owned, read-only bridge:

```text
runs_root + validated run_id
  └─ PinnedRunDirectory (one FD capability)
       ├─ strict LMM index/packet reads ──> verified PublicModelResult
       ├─ sealed execution-input verification
       └─ sealed execution record ──> verified executed model_options + binding
                                           └─> WO-A validated-facts functions
                                                          └─> plain proposal-shaped view only
```

The bridge is the only planned entrypoint for using the WO-A LMM candidate against persisted run
state. It creates no durable record and owns no model fact. The terminal result packet remains the
sole result source; the immutable pre-fit sealed execution record is the only source for the model
options that actually ran. Neither input alone is sufficient. Before this bridge can be implemented, WO-B and
the public-result adapter need the versioned execution binding described below; this is a prerequisite
enhancement, not an implementation authorization in this document.

The scope is deliberately one read-time `RepeatedMeasuresRecipeView`. It does **not** register
`LMM_RECIPE_ID`, modify `BUILTIN_AGENT_RECIPE_DECLARATIONS`, alter the Agent orchestrator, create a
proposal revision, call `ProposalStore`, register an operation, call `model.rerun`, make a child run,
write an artifact, or alter a result packet. Existing OLS analysis-loop dispatch remains unchanged.

## Versioned Execution Binding Prerequisite

The current public LMM result does not cryptographically bind its terminal packet to the specific run
whose inputs the Agent re-reads. Therefore an attacker or faulty caller could replay a valid LMM
packet from run A under run B and pair it with a plausible B-side execution record. The bridge must
not be implemented until the terminal packet and adapter expose this immutable C1 fact:

```json
"execution_binding": {
  "schema_version": 1,
  "run_id": "<exact current run directory id>",
  "executed_input_digest": "<64 lowercase sha256 hex>"
}
```

`execution_binding` is a required exact object in `LmmResultPayloadV1`; it is written once with the
terminal result envelope, covered by the envelope's packet digest, and cannot be derived from a
mutable standalone diagnostic or an Agent request. `run_id` is the exact producer-assigned current
run identifier, not an optional user label or a parent-rerun identifier. The producer derives it from
the trusted run creation context and asserts it equals the controlled current run-root name before
persistence.

Production ordering is mandatory. Before `handler.fit(ctx, env)`, the existing
`run_service._bg_run` worker calls its private
`_admit_lmm_execution_for_bg_run` owner, which builds and validates the canonical representation from
one pinned input snapshot, then seals it as the dedicated immutable run-relative record
`artifacts/execution/executed_input_v1.json`. It is deliberately **not** a field written by generic
`update_run_inputs_metadata`. A second seal with different canonical bytes fails closed; a
byte-identical reentrant admission returns the existing seal without rewriting. The admission owner
builds `execution_binding` from the sealed in-memory value and passes the same live admission/
`SealedExecutionInput` capability through `EstimationStage` (consumer only), `fit_from_context`, the
LMM runner, and result construction. The exact handoff is defined in the P1 amendment below. The
runner and EstimationStage must not re-read
`run_inputs.json` after admission, and no terminal packet may use a mutable post-fit input read. This
order applies to successful and terminal-failed fits.

The digest is exactly `sha256_canonical` of this *defined executed-input representation*. The
private admission owner builds it from its already validated server-side LMM request before fit and
persists it **only** as the dedicated sealed execution record. `admitted_lmm_fields` below is an
in-memory admission-local name, not a `run_inputs.json` field and not a second durable authority:

```python
{
    "schema_version": 1,
    "model_type": "linear_mixed_effects",
    "model_options": canonicalize_model_options(admitted_lmm_fields["model_options"]),
    "model_options_binding": ModelOptionsBinding.from_dict(
        admitted_lmm_fields["model_options_binding"]
    ).to_dict(),
}
```

No other generic `run_inputs` key participates: not `form`, `confirmed_payload`,
`executable_payload`, upload metadata, timestamps, diagnostics, or arbitrary metadata. This prevents unrelated mutable metadata
from changing the identity of an already executed model while keeping the exact model options and
server-owned binding in scope. The estimation/WO-B ordering must make this canonical executed payload
available before it writes the terminal packet; a terminal LMM packet lacking it is invalid, not a
legacy fallback. The standalone `fit_linear_mixed_effects(...)` entrypoint must accept a fully
validated `SealedExecutionInput` plus its live `PinnedRunDirectory`, verify before terminal persistence
that the supplied value equals the current trusted run-root seal, and pass its binding unchanged to
terminal construction. A merely well-shaped dictionary is insufficient. Without that sealed capability
it rejects terminal persistence with a stable closed error such as
`LMM_EXECUTION_BINDING_REQUIRED`; it may not create a binding by reading mutable run inputs after fit.

The strict adapter validates the exact shape, `schema_version`, nonempty `run_id`, lower-hex digest,
and `run_id == resolved current run-root name` as part of the payload, then projects a detached outer
`execution_binding` field on `PublicModelResult` alongside `artifact_*` and `source_packet_digest`.
It does not read `run_inputs.json` itself or silently synthesize the binding. The later bridge compares
the projected binding only against the fixed sealed execution record opened through the same pinned
capability: exact `run_id` and `executed_input_digest == seal.digest` are both required. This division
prevents a general public reader from acquiring Agent/run context or consulting mutable metadata while
still making a cross-run replay detectable.

## Source Preconditions

The bridge accepts only a trusted project `runs_root: Path` plus a separately validated `run_id`; it
constructs `run_root = runs_root / run_id` itself and does not accept an arbitrary run-root path, a
public-result dictionary, or an options dictionary from HTTP, UI, Agent prompt, or another run. The
allowed run-ID grammar is ASCII `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`; empty IDs, `.`, `..`, slash,
backslash, NUL, Unicode, whitespace, and every other name are rejected before filesystem access. It
re-reads the following on every call:

1. `open_pinned_run_directory(runs_root, run_id)`, the bridge-owned context manager described below.
   While the capability is open, it calls
   `read_lmm_public_results_from_pinned_run(pinned_run)`, not path-based `read_model_results(run_root)`.
   The strict adapter reads its artifact index and terminal packet through this same capability. The
   bridge selects exactly one public result whose outer values are
   `model_id="linear_mixed_effects_1"`, `model_type="linear_mixed_effects"`,
   `source_contract="linear_mixed_effects.result"`,
   `source_contract_version="1.0"`, and
   `source_producer_version="linear_mixed_effects@1.0"`.
2. one `read_execution_seal(pinned_run)` call. It uses that capability's fixed literal
   `artifacts/execution/executed_input_v1.json` reader, so seal and LMM artifact/index reads share
   the same anchored run-directory FD. It captures `fstat` device, inode, size, `mtime_ns`, and
   `ctime_ns` before and after exactly one `read(pre_fstat_size + 1)`: pre-size must be at most 1 MiB,
   identities must match, and returned bytes must be exactly pre-size. It rejects short reads,
   appended tails, duplicate-key/nonfinite JSON, and returns the detached canonical executed-input
   representation only from that byte snapshot. It never follows a link, reads outside the pinned
   child, retries, or returns a partially decoded value.

   This before/after descriptor comparison detects testable concurrent replacement/mutation races. It
   is not a claim of absolute same-UID immutability against an adversary that can modify and restore
   every observable metadata value; that stronger threat is explicitly outside this reader and remains
   governed by WO-D Frozen Containment. Such an environment is never represented as proven execution
   evidence merely because this reader passed.

## Pinned Run-Directory Capability

`PinnedRunDirectory` is the bridge's only filesystem capability for this LMM boundary, including its
small producer-side persistence protocol below. Its factory accepts trusted
`runs_root` plus an allowed run ID, opens `runs_root` as `O_DIRECTORY|O_NOFOLLOW`, then opens exactly
that child as `O_DIRECTORY|O_NOFOLLOW`. It stores only private child-FD state and a validated run ID;
it exposes no mutable or diagnostic logical path, raw `Path`, or directory FD to consumers. It is a
context manager: all temporary nested FDs close after each primitive; its root FD closes exactly once
on `__exit__`; every method rejects a closed capability.

The required public primitives are:

```python
with open_pinned_run_directory(runs_root, run_id) as pinned_run:
    public_results = read_lmm_public_results_from_pinned_run(pinned_run)
    sealed_input = pinned_run.read_execution_seal()
```

Private descriptor-relative snapshots use `O_NOFOLLOW`, directory regularity rules, pre/post `fstat`
identity comparison, and one exact-size binary read. Public callers have only fixed readers for
run inputs (admission only), the execution seal, LMM index, and LMM terminal packet; they cannot
provide arbitrary parts. The strict LMM adapter must use those fixed reads for `artifacts_index.json`
and `artifacts/model_results/linear_mixed_effects_1.result.json`; it may not call
`Path.resolve`, `Path.read_bytes`, `glob`, or path-based `read_model_results` first. A symlink, child
directory replacement, artifact/index replacement, identity mismatch, malformed index, or malformed
packet rejects before either payload is trusted or partially returned.

Tests must open a valid capability, replace `runs_root/run_id` with a symlink or another directory,
then prove both the strict result reader and input reader either keep reading the originally pinned
directory or reject its modified children—never redirect to the replacement. Tests also prove the
closed capability cannot be reused and all error paths close nested FDs. This capability prevents the
bridge from mixing an index/packet from a path-replaced run with inputs from a different run; it does
not promise absolute protection against a same-UID actor able to mutate an already-open directory and
restore all observed state.

Before **every** descriptor-relative open, mkdir, link, unlink, fsync, or read, each supplied relative
part is independently rejected if it is empty, `.`, `..`, contains `/`, `\\`, or NUL. This includes
fixed implementation parts (`artifacts`, `execution`, `executed_input_v1.json`), caller-supplied parts,
and generated temporary names; joining strings before validation is forbidden. The capability opens
each accepted component with `dir_fd`, `O_NOFOLLOW`, and the expected directory/regular-file mode, so
neither a missing nor a replacement parent is silently created/followed.

## Atomic Executed-Input Seal

`seal_executed_input_v1(pinned_run, representation)` is a dedicated protocol, not generic input
metadata mutation. It serializes the exact canonical representation to canonical JSON bytes. If the
seal path exists, it reads it through the private fixed-child snapshot primitive, compares **exact
canonical bytes**, and either returns the existing equal `SealedExecutionInput` without a write or
raises `EXECUTED_INPUT_SEAL_DIVERGENCE`. It never overwrites an existing seal: publication is
`renameat2(..., RENAME_NOREPLACE)` where supported, otherwise a tested `linkat` from the exclusive temp
to the final name followed by `unlinkat` of the temp; `EEXIST` requires reopening the final through the
anchored FD and only exact-byte identity succeeds. If those safe primitives are unavailable, sealing
fails closed rather than falling back to overwrite `rename`.

All `artifacts/execution` traversal, missing-parent handling, directory creation, temporary creation,
publication, fsync, and re-read use anchored `dir_fd` operations with `O_NOFOLLOW`; no `Path.mkdir`,
`Path.write_*`, path `rename`, or bare path re-read is allowed. A clean new run may lack `artifacts`
and/or `execution`: only then the capability may create each missing directory one component at a time
through the anchored parent FD, `fsync` that parent, reopen the new child with
`O_DIRECTORY|O_NOFOLLOW`, and verify its expected directory `fstat` identity before continuing.
Any post-create replacement, symlink, mode/type error, identity mismatch, creation race, divergent
pre-existing bytes, publication anomaly, or post-write identity mismatch is a closed failure. The
returned `SealedExecutionInput` contains only validated `run_id`, canonical bytes, and digest.

Immediately before a terminal LMM packet is written, runner/result code calls
`pinned_run.verify_sealed_execution_input(seal)`: it re-reads the controlled seal through the same
FD, compares exact bytes/digest/run ID, and rejects `LMM_EXECUTION_BINDING_INVALID` on any mutation or
replacement. It never re-reads `run_inputs.json`. Tests cover competing seals, divergent seal attempts,
atomic identical retry with unchanged seal inode/bytes, and a post-seal mutation before terminal write.

After LMM pre-fit sealing, `EstimationStage` must bypass/replace the current post-fit generic
`_persist_model_options_execution_binding` path for that handler. The executed model options and
binder carried by `ctx`, direct runner, terminal payload, and sealed representation must be exact
canonical equality—not a later read of form/executable/confirmed metadata and not a re-bound sibling.
Tests assert the generic post-fit helper is not invoked for LMM, attempts to change either option or
binder after sealing are rejected, and the terminal packet retains the pre-fit seal exactly.

   The fixed sealed `artifacts/execution/executed_input_v1.json` record must be a JSON object with
   `model_type="linear_mixed_effects"`, a nonempty `model_options` object, and a
   `model_options_binding` object. Before it is sealed, a pure non-loading validator verifies that
   exact pair and parses the canonical record with `LmmModelInput.from_dict`; it must not call
   `verify_binding_owner_for_model_type`, `_resolve_model_options_handler`,
   `bootstrap_builtin_packs`, or any registry loader.

There is no fallback from the fixed seal to `run_inputs.json`, including any historical
`executed_payload`, `confirmed_payload`, `executable_payload`, `form`, or a newly created options
binding. The Agent is explaining the run that executed, not a current draft or an intent to rerun. A
missing, malformed, stale, symlinked, concurrently mutated, owner-mismatched, or digest/run-ID-
mismatched sealed execution record is insufficient evidence.

## P1 Amendment: Pinned Durable LMM Writer

The initial implementation has a critical boundary gap: it correctly carries a live
`PinnedRunDirectory` into the LMM runner, but the runner still receives `run_root` and writes the
terminal result, diagnostic/recovery packets, and `artifacts_index.json` through raw `Path` helpers.
That splits one security claim across two unrelated filesystem authorities. This amendment replaces
only the LMM producer's persistence path. It does not convert the repository-wide legacy artifact
API in this work order.

`PinnedRunDirectory` is read/seal capability only: it has **no** public or private-to-caller LMM
packet writer. The only LMM write entrypoints live on an internal
`_LmmPinnedPersistenceFacade`, which is created by and retained inside one live
`LmmExecutionAdmission`. The facade is not constructible, retrievable, or attachable through
`PinnedRunDirectory`; it receives the exact active admission on every call and derives the pinned
directory, seal, and lease from that object. No entrypoint accepts `run_root`, a `Path`, a filename,
caller-selected relative parts, a detached seal, or a caller-supplied lease:

```python
terminal = _persist_lmm_terminal_packet(
    admission=live_admission,
    packet=terminal_envelope,
)
diagnostic = _persist_lmm_diagnostic_packet(
    admission=live_admission,
    packet=diagnostic_envelope,
    terminal=terminal_or_none,
)
recovery = _persist_lmm_recovery_packet(
    admission=live_admission,
    packet=recovery_envelope,
    terminal=terminal,
)
```

Each returned opaque `PinnedArtifactReceipt` has only the verified fixed logical identity,
run-relative path, byte SHA-256, and the exact `ArtifactRecord.to_dict()` value used in the index.
It is not a path capability. `persist_lmm_recovery_packet` requires the receipt returned by this
same open admission/facade; it rejects diagnostic-only/input-blocked flows and does not manufacture a
terminal identity. Each internal writer first proves object identity, active/open admission state,
and the admission's non-exported live scheduler lease before it touches storage. A foreign, forged,
or closed admission is `LMM_EXECUTION_BINDING_REQUIRED`/`LMM_PERSISTENCE_RECEIPT_INVALID` as
applicable and is rejected before descriptor traversal, temp creation, packet publication, or index
mutation. The LMM runner and `EstimationStage` retain the admission only until all allowed LMM
persistence has finished, then close it in `finally`.

### Fixed Records and Separation

The writer owns precisely these storage slots:

| Kind | Fixed logical path | `artifact_type` | Admission rule |
| --- | --- | --- | --- |
| execution seal | `artifacts/execution/executed_input_v1.json` | not an indexed result artifact | exact-byte idempotent seal only |
| input-invalidated tombstone | `artifacts/execution/invalidated_input_v1.<seal-sha256>.json` | not an indexed result artifact | immutable no-replace record; exact run ID and exact provisional seal digest only |
| terminal result | `artifacts/model_results/linear_mixed_effects_1.result.json` | `model_result_packet` | exactly one complete or failed terminal envelope per run |
| diagnostic | `artifacts/diagnostics/linear_mixed_effects_1.<packet-byte-sha256>.json` | `lmm_diagnostic_packet` | immutable, content-addressed diagnostic envelope; an input-blocked diagnostic has no terminal receipt |
| recovery proposal | `artifacts/recovery/linear_mixed_effects_1.<packet-byte-sha256>.json` | `lmm_recovery_packet` | immutable, content-addressed envelope and a same-capability terminal receipt |

The digest component is the lowercase SHA-256 of the exact canonical envelope bytes, not a
user-provided name. Every packet is parsed with `PacketEnvelope.from_dict`, checked against its one
allowed contract (`result`, `diagnostic`, or `recovery_proposal`), serialized by the writer with the
canonical C1 serializer, and hashed from those bytes. The terminal record uses the already frozen
path and identity from the public-result contract. Diagnostics and recovery proposals are never
declared as `model_result_packet`, never occupy the terminal slot, and are never read by
`read_lmm_public_results_from_pinned_run`. A diagnostic generated before `_fit_prepared` remains
diagnostic-only. A terminal failed result may have a diagnostic companion but must never create a
recovery packet. A recovery packet is an audit artifact, not an Agent operation, confirmation, or
execution right.

### Descriptor-Owned Publication Protocol

All traversal and writes use the pinned run-directory FD. The writer validates every *constant* and
generated component before each syscall; it opens existing directories with
`O_DIRECTORY|O_NOFOLLOW`, creates a missing controlled directory one component at a time using
`mkdirat`, `fsync(parent_fd)`, no-follow reopen, and directory `fstat`. It never calls `Path.mkdir`,
`Path.write_*`, `Path.resolve`, `Path.exists`, bare `os.rename`, `write_json`, or
`register_artifact` for an LMM-owned record.

For any new immutable packet, the protocol is:

1. serialize and validate canonical bytes before touching storage; for terminal publication, first
   call `verify_sealed_execution_input(seal)` through the same capability;
2. create a generated, validated temporary name with `openat(O_CREAT|O_EXCL|O_NOFOLLOW)` in the
   already pinned destination directory, write all bytes, `fsync(temp_fd)`, close it, and verify the
   temp is a regular file of the expected byte digest;
3. publish without replacement using `renameat2(..., RENAME_NOREPLACE)` where available, or the
   tested `linkat(temp, final, follow_symlinks=False)` then `unlinkat(temp)` fallback; finally
   `fsync(destination_dir_fd)` and re-read the final via the anchored descriptor for exact bytes and
   digest;
4. on `EEXIST`, re-open the fixed/content-addressed final through the pinned FD: exact byte identity
   is an idempotent retry, and any other bytes, non-regular target, symlink, or failed re-read is a
   closed conflict. No overwrite rename is permitted.

The terminal slot is immutable. A second terminal envelope with different bytes, a pre-existing index
record using its ID/path/type, an index containing any other LMM `model_result_packet`, or a
terminal receipt whose digest differs from the fixed file all fail with a stable non-disclosing
`LMM_TERMINAL_PERSISTENCE_CONFLICT`. This check uses the index snapshot described below as well as
the filesystem slot; a `lexists` pre-check is not sufficient. A crash after terminal file publication
but before index publication leaves an intentionally orphaned immutable file. A later retry may only
reconcile it by re-reading its exact bytes, reconstructing the same receipt, and adding the one
missing matching index record. It may never delete, replace, or silently choose a different terminal
packet.

### Index Transaction and Its Limits

`artifacts_index.json` remains the existing shared filename and exact
`{"schema_version":1,"artifacts":[...]}` wire shape. The capability owns its LMM read-modify-write:
while holding a capability-private run-level writer admission token, it reads one bounded descriptor
snapshot of the index, parses duplicate-key/nonfinite-safe JSON, validates every existing record as a
full `ArtifactRecord.to_dict()` shape, validates its own candidate record, applies the fixed identity
rules, and serializes the complete replacement index to canonical bytes. The admission token is an
anchored `O_CREAT|O_EXCL|O_NOFOLLOW` lock file with a fixed private name. `EEXIST` is
`LMM_PERSISTENCE_BUSY`; it is not automatically reaped, because a pathname's age cannot prove a
writer is dead. A crash may therefore require an explicit offline/operator recovery decision rather
than an unsafe automatic unlock.

With the token held, the replacement index is written to an exclusive temp, file-fsynced, atomically
renamed over the *index pathname* within its already pinned parent directory, then parent-fsynced and
re-read through the same FD. The writer verifies that the canonical re-read value contains exactly
the candidate record once and preserves every pre-existing record byte-for-byte at the JSON-value
level. It releases the admission token only after this verification; cleanup uses anchored unlink and
parent fsync. If index publication fails after an immutable packet has been published, the operation
returns a closed persistence error and leaves the packet recoverable only by the exact reconciliation
rule above.

This makes the packet-before-index ordering crash-safe for strict readers: a reader can observe the
old index (and ignore a new orphan), or the new index referring to an already fsynced final packet;
it must not observe a new index that points to an unpublished packet. It is **not** a claim that POSIX
atomically commits both files, that `O_EXCL`/`flock` controls non-participating processes, or that a
same-UID hostile actor cannot replace files and restore metadata. The bounded before/after identity
checks and post-publication re-reads detect testable substitutions; WO-D remains responsible for a
stronger execution threat model. Until a run scheduler guarantees one writer per run or every legacy
index writer is migrated to the same protocol, concurrent legacy `write_json`/`register_artifact`
calls are outside this LMM protocol and make that run ineligible for trusted LMM persistence.

Index uniqueness is exact and fail-closed:

- no duplicate `artifact_id`, normalized `path`, or `(artifact_type, sha256)` exists anywhere in the
  validated index;
- the only LMM terminal identity is
  `("linear_mixed_effects.result", "1.0", "linear_mixed_effects_1")`, represented by exactly one
  `model_result_packet` at the fixed path;
- a retry may retain an existing record only when all eight `ArtifactRecord.to_dict()` fields match
  the receipt exactly; a same path/ID with any changed digest, inputs, config hash, step, or code
  version is a conflict, not an update;
- a diagnostic/recovery record must use its digest-derived path and ID, may be retried only with the
  same complete record, and cannot be promoted to a terminal type.

### Errors, Cleanup, and Compatibility

All writer errors are stable codes without raw paths, packet bytes, exception text, or partial index
contents: `LMM_PERSISTENCE_UNSUPPORTED`, `LMM_PERSISTENCE_BUSY`,
`LMM_PERSISTENCE_INVALID_PACKET`, `LMM_PERSISTENCE_CONFLICT`,
`LMM_TERMINAL_PERSISTENCE_CONFLICT`, and `LMM_PERSISTENCE_IO_FAILED`. A failure is raised to the
estimation boundary; it must not be replaced by an in-memory success or an OLS fallback. The writer
closes every nested file/directory FD in `finally`, unlinks only its own verified temp and admission
token via anchored operations, and fsyncs the affected parent after successful removal. It never
removes a final immutable artifact, an unknown lock, or an existing index. Cleanup failure is included
in the closed failure outcome. Tests must expose descriptor-close hooks to prove no leaked nested FDs
on every error branch.

`workbench.artifacts.write_json` and `register_artifact` remain legacy APIs for pre-existing
non-LMM flows. They are not security equivalents and must not be called by
`engine/packs/linear_mixed_effects`, the LMM runner, the LMM result builder, or LMM error persistence.
This amendment does not change their historical behavior. Any future migration of other producers
needs a separate compatibility design, scheduler rule, and test plan; it may not silently broaden
this LMM capability.

## P1 Review Amendment: Admission, Capability, and Failure Semantics

This section supersedes any earlier wording that identifies
`run_inputs.json::executed_payload` or the post-fit generic
`_persist_model_options_execution_binding` field as the LMM execution authority. Those generic
fields are historical metadata and are never read, written, or used as a fallback by this protocol.
The only LMM executed payload is the canonical, immutable value in
`artifacts/execution/executed_input_v1.json` (the *sealed execution record* below).

### Current implementation is not fulfillment

The current provisional `PinnedRunDirectory` implementation still exposes
`logical_path: Path` and public arbitrary-part `read_regular_snapshot(parts, max_bytes)`. Those are
known Task 0 non-compliances, not accepted features of this design: they make it possible for a
consumer to acquire a raw-path escape or choose a non-fixed read target. No review, test pass, or
candidate claim may describe the capability as satisfying this specification until Task 0 removes both
public surfaces, replaces them with fixed named operations, and proves their absence by RED-to-green
tests. The same provisional code is not an authorization to wire the LMM writer into production.

### One pre-fit admission owner

The concrete production owner is a new private
`workbench.services.run_service._admit_lmm_execution_for_bg_run(...)`, called exactly once by the
existing `run_service._bg_run` worker immediately before `_run_workflow(...)` for an LMM run.
`_submit_run(...)` remains responsible only for creating the ordinary run and scheduling `_bg_run`; it
does not mint a process-local LMM lease. The already validated server-side request is the sole
construction source for the execution record. The worker opens the trusted `runs_root/run_id`
capability, takes the scheduler's exclusive LMM writer lease, and takes **one** pinned
`run_inputs.json` snapshot only as a same-run proof: its canonical `model_type`, canonical
`model_options`, and canonical `model_options_binding` must each exactly equal the corresponding
server-owned request field, and its trusted run identity must equal `run_id`. Missing, extra,
non-canonical, or unequal fields fail before sealing with `LMM_EXECUTION_INPUT_MISMATCH`; admission
may never select one side, merge fields, or consult a generic payload. It constructs the canonical
record from the request before
`EstimationStage` or a handler is entered:

```json
{
  "schema_version": 1,
  "model_type": "linear_mixed_effects",
  "model_options": { "...": "canonical validated options" },
  "model_options_binding": { "...": "canonical server-owned binding" }
}
```

It seals these exact bytes once and returns a non-forgeable, process-local
`LmmExecutionAdmission(pinned_run, writer_lease, sealed_execution_input)` to
`EstimationStage`. No caller may construct this object from a dictionary, a run path, a directory FD,
or a deserialized seal. `EstimationStage`, direct LMM fit, and every LMM terminal/error writer accept
only that live admission; they do not call `update_run_inputs_metadata`, do not persist a generic
post-fit payload, and do not reopen `run_inputs.json`. The binding digest is the SHA-256 of these
exact sealed bytes. Thus “executed_payload” means this record at this boundary, rather than a
similarly named mutable field elsewhere.

If server validation rejects the LMM request before this equality proof/seal, `_bg_run` may create a
private, non-serializable `LmmInputBlockedAdmission` instead. It has the same pinned run identity and
one diagnostic-only lease, but contains no seal, terminal writer, recovery writer, or model-result
right. `_LmmPinnedPersistenceFacade.persist_input_blocked_diagnostic(...)` accepts only this exact live
object and can publish one immutable diagnostic packet; every terminal, recovery, or generic writer
call fails closed **except** for the facade's one descriptor-relative diagnostic-index mutation: it
writes exactly the matching immutable `lmm_diagnostic_packet` `ArtifactRecord` and no other index
record. The generic index API remains forbidden, as do terminal/model-result and recovery records.
Thus an input-blocked run can retain its required diagnostic without
inventing a sealed execution input or falling back to a legacy writer.

This **pre-seal** rejection is intentionally distinct from the post-seal invalidation protocol below:
because it has no seal, it creates no invalidated-input tombstone.

Admission is one-write and fail closed within a live `_bg_run` invocation: a reentrant second
admission must prove the same sealed bytes and return the same live lease, or return
`LMM_EXECUTION_ADMISSION_CONFLICT`. A handler invoked without a live admission returns
`LMM_EXECUTION_BINDING_REQUIRED`. This ownership rule applies to complete, validation-failed, and
unexpected-fit-failed paths alike; none may create a later generic execution record.

### P1 independent-review amendment: sealed-input commitment state

Sealing proves a candidate input record, not yet a right to execute it. For each exact `(run_id,
seal_digest)` pair, the private scheduler/admission lock owns this state machine:

```text
PROVISIONAL_SEALED
  ├─ final locked input/state proof succeeds → COMMITTED_EXECUTION
  └─ final locked input/state proof fails    → INVALIDATED_INPUT_BLOCKED
```

Before `EstimationStage` starts, the admission owner performs its final proof while holding that
lock. Only a `COMMITTED_EXECUTION` admission may enter fitting. Every terminal packet/index write and
every recovery packet/index write must reacquire the same lock and, **before descriptor traversal or
mutation**, recheck the exact live run ID, seal digest, committed state, open admission, and absence
of an invalidation tombstone.

If a final proof fails after a seal exists, the owner performs no fit, retry under the old run ID,
terminal write, or recovery write. While holding the lock it first creates this canonical,
no-replace tombstone, fsyncs the file and parent directory, and re-reads/validates it through the
pinned capability:

`artifacts/execution/invalidated_input_v1.<seal-sha256>.json`

```json
{
  "schema_version": 1,
  "run_id": "<exact pinned run id>",
  "seal_digest": "<64 lowercase sha256 hex>",
  "reason_code": "<stable LMM_* input/state code>"
}
```

The path and body must bind the same exact run/seal pair; the record contains no raw input, path,
stack trace, or free-form failure text. Creation uses the same descriptor-relative safe primitive as
other fixed artifacts (`O_EXCL`/no-replace, no symlink following, file and parent fsync); an existing
file is accepted only when its canonical bytes exactly match the pinned run/seal/reason tuple.
Divergent, symlinked, replaced, unreadable, or not-provably-fsynced tombstones fail closed.

Only after that tombstone is durable does the owner atomically demote and revoke the full admission
and mint one private `LmmInputBlockedAdmission`. This post-seal blocked capability carries only the
run identity, tombstone identity, and one diagnostic-only lease: it cannot expose the seal, regain
terminal/recovery authority, invoke generic indexing, write a model result, or upgrade back to a
full admission. Its diagnostic write rechecks the same blocked state and tombstone and may publish
exactly one diagnostic packet and matching `lmm_diagnostic_packet` index record. A retry creates a
new run ID and cannot erase or replace the old tombstone.

The WO-A public reader consumes only a valid terminal model-result record. It ignores seals and
tombstones as result data and must never synthesize a public result, failed terminal packet, or
recovery record for an invalidated run; such a run simply has no qualifying public terminal result.

**Current-source noncompliance:** at this amendment there is no implementation of the three named
states, no sealed-digest no-replace/fsynced invalidation tombstone, no atomic full-admission
demotion, and no terminal/recovery state recheck. Existing early admission code therefore does not
satisfy this protocol until the RED tests and implementation below land.

### Exact object-identity handoff

`LmmExecutionAdmission` is private, non-serializable, non-copyable, and has no global registry key.
Its constructor is callable only by `_admit_lmm_execution_for_bg_run`; `__reduce__`, JSON/mapping
conversion, `copy.copy`, and `copy.deepcopy` fail closed. Its filesystem capability, writer lease, and
seal are private fields; no context dictionary, artifact, manifest, event, error payload, or trace
serializes any part of it.

For an LMM worker, `_bg_run` passes the *same object* by keyword only:

```python
_run_workflow(..., lmm_execution_admission=admission)
```

`_run_workflow` accepts that private optional parameter solely to install the exact object identity in
a private `RunEnv` carrier field. `RunEnv` exposes no public getter, serializer, or replacement
setter; its internal LMM consumer hands the same object directly to `EstimationStage`, then to the
LMM handler/runner/writer. Each seam must preserve `is` identity, not reconstruct an equivalent
seal/lease. `ModelingContext`, artifact metadata, `run_inputs.json`, globals, caches, and a late
`open_pinned_run_directory` call are prohibited as alternate carriers or recovery paths.

Direct calls to `_run_workflow`, a CLI workflow entrypoint, a test helper, or any other execution path
that selects `linear_mixed_effects` but does not supply this live object fail before estimation with
`LMM_EXECUTION_BINDING_REQUIRED`. They may not create an admission, look one up globally, reopen a
run, deserialize a stored value, or fall back to the legacy writer. This is a deliberate C1 boundary:
the sealed record is durable evidence, but it cannot recreate authority after the worker ends.

The lease, capability, and receipt are deliberately process-local. If the worker or server stops,
the existing `_mark_interrupted_if_dead` lifecycle marks the run interrupted; it must not auto-resume
the LMM workflow or recreate a lease from disk. A user retry goes through `_submit_run` and therefore
creates a new run ID/admission. The only permitted recovery for the old run is a separate,
coordinator-owned exact orphan reconciliation operation: it may open the old pinned run, acquire a
fresh *reconciliation-only* lease, and add exactly the missing index record for a verified already
published packet/seal digest. It cannot rerun fitting, create a new terminal packet, use a prior
receipt, or turn an interrupted/persistence-incomplete run into complete without satisfying the
publication checks. This operation is unavailable until its own authenticated operator/API boundary
and tests are implemented; no background startup repair is permitted.

For the same reason, the read-only bridge does **not** treat a later `run_inputs.json` snapshot as
the executed-options authority. It reads the fixed execution seal through the already pinned
capability, parses the sealed canonical record, and requires both its exact bytes/digest and
`execution_binding.run_id` to equal the terminal packet. `run_inputs.json` may be checked by
admission before fit, but cannot be used by the bridge to replace, supplement, or recover a missing
seal. This supersedes earlier bridge wording that compared the packet digest to a generic
`run_inputs.json::executed_payload` snapshot.

### Exact snapshot primitive and no raw escape hatch

For a regular file whose pre-read `fstat().st_size` is `size`, the private fixed-child snapshot
primitive first requires `0 <= size <= max_bytes`, performs exactly
one `read(size + 1)`, and accepts only `len(bytes) == size`. A shorter read—even if it is valid JSON
or a valid prefix—is `PINNED_SNAPSHOT_SHORT_READ`; a longer read is
`PINNED_SNAPSHOT_SIZE_CHANGED`; post-read identity must still equal the pre-read identity. There is
no retry or partial decode. This is deliberately stricter than a single `read(max_bytes + 1)` with
only an upper-bound check, which can accept a truncated valid prefix.

`PinnedRunDirectory` exposes neither `logical_path`, `run_root`, `Path`, raw directory FD, arbitrary
relative-part reader, nor a method that returns one. Its public read operations are named fixed
operations (`read_run_inputs_snapshot`, `read_lmm_index`, `read_lmm_terminal_packet`, and
`read_execution_seal`); component traversal is private implementation detail. Test-only fault
injection is passed at factory construction and cannot be obtained from a production capability.
Any implementation that exposes a raw path or FD is non-compliant.

### Opaque receipts and durable recovery linkage

`PinnedArtifactReceipt` is an opaque, non-serializable, process-local capability—not a dataclass
with a public path, record, or digest fields. At construction the open `PinnedRunDirectory` creates
a cryptographically random capability nonce; every receipt adds a fresh random receipt nonce and is
registered only in that admission's private facade table. Every writer verifies both nonces, the same
live admission/facade object, its non-exported active writer lease, open state, and immutable receipt
facts before use.
`__reduce__`, mapping conversion, and public constructors are forbidden. Closing the capability
invalidates every receipt, and a receipt from another open capability—even for the same run and
identical artifact—is rejected as `LMM_PERSISTENCE_RECEIPT_INVALID`.

Only private writer code can recover the receipt's internal terminal artifact facts. A recovery
packet must contain the terminal packet byte SHA-256 and fixed terminal identity in its validated
audit reference; the writer derives and verifies those values from the same receipt, rather than
trusting caller fields. The recovery index record carries the same terminal digest in validated
dependency/audit metadata where the existing schema permits it; otherwise persistence is rejected
until a versioned record extension is designed. A recovery artifact is therefore durably auditable
after its in-memory receipt expires, while the receipt itself cannot be replayed or forged.

### Enforceable single-writer boundary

The private `O_EXCL` token is not by itself authority over legacy writers. Before enabling LMM for a
run, `run_service._bg_run` calls its private `_admit_lmm_execution_for_bg_run` owner to issue a live
`LmmRunWriteLease` from the scheduler's per-run admission table and mark that run's write topology as
`lmm_pinned_v1`. The only scheduler dispatch for that topology passes the lease to the pinned LMM
writer; legacy `write_json`,
`register_artifact`, and generic post-fit writers are rejected at dispatch with
`LMM_LEGACY_WRITER_FORBIDDEN` and receive no lease. The pinned writer requires that lease before every
packet/index operation and also takes its private token. If the scheduler cannot prove this topology
(including a resumed historical run), it refuses admission with `LMM_SINGLE_WRITER_REQUIRED`; it does
not “best effort” coexist with legacy writers.

At each read-modify-write boundary, the writer records the index descriptor identity and canonical
bytes and rechecks them before and after publication. An injected or observed raw legacy mutation
between those checks is `LMM_LEGACY_WRITER_CONFLICT`, leaves no receipt, and permits only the exact
orphan reconciliation rule. This makes coordinated use enforceable and testable. It does not claim to
defeat a non-participating same-UID process that writes after a successful return; such a process
violates the scheduler invariant and remains outside this filesystem protocol/inside WO-D's stronger
threat model. LMM must remain disabled for runs where that invariant cannot be established.

### Publication outcomes, retry, and error mapping

Every persistence operation returns a receipt only after its final packet, index record, required
fsyncs, and descriptor re-read checks have succeeded. No API may convert a persistence exception to
an in-memory model success, a legacy write, an OLS result, or a fabricated terminal failure packet.
`LmmPersistenceError` is mapped at the estimation/service boundary to the stable structured LMM
error contract (code, safe category, retryability, and no raw filesystem detail):

The generic `errors.json`, manifest mutation, `write_json`, and generic error-persistence fallback
are not authorized for an admitted LMM run. For a persistence failure that cannot publish a trusted
diagnostic or terminal packet, the same private facade uses a descriptor-relative,
`LmmLifecycleFailureSink` bound to the live admission to record only the stable `LMM_*` code, run ID,
and retryability as non-result lifecycle state. It cannot write an artifact index, result packet,
generic payload, exception text, or success state. If this sink cannot durably publish, the run stays
`PERSISTENCE_INCOMPLETE` with no receipt; a caller receives the same safe error code. Existing generic
lifecycle files remain available only for non-LMM runs and must be denied at dispatch for
`lmm_pinned_v1`.

| Condition | Observable outcome | Retry / reconstruction rule |
| --- | --- | --- |
| Lease/token acquisition, seal verification, temp write, packet fsync, or packet re-read fails before final publication | no receipt and no trusted terminal packet | terminal request fails with its stable `LMM_*` code; a scheduler-authorized retry must use the same sealed record and a fresh valid lease |
| Final packet is fsynced but index publication/token/fsync/re-read fails | no receipt; run state is `PERSISTENCE_INCOMPLETE`, never `complete` | only coordinator-mediated exact reconciliation of that same final bytes/digest may add one missing index record; no delete, replacement, new terminal, or automatic lock reaping |
| A provisional seal fails the final locked input/state proof | durable exact run+seal tombstone; full admission is revoked; no terminal/recovery receipt or model-result record | only the one tombstone-bound diagnostic-only admission may publish its one diagnostic; retry creates a new run ID and cannot erase or replace the tombstone |
| A terminal or recovery writer observes `INVALIDATED_INPUT_BLOCKED`, a tombstone, changed seal, or non-committed state | no packet/index mutation and no receipt | return the stable `LMM_*` code before storage; never remove/replace the tombstone or use a generic fallback |
| Input-blocked diagnostic persistence fails | no diagnostic receipt and no terminal packet | return structured persistence failure, not an unrecorded input-blocked result; exact retry only (for a post-seal block, the durable tombstone remains) |
| Pinned lifecycle-failure sink fails | no lifecycle receipt, diagnostic, or terminal packet; run remains `PERSISTENCE_INCOMPLETE` | return the original stable persistence code; no generic `errors.json`/manifest/write_json fallback |
| Terminal packet is committed, then required diagnostic/recovery companion persistence fails | terminal receipt remains durable, but scheduler state is `PERSISTENCE_INCOMPLETE` and the API returns the structured companion-persistence failure | retry only that same canonical companion with the same active admission/terminal receipt; never silently omit the audit artifact or report full success |
| Token release or any parent/file fsync cleanup fails | operation is `PERSISTENCE_INCOMPLETE`; unknown token/final files are preserved | no automatic cleanup/retry; explicit coordinator/operator reconciliation first proves ownership and exact bytes |

All listed conditions, plus malformed packet, receipt misuse, unsupported safe primitive, conflict,
and legacy-writer conflict, must have a defined `LMM_*` code in
`tests/contracts/test_lmm_error_contract.py`. Estimation code catches `LmmPersistenceError` (not only
`ValueError`) and maps it once without exposing exception text. A persistence error after a model
calculation is still a failed **persistence outcome**, not valid execution evidence; strict evaluation
and the Agent bridge must reject it until exact reconciliation has completed.

### Required RED tests before code

Implementation starts with failing tests for all of the following: one admission creates the sole
sealed record and generic post-fit persistence is never called; duplicate/different admission and
missing/forged/closed admission are rejected; a short valid JSON prefix, a tail appended after
pre-`fstat`, and a normal exact-size snapshot respectively produce short-read, size-changed, and
success outcomes with one read only; `PinnedRunDirectory` has no LMM persistence method and no public
capability/receipt attribute exposes a `Path`, FD, writer, lease, or arbitrary-part reader; direct
writer calls with a foreign, forged, or closed admission fail before storage; serialized, forged,
cross-open, and post-close receipts fail; recovery stores
and verifies the terminal digest; scheduler denies legacy writer dispatch for a pinned run and an
injected concurrent legacy index mutation yields `LMM_LEGACY_WRITER_CONFLICT`; and every table row
above proves receipts/index/run-state/retry behavior with no legacy fallback.

The RED suite must additionally prove the sealed-state protocol: a valid final proof performs only
`PROVISIONAL_SEALED → COMMITTED_EXECUTION`; an invalid final proof first creates, fsyncs, and re-reads
one exact no-replace run+seal tombstone, then revokes the full admission before issuing a blocked
diagnostic-only capability. Cover divergent/existing, symlinked, replaced, and unfsynced tombstones;
concurrent terminal/recovery attempts during and after invalidation; restart/orphan handling that
cannot readmit, erase, or replace the tombstone; and the one-diagnostic limit. Assert every terminal
packet/index and recovery packet/index rechecks committed state and tombstone absence before storage,
and that the public reader ignores a seal or tombstone when no qualifying terminal model result
exists.

## Result Cross-Checks

After the strict adapter has returned a result, the bridge performs these additional exact checks
before any diagnostic can reach WO-A:

| Fact | Required equality / rule |
| --- | --- |
| Outer and nested model identity | Outer `model_id` / `model_type` equal payload `model_id` / `model_type`, and equal the LMM literals above. |
| Result contract | Outer source contract/version equal the LMM result literals; payload `contract_version="1.0"`. |
| Producer | Outer `source_producer_version="linear_mixed_effects@1.0"`. |
| Terminal state | Payload `status="complete"` and `converged is True`. Failed packets are explanatory evidence only, never recovery evidence. Input-blocked attempts have no public terminal packet and are insufficient evidence. |
| Identity | `artifact_id`, `artifact_path`, `artifact_sha256`, and `source_packet_digest` are nonempty canonical adapter values; payload `result_identity` is a 64-lowercase-hex string. The bridge carries these as evidence references and never recomputes or substitutes an identity from user input. |
| Current-run binding | Projected `execution_binding.run_id` equals the trusted current run ID and its `executed_input_digest` exactly equals the digest of the fixed sealed execution record opened through that same pinned capability. A packet from run A replayed under run B is neutral even when its options are otherwise valid. |
| Executed options | `LmmModelInput.fit_method == payload.fit_method`; its `random_slope=True` means the payload random-effects specification is the random-slope form, and `False` means it is exactly `"1"`. |
| Diagnostics | The candidate's `validate_lmm_diagnostics` must accept the entire payload diagnostics list. No diagnostic is individually cherry-picked. |

`result_identity` is intentionally not recalculated from the sealed record or generic run metadata:
the current result contract does not persist all identity inputs there. Treating it as recomputable
would create a second, weaker identity authority. A future contract may add a direct cross-reference
only through a new versioned packet schema and a new design review.

## Non-Loading Owner and Availability Check

The bridge needs two independent checks and neither may cause a side effect:

1. `validate_lmm_executed_options_v1` is a new pure contract helper. It calls
   `verify_bound_model_options` only for canonicalization/hash integrity, compares the parsed binding
   directly to the locked literals `owner_model_type="linear_mixed_effects"`,
   `owner_model_id="linear_mixed_effects_1"`, `producer_version="linear_mixed_effects@1.0"`, and
   `input_contract_version="1.0"`, then calls `LmmModelInput.from_dict`. It imports neither Pack
   loader nor estimator and has no registry write. This replaces the candidate's loading
   `verify_binding_owner_for_model_type` at this Integration boundary.
2. `lookup_registered_lmm_contract_without_bootstrap` is a read-only lookup over the already-existing
   registry mapping. It must not import an estimation stage for side effects, call a loader, or mutate
   the mapping. It accepts only an already registered handler whose literal identity/contract agrees
   with the same four values. If no such handler is already available—as is true in a C1 environment
   before the LMM Pack is registered—the bridge returns the neutral recipe. It must not make a Pack
   available merely in order to explain a packet.

Tests snapshot the complete registry mapping before every good and neutral call and require byte-for-
byte-equivalent mapping membership/handler identities afterward. This rule is intentionally stricter
than the existing WO-A unit candidate, whose binding helper may resolve a model handler.

## Output and Fail-Closed Behavior

The bridge returns the candidate-compatible, detached object with exactly these keys:

```python
{
    "proposal": dict | None,
    "plan_diff": dict | None,
    "explanation": str,
}
```

The neutral value is exactly:

```python
{
    "proposal": None,
    "plan_diff": None,
    "explanation": "未提供可用于生成说明的受控 LMM 诊断。",
}
```

It is returned (without exposing a raw parser exception, path, payload, or partial result) for all
of: missing sealed execution record; an absent or plural matching public LMM result; a strict-adapter exception;
wrong outer contract, producer, model type, or model ID; missing/malformed/mismatched executed
options binding; no-follow/pinning/JSON/mutation failure; missing or mismatched versioned execution
binding; unavailable non-loading registry contract; incompatible fit method or random-effects
specification; non-complete or non-converged status; empty, malformed, unknown, blocked, or failed
diagnostics; or an unexpected candidate output. This makes a terminal failed packet neutral at this bridge even though the
standalone WO-A unit function can explain a controlled failure when called with synthetic source
data. Persisted integration must not promote a failure to a recovery-capable Agent view.

For a valid complete result, the bridge delegates only to the hardened WO-A
`build_repeated_measures_recipe_from_validated_facts(model_input, diagnostics)`. It can produce a proposal only when
every diagnostic is a verified complete warning with code
`LMM_RANDOM_SLOPE_NEAR_ZERO` or `LMM_RANDOM_EFFECTS_SINGULAR`, each action candidate is the exact
locked `lmm.simplify_random_effects_v1` / `model.rerun` / `{model_options:{random_slope:false}}`
combination, and `required_confirmation=True`. The returned proposal remains only a presentation of
a possible next action; it does not create, confirm, or execute an Agent proposal.

Other valid complete diagnostics can receive only the existing controlled explanation and no
proposal. The unbalanced-time trajectory warning, for example, remains a complete model result but
has no recovery proposal. New prose, causal claims, parameter patches, model selection, transforms,
or forecasting recommendations are prohibited.

## Compatibility and WO-D Gate

Implementation reuses—not copies—the candidate constants and functions from
`backend/workbench/agent/recipes/lmm_explanation.py` and `repeated_measures.py` at candidate tip
`a450822`: `validate_lmm_diagnostics`, the locked recovery identifiers, and the common recovery/
explanation construction logic. Integration must first extract two new explicitly prevalidated-fact
helpers—`build_lmm_explanation_from_validated_facts` and
`build_repeated_measures_recipe_from_validated_facts`—whose inputs are an already parsed
`LmmModelInput` and a complete `tuple[LmmDiagnostic, ...]`. Those helpers must not call
`validate_lmm_source`, `verify_binding_owner_for_model_type`, or any registry/loader. The legacy
candidate entrypoints retain their source-based behavior for backward test compatibility, but this
bridge never calls them and never accepts their `source` argument from a caller. The candidate must
first be merged only after ordinary Integration conflict and regression review; the extraction must
not revive older permissive behavior or duplicate the recovery vocabulary.

The bridge itself is read-only and therefore does not require a candidate evaluator. Any later path
that turns its displayed proposal into `model.rerun` must be separately registered, confirmation
bound, and rejected unless WO-D's Frozen Containment Executor provides successful capability/canary
evidence for the exact allowed execution backend. The bridge must never implement a Python fallback,
inspect an environment variable as a substitute for that capability, or bypass the fail-closed
operation boundary. Until WO-D is accepted, a user may see a conditional proposal only; no Agent or
system action may execute it.

## Non-Goals and Acceptance Conditions

This proposal does not make LMM available to the Agent registry, Agent HTTP routes, Compare, UI,
analysis-loop resolver, report generation, or release train. It does not assert browser acceptance,
performance, strict-candidate evidence, or a release gate.

It is ready for implementation review only when focused tests prove: (1) a versioned packet binds one
precise run ID and one canonical executed-input digest; (2) the good path is built from one public
result plus one no-follow, duplicate-key-safe pinned executed-input snapshot; (3) every missing,
tampered, symlinked, mutated, cross-run, failed, blocked, unknown, unavailable, or plural case returns
the exact neutral shape; (4) proposed recovery is exactly confirmation-gated and never writes or calls
an operation; (5) old WO-A unit behavior remains covered without source-interface widening; and (6) no
registry, route, execution, containment, or Pack-bootstrap bypass is introduced.
