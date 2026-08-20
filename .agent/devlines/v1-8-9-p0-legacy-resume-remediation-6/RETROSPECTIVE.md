# Retrospective — v1-8-9-p0-legacy-resume-remediation-6

## Goal

# Workbench v1.8.9 P0 Legacy/Resume Remediation-6 Objective  ## Objective  Close the independent spec-review authority bypass remaining at remediation-5 HEAD \`4e8fe623e00a2216f11202fce38527ecfd317e9f\`. Caller-created, reconstructed, cross-scope, tampered, replayed, and concurrently misused proposal-store capabilities must fail closed before proposal, repository, or event side effects, while the existing route-owned proposal lifecycle remains valid and compatible.  ## Required outcomes  - Replace caller-supplied \`owner_token\` issuance with a server issuer and   registry that binds each capability to an issuer identity, nonce, process   generation, and exact proposal-store root identity. - Bind the route issuer explicitly into \`WorkbenchOrchestrator\`; the   orchestrator must validate the exact issuer/registry binding before every   proposal read or mutation. - Direct access to the old \`_issue\` and \`_issue_server_capability\` authority   seams cannot mint a usable capability. Forged, reconstructed, copied,   serialized, cross-scope, tampered, stale, replayed, and concurrent misuse   fail closed with zero proposal/repository/event side effects. - Preserve route-owned create/revise/decline compatibility semantics and the   existing Resume, legacy compiler, and workflow safety boundaries. - Add real TDD probes for all rejected classes, side-effect ordering, legal   route success, one-time/replay behavior, and concurrent misuse.  ## Boundary  Affected paths:  - \`backend/workbench/agent/proposals.py\` - \`backend/workbench/agent/orchestrator.py\` - \`backend/workbench/http/agent_routes.py\` - \`tests/test_v189_legacy_resume_remediation6.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6-objective.md\` - \`docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6-handoff.md\`  Allowed paths are exactly the affected paths above. Protected paths include the root checkout, all other worktrees, all predecessor \`.agent/devlines/*\` records, Report/data/classification/survey/provider paths, unrelated HTTP routes, and existing remediation source/test files unless a test regression proves a narrowly necessary compatibility edit.  Baseline: \`4e8fe623e00a2216f11202fce38527ecfd317e9f\`.  Dependencies: remediation-5, remediation-4, remediation-3, remediation-2, legacy proposal-binding remediation, legacy/resume authority hardening, Agent compiler core, and contract-lock evidence. These are historical inputs only; their closeout counts are not evidence for this line.  ## Tests and gates  - RED then GREEN: \`tests/test_v189_legacy_resume_remediation6.py\`. - Impacted legacy proposal/route/compiler/Resume/workflow focused suites. - \`PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests\`. - \`git diff --check\`. - Formal line verify and retrospective generation.  Known gates remaining outside this line: browser acceptance, external provider runtime, host restart, multi-worker process deployment, full repository gate, integration/release/merge/tag. These remain \`NOT VERIFIED\` unless directly run and evidenced here.  No dependency installation, root write, other-worktree write, push, PR, merge, tag, or release operation is authorized.

## Final status

COMPLETED

## Metrics

- Failure frequency: 8/15 (53.3%; 53.3 per 100 events)
- Repeat rate: 0/8 (0.0%)
- Recurrence rate: 0/8 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=5)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-20T04:16:05.000Z `remediation6_red_authority_bypass`; cause_status: `known`; cause: The baseline ProposalStore capability issuance accepts caller-supplied owner tokens and the orchestrator validates admission without exact server issuer identity.; resolution: `open`; lesson: Keep caller-created, direct-issued, and concurrent authority probes red before implementing the server issuer and exact orchestrator binding.
- #4 2026-08-20T04:23:12.000Z `remediation6_red_default_issuer_bypass`; cause_status: `known`; cause: The first implementation left the imported DEFAULT_ROUTE_PROPOSAL_STORE_ISSUER usable as a direct issuance input and gave WorkbenchOrchestrator an implicit default issuer.; resolution: `resolved`; lesson: A route issuer must not be sufficient by itself for direct issuance, and a direct orchestrator must fail closed without explicit issuer binding.

## All errors

