# Work Order: v1.8.9 Hardening Integration

## Scope

This is a serial merge-and-proof line. It owns only merge commits, candidate
locks/evidence updates, integration-only regressions and the final handoff.
Feature behavior remains owned by the reviewed P0/P1 lines.

## Baseline and branch

- exact baseline: `05362b5697e10eb25fd219da003641f96eeec082`
- branch: `workbench-v1.8.9-hardening-integration`
- worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration`

## Serial order

1. P0 legacy/resume hardening, after spec and quality approval.
2. P0 evidence/Report hardening, after foreign-identity and bundle checks pass.
3. P1 data consumer, classification production, and survey extension, each only after its own review.
4. Acceptance harness as a read-only candidate-bound test/sidecar input; it must not change statistical semantics.
5. Rebuild locks/manifests and run the complete candidate-bound matrix on the resulting exact SHA.

## Owned paths

- `docs/superpowers/objectives/2026-08-19-v1.8.9-hardening-integration-objective.md`
- `docs/superpowers/release-trains/v1.8.9/work-orders/wo-hardening-integration.md`
- `docs/superpowers/release-trains/v1.8.9/locks/`
- `docs/superpowers/release-trains/v1.8.9/evidence/`
- `docs/superpowers/handoff/2026-08-19-v1.8.9-hardening-integration-handoff.md`
- integration-only tests and candidate-bound manifests explicitly added after review

## Protected paths

- root `main` and the existing C3 candidate worktree
- all feature worktrees and their owner paths
- public statistical contracts and canonical fixtures unless a Contract Change Request is approved

## Gates

- exact input SHA and clean feature worktree before every merge
- spec review then code-quality review for every line
- focused impacted tests after every merge
- provider catalog/coverage and `git diff --check`
- compileall, frontend integration and typecheck
- formal event verification and retrospective through `scripts/devline_control.py`
- candidate-bound acceptance with blocked/unavailable rows preserved
- browser/provider/full host gate/release status kept separate
