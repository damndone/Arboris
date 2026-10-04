# Frozen Containment Executor — C2 executable-containment design

## Status and precise claim

**DESIGN ONLY — NOT IMPLEMENTED, NOT CANARY-ACCEPTED, NOT RELEASE EVIDENCE.**

C1, represented by `backend/workbench/frozen_containment.py` and
`tests/test_frozen_containment.py`, establishes exact-Git materialisation,
policy identity checks, backend discovery, and static refusal.  Its only public
preparation method ends in `CANARY_REQUIRED`; it must not start Python or
produce passing candidate evidence.  C2 is a separate implementation phase
that may begin only from that C1 fail-closed baseline.  It does not make C1's
unit tests, a discovered backend, an in-process guard, or an ordinary G3
`sandbox.py` invocation into proof of containment.

The C2 claim is deliberately narrow: on one policy-pinned, canary-accepted
host, the trusted evaluator parent may launch one frozen candidate child whose
source, inputs, runtime reads, write root, networking, process budget, IPC and
result ingestion all satisfy this document.  Only the trusted parent can turn
its independently verified fixtures into an evaluation verdict.  Candidate
`passed`, JUnit, stdout, or JSON claims are untrusted observations.

No host is accepted at present.  In particular, the managed macOS environment
where `sandbox-exec` returns `sandbox_apply: Operation not permitted` is
**unsupported**, even if the binary exists and unit tests can render a profile.

## Non-negotiable boundaries

* C2 is not a repair or replacement for `backend/workbench/sandbox.py` or
  `backend/workbench/code_execution.py`.  G3 has an explicit ambient-read
  threat model; C2 does not.
* Candidate code never imports into the collector, `FrozenContainmentService`,
  or the trusted verifier parent.  There is no `exec`, raw command, arbitrary
  interpreter, caller-supplied path, environment, or backend argument surface.
* A live candidate checkout is never an execution input.  Candidate and
  evaluator are independently materialised from the exact approved Git
  commits; dirty/untracked/ignored files are neither mounted nor treated as
  evidence.
* Python guards in the existing strict runner remain defence in depth only.
  They cannot compensate for a missing OS policy, unsupported host, failed
  canary, or failed ingestion.
* There is no bare-Python fallback.  Failure to prove the configured backend,
  fixed interpreter, runner, or profile causes a structured non-passing
  rejection before `Popen`/`posix_spawn`.

## Supported-host contract

The checked-in policy must contain an exact `SupportedHostC2` record; broad
classes such as “macOS” or “Linux” are invalid.  Acceptance is per record and
per full canary audit, not inferred from a neighbouring machine.

| Host class | Permitted only when all conditions hold | C2 status now |
| --- | --- | --- |
| macOS `arm64` or `x86_64` with Seatbelt | Immutable, absolute Apple `sandbox-exec`; policy renders deny-default Seatbelt; the process may actually apply that profile; all C2 canary assertions pass on that exact OS/build/backend fingerprint. | No accepted record. The managed macOS host is explicitly rejected. |
| Linux `x86_64` or `aarch64` with Bubblewrap | Immutable absolute `bwrap`; unprivileged namespace/mount/network features required by the policy are actually available; the adapter starts from an empty mount namespace and every C2 canary assertion passes. | No accepted record. |
| Windows, WSL, other architectures/backends, emulation, containers that hide required namespace features | No adapter is defined. | Unsupported; reject. |

Each record constrains one OS family and explicitly enumerated build(s),
architecture, backend name/version and executable identity, required
kernel/Seatbelt capability flags, fixed Python and runner identities,
runtime/fixture identity manifests, limits, and the policy-template digest.
At admission, `HostProbeV1` produces a canonical `HostInstanceFingerprintV1`:
the SHA-256 of the exact observed OS build, architecture, backend
identity/version, and required feature facts. The canary receipt, capability,
launch binding, and verdict all carry this digest. The parent probes once
before canary and again immediately before launch; any mismatch is
`C2_UNSUPPORTED_HOST` or `C2_TRUST_IDENTITY_MISMATCH`, and no capability or
verdict is produced. An OS upgrade, backend upgrade, identity drift, policy
change, unavailable feature, or stale canary record is a new host/policy
combination and requires a new canary. There is no global “Seatbelt passed
once” cache.

