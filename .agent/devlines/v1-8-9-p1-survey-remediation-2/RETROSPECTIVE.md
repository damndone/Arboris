# Retrospective — v1-8-9-p1-survey-remediation-2

## Goal

# Workbench v1.8.9 Survey remediation-2 objective  ## Objective  Repair the independent Survey spec-review-2 blockers after product tip \`35898162aa6f15420997665a05f70c4f589e6f97\`, only at the Agent result, diagnostics, and committed Notebook packet projection seams. Make absent persisted fields disappear rather than becoming synthetic \`None\`/\`[]\` values, while preserving typed unavailable status/reason and the existing bounded Survey metadata contract.  ## Required behavior  - \`_agent_result_unavailable()\` and every Agent result/diagnostics unavailable   path omit \`survey_design\`, \`regression_table\`, \`marginal_effects\`, and any   other optional persisted field that is not present. Ordinary non-Survey   result/diagnostic paths must not synthesize those fields either. Typed   \`available\`, status, and reason fields remain present. - Real Agent workflow probes cover invalid server-owned model artifacts and   ordinary non-Survey diagnostic/result reads, asserting omission rather than   \`None\`/empty placeholders. - A real committed Notebook receipt probe projects a persisted Survey packet   through the bounded Agent public-result seam, preserving typed Survey   metadata when present and omitting it when absent. If admitted Notebook   coverage is not reachable from this package-local line, record that boundary   explicitly as \`NOT VERIFIED\`. - Existing Survey declaration falsey semantics, fail-closed validation, shared   OLS/Logit/Probit/Poisson variance engine, weights, replicate weights,   exposure safety, and Report projection remain unchanged and green.  ## Boundary  This is a new package-local remediation line only. It may change the Agent context projection and directly affected Agent/Notebook/Report tests, this objective/plan, formal records, and the exact handoff. Do not modify root, other worktrees, the completed \`v1-8-9-p1-survey-spec-remediation\` line, the historical \`v1-8-9-p1-survey-extension\` line, central integration, or release machinery.  ## Baseline and gates  - Baseline SHA: \`35898162aa6f15420997665a05f70c4f589e6f97\` - Dependencies: \`v1-8-9-p1-survey-spec-remediation\`,   \`v1-8-9-p1-survey-formal-closeout-remediation\` - Central admitted Report, browser acceptance, provider evidence, host   acceptance, full gate, and release/merge/tag/push remain \`NOT VERIFIED\`. - Historical line state-chain breaks are a known formal GAP; remediation-2   must report the computed number and must not relabel the historical line as   zero-mismatch.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/11 (45.5%; 45.5 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: N/A (sample=0; unresolved=5)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T02:30:00.000Z `agent_notebook_optional_projection_red`; cause_status: `known`; cause: Real Agent reads still synthesize unavailable survey/table fields and diagnostics attach absent Survey metadata; the committed Notebook receipt path uses generic budgeting that truncates typed Survey metadata instead of applying the bounded Survey projection.; resolution: `open`; lesson: Exercise unavailable, ordinary non-Survey, and committed Notebook result paths independently before changing shared Agent projection assembly.

## All errors

- None recorded.

## All gaps

- #7 2026-08-20T03:01:00.000Z `agent_context_foreign_owner_boundary`; cause_status: `external`; cause: The full Agent context suite still has 11 foreign-owner or synthetic fixture failures that require server-owned indexes, bindings, receipts, or artifact identities outside this remediation line.; resolution: `accepted`; lesson: Do not convert a package-local projection gate into central Agent context acceptance when unrelated owner fixtures are unavailable.
- #8 2026-08-20T03:02:00.000Z `report_admission_not_verified`; cause_status: `external`; cause: The broad Report export suite cannot enter the admitted write-capable workflow because the server receipt is absent; this remediation only verified the bounded Report view and projection export probes.; resolution: `accepted`; lesson: Keep bounded Report projection evidence separate from admitted HTML/PDF/XLSX consumer acceptance.
- #9 2026-08-20T03:03:00.000Z `central_external_acceptance_not_verified`; cause_status: `external`; cause: This package-local remediation has no admitted central Notebook receipt, browser/provider/host acceptance, full-gate execution, or release integration evidence.; resolution: `accepted`; lesson: Do not promote package-local green projection evidence to browser, provider, host, central, full-gate, or release acceptance.
- #10 2026-08-20T03:04:00.000Z `historical_state_chain_gap`; cause_status: `known`; cause: The historical survey spec-remediation line contains two non-contiguous state transitions; remediation-2 preserves that fact and does not relabel the historical line as zero-mismatch.; resolution: `accepted`; lesson: Report state-chain continuity per formal line and preserve computed historical breaks as explicit gaps.

