# Workbench v1.8.9 C3 candidate-bound cutover gate

This is deterministic candidate-bound evidence for the Foundation Integration
candidate. It is not browser, provider, host full-gate, or release evidence.

## Candidate

- Candidate SHA: "da0eb1bf131463c3817cd0f3343949032b0c7f0e"
- Candidate worktree: "/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-foundation-integration"
- Runner: "scripts/v189_foundation_acceptance_runner.py"
- Sidecar manifest: "/private/tmp/workbench-v189-foundation-acceptance/run-20260819T233503479302Z-638b2cf22458/manifest.json"
- Sidecar manifest SHA-256: "0d2954c594904ce8aef73475abe3460b44a83fe5e1e92d8efa44d5afdc2e3b0c"

## Deterministic result

The runner passed its candidate identity preflight, fixed backend/frontend
product-path commands, and post-run candidate integrity check.

- Backend product-path result: "PASS"
- Frontend product-path result: "PASS"
- Post-run candidate integrity: "PASS"
- Live acceptance matrix: 15 rows
- Covered rows: 5
- Blocked rows: 10
- Matrix digest: "21c9aadecdd05719669f3ef572f003e3e3b581df43349f68bb1310e495e1132a"
- Provider called: false

Blocked rows remain in the matrix with reason codes. They are not counted as
successful execution paths and are not silently removed from the denominator.

## Fixed command

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python scripts/v189_foundation_acceptance_runner.py --candidate-worktree /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-foundation-integration --candidate-sha da0eb1bf131463c3817cd0f3343949032b0c7f0e --deterministic --output-dir /private/tmp/workbench-v189-foundation-acceptance

## Explicitly unverified

- Real browser interaction and reload durability
- External provider or LLM benchmark
- Restart/multi-worker durability of process-local authority/evidence stores
- Host full gate
- Release, tag, push, or merge

