# Work order: v1.8.9 P0 Agent natural-language route bridge

## Objective

Connect the ordinary HTTP Agent turn to the same server-owned compiler used by
the explicit Agent/Notebook cutover endpoints. The provider loop remains
durable and budgeted, but analysis requests must reach a typed compiler preview
before any confirmation or execution boundary.

## Required behavior

1. Resolve the real HTTP actor/session/project identity before using a bound
   compiler; URL and model claims remain hints only.
2. Expose a narrow compiler-backed preview tool whose source text is the exact
   user turn and whose optional fields are validated by the shared compiler.
3. When a compiler is bound for the exact scope, do not expose the legacy
   proposal tool as an execution-authority fallback.
4. Preserve AgentCore persistence, step budget, abort, and typed tool evidence.
5. Missing compiler or identity remains a typed unavailable boundary; no direct
   compiler execution or client-shaped confirmation is accepted.

## Non-goals

- No direct execution from a natural-language turn.
- No statistical estimator changes.
- No browser/provider/cross-process/release acceptance claim.
- No merge, push, tag, release, or deployment mutation.

## Verification boundary

Focused route/compiler tests and `git diff --check` prove this bridge only.
Full repository, browser, external-provider, cross-process, and release gates
remain separate.
