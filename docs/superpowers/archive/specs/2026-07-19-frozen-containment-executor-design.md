# Frozen Containment Executor — C1 design

## Status

PROPOSED_FOR_IMPLEMENTATION. This document defines a deliberately narrow,
fail-closed capability for the v1.7.3 independent evaluator. It does not
approve candidate execution, a candidate, a release, or the existing G3
code.execute sandbox. A host is not a supported execution host until it passes
the complete canary protocol defined here.

## Threat model and claim boundary

The candidate is adversarial at the same UID as the evaluator process. It may
change a live working tree and restore it, load ignored helpers or bytecode,
read host material, exfiltrate over the network, forge result files, or exhaust
output and process resources. Existing G3 run_python_sandboxed intentionally
permits host reads and therefore cannot make this claim.

Materialising exact source proves source attribution only: the files made
available to a child came from the specified Git objects. In C1 source-only
mode it must never produce adversarial passed evidence. A later execution mode
may issue passed only when a candidate child is separate from the trusted
evaluator parent, communicates through a versioned, validated and bounded
IPC/result contract, and every containment and ingestion assertion succeeds.
Candidate code must never import into, or share an interpreter with, the
evaluator parent.

The executor is a separate capability, not a parameter or a permissive mode of
G3. If it cannot establish every required invariant, it records a static
rejection and never starts Python.

## Trusted Git materialisation protocol

Inputs are accepted only as (trusted_repo_id, commit_sha) pairs. The
containment service resolves trusted_repo_id through an Integration-owned
allowlist of configured repository roots; it does not accept caller-supplied
paths. Before use it canonicalises the root, rejects symlinked or missing
roots, records the trusted-root configuration digest, and uses an absolute,
approved Git executable with a scrubbed Git environment. GIT_DIR,
GIT_WORK_TREE, replacement refs, hooks and external helpers cannot be
inherited.

commit_sha is exactly 40 lower-case hexadecimal characters. Hermetic Git
invocation must resolve that exact object as a commit, obtain its tree object,
and verify that the resolved object name equals the requested SHA. It then
streams git archive --format=tar <commit>, with no live-worktree copy or
clean/dirty assertion as an input to trust. Local modifications, ignored files
and untracked files are irrelevant because they are absent from the Git
object; their existence is recorded neither as approval nor as a substitute
for object verification.

The archive extractor is hostile-input code. It enforces configured per-file,
file-count and total-byte limits before allocation; rejects absolute paths,
parent traversal, duplicate paths, non-UTF-8 names, symlinks, hard links,
devices, FIFOs, directories with unsafe modes and every unsupported tar entry;
and creates every directory/file with descriptor-relative no-follow operations.
It rejects any path escaping the dedicated fresh snapshot root. After
extraction it walks descriptor-relative with no-follow semantics, permits only
regular files and directories, rejects __pycache__ and *.pyc, and emits a
sorted relative-file manifest. Each manifest record contains path, byte size
and SHA-256; the manifest digest, commit SHA, tree SHA, Git executable/version
and archive/extraction limits form source evidence. Candidate and evaluator are
materialised independently into distinct snapshot roots.

## Versioned trusted-host runtime policy

RuntimePolicy is a versioned, Integration-owned configuration object, not a
caller-provided list of paths or command arguments. The trusted evaluator
parent validates its schema, policy digest, approved backend/version range,
fixed absolute Python interpreter identity, runtime-root identities, approved
immutable fixture identities, limits and output schema before use. Every
runtime read root is canonical, exists, has an approved owner/mode, is
read-only to the child, and is explicitly listed; a broad root such as slash,
a home directory, a repository root or an unresolved symlink is invalid.

The fixed invocation is constructed only by the parent:

    <policy-approved-python> -B -I -S <policy-approved-runner>

It receives a scrubbed environment, private HOME and TMPDIR, controlled cwd,
no inherited secrets, no PYTHONPATH/user site, and no automatic site import.
If a trusted runner needs packages, its explicit immutable runtime roots and
bootstrap are part of RuntimePolicy and its digest; child input cannot add a
site directory or executable.

Seatbelt adapters begin with deny default and add only required process,
file-read and designated file-write permissions. Bubblewrap adapters begin
with an empty mount namespace, bind only validated read roots and fresh write
roots, and unshare the network namespace; they never bind slash or an ambient
host directory. Adapter evidence records backend executable path/version,
generated-profile digest and every canonical mount/read/write root. The
parent first derives a policy-template digest over the backend binary/version,
RuntimePolicy, interpreter, runner/argv template, runtime and fixture roots,
limits, and access-rule structure. Canary and strict execution must derive
from this same template: only audited role paths (the fresh canary or strict
snapshot and its fresh write root) may differ. Evidence records both rendered
profile digests and the template-to-role-path mapping. Before consuming a
capability, the parent verifies that the strict rendered profile derives from
the approved template and that its argv has no non-role variation. The
existing G3 profiles are out of scope: Seatbelt starts with allow default and
Bubblewrap read-only-binds slash, so neither meets this contract.

## Parent-owned single-use capability

