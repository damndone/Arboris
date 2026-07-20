# Frozen Containment Executor C2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans task-by-task. Each implementation task is separately reviewed before the next task; no candidate-execution capability may be enabled early.

**Goal:** add a supported-host-only, OS-enforced, parent-owned strict evaluation
path that converts exact frozen inputs into independently validated evidence,
or rejects before candidate import.

**Architecture:** retain C1 source-only refusal as the default.  C2 adds
typed policy/host contracts, OS adapters and a fresh canary, then a parent-only
capability/lifecycle/IPC layer.  Only after those gates pass may the WO-D
collector call a private C2 adapter; it consumes a parent verifier verdict,
not candidate files or raw process output.

**Tech Stack:** Python standard library descriptor/process primitives,
Git archive snapshots from C1, macOS Seatbelt or Linux Bubblewrap only, pytest.

---

## Preconditions and working rules

* Work only in `/Users/jiayuanren/项目规划/.worktrees/integration-v1.7.3`.
  Preserve all unrelated WO-A/B/C dirty changes.
* C1 (`backend/workbench/frozen_containment.py` and
  `tests/test_frozen_containment.py`) is a source-attribution/static-refusal
  baseline, not a partial execution path.  Keep `prepare_source_only` fail
  closed until C2 collector migration is explicitly accepted.
* Do not install a backend, modify OS security configuration, run a candidate,
  push, PR, merge or tag as part of this plan.  Supported-host canaries need a
  separately approved controlled host.
* Do not modify `backend/workbench/sandbox.py` or
  `backend/workbench/code_execution.py`.  The old `sandbox-exec` managed-host
  failure is a rejection signal, never a reason to weaken policy.
* The lane collector to migrate is
  `.worktrees/v173-evaluation-harness/scripts/collect_v173_lmm_evidence.py`.
  Integration does not currently contain its scripts/tests. Before any code
  import, create a reviewed harness manifest recording the exact lane source
  SHA, source/test relative-path inventory, per-file SHA-256, owners and test
  commands. Reject missing, extra, renamed or hash-drifted files, and bind the
  manifest to the assembled Integration SHA. Import reviewed files only; never
  merge the dirty worktree wholesale. If verbatim import is impossible, define
  the same manifest as an independent evaluator-package contract.
* C1 and C2 are separate APIs. C1 must stay source-only with no optional C2
  imports, backend invocation, host probe, capability, evaluator or execution
  entrypoint. C2 may consume sealed C1 snapshot facts but must own a separate
  private capability registry and may not treat a C1 receipt as authority.

## TDD red-test sequence and implementation tasks

### Task 1: Make C2 policy and host eligibility explicit

**Files:**

* Modify: `backend/workbench/frozen_containment.py`
* Modify: `tests/test_frozen_containment.py`
* Create: `tests/test_frozen_containment_c2_policy.py`
* Create: `tests/test_frozen_containment_c2_isolation.py`
* Create: `backend/workbench/frozen_containment_c2.py`

- [ ] Write failing tests that construct a `RuntimePolicyC2` and assert these
  exact pre-launch error codes: `C2_UNSUPPORTED_HOST` for no matching OS/arch/
  backend capability, `C2_TRUST_IDENTITY_MISMATCH` for a changed backend,
  Python, runner or ancestor chain, and `C2_POLICY_INVALID` for `/`, home,
  live repository, symlink, nested read roots, user-owned runtime or a
  caller-supplied command/environment.
- [ ] Run `pytest tests/test_frozen_containment_c2_policy.py -q`; expected
  result before implementation: import/type failures.
- [ ] Implement immutable `SupportedHostC2`, `RuntimePolicyC2` and policy
  digest/revalidation.  Require root-owned, non-writable parent chains for
  backend/Python/runner/runtime/fixture inputs; reject broad/mutable roots;
  bind explicit limits and fixed `-B -I -S` template.  Do not expose a command
  runner.
- [ ] Define injectable `HostProbeV1` and canonical `HostInstanceFingerprintV1`;
  write fake-probe tests for each exact host/backend/build/feature mismatch,
  malformed fact, and probe drift between canary and launch. Bind its digest to
  the policy/template/canary receipt/capability/verdict and re-probe immediately
  before launch. Define an allowlisted
  `TrustedEvaluatorV1` record bound to evaluator package/tree SHA, runner and
  fixture-manifest digests, fixed interpreter/runtime identities, schema, and
  exact assembled Integration SHA. Verify every identity before materialising
  and again before publishing a verdict.
