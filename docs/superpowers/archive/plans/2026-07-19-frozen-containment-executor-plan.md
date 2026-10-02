# Frozen Containment Executor — implementation plan

**Goal:** make WO-D strict candidate evaluation either source-attributable to
exact Git objects and fail-closed, or (only on a supported host) able to issue
separate-child evidence through validated IPC. C1 does not permit adversarial
passed evidence in source-attribution-only mode.

**Scope boundary:** this plan follows the LMM public-result adapter/Pack
transport foundation. It does not unblock time-series work or declare a
release. The six uncommitted WO-D safety files remain evidence for a later,
surgical collector migration; this plan does not merge that worktree.

## 1. Lock the threat, policy and host-matrix contracts

Create Integration-owned, versioned contracts for the same-UID adversary,
source-attribution versus executable-evidence claim, RuntimePolicy, trusted
repository IDs, fixed runner/output schema, limits and evidence records.
Specify a maintained supported-host matrix: OS/architecture, backend binary and
version range, required kernel/macOS capability, fixed Python/runtime-root
identities, fixture roots and canary expectations. The parent validates all
policy/runtime roots and rejects broad roots, symlinks, mutable/unapproved
roots and caller-supplied command/path/environment values.

Define Seatbelt as deny-default with explicit reads/writes and Bubblewrap as
empty namespace plus only explicit binds/unshared network. Define the fixed
parent-built interpreter invocation (-B -I -S) and site/bootstrap policy.
Document source-only status as non-passing and the later separate candidate
child to trusted evaluator parent IPC boundary as mandatory for any adversarial
pass claim.

Tests: contract parsing/versioning, policy digest determinism, root ownership
and canonicalisation rejection, broad-root rejection, fixed-runner/invocation
construction, host-matrix unsupported static rejection, and no raw command
public API.

## 2. Build the exact-Git materialiser

Implement an Integration-owned materialiser that resolves only configured
trusted repository IDs and exactly 40-hex commit SHAs. Use an absolute,
scrubbed hermetic Git invocation to verify the exact commit/tree object and
stream git archive; never copy a live worktree or treat a dirty check as proof.
Extract with bounded, descriptor-relative no-follow operations, reject unsafe
tar entries/paths/links and build independent candidate and evaluator snapshots
plus sorted manifest evidence.

Tests: wrong/non-commit SHA, Git environment injection, archive byte/file
limits, traversal/absolute/duplicate names, symlink/hardlink/device/FIFO
rejection, bytecode exclusion, no-follow extraction walk, distinct snapshot
roots, deterministic manifest/tree evidence and live dirty/untracked/ignored
files having no influence on the frozen Git-object result.

## 3. Implement policy adapters and the separate frozen canary

Implement Seatbelt and Bubblewrap adapters only behind validated RuntimePolicy;
adapters generate profiles with no ambient host reads and emit
backend/version/profile/root evidence. Derive a policy-template digest over
backend binary/version, RuntimePolicy, fixed interpreter/runner argv template,
runtime/fixture roots, limits and access-rule structure. Build a new minimal
canary snapshot/output root and render it from that same template; strict
execution may differ only in recorded role paths. Record both rendered-profile
digests and their template-to-role mappings, and require capability issuance to
verify strict-profile derivation before Popen. The parent, not a child,
captures and writes the audit record.

The canary result contract must separately assert frozen-input write denial,
external sentinel read/write/rename/list denial, network/DNS denial,
ignored-helper and bytecode non-importability, output-root-only writes and
required runtime/fixture reads. It must be a fresh run; candidate/evaluator
results cannot stand in for it.

Tests: unavailable or unusable backend; profile shape deny-default; every
individual assertion and result code; bounded canary streams; invalid result
schema; profile-template/role-equivalence and changed-argv rejection; no
capability after any failed/skipped assertion; current managed-host static
rejection. A supported-host canary pass is an acceptance prerequisite, not an
optional later enhancement.

## 4. Add parent-only capability and hostile-result ingestion

After all canary assertions pass, store a private opaque, atomic single-use
capability in the trusted parent registry. Bind candidate/evaluator manifest
digests, snapshot/output directory descriptor/inode identities, policy/profile
template/role-mapping digest, fixed runner inode/content digest and expiry. Do
not export helper APIs that accept arbitrary commands; delete rather than
publish a raw-command helper.

Implement parent-only ingestion from a fixed child output allowlist (C1:
result.json) using descriptor-relative no-follow opens. Capture stdout and
stderr independently as binary streams capped at 1 MiB, read/size/hash one
descriptor snapshot under aggregate limits, validate the versioned result/IPC
schema, record immutable parent audit evidence, then clean child roots safely.
Record and verify output-root device/inode before launch and after exit; accept
only regular fixed-name files with st_nlink equal to one and reject any output
inode that references a source, runtime or fixture inode. The trusted evaluator
parent owns tests, fixtures, invariant checks and final verdict. Candidate IPC,
status, passed claims and JUnit are bounded non-authoritative inputs and are
never promoted to evidence. Unexpected files, links/races, rename replacement,
invalid schema, timeout, output overflow, ingestion failure or cleanup failure
are non-passing outcomes.

Tests: replay/expiry/digest/inode/runner mismatch before Popen; no
arbitrary-command construction; fixed allowlist and link/race rejection;
hardlink and post-exit output-root/file replacement rejection;
source/runtime/fixture-inode reference rejection; per-file/aggregate/stream
limits; malformed or forged result; forged passed IPC/JUnit regression; timeout,
TERM/KILL/drain/reap; audit written only by parent; retention-before-cleanup;
and source-only mode cannot emit passed.

## 5. Migrate the collector only after supported-host acceptance

Only after steps 1–4 receive code/spec review **and** the supported-host matrix
has a recorded complete canary pass may the collector call the private
capability service. Preserve the current fail-closed early rejection when
materialisation, policy validation, canary, capability or ingestion fails. For
executable evidence, launch a separate candidate child and validate its bounded
IPC/result in the evaluator parent; never import candidate code into the
collector/evaluator process. The trusted parent must independently execute its
tests/fixture/invariant checks and own the verdict; a candidate-published
status, passed value or JUnit cannot satisfy any collector gate.

Import the smallest reviewed subset of the six dirty WO-D changes; do not merge
the WO-D worktree wholesale. Keep any execution helper private. If the required
separation cannot be retained, delete the helper and preserve static rejection.

Tests: collector rejects before command/Popen/candidate/evaluator import when
any prerequisite is absent; dynamic evidence only follows all canary,
capability, separate-child and ingestion checks; old guardrails stay green;
source-only evidence is explicitly non-passing.

## Verification and acceptance sequence

1. Targeted materialiser, policy, adapter/canary, capability and ingestion
   unit/contract tests.
2. Existing WO-D guardrail and strict-runner suites.
3. py_compile, whitespace check and focused LMM evaluation suite.
4. Supported-host full canary with retained parent audit evidence. Without this
   result, keep production execution disabled and report static rejection.
5. Controlled separate-child strict smoke with validated IPC (only after step
   4 succeeds).
6. Independent spec and code review before enabling the collector production
   path.