There is no public function that accepts a raw command, interpreter, script,
path or environment. The service exposes a typed evaluation request containing
only trusted repository identifiers, exact SHAs and declared fixture IDs. After
materialisation and canary success, the trusted parent stores an opaque
single-use capability in a private registry. Registry records bind:

- candidate/evaluator manifest and snapshot digests;
- descriptor/inode identities of both snapshot roots and the fixed output root;
- RuntimePolicy, policy-template, rendered strict-profile and role-mapping
  digests;
- policy-approved runner path, inode and content digest; and
- an expiry and atomic unconsumed state.

Only the parent can resolve and atomically consume that handle. Any changed
inode/digest, expired/replayed handle, backend/policy mismatch, or missing
record is a static rejection before command construction and Popen. The private
helper that performs child execution remains unexported; it must be deleted
rather than promoted if a public raw-command interface would otherwise be
needed.

## Separate frozen canary protocol

The canary is not a candidate or evaluator run and never reuses their output
as evidence. The parent creates a new minimal frozen canary snapshot and fresh
canary write root, renders the canary role from the same policy template that a
strict run will use, and runs the policy-approved argv template with fixed
Python flags. Its rendered profile/argv may differ from strict execution only
in the audited role paths. The canary must assert, with individual pass/fail
result codes:

1. the expected frozen canary input is readable but a write, rename or chmod
   there is denied;
2. a snapshot-external sentinel cannot be read, written, renamed or listed;
3. network connection and DNS resolution are denied;
4. an ignored helper and a pre-existing bytecode file are not importable;
5. only the declared fresh canary output location is writable; and
6. the fixed Python/runtime and approved fixture reads required by the runner
   still work.

The parent captures bounded binary stdout/stderr, validates the canary's
versioned result schema, checks backend exit/termination state and writes the
audit record itself outside every child-write root. A child, including the
canary, never writes an audit or pass record. Capability issuance requires all
assertions to pass in the same policy/runtime configuration and records the
canary snapshot digest, assertion results, backend/profile digest, limits and
captured-stream hashes. Backend discovery, a skipped check, or an unsupported
host is a static rejection. The current managed macOS host rejects Seatbelt
with sandbox_apply: Operation not permitted; it remains unsupported.

## Hostile child-result ingestion and lifecycle

The trusted evaluator parent owns the tests, fixtures, invariant checks and
final verdict. The candidate may return only a bounded, versioned typed
response through the declared IPC/result schema. A candidate-provided status,
passed flag or JUnit report is non-authoritative input and is never copied,
promoted or interpreted as evaluator pass evidence; only the parent's fixture
checks and final verdict can make a result passing.

The evaluator parent owns the only audit/evidence directory. The child gets
one fresh write directory and may produce only fixed allowlisted names (C1:
result.json); stdout and stderr are separate binary pipes, each capped at
1 MiB. Before launch the parent opens the output root by descriptor with
no-follow semantics and records its device/inode; after the child exits it
reopens through the trusted parent root and rejects any root inode replacement.
It opens each fixed-name result by descriptor-relative no-follow operations,
accepts a regular file only when st_nlink equals one, rejects an inode equal to
any source, runtime or fixture inode recorded in the capability, and reads one
descriptor snapshot under configured per-file and aggregate limits. It then
hashes and validates the versioned schema and declared bounds before
interpreting it. Unexpected entries, hardlinks, symlinks, rename replacements,
invalid UTF-8/JSON, overflow or schema failure reject the run.

The process budget is 120 seconds total with bounded process-group TERM/KILL,
stream drain and reaping. Timeout, incomplete capture, failed containment
assertion, failed cleanup or failed parent ingestion cannot become pass
evidence. The parent retains immutable audit evidence (source/policy/canary
digests, validated result digest, stream hashes, limits and termination state)
before descriptor-safe cleanup of child-write roots; cleanup failure is itself
recorded as failure. No unvalidated child file is retained as an audit source.

## Required invariants and evidence status

1. Exact Git objects, not live worktrees, are the only candidate/evaluator
   source input.
2. The OS backend has deny-by-default reads, designated writes and no network;
   Python guards are defence in depth only.
3. Runtime policy, interpreter, runner and roots are trusted, versioned and
   evidence-bound.
4. A separate full canary proves the generated configuration before a
   capability exists.
5. A parent-only, opaque single-use registry capability prevents arbitrary
   command execution and is bound to digests/inodes/runner and approved profile
   template.
6. Hostile output is bounded and validated by the parent before it affects
   evidence; candidate status, passed and JUnit claims are non-authoritative.
7. Missing Git, bad objects/archive, unsupported backend, failed canary or
   failed ingestion prevents candidate/evaluator import and passed evidence.

Each attempt records source identities, frozen manifest digests, policy and
backend evidence, canary results, lifecycle/ingestion state and output hashes.
Passed is unavailable in C1 source-only mode and, later, legal only for the
separate-child/validated-IPC mode above. It never substitutes for browser,
integration or release acceptance.

## Non-goals

- Replacing or weakening the existing G3 code.execute sandbox.
- Executing candidates on the current unsupported managed host.
- Solving kernel-level compromise or malicious privileged host tooling.
- Treating a static rejection, source attribution, or a canary as a candidate
  test result.