- [ ] Add negative C1/C2 isolation tests: C1 cannot import/construct C2,
  invoke a backend or `Popen`, or expose `execute_c2_request`; C2 cannot
  consume a C1 receipt as a capability; and removing C2 leaves C1 refusal tests
  unchanged. `C2ContainmentExecutor` lives in the separate C2 module; it is
  never a method or optional import of `FrozenContainmentService`.
- [ ] Re-run the file; expected: all policy tests pass.  Re-run
  `pytest tests/test_frozen_containment.py -q`; expected: C1 remains passing.

### Task 2: Define pure deny-default profile renderers

**Files:**

* Create: `backend/workbench/frozen_containment_adapters.py`
* Create: `tests/test_frozen_containment_adapters.py`
* Modify: `backend/workbench/frozen_containment_c2.py`

- [ ] Write red tests that inspect rendered Seatbelt and Bubblewrap plans,
  asserting: deny-default start; no `allow default`; no `/` or home bind; exact
  enumerated read roots; one fresh write root; network denial/unshare; fixed
  backend/Python/runner argv; and a deterministic template/role mapping digest.
  Include a test where strict role argv differs by any non-role token and
  expect `C2_POLICY_BINDING_MISMATCH` before process creation.
- [ ] Run `pytest tests/test_frozen_containment_adapters.py -q`; expected:
  fail because no C2 adapter exists.
- [ ] Implement pure data renderers only.  They accept a validated C2 policy
  and parent-created descriptor identities, not raw paths/commands.  Make each
  returned plan immutable and serialize it canonically for audit.
- [ ] Define canonical `RoleBindingsV1`, mapping every role to a no-follow
  descriptor identity, access mode and backend-rendered rule. Add tests that
  reject omitted, duplicate, overlapping, broad or substituted bindings. For
  Seatbelt, assert a deny-default profile with exact literal path rules only;
  do not describe it as a mount namespace or accept lexical path policy as
  proof of descendant containment.
- [ ] Re-run both C2 policy and adapter tests; expected: pass without invoking
  `sandbox-exec` or `bwrap`.

### Task 3: Add the trusted standalone canary protocol

**Files:**

* Create: `backend/workbench/frozen_containment_canary.py`
* Create: `tests/test_frozen_containment_canary.py`
* Modify: `backend/workbench/frozen_containment.py`

- [ ] Write seven red tests, one per required canary assertion: frozen read
  works; frozen write/rename/chmod denied; external sentinel read/list/write/
  rename denied; DNS and TCP/UDP denied; ignored helper/bytecode unimportable;
  sole output root writable but sibling denied; fixed Python bootstrap works.
  Add failures for missing assertion, false/contradictory assertion,
  malformed/extra frame, timeout, overflow, non-zero exit, audit write/reread
  error and managed `sandbox_apply: Operation not permitted`; each must yield
  `C2_CANARY_FAILED` and issue no capability.
- [ ] Add trusted-fixture canaries for CPU, address-space, file-size,
  open-file, process-count and wall-clock limits; fork/setsid escape; TERM →
  KILL → reap; no surviving descendant/network listener/mount/temp/output
  residue. A fake `HostProbeV1` may make policy tests deterministic, but these
  resource/process tests need the real adapter on a separately approved host.
- [ ] Run `pytest tests/test_frozen_containment_canary.py -q`; expected: fail.
- [ ] Implement a parent-created minimal canary snapshot/output/sentinel set,
  bounded binary pipes, versioned canary frame parser and parent-owned
  append-only audit receipt. It must invoke only an adapter-rendered fixed
  argv after policy/template/identity revalidation.  It must never call a
  candidate runner.
- [ ] Implement an independent, descriptor-anchored audit/rejection sink.
  Audit publication must use FD-relative no-replace creation, file and
  directory `fsync`, then no-follow FD reread. On write/reread/retention
  cleanup failure, emit only a bounded rejection record with
  `audit_receipt: null`; never reuse or synthesize a receipt. Test retention
  cannot delete live evidence.
