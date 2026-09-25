# Retrospective — v1-8-9-p0-workflow-derived-node-identity

## Goal

# Workbench v1.8.9 P0 Workflow Derived Node Identity  ## Objective  Make workflow dataset-producing node identities deterministic and input-bound. A step specification fingerprint alone is not sufficient when the same transform is applied to different source bindings or when a chain contains repeated derivations. The node id, artifact paths, graph child, and \`node_index.json\` entry must agree on the producing step and the actual source identity, remain stable on replay/resume, and never collide across inputs.  ## Scope  - \`backend/workbench/agent/workflow_runtime.py\` - \`tests/test_v189_workflow_derived_node_identity.py\`  ## Acceptance  - Repeated identical execution against the same bound source is idempotent. - Identical transform specs against different source bindings produce distinct   deterministic node/artifact identities. - Chained numeric derivation and prepared/capability dataset lineage can write   and resume without \`node identity is not deterministic\` collisions. - Existing artifact digest, server-owned evidence port, and fail-closed path   protections remain unchanged.  ## Boundary  - Affected paths: the two paths above - Allowed paths: the two paths above - Protected paths: Agent/Notebook routes, evidence authority, registry, release state - Dependencies: current workflow produced-dataset and node_index contracts - Tests: \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_v189_workflow_derived_node_identity.py\` - Known gates: full backend, browser, production host/provider, and release acceptance remain separate

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/7 (57.1%; 57.1 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-21T10:14:30.612Z `derived_identity_red`; cause_status: `known`; cause: The existing numeric producer keys recipe, artifact and child paths only by the step fingerprint, so a second real source binding is rejected as an occupied recipe path before it can publish a distinct node.; resolution: `open`; lesson: Bind every dataset producer identity to the resolved lineage source artifact, node and content hash before writing paths or index entries.

## All errors

- #2 2026-08-21T10:14:30.487Z `formal_cli_import_error`; cause_status: `known`; cause: The shared virtualenv editable installation resolved workbench to a stale v1.8.6 worktree, so the formal CLI failed during import before dispatch.; resolution: `resolved`; lesson: Run formal CLI commands with the current worktree backend explicitly first on PYTHONPATH.
- #4 2026-08-21T10:15:07.025Z `unsupported_status_query`; cause_status: `known`; cause: A read-only process-control status query used an unsupported subcommand; devline_control.py exposes verify and index rather than status.; resolution: `resolved`; lesson: Use only the documented devline_control subcommands when inspecting formal line state.
- #5 2026-08-21T10:16:57.701Z `index_context_pack_drift`; cause_status: `known`; cause: The documented index --all inspection command stopped on an existing frozen Context Pack drift before producing an index.; resolution: `open`; lesson: Run index only against a context-consistent formal root, and treat Context Pack drift as a stop condition rather than bypassing it.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `context-drift-stops-index`: occurrences=1; cause_status: `known`; root cause: The documented index --all inspection command stopped on an existing frozen Context Pack drift before producing an index.; solution: `open`
- `devline-command-surface`: occurrences=1; cause_status: `known`; root cause: A read-only process-control status query used an unsupported subcommand; devline_control.py exposes verify and index rather than status.; solution: `resolved`
- `formal-cli-current-worktree-import`: occurrences=1; cause_status: `known`; root cause: The shared virtualenv editable installation resolved workbench to a stale v1.8.6 worktree, so the formal CLI failed during import before dispatch.; solution: `resolved`
- `input-bound-derived-node-identity`: occurrences=1; cause_status: `known`; root cause: The existing numeric producer keys recipe, artifact and child paths only by the step fingerprint, so a second real source binding is rejected as an occupied recipe path before it can publish a distinct node.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `context-drift-stops-index`: line experience occurrence(s)=1
- `devline-command-surface`: line experience occurrence(s)=1
- `formal-cli-current-worktree-import`: line experience occurrence(s)=1
- `input-bound-derived-node-identity`: line experience occurrence(s)=1

## Future guidance

- Bind every dataset producer identity to the resolved lineage source artifact, node and content hash before writing paths or index entries.
- Run formal CLI commands with the current worktree backend explicitly first on PYTHONPATH.
- Run index only against a context-consistent formal root, and treat Context Pack drift as a stop condition rather than bypassing it.
- Use only the documented devline_control subcommands when inspecting formal line state.

## Event index

- #1: `d3fc422a-ef01-4609-89c3-7752c29b833d` | 2026-08-21T10:05:02.408Z | STATE_CHANGE/line_started | incident=`a69f5748-d439-4ecc-9012-a929770a9760` | lesson_key=`frozen-context-before-start` | event_sha256=`46cb754ab84ff8b488083ed0140693712ef9f2153f3ae35de8d0e365eb46b88c`
- #2: `2f0a4b7c-8d1e-4f23-9a56-0b7c8d1e2f34` | 2026-08-21T10:14:30.487Z | ERROR/formal_cli_import_error | incident=`3a1b5c7d-9e2f-4a60-b1c3-d5e7f9a2b4c6` | lesson_key=`formal-cli-current-worktree-import` | event_sha256=`f22be8dea6c31a88eb131d0996a32e8828182cba6703e1df39c104118f1e151f`
- #3: `4b7c8d1e-2f34-4a56-b0c7-8d1e2f345a67` | 2026-08-21T10:14:30.612Z | FAILURE/derived_identity_red | incident=`5c7d9e2f-4a60-b1c3-d5e7-f9a2b4c6d8e0` | lesson_key=`input-bound-derived-node-identity` | event_sha256=`6bb0f48f3d226e65e606570b76f523c0ba6313e7090ef417c9ff04aa7bf74279`
- #4: `b2d6f8a4-1c9e-4a70-8d3b-5f2e7c1a9b6d` | 2026-08-21T10:15:07.025Z | ERROR/unsupported_status_query | incident=`c4e8a2f6-1b7d-49c0-835e-2a6f7d1b9c4e` | lesson_key=`devline-command-surface` | event_sha256=`de46a4e8d8c4a94ef8214e1bb8c086957d3b18ca6d15418520586e3519eb0d24`
- #5: `d7a1c5e9-3b8f-46d0-9c2a-7e4b1f8d5a6c` | 2026-08-21T10:16:57.701Z | ERROR/index_context_pack_drift | incident=`e5a9c3f7-2b6d-41e8-904c-7a1f5d3b9e2c` | lesson_key=`context-drift-stops-index` | event_sha256=`eadebce05a6a2d74ff3da8b630463afc1ed245c7a3ba040af9e92ba8743d0e30`
- #6: `e8c2a6f4-1b7d-49e0-835c-2a6f7d1b9e4c` | 2026-08-21T10:25:31.110Z | GATE/derived_node_identity_focused_gate | incident=`f1d7b3a9-6e2c-4a80-b5d1-9c7e3f2a6b84` | lesson_key=`source-bound-identity-and-index-merge` | event_sha256=`c973a23000d9a92aeb0c9ad52620746557f6a7b659bd47155b55a52569f37b8f`
- #7: `a4f8c2e6-1b7d-49d0-835c-2a6f7d1b9e4c` | 2026-08-21T10:25:52.164Z | STATE_CHANGE/line_completed | incident=`b6e0a4c8-2f7d-49b1-835c-2a6f7d1e9c4b` | lesson_key=`derived-identity-scoped-closeout` | event_sha256=`ee33da54452899d052bb36f57d1463fe98fc69ccb5c097b16d9173b687335641`
