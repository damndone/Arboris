# Retrospective — v1-8-9-p0-legacy-resume-remediation-8

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Remediation-8 Objective  ## Objective  Close the remaining P0 proposal authority bypass at exact baseline \`69b5b0079f0532ea7be7b6d8bd2a352dfa9f4294\`: a caller can directly construct \`_ProposalStoreServerAuthorityV1\`, call \`issue()\`, and pass the self-consistent issuer/service entry to \`ProposalStore._issue_server_capability\`, reaching real proposal side effects.  ## Required outcomes  - The module owns exactly one live server authority object. Direct constructor   calls fail closed permanently; \`object.__new__\` instances and field-forged,   copied, or serialized authority/entry objects cannot issue or admit anything. - \`authority.issue()\` succeeds only on the module-initialized singleton and   only creates entries admitted by that authority's registry and secret. - \`ProposalStore._issue_server_capability\` and \`_issue\` validate unique   authority object identity plus registry, secret, owner identity, issuer and   entry nonce, PID, generation, and exact root identity before any proposal,   repository, or event side effect. \`entry_nonce\` equality is explicit. - Add real adversarial RED/GREEN regressions for direct construction,   \`object.__new__\` forgery, caller \`issue()\`, forged entry/issuer bindings, and   zero side effects before and after the attempted path. - Preserve route-owned issuance and compiler/orchestrator positive proposal   paths. - Keep predecessor remediation-7 \`.agent/devlines\` records immutable. The new   handoff records its predecessor's corrected final exact HEAD/tree digest:   \`97c82f5e59e8e3cd104170152f7b53da8eda416a\` /   \`d15da557e1a704e4333fc685a9bfa30beaba1fb8\`.  ## Boundary  Affected paths:  - \`backend/workbench/agent/proposals.py\` - \`tests/test_v189_legacy_resume_remediation8.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8-objective.md\` - \`docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-8-handoff.md\`  Protected paths include all predecessor \`.agent/devlines/*\` records, the root checkout, other worktrees, unrelated route/compiler/orchestrator source, Report/data/classification/survey/provider paths, and predecessor source/tests.  Baseline: \`69b5b0079f0532ea7be7b6d8bd2a352dfa9f4294\`.  Dependencies: \`v1-8-9-p0-legacy-resume-remediation-7\`, its corrected handoff digest, legacy/resume authority hardening, route authority, Agent compiler cutover, workflow truth, and contract-lock evidence.  ## Tests and gates  - TDD RED then GREEN: \`tests/test_v189_legacy_resume_remediation8.py\`. - Focused remediation-8 adversarial suite plus remediation-7, remediation-6,   remediation-5, remediation-2, route authority, Agent Notebook compiler,   workflow-resume, and relevant workflow seam positive-path suites. - \`PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests\`. - \`git diff --check\` and scoped diff/path verification. - Formal line verify, final GATE, retrospective, and exact HEAD/tree digest   handoff.  Known external gates remain \`NOT VERIFIED\` unless run here: browser acceptance, external provider runtime, host restart, true multi-worker deployment, full repository gate, integration, release, merge, tag, and push. No dependency installation, destructive cleanup, root write, other-worktree write, push, merge, tag, or release operation is authorized.

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

- #1: `4e208893-0cab-4f99-aacc-933a0b8f9deb` | 2026-08-20T05:36:00.876Z | STATE_CHANGE/line_started | incident=`749b4d2b-00a4-4f83-8550-97be7ecda85f` | lesson_key=`frozen-context-before-start` | event_sha256=`9b9e98fd266a5a7fda128ba19841278f3812e0ee66e3a9a559e0030a3d062fa4`
