# Workbench v1.7 Agent workbench implementation

## Goal

Implement the confirmed Agent work surface and close the smoke-test failures
without drifting from the v1.7 Global Main Agent / Chain Agent architecture.

## Phases

- [x] Identify launch command, fake-data source, and current baseline
- [x] Start Workbench and verify health plus visible UI
- [x] Exercise representative operations and failure boundaries
- [x] Review evidence for antifragility and consolidate findings
- [x] Verify process cleanup and worktree boundaries (services intentionally retained for handoff)
- [x] Confirm Agent frontend layout and write implementation design
- [x] Add durable Agent session HTTP seam with bounded read-only context
- [x] Add shared Agent surface state, Graph composer, and Agent bottom panel
- [x] Repair AI activity/result, Draft Editor lifecycle, rerun errors, and proxy default
- [x] Run focused tests, browser smoke, quick gate, then full gate at stage close
- [x] Prepare a Claude Code continuation handoff with canonical read order and remaining debt
- [x] Smoke + antifragile review on examples/datasets (4 families, isolated project)
- [x] Theme-aware Claude-Code composer bar + terminal-form Agent panel (light/dark verified)
- [x] Fix smoke findings: fork-draft visible error, x selector contract, workbench/ storage, OLS covariance honesty
- [x] Handoff §7 slice: chain-scoped read-only tools wired into HTTP turns (zero-mutation, DeepSeek live-verified)
- [x] Proposal slice: proposal listing + confirmation HTTP seam, typed AgentPanel card, structured proposal protocol/schema, stale/cross-scope fail-closed tests, and DeepSeek browser confirmation smoke
- [x] Follow-up: selection/context-scoped session rebind and event-cursor live projection
- [x] Follow-up: Agent UI usability revision (terminal-integrated prompt, Markdown projection, true circular context control, compact chrome, direct model settings)
- [x] Follow-up: confirmed-operation execution UI (confirm→execute→reconcile, canonical target derivation, typed operation status, DeepSeek browser-verified)
- [x] Follow-up: proposal decline/revision lifecycle (append-only decision, scoped HTTP seam, bounded changes editor, regression coverage)
- [x] Foundation v2.1 closeout: single-worker contract, shared lifecycle recovery, deterministic rerun browser closure
- [x] V11 first vertical slice: typed `data.column.cast` preview, confirmation, immutable child artifact/node, invalidation, reload evidence
- [ ] V11 hardening: broaden data-operation crash matrix and duplicate confirmation/browser E2E coverage
- [ ] V11 follow-up: expose `data.column.cast` to natural-language Agent only after typed manual contract is stable

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| zsh `read-only variable: status` | 1 | Renamed the probe variable to `http_code`; no application conclusion was drawn from the shell error. |
| Expected two `Generate report` buttons, found one | 1 | Re-snapshot the current Report DOM before choosing a unique locator; do not assume the toolbar action is exposed in this state. |
| macOS `find` does not support GNU `-printf` | 1 | Treat the manifest inspection as valid and replace the listing command with portable `find`/Python when needed. |
| Baseline CLI run has no `run_inputs.json` | 1 | Treat missing optional provenance as a data point; guard the inspection instead of calling `.get()` on `None`. |
| `pytest` was not on PATH | 1 | Use the repository interpreter at `.venv/bin/pytest`; no dependency or environment mutation was needed. |
| Quick gate initially selected the backend full fallback for Agent HTTP wiring | 1 | Added `backend/workbench/http/agent_routes.py` and `backend/workbench/app.py` to the existing Agent/LLM focused classification; future Agent route changes avoid the 8-minute fallback. |
| Existing Workbench tests assumed a single page combobox after Agent model selection was added | 1 | Kept the model control independently addressable as a listbox, preserving the existing operation combobox contract. |
| Quick gate reported 4 unhandled frontend errors while all assertions passed | 1 | Added provider boundary regression tests; missing lineage nodes and incomplete LLM payloads now degrade safely. Re-ran focused tests, quick gate, and full gate successfully. |

| Companion server bind failed with `EPERM` | 1 | Restarted with controlled local bind approval; mockup server is isolated under `/tmp`. |

## Constraints

- Use `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.7` only.
- Do not push, PR, merge, tag, or create another worktree.
- Do not modify existing adversarial review files.
- Smoke tests must not silently mutate project code or durable user data.
