# Retrospective — v1-8-9-p0-legacy-resume-remediation-4

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Remediation-4 Objective  Remediate the independent spec-review finding against exact remediation-3 tip \`8003f27b95bf8f8f2dcad4c35f556d68238c079e\` without editing remediation-3 or any other formal line, root checkout, or worktree.  ## Required outcomes  - ProposalStore admission is an opaque, server-issued capability rather than a   \`type(ProposalStore)\` check. A caller-created, temporary, forged, copied, or   reconstructed store is rejected even when it points at a complete file. The   compiler binds only a capability admitted by its server authority, and the   persisted compilation record and confirmation identity come from that same   authority and exactly match proposal id, revision, fingerprint, semantic   plan hash, actor, session, project, target, chain, and operation. - The legacy route reloads a canonical persisted proposal through the   server-owned store capability before parsing any precondition or consulting   authority, record, execute, claim, or write state. \`SimpleNamespace\`, a   synthetic/reconstructed ProposalRevision, forged caller revision, stale   receipt, replay, and persisted tamper all fail closed with no side effect. - Real repository and route probes cover caller-store admission, incomplete and   cross-scope compilation, persisted target tamper with an old fingerprint,   forged revision/receipt/replay, and synthetic direct-service calls. Positive   paths use the server-owned persisted proposal lifecycle. - Existing Resume artifact/output/lineage/model-branch and Agent/Notebook   focused safety coverage remains green. The remediation-3 \`COMPLETED\` versus   \`unresolved=5\` contradiction is recorded as a new formal review/gap and   resolved by this line's exact evidence; historical counts are not reused.  ## Boundary  - Affected paths: \`backend/workbench/agent/proposals.py\`,   \`backend/workbench/agent/orchestrator.py\`,   \`backend/workbench/http/agent_routes.py\`,   \`tests/test_v189_legacy_resume_remediation4.py\`,   \`tests/test_v189_legacy_resume_remediation3.py\`,   \`tests/test_v189_legacy_resume_remediation2.py\`,   \`tests/test_v189_agent_notebook_cutover.py\`,   \`tests/test_v189_legacy_route_authority.py\`,   \`docs/superpowers/objectives/2026-08-19-v1.8.9-p0-legacy-resume-remediation-4-objective.md\`,   \`docs/superpowers/plans/2026-08-19-v1.8.9-p0-legacy-resume-remediation-4.md\` - Allowed paths: exactly the affected paths above. - Protected paths: all root-level files, all other worktrees, all prior   \`.agent/devlines/*\` records, \`Report\`, \`data\`, \`classification\`, \`survey\`,   \`backend/workbench/providers\`, \`backend/workbench/http/runs_routes.py\`,   \`backend/workbench/report_view_model.py\`, and   \`backend/workbench/engine/stages/estimation.py\`. - Baseline: \`8003f27b95bf8f8f2dcad4c35f556d68238c079e\`. - Dependencies: remediation-3 predecessor and its review, remediation-2,   legacy proposal-binding remediation, legacy/resume hardening, Agent compiler   core, and contract-lock. - Tests: RED then GREEN real ProposalStore/compiler/route probes; focused   legacy route/proposal/compiler/resume/workflow/Agent-Notebook suites;   isolated compileall with cleanup; \`git diff --check\`; formal verify and   retrospective. - Known gates: browser acceptance NOT VERIFIED; provider/external runtime NOT   VERIFIED; full repository gate NOT VERIFIED; release NOT VERIFIED;   merge/tag NOT VERIFIED. No dependency installation, root write, push, PR,   merge, tag, or release operation.

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

- #1: `2781237f-df5b-40f3-b7b7-3bd6df45b615` | 2026-08-20T02:26:32.885Z | STATE_CHANGE/line_started | incident=`b6ac8f19-c4c9-437d-885f-e93d4f6bf1ec` | lesson_key=`frozen-context-before-start` | event_sha256=`0f67499898227f51f3d7978acf06eae580e58ed379409c1958f532d839c9d8c6`