## All waste

- None recorded.

## Root causes and solutions

- `central-external-acceptance-boundary`: occurrences=1; cause_status: `external`; root cause: This package-local remediation has no admitted central Notebook receipt, browser/provider/host acceptance, full-gate execution, or release integration evidence.; solution: `accepted`
- `foreign-owner-suite-boundary`: occurrences=1; cause_status: `external`; root cause: The full Agent context suite still has 11 foreign-owner or synthetic fixture failures that require server-owned indexes, bindings, receipts, or artifact identities outside this remediation line.; solution: `accepted`
- `historical-state-chain-gap`: occurrences=1; cause_status: `known`; root cause: The historical survey spec-remediation line contains two non-contiguous state transitions; remediation-2 preserves that fact and does not relabel the historical line as zero-mismatch.; solution: `accepted`
- `report-admission-receipt-boundary`: occurrences=1; cause_status: `external`; root cause: The broad Report export suite cannot enter the admitted write-capable workflow because the server receipt is absent; this remediation only verified the bounded Report view and projection export probes.; solution: `accepted`
- `survey-agent-notebook-red-boundary`: occurrences=1; cause_status: `known`; root cause: Real Agent reads still synthesize unavailable survey/table fields and diagnostics attach absent Survey metadata; the committed Notebook receipt path uses generic budgeting that truncates typed Survey metadata instead of applying the bounded Survey projection.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `central-external-acceptance-boundary`: line experience occurrence(s)=1
- `foreign-owner-suite-boundary`: line experience occurrence(s)=1
- `historical-state-chain-gap`: line experience occurrence(s)=1
- `report-admission-receipt-boundary`: line experience occurrence(s)=1
- `survey-agent-notebook-red-boundary`: line experience occurrence(s)=1

## Future guidance

- Do not convert a package-local projection gate into central Agent context acceptance when unrelated owner fixtures are unavailable.
- Do not promote package-local green projection evidence to browser, provider, host, central, full-gate, or release acceptance.
- Exercise unavailable, ordinary non-Survey, and committed Notebook result paths independently before changing shared Agent projection assembly.
- Keep bounded Report projection evidence separate from admitted HTML/PDF/XLSX consumer acceptance.
- Report state-chain continuity per formal line and preserve computed historical breaks as explicit gaps.

## Event index

