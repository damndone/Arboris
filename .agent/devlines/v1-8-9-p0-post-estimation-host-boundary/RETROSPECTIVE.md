# Retrospective — v1-8-9-p0-post-estimation-host-boundary

## Goal

# Workbench v1.8.9 P0 Post-estimation Host Boundary  ## Objective  Migrate post-estimation run-surface tests to the deployment-owned workflow host admission seam. The tests must explicitly provide an admitted host endpoint when exercising real workflow execution, while missing host authority continues to fail closed.  ## Scope  - \`tests/test_run_post_estimation_projection.py\`  ## Acceptance  - All scoped post-estimation projection tests pass with explicit host   admission. - No production default endpoint or caller-controlled authority is introduced.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/8 (62.5%; 62.5 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=4; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-21T09:17:56.853Z `host_admission_red`; cause_status: `known`; cause: The focused post-estimation projection tests executed the real workflow without replacing the deployment-owned host resolver with an explicitly admitted test endpoint, so the runtime correctly failed closed with WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED.; resolution: `resolved`; lesson: Real workflow tests must admit a deployment-owned host endpoint through the explicit supervisor seam before execution.
- #4 2026-08-21T09:17:56.971Z `canonical_fixture_red`; cause_status: `known`; cause: After host admission was supplied, the legacy source fixture exposed a noncanonical artifact index and the real model workflow rejected it before execution could persist its branch.; resolution: `resolved`; lesson: Real workflow fixtures must register source artifacts through the current canonical artifact-index helper before execution.

## All errors

- #2 2026-08-21T09:14:39.747Z `formal_cli_import_path`; cause_status: `known`; cause: The first formal CLI invocation used PYTHONPATH=. and imported the installed workbench package from the v1.8.6 worktree, which lacked the current context-pack API; the immediate retry also placed its event draft outside the repository-relative file boundary.; resolution: `resolved`; lesson: Invoke formal development control with the current worktree backend on PYTHONPATH and keep event drafts repository-relative until the CLI consumes them.
- #6 2026-08-21T09:19:34.523Z `formal_gate_event_schema`; cause_status: `known`; cause: The first focused-green gate event draft used not_applicable for preventability, but the formal event contract permits only the controlled preventability enum.; resolution: `resolved`; lesson: Validate every formal event enum against the CLI contract before treating a gate append as recorded.

## All gaps

- #5 2026-08-21T09:19:09.868Z `dependency_warning`; cause_status: `external`; cause: The scoped pytest command passes but the installed Starlette/httpx compatibility layer emits one StarletteDeprecationWarning.; resolution: `accepted`; lesson: Report pre-existing dependency warnings separately from the scoped host-boundary test result.

## All waste

- None recorded.

## Root causes and solutions

- `canonical-fixture-registration`: occurrences=1; cause_status: `known`; root cause: After host admission was supplied, the legacy source fixture exposed a noncanonical artifact index and the real model workflow rejected it before execution could persist its branch.; solution: `resolved`
- `dependency-warning-boundary`: occurrences=1; cause_status: `external`; root cause: The scoped pytest command passes but the installed Starlette/httpx compatibility layer emits one StarletteDeprecationWarning.; solution: `accepted`
- `formal-cli-current-backend`: occurrences=1; cause_status: `known`; root cause: The first formal CLI invocation used PYTHONPATH=. and imported the installed workbench package from the v1.8.6 worktree, which lacked the current context-pack API; the immediate retry also placed its event draft outside the repository-relative file boundary.; solution: `resolved`
- `formal-gate-event-envelope`: occurrences=1; cause_status: `known`; root cause: The first focused-green gate event draft used not_applicable for preventability, but the formal event contract permits only the controlled preventability enum.; solution: `resolved`
- `host-admission-boundary`: occurrences=1; cause_status: `known`; root cause: The focused post-estimation projection tests executed the real workflow without replacing the deployment-owned host resolver with an explicitly admitted test endpoint, so the runtime correctly failed closed with WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED.; solution: `resolved`

## Added tests

- `tests/test_run_post_estimation_projection.py`

## New rules