- #2 2026-08-20T04:12:42.000Z `formal_start_cli_surface`; cause_status: `known`; cause: The first two formal start attempts were rejected before line creation: one split multiword option values, and one used a tag outside the normalized identifier grammar.; resolution: `resolved`; lesson: Quote every multiword formal CLI value and use normalized identifier tags before invoking start.
- #9 2026-08-20T04:29:59.000Z `formal_gate_event_vocabulary`; cause_status: `known`; cause: The first closeout GATE, REVIEW, and STATE_CHANGE append attempts used preventability not_applicable, which the formal event contract does not accept.; resolution: `resolved`; lesson: Validate formal preventability vocabulary before appending closeout events; use unknown when a field is not applicable.

## All gaps

- #5 2026-08-20T04:23:12.000Z `impacted_historical_direct_service_fixtures`; cause_status: `known`; cause: The impacted test_agent_proposal_operations suite still constructs WorkbenchOrchestrator without a server-owned proposal capability and asserts the historical direct-service mutation/response contract.; resolution: `open`; lesson: Do not weaken the server-owned mutation boundary to satisfy historical direct-service fixtures; classify them separately from current route evidence.
- #6 2026-08-20T04:25:56.000Z `remediation2_implicit_issuer_fixture`; cause_status: `known`; cause: An impacted remediation-2 positive setup fixture passes a route-owned capability to WorkbenchOrchestrator without the now-required explicit issuer binding.; resolution: `open`; lesson: Keep direct orchestrator calls fail-closed without an explicit issuer; migrate positive fixtures only in an authorized follow-up line.
- #7 2026-08-20T04:26:51.000Z `focused_predecessor_issuer_fixtures`; cause_status: `known`; cause: Two predecessor positive fixtures call WorkbenchOrchestrator with a server capability but omit the explicit route issuer now required by the P0 authority boundary.; resolution: `open`; lesson: Migrate predecessor positive fixtures in a separately authorized scope; never restore implicit issuer trust to satisfy them.
- #8 2026-08-20T04:29:59.000Z `known_external_acceptance_boundaries`; cause_status: `external`; cause: This line did not run browser acceptance, external provider runtime, host restart, true multi-worker deployment, full repository gate, integration, or release procedures.; resolution: `accepted`; lesson: Keep package and local security evidence separate from external acceptance and release claims.

## All waste

- None recorded.

## Root causes and solutions

- `default-route-issuer-bypass`: occurrences=1; cause_status: `known`; root cause: The first implementation left the imported DEFAULT_ROUTE_PROPOSAL_STORE_ISSUER usable as a direct issuance input and gave WorkbenchOrchestrator an implicit default issuer.; solution: `resolved`
- `external-gates-remain-not-verified`: occurrences=1; cause_status: `external`; root cause: This line did not run browser acceptance, external provider runtime, host restart, true multi-worker deployment, full repository gate, integration, or release procedures.; solution: `accepted`
- `formal-gate-event-vocabulary`: occurrences=1; cause_status: `known`; root cause: The first closeout GATE, REVIEW, and STATE_CHANGE append attempts used preventability not_applicable, which the formal event contract does not accept.; solution: `resolved`
- `formal-start-cli-surface`: occurrences=1; cause_status: `known`; root cause: The first two formal start attempts were rejected before line creation: one split multiword option values, and one used a tag outside the normalized identifier grammar.; solution: `resolved`
- `historical-direct-service-fixtures`: occurrences=1; cause_status: `known`; root cause: The impacted test_agent_proposal_operations suite still constructs WorkbenchOrchestrator without a server-owned proposal capability and asserts the historical direct-service mutation/response contract.; solution: `open`
- `implicit-issuer-fixture`: occurrences=1; cause_status: `known`; root cause: An impacted remediation-2 positive setup fixture passes a route-owned capability to WorkbenchOrchestrator without the now-required explicit issuer binding.; solution: `open`
- `predecessor-explicit-issuer-fixtures`: occurrences=1; cause_status: `known`; root cause: Two predecessor positive fixtures call WorkbenchOrchestrator with a server capability but omit the explicit route issuer now required by the P0 authority boundary.; solution: `open`
- `remediation6-red-authority-bypass`: occurrences=1; cause_status: `known`; root cause: The baseline ProposalStore capability issuance accepts caller-supplied owner tokens and the orchestrator validates admission without exact server issuer identity.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `default-route-issuer-bypass`: line experience occurrence(s)=1
- `external-gates-remain-not-verified`: line experience occurrence(s)=1
- `formal-gate-event-vocabulary`: line experience occurrence(s)=1
- `formal-start-cli-surface`: line experience occurrence(s)=1
- `historical-direct-service-fixtures`: line experience occurrence(s)=1
- `implicit-issuer-fixture`: line experience occurrence(s)=1
- `predecessor-explicit-issuer-fixtures`: line experience occurrence(s)=1
- `remediation6-red-authority-bypass`: line experience occurrence(s)=1

