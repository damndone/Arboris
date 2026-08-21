# Work order: v1.8.9 P0 atomic host bootstrap

## Objective

Close the production-host boundary for the shared Agent/Notebook runtime. A
host must be able to validate and install the compiler, Report evidence owner,
and server identity resolvers as one explicit, server-owned composition. No
client request may create or partially configure this bundle.

## Required behavior

1. Require the exact project/session scope and all host authorities explicitly.
2. Validate every contribution before mutating application state.
3. On any validation or composition failure, preserve the previous application
   state byte-for-byte at the binding level.
4. On success, bind one compiler, one Report owner, and both identity seams to
   the same application instance and exact scope.
5. Keep missing host authorities fail-closed; do not infer identity, provider,
   evidence persistence, or data roots.

## Non-goals

- No statistical estimator changes.
- No HTTP client-controlled bootstrap.
- No provider execution or browser acceptance claim.
- No merge, push, tag, release, or deployment mutation.

## Verification boundary

Focused contract tests and `git diff --check` prove this composition boundary
only. Browser, external-provider, cross-process, full-gate, and release
acceptance remain separate evidence layers.
