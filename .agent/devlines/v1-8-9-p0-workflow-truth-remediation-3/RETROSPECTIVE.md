# Retrospective — v1-8-9-p0-workflow-truth-remediation-3

## Goal

# v1.8.9 P0 Workflow Truth Remediation 3 Objective  Close the remaining Workflow Truth execution and evidence gaps found by the remediation-2 adversarial review. After admission, execution must use an immutable complete snapshot of the target, scope, plan, step contract and preconditions; no legacy/plain callback may write without the receipt-gated executor; model-run paths and source hashes must be confined and recomputed; and completion can only promote artifacts that are registered, project-owned and allowed by the step contract.  Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749 Remediation line: v1-8-9-p0-workflow-truth-remediation-3 Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-workflow-truth  Required outcomes:  - admission seals the full execution snapshot and callback revalidates it,   preventing post-admission TOCTOU changes; - every public and compatibility callback path is receipt-gated or fails   closed before any write; no legacy callback can promote forged artifacts; - model-run identifiers are strict project-local opaque refs with containment   checks, and source content hashes are recomputed from the admitted file; - completion verifies artifact registry existence, project ownership, digest,   expected output and step contract before persistence; - authority/seals survive the intended worker/restart boundary or explicitly   fail closed without silently accepting a new process identity; - legacy OLS/model helpers cannot write outside the admitted workflow route.  Keep C0 contracts and the package-local boundary. Do not modify shared cutover, consumers, central catalog, frontend, provider wiring, or protected paths.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/6 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=5250000 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T12:30:00.000Z `tdd_red_workflow_remediation_3`; cause_status: `known`; cause: Remediation-2 adversarial probes reproduced a plain callback write bypass, incomplete post-admission snapshot validation, path-like model-run acceptance until filesystem lookup, legacy OLS helper execution outside an admitted family workflow, and restart refusal without a stable authority reason code.; resolution: `open`; lesson: Admission must seal and revalidate the complete execution snapshot, completion must prove registered project-owned artifacts, and every compatibility route must fail closed without a durable authority proof.

## All errors

- #3 2026-08-16T15:10:00.000Z `verification_command_error`; cause_status: `known`; cause: The first formal verification attempt used the unsupported devline_control status subcommand; the CLI rejected it before any verification or repository mutation.; resolution: `resolved`; lesson: Use the devline control CLI help surface and record command failures before retrying the supported formal gate.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `unsupported-formal-status-command`: occurrences=1; cause_status: `known`; root cause: The first formal verification attempt used the unsupported devline_control status subcommand; the CLI rejected it before any verification or repository mutation.; solution: `resolved`
- `workflow-remediation-3-red-before-fix`: occurrences=1; cause_status: `known`; root cause: Remediation-2 adversarial probes reproduced a plain callback write bypass, incomplete post-admission snapshot validation, path-like model-run acceptance until filesystem lookup, legacy OLS helper execution outside an admitted family workflow, and restart refusal without a stable authority reason code.; solution: `open`

## Added tests

- `tests/test_v189_workflow_truth.py`
- `tests/test_v189_workflow_truth.py;tests/test_workflow_resume.py;tests/test_workflow_runtime.py`

## New rules

- `unsupported-formal-status-command`: line experience occurrence(s)=1
- `workflow-remediation-3-red-before-fix`: line experience occurrence(s)=1

## Future guidance

- Admission must seal and revalidate the complete execution snapshot, completion must prove registered project-owned artifacts, and every compatibility route must fail closed without a durable authority proof.
- Resolve an append-only failure through a linked review event rather than mutating its historical record.
- Use the devline control CLI help surface and record command failures before retrying the supported formal gate.

## Event index

- #1: `57a8c31a-1dbe-4681-adb3-4d7cbd7ecbee` | 2026-08-16T11:25:10.029Z | STATE_CHANGE/line_started | incident=`bbefe763-6977-4c2e-acea-35ed49abef4f` | lesson_key=`frozen-context-before-start` | event_sha256=`319befcc84f7f92e879a999288b7e63d9ec99e62da5262ad36cfa9936c2381b4`
- #2: `4d7f3a91-2e6b-4c08-9a51-7f0d3b2e6c18` | 2026-08-16T12:30:00.000Z | FAILURE/tdd_red_workflow_remediation_3 | incident=`7c2e9a14-5b68-4d03-8f71-2a6c9e0b4d57` | lesson_key=`workflow-remediation-3-red-before-fix` | event_sha256=`c26f18f8983ac3239f36f87fd5b453274a66a46377c89a8602c5fc127cd6ec2f`
- #3: `8a1f4d7e-2c63-4b90-9e18-5f7a0d3c6b21` | 2026-08-16T15:10:00.000Z | ERROR/verification_command_error | incident=`b6e0f9a4-3d72-4c18-8a5f-1e9b6d2c7f40` | lesson_key=`unsupported-formal-status-command` | event_sha256=`cad9f690cce65d7d01372726d4e2fd4675467914ecb50901a4fba2dd0859b6f3`
- #4: `c4b7e1a9-6d23-4f80-9c15-2a7e5b3d8f61` | 2026-08-16T15:20:00.000Z | GATE/local_workflow_truth_gate | incident=`d8f2a6c1-4b79-45e0-9a13-6e5c2b7f084d` | lesson_key=`local-gate-does-not-prove-release` | event_sha256=`c04ce8a92f60e48c846295686122bf7b7bd986ce948d97cf33aa1610bf6bc0a9`
- #5: `e9c2a6f4-1d73-4b80-9e15-6a7c3f2d8b04` | 2026-08-16T15:25:00.000Z | REVIEW/remediation_resolved | incident=`7c2e9a14-5b68-4d03-8f71-2a6c9e0b4d57` | lesson_key=`append-only-failure-resolution` | event_sha256=`5177484d394e5f13be6b1d85b7bfcfcb2d79a7ff713bf637132ea6d4abf969dc`
- #6: `f6a3c9e1-7d24-4b80-951f-2c8e6a4d0b37` | 2026-08-16T15:26:00.000Z | STATE_CHANGE/line_completed | incident=`a1d7f3c9-5b20-4e86-9c42-7f1a6d3b8e05` | lesson_key=`completed-scope-preserves-limits` | event_sha256=`da705439ca5a5ed34ab7183c33f483bdaaa73f48452df58b9552d6858fa10783`