- [ ] Re-run the tests with a fake adapter and trusted canary fixture; expected:
  every negative case rejects and the positive fake-adapter case produces only
  a canary receipt, never evaluation evidence.
- [ ] On a separately approved real host, run the full backend canary.  Record
  OS/build/arch/backend identity/version, policy/template/profile digests,
  all seven assertions, streams hashes and audit receipt.  If any assertion
  cannot be performed, mark that host unsupported and stop; do not fall back.

### Task 4: Implement private capability, lifecycle and candidate IPC

**Files:**

* Create: `backend/workbench/frozen_containment_execution.py`
* Create: `tests/test_frozen_containment_execution.py`
* Modify: `backend/workbench/frozen_containment.py`

- [ ] Write red tests asserting unknown/replayed/expired/cross-policy/
  cross-snapshot/changed-runner capabilities are rejected before `Popen`, and
  that neither a collector response, a log, a receipt nor a C1 object can
  contain a serializable/reusable C2 capability.
  Add a spy proving no raw command, `sys.executable`, `python`, shell or
  `PATH` lookup reaches launch.
- [ ] Add red tests for deadline → TERM → KILL → bounded drain → reap;
  process-containment failure; stdout/stderr above 1 MiB; zero/multiple/trailing
  IPC frames; declared length above 64 KiB; invalid UTF-8/JSON/schema; and
  candidate `passed`/JUnit being unable to set a parent verdict.
- [ ] Run `pytest tests/test_frozen_containment_execution.py -q`; expected:
  fail.
- [ ] Implement an in-memory opaque single-use capability registry private to
  `C2ContainmentExecutor` and its one `execute_c2_request` service operation.
  Within that operation,
  materialise → fresh-canary → issue → consume must be one trusted lifecycle;
  no collector-callable step may return a capability. Bind C1 snapshot
  FDs/manifests, policy and canary receipt, rendered strict profile, output
  root identity, runner identity, exact host-instance fingerprint and monotonic
  deadline. Parent constructs the fixed launch itself; candidate receives no
  caller-provided, unbound or writable host paths. For Seatbelt, test that
  argv/env/cwd and role bindings contain only approved roles and bindings; do
  not promise hidden host literals without a synthetic-mount backend. Use exactly
  one length-prefixed `CandidateObservationV1` pipe plus bounded stdout/stderr.
- [ ] Re-run the file; expected: every malformed/forged/lifecycle case is
  non-passing and no candidate code is imported by parent tests.

### Task 5: Add hostile output ingestion and independent verdict

**Files:**

* Create: `backend/workbench/frozen_containment_ingestion.py`
* Create: `tests/test_frozen_containment_ingestion.py`
* Modify: `backend/workbench/frozen_containment_execution.py`

- [ ] Write red tests for output-root replacement, symlink/hardlink/unexpected
  entry, source/runtime/fixture inode alias, post-exit replacement, file/total
  size limit, short/changed descriptor read, malformed frame, audit overwrite,
  audit reread failure and cleanup failure.  Each expects
  `C2_INGESTION_FAILED`, no published pass and preserved parent audit failure
  metadata.
- [ ] Assert failure publication has `verdict: non_passing` and
  `audit_receipt: null`, with only the independent rejection sink retained.
  Add no-replace FD-relative audit, file/directory fsync, reread and retention
  cleanup tests; no cleanup failure may erase or replace a valid receipt.
- [ ] Add a red regression that candidate-generated `strict-suite.json`, JUnit
  or `passed: true` cannot satisfy an evaluator result when a parent fixture
  check fails.
- [ ] Run `pytest tests/test_frozen_containment_ingestion.py -q`; expected:
  fail.
- [ ] Implement descriptor-relative no-follow output inspection, bounded
  snapshot reads, exact schema validation, parent-only audit writing and
  `EvaluatorVerdictV1`.  Parent verifier consumes only trusted fixtures plus
  validated observation; it hashes every retained fact and fsync/rereads audit
  before a verdict can be published.
- [ ] Re-run the file and Tasks 1–4 files; expected: all pass, source-only
  mode still cannot return `passed`.

### Task 6: Migrate the WO-D collector only behind C2 acceptance

**Files:**