### Host probing is a testable, closed contract

`HostProbeV1` is an injected, typed dependency of host admission; production
uses the platform probe and tests use a deterministic fake. It returns only
the exact facts named by `SupportedHostC2`: OS family/build, architecture,
backend executable identity and version, required Seatbelt/namespace features,
and a monotonic clock. It must not run a candidate, infer acceptance from the
presence of a binary, or consult an ambient cache. A missing, contradictory,
or unparseable probe fact is `C2_UNSUPPORTED_HOST`.

The real canary is also the acceptance test for resources an API probe cannot
prove. In addition to the seven functional assertions below, it must prove the
exact policy's CPU, address-space, file-size, open-file, process-count and
wall-clock limits; dedicated session/process-group placement; TERM then KILL
and reaping; and no surviving child, grandchild, output, mount, temporary root
or network listener after termination. A fork/setsid escape, resource-limit
escape, residue, or inability of the backend to observe/reap descendants
rejects that host-policy pair as `C2_CANARY_FAILED`.

### Trusted identities and ownership

`RuntimePolicyC2` is Integration-owned and versioned.  It names only opaque
repository IDs, exact 40-character lowercase SHAs, declared fixture IDs and a
policy ID.  It must bind and revalidate, before every launch:

1. the absolute Git executable, its immutable parent chain and content/inode;
2. backend executable, fixed Python interpreter, fixed runner and every
   ancestor directory; these are root-owned, non-symlinked and not writable by
   group/other.  C2 production policy does not trust user-owned Python,
   virtualenvs, site-packages, runners, or `PATH` lookup;
3. each finite runtime and fixture read root, recursively manifested with
   no-follow descriptors; roots may not be `/`, home, a repository checkout,
   nested, or overlapping;
4. fresh parent-owned snapshot, child-write and parent-audit roots, all with
   descriptor/inode identity.  The child receives only its designated write
   root; it never receives the audit root; and
5. evaluator-parent service identity, policy digest, schema versions, stream,
   IPC, archive, CPU/memory/process-count and deadline limits.

`TrustedEvaluatorV1` is a distinct allowlisted Integration contract, not an
importable lane helper. Its immutable record includes evaluator package/tree
SHA, runner entrypoint digest, evaluator fixture-manifest digest, interpreter
and runtime identities, schema version, and the exact assembled Integration
SHA. All are revalidated in the parent before materialisation and again before
verdict publication. Candidate and evaluator snapshots are independently
archived; neither may be supplied by the collector. A policy is invalid unless
it carries an exact `TrustedEvaluatorV1` identity and its Integration SHA is
the SHA for which C2 evidence will be recorded. Drift is
`C2_TRUST_IDENTITY_MISMATCH`, never a best-effort rerun.

The fixed launch template is parent-built only:

```
<approved-backend> <adapter-fixed-flags> -- <approved-python> -B -I -S <approved-runner>
```

The inherited environment is replaced, not filtered: fixed locale; private
empty `HOME`, `TMPDIR`, XDG roots and `MPLCONFIGDIR` under the child write
root; no provider credentials; no `PYTHONPATH`, `PYTHONHOME`, user site, shell
startup, or ambient working directory.  Site packages are usable only when
they are inside an identity-pinned runtime read root and are explicitly
bootstrapped by the trusted runner.  A backend unable to support this invocation
is rejected; it may not run `python`, `sys.executable`, or a shell as a
substitute.

## OS policy, snapshots and child topology

The parent materialises two distinct C1 snapshots from exact Git trees:

```
trusted evaluator parent
  ├─ immutable evaluator snapshot + fixed runner + immutable runtime/fixtures (read only)
  ├─ immutable candidate snapshot (read only)
  ├─ parent-only audit directory (not mounted into child)
  ├─ anonymous bounded result pipe + stdout/stderr pipes (parent owns readers)
  └─ OS-contained candidate child (one fresh output root, no audit mount)
```

Seatbelt profiles begin with deny-default. They grant only process execution
needed for the already-selected backend/runner chain, fixed file reads for
enumerated snapshots/runtime/fixtures, and the exact child write root; they
deny network and all reads/writes not enumerated. The rendered profile must use
exact literal path rules for each `RoleBindingsV1` member; it must not claim
Seatbelt creates Linux-like mount namespaces or that a lexical profile alone
proves descendant containment. `RoleBindingsV1` is a canonical,
machine-checkable mapping from named roles `candidate_snapshot`,
`evaluator_snapshot`, `runtime_root`, `fixture_root`, `child_write_root`, and
`parent_audit_root` to descriptor identity, access (`read`, `write`, or
`unmounted`), and backend rendering. The parent rejects any unbound, duplicate,
overlapping, substituted, or broad path before launch. Bubblewrap begins with an empty mount
namespace, read-only binds only the enumerated roots, one writable bind for the
fresh child output root, a private temporary directory, and an unshared network
namespace.  Neither adapter binds `/`, the host home, a live checkout, the
collector directory, the parent audit root, or an ambient package directory.

The adapter also enforces the policy's process/session and resource limits.
The child is placed in a dedicated process group/session by the trusted parent;
on deadline it receives TERM, then KILL, and the parent drains bounded streams
and reaps every descendant the backend can contain.  A backend that cannot
prove the selected process-containment semantics is not C2-capable for that
host record.

Before launch, parent checks every descriptor/inode/manifest and derives a
template digest from identities, limits, read/write rule structure, backend,
Python and runner.  It renders a strict role profile only by substituting the
fresh snapshot/output role paths.  Any changed argv, path, profile rule,
identity, root inode, or template mapping is `C2_POLICY_BINDING_MISMATCH`
before launch.

## Separate canary and parent-only capability

Every C2 evaluation requires a fresh canary for the exact host-policy-template
combination; a canary is never a candidate evaluation.  The parent creates a
minimal trusted canary snapshot, fresh output root, external sentinel and
ignored-helper/bytecode sentinels, then runs the fixed canary runner through
the same backend/template as strict execution.  The role paths are the only
allowed profile difference.

The parent accepts canary success only if the trusted canary schema reports
every assertion and the parent independently validates process state, bounded
streams, output identity and audit record:

1. declared frozen input and runtime/fixture reads work;
2. write, rename and chmod of frozen input are denied;
3. read, list, write and rename of an external sentinel are denied;
4. TCP/UDP connect and DNS resolution are denied;
5. ignored helper and existing `.pyc` cannot be imported;
6. the sole declared output location is writable and a sibling is not; and
7. parent-built `-B -I -S` invocation and no-site bootstrap facts are present.

Missing, skipped, malformed, over-limit, timed-out, non-zero, partial, or
contradictory assertions are failures.  The parent writes an append-only audit
record outside child-controlled roots with policy/template/profile digests,
backend version, input/sentinel facts, per-assertion results, streams hashes
and termination state. The audit sink is independently configured and
descriptor-anchored; it is not the child output root, collector destination, or
candidate/evaluator snapshot. Publication uses no-replace creation relative to
its trusted directory FD, `fsync` of file and directory, then no-follow FD
reread. A write/reread/retention-cleanup failure may not manufacture an audit
receipt. The parent emits only `C2_CANARY_FAILED` with `audit_receipt: null`
and a bounded rejection reason to the independent rejection sink; it never
records a success by copying an old receipt. Retention cleanup runs only after
publication from a separate, tested policy and can never delete live evidence.