## Future guidance

- A route issuer must not be sufficient by itself for direct issuance, and a direct orchestrator must fail closed without explicit issuer binding.
- Do not weaken the server-owned mutation boundary to satisfy historical direct-service fixtures; classify them separately from current route evidence.
- Handoffs must distinguish current evidence, historical fixture gaps, and unverified release boundaries.
- Keep caller-created, direct-issued, and concurrent authority probes red before implementing the server issuer and exact orchestrator binding.
- Keep direct orchestrator calls fail-closed without an explicit issuer; migrate positive fixtures only in an authorized follow-up line.
- Keep package and local security evidence separate from external acceptance and release claims.
- Migrate predecessor positive fixtures in a separately authorized scope; never restore implicit issuer trust to satisfy them.
- Quote every multiword formal CLI value and use normalized identifier tags before invoking start.
- Validate formal preventability vocabulary before appending closeout events; use unknown when a field is not applicable.

## Event index

- #1: `5d481b0f-0fe7-4976-8b0a-a2e4718e880c` | 2026-08-20T04:12:12.393Z | STATE_CHANGE/line_started | incident=`250f053b-66a1-48bb-ab7a-0cf90ffca373` | lesson_key=`frozen-context-before-start` | event_sha256=`af16673d74e9f513319ce4b7f72780ec4c7d3c6a69a729f741659b794022c236`
- #2: `7b1c5d9e-2f43-4a67-8b91-0c3d5e7f9a12` | 2026-08-20T04:12:42.000Z | ERROR/formal_start_cli_surface | incident=`2e4f6a8c-1b3d-4e5f-9a70-c2d4f6b8e1a3` | lesson_key=`formal-start-cli-surface` | event_sha256=`216f17f4c06e9b488fe0488c04058c11ead30fa0c65fe01dd7f30f81b767f0e9`
- #3: `8c2e4f6a-1b3d-4e5f-9a70-c2d4f6b8e1a4` | 2026-08-20T04:16:05.000Z | FAILURE/remediation6_red_authority_bypass | incident=`3f5a7c9e-1b2d-4e6f-8a0c-2d4f6b8e1a35` | lesson_key=`remediation6-red-authority-bypass` | event_sha256=`ce94013740a81eb853cf7e291fa0678efbd4bdbb4b1272414341913b4f778cad`
- #4: `9d3f5a7c-1b2e-4f6a-8c0d-2e4f6b8a1c36` | 2026-08-20T04:23:12.000Z | FAILURE/remediation6_red_default_issuer_bypass | incident=`4a6c8e0f-2b3d-5e7f-9a1c-3d5f7b9e2a46` | lesson_key=`default-route-issuer-bypass` | event_sha256=`300b3aeeeed062b9cf5c5ef37bd2ab35a8ee623018d43a3deecab2e8ceae0fc0`
- #5: `0e4f6a8c-2b3d-5e7f-9a1c-3d5f7b9e2a47` | 2026-08-20T04:23:12.000Z | GAP/impacted_historical_direct_service_fixtures | incident=`5b7d9f1c-3e4a-6f8b-0d2e-4f6a8c1b3d59` | lesson_key=`historical-direct-service-fixtures` | event_sha256=`916f046f51165a14e3537d98ac83e7f01001bc5608cba1341f230bbbc0409817`
- #6: `1f5a7c9e-3b4d-6f8a-0c2e-4f6b8d1a3e59` | 2026-08-20T04:25:56.000Z | GAP/remediation2_implicit_issuer_fixture | incident=`2e6a8c0f-4b5d-7f9a-1c3e-5f7b9d2a4c60` | lesson_key=`implicit-issuer-fixture` | event_sha256=`6893baaf9d58ccab9eff8562c4605089fa80be9e1bde7a63a3babf16a5b0a2dd`
- #7: `2f6a8c0e-4b5d-7f9a-1c3e-5f7b9d2a4c61` | 2026-08-20T04:26:51.000Z | GAP/focused_predecessor_issuer_fixtures | incident=`3a7c9e1f-5b6d-8a0c-2e4f-6b8d1a3c5e72` | lesson_key=`predecessor-explicit-issuer-fixtures` | event_sha256=`52f72da7f6e6cb95b1a7f277ff6ffe038a0324c804a6dcaf9c2cab67e5ff79c8`
- #8: `8f1b3d5a-7c9e-0a2e-4f6b-8d1c3e5a7b94` | 2026-08-20T04:29:59.000Z | GAP/known_external_acceptance_boundaries | incident=`9a2c4e6f-8b0d-1e3a-5f7c-9b2d4a6e8c05` | lesson_key=`external-gates-remain-not-verified` | event_sha256=`650807bbeaf66761d8b111781d0a22619046a5ab9697b8d17f2bcf1452f1c828`
- #9: `4f6a8c0e-2b3d-5e7f-9a1c-3d5f7b9e2a48` | 2026-08-20T04:29:59.000Z | ERROR/formal_gate_event_vocabulary | incident=`5a7c9e1f-3b4d-6f8a-0c2e-4f6b8d1a3e60` | lesson_key=`formal-gate-event-vocabulary` | event_sha256=`9103c45b3e87a866ae26cc7d24009f68baeb23cfca89d4eb127e6010dedaf76d`
- #10: `c8337a1d-77e4-400a-b470-8532ec20c123` | 2026-08-20T04:34:38.476Z | STATE_CHANGE/context_rescope_required | incident=`da557735-e743-4cd8-99e2-069dc0c41c15` | lesson_key=`context-pack-rescope` | event_sha256=`fff01419f09d701591beb38d4d8451e7861fdc4cf7315557700808ba83fcb8ec`
- #11: `77083445-f428-4205-8a78-5de60ad59f0e` | 2026-08-20T04:34:38.483Z | STATE_CHANGE/context_rescoped | incident=`00f725fa-4905-46c5-8f90-901b1fc5aef2` | lesson_key=`context-pack-rescope` | event_sha256=`5bc69bdf5dcc6bd884b202aacea1394f79e05333adc7d8ee1541def8b7d699bd`
- #12: `4b7d9f1c-3e5a-6f8b-0d2e-4f6a8c1b3d60` | 2026-08-20T04:36:35.000Z | GATE/remediation6_focused_current | incident=`5c8e0f2a-4d6b-7f9c-1e3a-5f7b9d2c4a61` | lesson_key=`current-focused-gate-count-only` | event_sha256=`3ad89c0fa67cef4001e4aeb436770a7fb2287516a0f61f659b7d966e2b612451`
- #13: `6d9f1b3e-5a7c-8f0d-2e4b-6f8a1c3d5e72` | 2026-08-20T04:37:39.000Z | GATE/compileall_diff_check | incident=`7e0a2c4f-6b8d-9f1a-3e5c-7b9d2f4a6c83` | lesson_key=`isolated-compileall-diff-current` | event_sha256=`72225c94ce0ce642797a5a99c760fd5d3a0e17546cf8f52ae698e1daeee46014`
- #14: `0b3d5f7a-9c1e-2f4b-6d8a-0c3e5f7b9a16` | 2026-08-20T04:36:35.000Z | REVIEW/exact_tip_handoff | incident=`1c4e6a8b-0d2f-5a7c-9e1b-3d5f7b9a2c06` | lesson_key=`exact-tip-remediation-handoff` | event_sha256=`07496ff6237b83a4d0ba37f163f96af927ea949bb428b5dd8dd54991060f531e`
- #15: `2d5f7b9a-1c3e-4f6a-8b0d-2e4f6a8c1b07` | 2026-08-20T04:36:35.000Z | STATE_CHANGE/line_completed | incident=`3e6a8c0f-2b4d-5f7a-9c1e-3d5f7b9a2c08` | lesson_key=`close-formal-line-on-current-evidence` | event_sha256=`f43e27c46e2ec0be7348348e1d1d37c67fe3487cb3ee67e7066daf5b0ca23057`