* Modify: `scripts/collect_v173_lmm_evidence.py` (copy reviewed content into
  Integration; do not alter the lane checkout)
* Modify: `tests/evaluation/linear_mixed_effects/strict_runner.py`
* Modify: `tests/evaluation/linear_mixed_effects/test_collector_guardrails.py`
* Modify: `tests/evaluation/linear_mixed_effects/test_strict_runner_guardrails.py`
* Create: `tests/evaluation/linear_mixed_effects/test_collector_c2_adapter.py`

- [ ] Write red collector tests proving a missing/failed/stale canary,
  unavailable host, rejected internal capability, malformed parent verdict or audit
  receipt rejects before command/Popen/candidate/evaluator import.  Add a spy
  proving the migrated path never invokes the old future helper,
  `sys.executable`, raw root paths or child JUnit/result.
- [ ] Run the collector test files; expected: fail until the C2 adapter exists.
- [ ] First import and verify the harness inventory manifest, including its
  exact lane source SHA and every test/source hash. Replace only
  `_run_strict_candidate_evaluation_after_frozen_containment` with a private
  typed `C2ContainmentExecutor.execute_c2_request` call. Keep `_run_strict_candidate_evaluation`
  fail-closed unless that internal service returns a successful parent verdict.
  The collector neither receives nor checks a capability, and converts only
  `EvaluatorVerdictV1` plus a valid parent audit receipt (when present) into
  metadata without reinterpreting candidate claims. Retain all protected-path/
  preflight guardrails.
- [ ] Re-run collector/strict-runner guardrail tests plus C2 tests; expected:
  static rejection remains the default and dynamic evidence only follows a
  successful parent verifier verdict.

### Task 7: Supported-host acceptance and integration evidence

**Files:**

* Modify: `docs/superpowers/release-trains/v1.7.3/release-ledger.json`
* Create: `docs/superpowers/release-trains/v1.7.3/evidence/frozen-containment-c2-<policy-digest>.json`

- [ ] Before a real run, verify the exact policy host record, backend/Python/
  runner/runtime/fixture identities, fixed runner digest, candidate/evaluator
  C1 manifests, `TrustedEvaluatorV1` allowlist snapshot and clean Integration
  SHA. Any mismatch is a recorded static
  rejection, not a retry with ambient tools.
- [ ] Run the full C2 canary on the approved host, then one controlled
  separate-child smoke using only a known trusted fixture.  Confirm all seven
  canary assertions, resource/process/fork/no-residue assertions, parent-only
  verdict, bounded streams, no child audit write, ingestion checks and cleanup.
  Retain parent audit receipts and
  hashes, not raw untrusted streams.
- [ ] Run targeted C2 tests, existing C1 tests, collector guardrails,
  `python -m py_compile` on changed Python files and `git diff --check`.
  Then run the strict LMM evidence collector against the exact assembled
  Integration SHA.  A managed macOS Seatbelt denial remains a documented
  unsupported-host result, not a passing gate.
- [ ] Have an independent code/spec review verify the evidence file matches
  the exact policy and assembled SHA.  Only then update the ledger from
  `IMPLEMENTATION_IN_PROGRESS_NO_SUPPORTED_HOST_CANARY`; C2 acceptance still
  does not pass browser, performance, Report/Operations or release gates.

## Non-bypass acceptance checklist

- [ ] C1 static refusal still has no public raw execution surface.
- [ ] Every C2 launch has fresh successful canary evidence bound to its policy.
- [ ] OS policy is deny-default for both reads and writes and denies network.
- [ ] Parent owns command construction, capability, fixtures, audit and verdict.
- [ ] Candidate source is an exact Git snapshot; candidate never shares the
  parent interpreter.
- [ ] IPC and output handling are bounded, descriptor-safe and hostile by
  default.
- [ ] The collector cannot downgrade any C2 rejection to fallback execution.
- [ ] The exact supported host, policy digest and Integration SHA have retained
  evidence and independent review.
- [ ] The managed macOS `sandbox-exec` failure is recorded as unsupported, not
  silently skipped or accepted.
- [ ] The evaluated harness inventory, evaluator allowlist snapshot, policy
  digest and evidence file all name the same exact assembled Integration SHA.
- [ ] C2 has no public capability/issuance API and C1 retains static refusal
  without C2 imports or execution behavior.