- #1: `b51f30a6-0466-4124-85da-975791e2ff38` | 2026-08-20T02:23:00.654Z | STATE_CHANGE/line_started | incident=`00cb3541-679a-422e-8ce9-6f7190b848cc` | lesson_key=`frozen-context-before-start` | event_sha256=`a4c03d6c1f11853723f4935b2106a5d57c41751d592c1c6a592fc14f9e00430e`
- #2: `c4e6a8b0-2d4f-6a8c-0e1b-3d5f7a9c2e4b` | 2026-08-20T02:30:00.000Z | FAILURE/agent_notebook_optional_projection_red | incident=`d5f7a9c2-e4b6-8a0c-2d4f-6a8b0e1c3d5f` | lesson_key=`survey-agent-notebook-red-boundary` | event_sha256=`66453dab6813b2803b8592aa5b34859d6f3aa89023e918eeb2d0bc93e9342859`
- #3: `e6a8b0d2-4f6a-8c0e-1b3d-5f7a9c2e4b6d` | 2026-08-20T02:30:01.000Z | STATE_CHANGE/red_probes_observed | incident=`f7a9c2e4-b6d8-0a2c-4e6f-8b0d2f4a6c8e` | lesson_key=`remediation-2-red-state-continuity` | event_sha256=`65eae7e6aa4dc8fc381a7a6ad5614ea4212aba93a03c3d19c1e3eeeb6130fa2c`
- #4: `a8c0e1b3-d5f7-9a2c-4e6f-8b0d2f4a6c8e` | 2026-08-20T02:34:00.000Z | GATE/agent_notebook_optional_projection_green | incident=`b9d1f3a5-c7e9-1b3d-5f7a-9c2e4a6b8d0f` | lesson_key=`survey-agent-notebook-optional-green` | event_sha256=`65eb5b85bf23c7f87551c9599c7569bb5ffea3d241ad1200f722b843bab24e6c`
- #5: `c0e1b3d5-f7a9-2c4e-6f8b-0d2f4a6c8e1b` | 2026-08-20T02:34:01.000Z | STATE_CHANGE/focused_projection_green | incident=`d1f3a5c7-e9b1-3d5f-7a9c-2e4a6b8d0f1b` | lesson_key=`remediation-2-green-state-continuity` | event_sha256=`c7ef48f47e0da1859a18332c7cc675d5e95a53b3c3913f64805d843499035296`
- #6: `1a2b3c4d-5e6f-7081-92a3-b4c5d6e7f801` | 2026-08-20T03:00:00.000Z | GATE/remediation_2_focused_regression_green | incident=`2b3c4d5e-6f70-8192-a3b4-c5d6e7f80192` | lesson_key=`survey-agent-optional-omission` | event_sha256=`4eea9216d4c72ddb3f44340269bd890b3cc91f6e48f13b7be535b1b15276fc1a`
- #7: `3c4d5e6f-7081-92a3-b4c5-d6e7f8019234` | 2026-08-20T03:01:00.000Z | GAP/agent_context_foreign_owner_boundary | incident=`4d5e6f70-8192-a3b4-c5d6-e7f801923456` | lesson_key=`foreign-owner-suite-boundary` | event_sha256=`0b07369fda87cc3c60aaa100ced5797e312b7ad130fcc4ebd85d2e557f3b716e`
- #8: `5e6f7081-92a3-b4c5-d6e7-f80192345678` | 2026-08-20T03:02:00.000Z | GAP/report_admission_not_verified | incident=`6f708192-a3b4-c5d6-e7f8-01923456789a` | lesson_key=`report-admission-receipt-boundary` | event_sha256=`54119c65474c347db433ebe82ff328b7cf31fc45b8ba511b2da5b0dc67fe28c0`
- #9: `708192a3-b4c5-d6e7-f801-923456789abc` | 2026-08-20T03:03:00.000Z | GAP/central_external_acceptance_not_verified | incident=`8192a3b4-c5d6-e7f8-0192-3456789abcde` | lesson_key=`central-external-acceptance-boundary` | event_sha256=`c30efd3fdb33509cc7e6de54028f8e278d8ee5d721c7461dce71d579352c1ac1`
- #10: `92a3b4c5-d6e7-f801-9234-56789abcdef0` | 2026-08-20T03:04:00.000Z | GAP/historical_state_chain_gap | incident=`a3b4c5d6-e7f8-0192-3456-789abcdef012` | lesson_key=`historical-state-chain-gap` | event_sha256=`a2be92585fe33b763c4f3506bb673887e412a3d454a4a61a341e8b5eafc6c969`
- #11: `b4c5d6e7-f801-9234-5678-9abcdef01234` | 2026-08-20T03:05:00.000Z | STATE_CHANGE/remediation_2_completed | incident=`c5d6e7f8-0192-3456-789a-bcdef0123456` | lesson_key=`survey-remediation-2-exact-handoff` | event_sha256=`01b104dffcb2a3a3a704ed0ce256dd33871ca0108b302586059f688bee419afc`
