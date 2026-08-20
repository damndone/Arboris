# Retrospective — v1-8-9-p0-legacy-resume-remediation-7

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Remediation-7 Objective  ## Objective  Close the P0 authority bypass found at baseline \`4764a97b2093940417eeb9303d06aacc086ff82c\`: caller-created \`ProposalStoreCapabilityIssuerV1\` objects must not be able to self-register mutation admission or service-entry admission and then mint a proposal-store capability that reaches \`WorkbenchOrchestrator.decline_proposal\` side effects.  ## Required outcomes  - Make issuer and service admission server-owned opaque authority. A caller may   consume only an already issued, non-forgeable service-entry handle; it cannot   register or upgrade an issuer. - Bind every issuer and capability to the existing registry, server secret,   owner identity, nonce, process generation, PID, and exact store-root identity   boundaries. Copying, serialization, reconstruction, and cross-process use   must fail closed. - Keep the formal compiler, route, and workflow proposal paths valid. - Add adversarial TDD regressions for caller-created issuer plus self-registered   service handle, and imported/default route issuer directly registered then   minted. Both must reject before proposal, repository, or event side effects. - Run focused legacy/resume/route/compiler/workflow suites, the adversarial   suite, compileall, and diff-check. - Record the historical \`tests/test_agent_proposal_operations.py\` 19 direct-   service failures as a known GAP; do not weaken the authority boundary.  ## Boundary  Affected paths:  - \`backend/workbench/agent/proposals.py\` - \`backend/workbench/agent/orchestrator.py\` - \`tests/test_v189_legacy_resume_remediation7.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7-objective.md\` - \`docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7-handoff.md\`  Allowed paths are exactly the affected paths above. Protected paths include the root checkout, all other worktrees, all predecessor \`.agent/devlines/*\` records, Report/data/classification/survey/provider paths, unrelated HTTP routes, and predecessor remediation source/test files unless a regression proves a narrowly necessary compatibility edit.  Baseline: \`4764a97b2093940417eeb9303d06aacc086ff82c\`.  Dependencies: legacy/resume remediation-6 and its predecessor authority hardening lines, Agent compiler cutover, route authority, workflow truth, and contract-lock evidence. Historical closeout counts are inputs only, not this line's evidence.  ## Tests and gates  - RED then GREEN: \`tests/test_v189_legacy_resume_remediation7.py\`. - Focused legacy/resume/route/compiler/workflow suites and the historical   direct-service suite, with its 19 failures recorded as a known GAP if still   present. - \`PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests\`. - \`git diff --check\`. - Formal line verify, final GATE, retrospective, and exact HEAD/digest handoff.  Known external gates remain outside this line: browser acceptance, external provider runtime, host restart, true multi-worker deployment, full repository gate, integration/release/merge/tag. They remain \`NOT VERIFIED\` unless directly run and evidenced here. No dependency installation, root write, other-worktree write, push, merge, tag, or release operation is authorized.

## Final status

STARTED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
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

- #1: `ff2f8b70-9a21-48ca-9bb8-95232956243b` | 2026-08-20T05:12:39.419Z | STATE_CHANGE/line_started | incident=`c6416487-8de3-41ff-84db-5cd579823ebf` | lesson_key=`frozen-context-before-start` | event_sha256=`b5b5de731bd5db3a87860a29dde35560ee6e1e6c0f2cf876cefea02e7d20a12d`
