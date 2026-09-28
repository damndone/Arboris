# Work Order — v1.8.9 P1 Classification ML Core

```yaml
work_package: v1-8-9-p1-classification-ml-core
lane: classification-ml
baseline_sha: c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
contract_lock_manifest_sha256: 7249f343407c299193b2e772b89202f4c7e8666c7ad3a935b8f9a1f94c4e8f7e
worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p1-classification-ml
branch: workbench-v1.8.9-p1-classification-ml
formal_line: v1-8-9-p1-classification-ml-core
```

## Scope

The lane owns the classification typed contracts, safe split and preprocessing
kernel, protocol/adapters/metrics/explanations, artifact/lineage/evidence
contribution, package-local provider declaration, and an unmounted typed
renderer. It may add tests under `tests/predictive_research/` and must leave
central Agent/Notebook/Report routing untouched.

## Dependencies and gates

- Contract Lock C0 is frozen at the baseline above.
- Workflow Truth, Evidence Core and Agent Compiler package lines exist as
  dirty, not-yet-integrated candidate worktrees; their C1 compatibility and
  real host integration are `NOT VERIFIED` and must be reported separately.
- Data Consumer Core is not a prerequisite for this package-local lane.
- The lane must not claim natural-language discovery, execution, browser or
  release readiness.

## Required acceptance

- Formal Context Pack is started before implementation and read in full.
- TDD red/green evidence covers contract failures, information-set leakage,
  split overlap/purge/embargo, fold-local transforms, holdout seal, metrics,
  calibration, adapter determinism, provider adversaries and renderer states.
- Known-answer numerical oracles, same-library regression labels, metamorphic
  checks and bounded multi-seed sensitivity are recorded distinctly.
- Backend focused suites, renderer tests, typecheck, compile/diff checks,
  formal verify and generated retrospective pass.
- Handoff records exact paths, digests, test results and all `NOT VERIFIED`
  boundaries. No commit, merge, push or tag is part of this work order.