- `canonical-fixture-registration`: line experience occurrence(s)=1
- `dependency-warning-boundary`: line experience occurrence(s)=1
- `formal-cli-current-backend`: line experience occurrence(s)=1
- `formal-gate-event-envelope`: line experience occurrence(s)=1
- `host-admission-boundary`: line experience occurrence(s)=1

## Future guidance

- Invoke formal development control with the current worktree backend on PYTHONPATH and keep event drafts repository-relative until the CLI consumes them.
- Real workflow fixtures must register source artifacts through the current canonical artifact-index helper before execution.
- Real workflow tests must admit a deployment-owned host endpoint through the explicit supervisor seam before execution.
- Report pre-existing dependency warnings separately from the scoped host-boundary test result.
- Validate every formal event enum against the CLI contract before treating a gate append as recorded.

## Event index

- #1: `bc696ec7-9a62-455e-9044-7c193a27dbb6` | 2026-08-21T09:08:07.661Z | STATE_CHANGE/line_started | incident=`968ef0e4-d5fb-44ad-b6f4-2bce68ec92e5` | lesson_key=`frozen-context-before-start` | event_sha256=`ff32bf0c2e1b35ff1e970ea453c567d0f03910b97e887caeef878084dade58ec`
- #2: `6b4e5f40-11cd-4f3e-8a73-2ec6f168f1e4` | 2026-08-21T09:14:39.747Z | ERROR/formal_cli_import_path | incident=`9a4d6b9e-0c7f-4b2e-8d16-53f0c2a71b84` | lesson_key=`formal-cli-current-backend` | event_sha256=`7a46b1e291da0e50a151b3c0b06c36fcbde7f420120e62eea03dd1036d9e7c6f`
- #3: `c2f4a9d7-68e1-4b53-9a20-7d6c1f8e3b45` | 2026-08-21T09:17:56.853Z | FAILURE/host_admission_red | incident=`f8d1a6c3-5e2b-4a97-8c40-1b6e9d2f7358` | lesson_key=`host-admission-boundary` | event_sha256=`fd44ce21072dda3197ef00875367165c3fa82afa3da5f94e43b74ae53c772388`
- #4: `d3a5b8e2-79f4-4c61-a02b-8e7d2f9c4b56` | 2026-08-21T09:17:56.971Z | FAILURE/canonical_fixture_red | incident=`a7c2e9f4-6b18-4d53-9a70-2e5f8c1b6349` | lesson_key=`canonical-fixture-registration` | event_sha256=`7d627e5e5cec8cdbb09b4ec9bb53285165937541015ffeff8c86f5caf6f6c996`
- #5: `e4b7c1d9-80f5-4a62-b318-9c7d2e5f6a04` | 2026-08-21T09:19:09.868Z | GAP/dependency_warning | incident=`b9e3f6c1-7a24-4d58-8f02-6c5e1a9d7348` | lesson_key=`dependency-warning-boundary` | event_sha256=`0d31a33e37b12cc43dbe21b3c1e69efc59f400154ea0f2a521364d1029a23123`
- #6: `a6d9f3b1-2e74-4c58-9a10-7f6b2d8e4350` | 2026-08-21T09:19:34.523Z | ERROR/formal_gate_event_schema | incident=`d2f7a4c9-6b18-4e53-9a70-1c5e8d2b6340` | lesson_key=`formal-gate-event-envelope` | event_sha256=`c37e0a673c00a0a321387e357fbc57e2cf2addaada47a53ccddb71607f7158f2`
- #7: `f5c8d2a0-91e6-4b73-c429-0d8e3f6a7b15` | 2026-08-21T09:19:34.652Z | GATE/focused_post_estimation_green | incident=`c0f4a7e2-8b15-4d69-9e30-5a6c1f8d7342` | lesson_key=`focused-host-boundary-green` | event_sha256=`481cf033965960b98b13aaec3e9ee1d952252cc04f8e432ac35ba27f4e08757c`
- #8: `b7e0c4a2-5f19-4d68-9a31-6c8e2f7d4350` | 2026-08-21T09:19:58.510Z | STATE_CHANGE/line_completed | incident=`c8f1a5d3-7b20-4e69-9a42-6d5c2f8e1037` | lesson_key=`close-at-verified-boundary` | event_sha256=`0a9933dcb2d05c7f7a1003e708245d6ad4d4eeabf03965f7e592b15641e7f0d3`