Only after all seven checks pass does the parent create an in-memory,
unserializable `C2Capability`. The 256-bit opaque token is known only inside
the C2 execution service's private registry (never the C1 registry), has a
short monotonic TTL, is atomically single-consumed,
and binds candidate/evaluator snapshot manifests and root FDs, output-root
identity, policy/template/rendered-profile/runner digests, canary-audit digest
and deadline.  Candidate code never receives the token.  Unknown, replayed,
expired, cross-policy, cross-snapshot, changed-root or changed-runner use is a
pre-launch rejection. The capability has no serializer, `repr` secret, public
accessor, receipt, or return value. `C2ContainmentExecutor.execute_c2_request`
is the only Integration-facing operation: inside one trusted service call it
validates the typed request, materialises snapshots, runs the fresh canary,
creates and consumes the capability, launches/ingests, and returns only an
`EvaluatorVerdictV1` or structured rejection. A collector can submit the
request but cannot obtain, cache, replay, inspect, or transmit a capability.
Materialisation, canary issuance and capability consumption may not be split
into collector-callable methods.

## Candidate IPC, hostile ingestion and verdict

The candidate runner receives only a read-only request whose facts are already
bound into the capability: candidate/evaluator manifest digests, fixture IDs,
schema version, deterministic test selection and deadline. It has no
caller-provided, unbound, or writable host path; no capability token, arbitrary
command, environment override, or audit destination. A Seatbelt adapter may
need literal approved host paths and must not claim mount-namespace semantics.
Its argv, environment, cwd, and `RoleBindingsV1` contain only approved logical
roles and bindings. A backend that requires the stronger promise that the child
cannot observe any literal host path is unsupported unless it provides verified
synthetic mount-path semantics.

The candidate may emit exactly one `CandidateObservationV1` on a dedicated
anonymous result pipe: one big-endian length prefix (maximum 64 KiB), followed
by UTF-8 JSON with an exact versioned schema.  EOF must follow immediately;
zero, multiple, trailing, invalid UTF-8, oversized or malformed frames reject.
stdout and stderr are separate binary pipes, each capped at 1 MiB, and are
hashed but never treated as verdict data.  The child output root may contain
only a fixed, schema-declared bounded file allowlist when a selected test needs
file output; it is read descriptor-relatively with `O_NOFOLLOW`, regular-file,
single-link, pre/post `fstat`, size and inode-reference checks.  Unexpected
entries, symlinks, hardlinks, replacements and parent-audit references reject.

The observation may state `status`, test measurements and error codes, but its
`passed`, JUnit or performance values are not authoritative.  The parent
validates framing/schema/bounds, runs its fixed evaluator checks over the
trusted fixtures and frozen observation, and emits a separately versioned
`EvaluatorVerdictV1`. Only this parent-built verdict may be `passed`; it binds
source manifests, policy/canary/audit digests, all input/output hashes,
independent check outcomes and termination facts. The audit writer rejects
attempted overwrite, uses no-replace FD-relative creation, `fsync`s file and
directory, and rereads by no-follow FD before publishing the verdict. If this
cannot complete, the result is `C2_INGESTION_FAILED`, `verdict: non_passing`,
and `audit_receipt: null`; its independently written rejection record binds
only nonsecret failure facts. Any ingestion/audit/cleanup failure is never an
“unknown pass”.

## Collector migration boundary

The current collector in the WO-D lane,
`scripts/collect_v173_lmm_evidence.py`, correctly fail-closes
`_run_strict_candidate_evaluation` before candidate import.  Its
`_run_strict_candidate_evaluation_after_frozen_containment` uses live roots,
`sys.executable`, path-based artifacts and a future-only raw subprocess
helper.  That helper is not eligible to be enabled as-is.

C2 migration is additive and surgical:

1. retain the existing public collector entrypoint, preflight, protected-path
   checks and current early rejection;
2. replace only the future-only helper with a private adapter that submits one
   typed request to `C2ContainmentExecutor.execute_c2_request` from the
   separate C2 module; the executor, not the collector, atomically materialises,
   canaries, issues and consumes
   its private capability. No API may return or serialize that capability;
