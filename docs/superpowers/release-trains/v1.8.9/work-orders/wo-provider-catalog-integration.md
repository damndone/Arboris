# Work Order — v1.8.9 Provider Catalog Integration

## Scope

- Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`
- Worktree: `.worktrees/workbench-v1.8.9-wave-a`
- Formal line: `v1-8-9-provider-catalog-integration`
- Owned paths: `backend/workbench/providers/catalog.py`,
  `tests/contracts/test_v189_contract_lock.py`, this work order, the objective,
  and the handoff.
- Protected paths: all builtin provider manifests, central Agent/Notebook
  routing and compiler, runtime executors, frontend mounts, evidence producer
  contracts, and release artifacts.

## Required outcome

The builtin catalog and injected fixture catalog must be deterministic and
identity-ordered: `provider_id` is the primary key and normalized filename is
the tie-breaker. The digest must be derived from that exact order. Existing
duplicate, path-like, unresolved-reference, mutation, and fixture ordering
tests must remain valid.

## Verification boundary

Run the focused provider contract tests, the three completed v1.8.9 consumer
line suites, Python compileall, diff check, and formal verification. Browser,
provider runtime, Agent/Notebook cutover, full gate, merge, push, and tag are
out of scope.
