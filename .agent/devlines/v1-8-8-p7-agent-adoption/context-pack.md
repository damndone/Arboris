# Frozen Context Pack

Line: `v1-8-8-p7-agent-adoption`
Baseline SHA: `b418db540c5b37af68b478339d869b1722ada49e`

## Objective
# v1.8.8 Agent Chain Active-Head and P7 Adoption Plan

## Goal

Make a Chain Agent session usable when the UI focuses a historical node while
the durable Chain has advanced to another active head, then make every frozen
P7 operation reachable through the existing generic `operation.multi_step@v1`
seam. The selected node remains the explicit source context, while the session
packet and every typed inspection use the durable Chain active head. A P7
operation owns its nested request schema and adapter; the orchestrator does not
grow one dispatch branch per pack.

## Verified scope

- Worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.8-p6`.
- Baseline: `b418db540c5b37af68b478339d869b1722ada49e`.
- Live reproduction project: `/private/tmp/workbench-p7-real-qa-20260809/p7-real-qa`.
- Frozen P7 denominator: 64 declared operations, 64 registry entries, and 64
  declaration-derived request schemas.
- Reproduction: the Chain record `chain:20260809_012258_130557_28b925ab` has
  durable active head `20260809_012947_489434_fa8fea49`, while the saved Agent
  context packet says `ownership.active_head_run_id=20260809_012258_130557_28b925ab`.
  Session creation succeeds, then `inspect_node_context`,
  `inspect_operation_contract`, and `inspect_data_schema` all return
  `ChainHeadConflict`.
- Relevant design rule: the backend is the fact source for Chain context and
  must regenerate the context fingerprint; a client preview packet is not a
  write authorization.

## Non-negotiable boundaries

- Keep `ChainStore` and the read-only context tools fail-closed: a direct tool
  call with a forged active head must continue to return `ChainHeadConflict`.
- Publish only top-level operation identities in the direct contract-inspection
  tool. Workflow children are executable only under the parent
  `operation.multi_step` proposal and must not be presented as independent
  model-node operations.
- Reject unknown nested option fields instead of passing them through or
  silently dropping them. Per-operation schemas must not be family-wide
  supersets when the adapter would ignore or reject an inapplicable option.
- Preserve `owner_run_id`, `op_node_id`, node hash, and the selected historical
  node as source context. Canonicalizing the active head must not silently
  substitute a similarly named run or discard the selected node.
- Canonicalization is allowed only at session construction against an existing
  durable Chain record; any missing/invalid source context or missing durable
  head is an explicit API error, not a fallback to a nearby run.
- Recompute the canonical context fingerprint from backend lineage facts and
  publish a diagnostic explaining that the client preview was normalized.
- Keep Global Agent read-only and preserve the confirmation boundary:
  `propose_operation` creates a pending proposal; only the user confirmation
  route executes it.
- Do not change P0/P1/P2 capability contracts, P7 numerical engines, or add a
  direct operation branch for each P7 pack.

## Files and architecture

| File | Responsibility |
| --- | --- |
| `backend/workbench/http/agent_routes.py` | Canonicalize a selected-node Chain context against `ChainStore` before persisting the session packet. |
| `tests/test_agent_routes.py` | Route regression for a stale client active head, fingerprint replacement, and preserved source node. |
| `docs/superpowers/plans/2026-08-09-v1.8.8-agent-chain-active-head-p7.md` | This TDD record and browser acceptance boundary. |

The session route remains the single Workbench boundary. It will first resolve
the requested Chain scope, then derive the backend rerun context for the packet's
declared `owner_run_id` and `op_node_id`. The packet's selected-node display
evidence remains intact, while authoritative active-head fields and the
fingerprint come from `build_rerun_operation_context`.

## TDD tasks

### Task 1 — reproduce the stale packet as a red route test

- [ ] Add a real inspectable two-run fixture or extend the existing route
  fixture so a managed Chain's durable head differs from the selected source
  run.
- [ ] Post a chain session with `run_id` equal to the durable head but a packet
  whose ownership active head is the historical source run.
- [ ] Assert the returned session context is canonical: durable active head,
  source owner unchanged, and a backend fingerprint different from the forged
  preview fingerprint. Run the test before implementation and record the exact
  failure.

### Task 2 — implement the smallest backend canonicalization

- [ ] Resolve the existing Chain's authoritative head without weakening the
  requested-head mismatch check.
- [ ] Read the declared source node from the packet and derive the canonical
  context with the existing lineage validator.
- [ ] Update only active-head-dependent ownership/target fields, diagnostics,
  and fingerprint; reject malformed or unresolvable packets loudly.
- [ ] Run the focused route tests green and the existing forged-head context
  tool test to prove stale tool calls still fail closed.

### Task 3 — prove each new guard is alive

- [ ] Mutate the canonicalization anchor so the stale packet's old active head
  is persisted again; assert the new route test fails with the actual mismatch.
- [ ] Mutate fingerprint derivation so the client fingerprint survives; assert
  the fingerprint assertion fails with the actual value mismatch.
- [ ] Mutate the source-owner preservation assignment; assert the source node
  assertion fails rather than accepting a different owner.
- [ ] Each mutation harness must assert its source anchor exists, assert the
  file hash changes, prove behavior changes, print the real pytest error, then
  restore the original bytes and rerun the focused green suite. A file-only or
  no-op mutation is invalid evidence.

### Task 4 — real Chain Agent P7 acceptance

- [ ] Restart the local backend from this worktree and retain the existing
  DeepSeek provider-store configuration.
- [ ] In the browser, open the real project, select a source/raw node that is
  valid for a composed workflow, and ask the Chain Agent for one typed
  `operation.multi_step@v1` proposal containing a registered P7 step.
- [ ] Verify the transcript contains successful context/contract inspection,
  one pending typed proposal, and no guessed run/node identifiers.
- [ ] Confirm it through the visible confirmation control, poll the durable
  operation record, and inspect the resulting P7 artifact/provenance. Do not
  count a provider prose answer, a unit-test green, or a Global Agent
  `ERR_NO_EXEC_TOOL` as execution evidence.
- [ ] Keep Notebook/Report failures and the Genesis draft-editor mismatch as
  explicit concerns until independently fixed; they are outside this narrow
  active-head patch.

### Task 5 — verification and handoff

- [ ] Run focused backend/frontend tests, `git diff --check`, and the relevant
  P7 workflow integration suite.
- [ ] Re-run the browser chain and capture exact success/failure evidence,
  including operation status and artifact identity.
- [ ] Append any material GAP/FAILURE/STATE_CHANGE through formal devline
  control, regenerate the retrospective if the line requires it, and commit
  locally with an English message. No push, PR, merge, tag, or release.

## Explicitly not claimed by this plan

- This plan does not claim all 64 P7 operations have been individually called
  by a human; the generic registry/runtime coverage remains the denominator,
  while browser acceptance proves a representative natural-language path.
- This plan does not make the Global Agent mutating; its read-only boundary is
  intentional and remains a separate consumer-scope decision.
- This plan does not repair the Genesis params-only editor wiring or report
  provider failures; both remain visible follow-up defects.

## Execution update — 2026-08-09

Completed in this worktree:

- Active-head canonicalization and fail-closed stale-context route coverage.
- Nested P7 binding/option schemas and `consumes_input_frame` publication from
  the registry-owned declarations.
- Exact per-operation option boundaries for all 64 P7 operations; unknown
  fields are rejected and no family-wide option superset is used where an
  adapter would ignore the option.
- Generic P7 workflow execution remains the only runtime seam. The all-64
  adapter call guard is green; no per-pack orchestrator branch was added.
- Design-only VIF support uses only neutral algebraic metadata required by the
  frozen engine. Workflow failures preserve the original failed step and
  guard message.
- Direct contract inspection advertises only top-level operation IDs; child
  IDs remain reachable through the parent workflow vocabulary.

Live acceptance recorded so far:

- DeepSeek browser chain: `diagnostics.vif` completed from a selected dataset
  node and produced a persisted VIF artifact.
- DeepSeek browser chain: `missingness.profile` completed from the same
  dataset node and produced a persisted missingness artifact.
- A model-node VIF request was refused with an explicit dataset-stage scope
  explanation; no guessed model payload or execution was accepted.

Remaining gates before local commit:

- Repeat browser acceptance after the latest schema/context changes and poll
  the durable records again.
- Keep the Notebook artifact-manifest warnings and Report provider/contract
  failures as `NOT VERIFIED` or explicit concerns; do not convert them into
  green claims.
- Run focused and repository-level verification, append material events via
  formal devline control, and commit locally only.

## Boundary
- Affected paths: `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/p7_pack_adapters.py`, `backend/workbench/agent/p7_pack_registry.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/http/agent_routes.py`, `tests/test_agent_context_tools.py`, `tests/test_agent_operation_audit.py`, `tests/test_agent_routes.py`, `tests/test_p7_adoption_calls.py`, `tests/test_p7_adoption_registry.py`, `tests/test_workflow_seam.py`, `docs/superpowers/plans/2026-08-09-v1.8.8-agent-chain-active-head-p7.md`
- Allowed paths: `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/p7_pack_adapters.py`, `backend/workbench/agent/p7_pack_registry.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/http/agent_routes.py`, `tests/test_agent_context_tools.py`, `tests/test_agent_operation_audit.py`, `tests/test_agent_routes.py`, `tests/test_p7_adoption_calls.py`, `tests/test_p7_adoption_registry.py`, `tests/test_workflow_seam.py`, `docs/superpowers/plans/2026-08-09-v1.8.8-agent-chain-active-head-p7.md`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_p7_adoption_registry.py tests/test_p7_adoption_calls.py`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_agent_context_tools.py tests/test_agent_operation_audit.py tests/test_agent_routes.py tests/test_workflow_seam.py`
- Known gates: `Full gate must run from repository root on the host terminal; R DID oracle fixtures may be absent in the sandbox`, `Browser acceptance is separate evidence from pytest and full gate`, `No push, PR, merge, tag, or release without explicit authorization`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### wo-a-live-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-live-agent; final_state=CLOSED; failure_lesson_keys=none