3. consume only a parent-authored `EvaluatorVerdictV1` plus a valid parent
   audit receipt when one exists. The collector must not open candidate paths, accept child artifact
   paths, invoke `sys.executable`, reconstruct a command, or reinterpret a
   candidate JUnit/result; and
4. preserve a static rejection when C2 is unavailable.  Do not change G3
   `code_execution.py`, `sandbox.py`, or release status.

Integration currently lacks the lane collector scripts and strict-runner tests.
Before code migration, the selected harness must be imported as a reviewed,
fixed inventory: lane source SHA, every source and test relative path, SHA-256
per file, test command, and expected ownership must be recorded in a checked-in
manifest. The import rejects missing, extra, renamed, or hash-drifted files;
the manifest itself is bound to the assembled Integration SHA. This is an
explicit independent-evaluator-package contract if the harness cannot be
imported verbatim. Until inventory/import tests and supported-host acceptance pass, the
collector remains fail-closed and all release ledger entries remain NOT READY.

### C1/C2 API isolation

C1 remains source-only and has no public capability, host probe, adapter,
evaluator or execution entrypoint. C2 may depend on C1's sealed snapshot
facts, but neither imports nor mutates C1's registry/state, and C1 cannot
discover C2 through reflection or optional imports. Negative regression tests
must prove: C1 never invokes a backend or `Popen`; C2 cannot use a C1 receipt
as a capability; a C1 caller cannot call C2 execution; and disabling/removing
C2 leaves C1's static refusal behavior byte-for-byte and test-for-test intact.

## Failure codes and forbidden shortcuts

Every rejection is structured, audit-safe and happens before candidate import
where applicable.  The required code family includes:

| Situation | Required code |
| --- | --- |
| no exact host record, backend cannot apply profile, or managed Seatbelt denial | `C2_UNSUPPORTED_HOST` |
| immutable identity/ancestor/root/manifest mismatch | `C2_TRUST_IDENTITY_MISMATCH` |
| mutable/broad/overlapping root or ambient interpreter/site path | `C2_POLICY_INVALID` |
| rendered policy/argv differs from template binding | `C2_POLICY_BINDING_MISMATCH` |
| any canary assertion, stream, schema, timeout or audit failure | `C2_CANARY_FAILED` |
| missing/replayed/expired or mismatched capability | `C2_CAPABILITY_REJECTED` |
| launch, deadline, process containment or drain/reap failure | `C2_LIFECYCLE_FAILED` |
| IPC/result/output-root/schema/limit/inode/audit/cleanup failure | `C2_INGESTION_FAILED` |
| parent verifier does not independently pass all required checks | `C2_EVALUATOR_NONPASSING` |

Forbidden shortcuts: an allow-default Seatbelt profile; Bubblewrap binding
`/`; using `shutil.which`, shell execution, `sys.executable`, bare `python`,
or fallback subprocess; trusting `git status`; reusing a canary from another
policy/host; importing candidate modules in the parent; allowing a child to
write evidence; or treating failure to test a control as a pass.

## Acceptance table

| Gate | Required retained evidence | A failure means |
| --- | --- | --- |
| C1 source | exact commit/tree/manifests and C1 tests | no C2 launch |
| Host/policy | approved exact record plus identity revalidation | `C2_UNSUPPORTED_HOST` or `C2_TRUST_IDENTITY_MISMATCH` |
| Canary | all seven assertions, parent audit receipt and reread | no capability, no candidate import |
| Capability | single-use parent registry receipt bound to the canary and snapshots | no launch |
| Child lifecycle | fixed argv/profile digest, bounded streams, deadline and reaping facts | non-passing |
| Ingestion | one valid IPC frame, allowlisted output checks and parent audit | non-passing |
| Verdict | parent evaluator’s complete fixture/check record | no accepted evidence |
| Collector | existing guardrails plus C2-only adapter proof | collector stays fail-closed |
| Integration | exact assembled Integration SHA independently evaluated | no release; browser/performance/other release gates remain separate |
