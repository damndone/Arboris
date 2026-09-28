# Work Order — v1.8.9 P1 Data Consumer Core

## Baseline

- Exact parent: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`
- Branch: `workbench-v1.8.9-wave-a`
- Worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-wave-a`
- Formal line: `v1-8-9-p1-data-consumer-core`

## Required outcomes

1. Build provenance-aware dataset and column profiles with observed, declared,
   and inferred metadata kept distinct and bounded.
2. Execute subset filters through a closed typed AST; arbitrary Python,
   pandas-query, regex, and implicit lossy coercion are rejected.
3. Derive data-operation descriptors from one server-owned declaration surface
   so Agent/Notebook/UI consumers receive the same operation identity, schema,
   preview, risk, and output-port facts.
4. Expose bounded profile/manifest/preview/confirm contracts without moving
   data algorithms into HTTP handlers or bypassing existing confirmation gates.
5. Add a schema-driven UI component and bounded provider egress contribution;
   raw, sensitive, unknown, and instruction-like data are denied by default.
6. Prove the package-local Agent/Notebook composition shape with Draft-only
   fixtures. Do not claim that production Agent/Notebook mounting is complete.

## Explicit non-goals

- No edits to the central Agent registry, Agent Context Compiler, Notebook
  planner/service, workflow runtime, evidence core, prediction research, or
  frontend section registry mount.
- No arbitrary code, shell, network, package installation, or third-party
  provider discovery.
- No automatic execution from natural language, no client-minted authority,
  no silent metadata-loss claims, and no browser, provider, full-gate, merge,
  push, tag, or release claim.

## Verification boundary

Focused backend tests must cover profile truth, closed filters, operation
manifest derivation, preview/confirmation request shape, and provider egress.
Focused frontend tests and typecheck must cover schema-driven rendering and
the preview-before-confirm interaction. Browser-visible Agent/Notebook
cutover is `NOT VERIFIED` by this line.
