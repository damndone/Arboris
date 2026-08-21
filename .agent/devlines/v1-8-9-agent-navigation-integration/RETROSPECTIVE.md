# Retrospective — v1-8-9-agent-navigation-integration

## Goal

# Workbench v1.8.9 Agent navigation integration objective  ## Objective  Close the current C3 integration regression without weakening the server-owned proposal boundary. Existing Agent navigation tests must create durable records through the admitted proposal capability and the shared operation lifecycle; they must not regain raw \`ProposalStore\` mutation or the retired \`WorkbenchOrchestrator.confirm_proposal\` execution authority. Read-only graph navigation over a project with no Workbench storage must return an unavailable projection, not leak a filesystem capability error or create storage.  ## Baseline  - Worktree: \`workbench-v1.8.9-hardening-integration\` - Exact baseline SHA: \`91ee6a05eab2a1892844c8a3057e1e607359a29e\` - Existing dirty v1.8.9 changes are in scope and must be preserved.  ## In scope  - \`backend/workbench/agent/navigation.py\` read-only unavailable boundary. - \`tests/test_agent_navigation.py\` migration to the server-owned proposal and   operation lifecycle. - \`tests/test_agent_routes.py\` fixture migration or explicit fail-closed   assertions where the historical route lacks a persisted server compilation. - This objective, work order, handoff, and focused contract/acceptance tests.  ## Out of scope  - Removing or weakening \`ProposalStoreCapabilityV1\` admission. - Reintroducing \`WorkbenchOrchestrator.confirm_proposal\` as an execution path. - Estimator, data-consumer, classification, survey, Report, or Notebook   implementation changes. - Browser, external provider, cross-process, full-host, full-repository,   merge, tag, release, or root-main synchronization.  ## Required outcomes  1. Navigation fixtures use an admitted server capability and a durable    \`ProposalConfirmation\` → \`OperationRecord\` lifecycle. 2. Missing Workbench storage is represented as an unavailable read projection;    no directory is created as a side effect. 3. Historical Agent routes without a server-owned compilation remain typed    fail-closed; tests do not silently accept their old execution semantics. 4. Focused Agent/Notebook C3 tests and the affected route/navigation tests pass.  ## Known gates  Production host identity/data/evidence injection, browser acceptance, external provider execution, cross-process authority, full host/repository gate, and release readiness remain unverified.

## Final status

COMPLETED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `49081629-8770-41b4-a949-07d0347f63c3` | 2026-08-21T02:30:12.206Z | STATE_CHANGE/line_started | incident=`5cec9afd-eed8-409e-8d4e-b93ffa5feafa` | lesson_key=`frozen-context-before-start` | event_sha256=`c9e7bf7f68f34e49ff612d8ff76aac11d829f26f9d90a15602c40e7c505b4792`
- #2: `d5f5e6a4-9b3e-4c15-a4c5-7b3a8e2b4d11` | 2026-08-21T02:39:54.264Z | GATE/agent_navigation_integration_green | incident=`fb9d4e2c-7a5f-4e31-9c8b-2d6f1a7e5c40` | lesson_key=`integration-candidate-boundary` | event_sha256=`97661dab9bb2cbabe92d4eeaeca22fe29d8914b3d3b2548a5c8f3298f1db8e8d`
- #3: `e6a4f5b3-8c2d-4e17-b6a9-1d7f3c5b8e20` | 2026-08-21T02:40:16.263Z | STATE_CHANGE/agent_navigation_integration_completed | incident=`a4c5d6e7-f8b9-4012-9345-6a7b8c9d0e21` | lesson_key=`formal-terminal-state` | event_sha256=`27bc3efe37ba0d75262c2b3c6491c2c51e400ef8e362cdc9295072f6a23561e6`
