# Retrospective — v1-8-9-p1-survey-spec-remediation

## Goal

# Workbench v1.8.9 P1 Survey specification remediation objective  ## Objective  Repair only the independent Survey P1 specification blockers at the existing workflow, Agent result-summary, and Report projection seams. Preserve the shared OLS/Logit/Probit/Poisson survey variance engine, sampling weights, replicate weights, and Poisson exposure validation. Do not modify central integration, browser/provider/host acceptance, or release machinery.  ## Required behavior  - Every survey declaration distinguishes absent from present falsey values.   \`0\`, \`False\`, empty weight/subpopulation frames, and other declared values   must not be swallowed by defaults. A present value with the wrong type or   invalid content fails closed with a typed Survey error and cannot continue as   an ordinary model. - Agent result summaries and consumer projections omit optional fields that are   absent from persisted evidence. They must not invent \`survey_design=None\`,   \`marginal_effects=[]\`, or equivalent placeholders. Persisted survey design,   variance source, provenance, and replicate metadata remain bounded and typed. - Real workflow and Agent/Report probes cover the falsey and no-invention   boundaries. Existing shared variance, weights, replicate weights, and   exposure safety must remain green. - Formal records use only \`scripts/devline_control.py\`; every material review,   gap, failure, state change, and gate is appended through the CLI. The final   handoff reports the exact product tip and current test numbers and keeps   central admitted Report, browser, provider, host, full-gate, and release   evidence explicitly \`NOT VERIFIED\`.  ## Boundary  This is a package-local remediation. It may change only the Survey declaration and projection seams, their directly affected tests, this objective, the new formal line records, and the exact handoff. It must not alter the historical \`v1-8-9-p1-survey-extension\` line or the completed \`v1-8-9-p1-survey-formal-closeout-remediation\` line.  ## Baseline and gates  - Baseline SHA: \`319249e6541d202345f2acb63484cf90c7dc3153\` - Dependencies: \`v1-8-9-p1-survey-formal-closeout-remediation\`,   \`v1-8-9-p1-survey-extension\` - Known gates: central admitted Report, browser acceptance, provider evidence,   host acceptance, full gate, release/merge/tag remain \`NOT VERIFIED\`.

## Final status

COMPLETED

## Metrics

- Failure frequency: 6/13 (46.2%; 46.2 per 100 events)
- Repeat rate: 0/6 (0.0%)
- Recurrence rate: 0/6 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=5)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-20T01:54:00.000Z `falsey_and_no_invention_red`; cause_status: `known`; cause: Real workflow probes showed falsey survey declarations were swallowed by truthiness/default coercion, while Agent and Report projections synthesized absent survey sections.; resolution: `open`; lesson: Turn each independent Survey review boundary into a real workflow or consumer RED probe before changing the shared typed seam.

## All errors

- #2 2026-08-20T01:54:00.000Z `formal_event_schema_probe`; cause_status: `known`; cause: The first RED event draft omitted the required single evidence digest, so the formal CLI rejected it before append.; resolution: `resolved`; lesson: Validate formal event vocabulary and evidence shape before treating a failure record as appended.

## All gaps

- #7 2026-08-20T02:01:00.000Z `agent_foreign_fixture_boundary`; cause_status: `external`; cause: The full Agent context-tools suite still contains foreign-owner synthetic fixtures without server-owned model indexes, bindings, workflow receipts, or artifact identities; those fixtures return typed unavailable instead of being repaired in this Survey line.; resolution: `accepted`; lesson: Keep foreign-owner server evidence prerequisites visible and fail closed; do not widen a package-local Survey repair to synthetic Agent fixtures.
- #8 2026-08-20T02:01:00.000Z `report_admission_not_verified`; cause_status: `external`; cause: The broad workflow E2E suite still expects admitted Report HTML, but the protected write-capable Report path has no admitted receipt in this package-local run; Survey projection remains tested separately.; resolution: `accepted`; lesson: Keep protected Report admission and browser acceptance separate from package-local Survey projection evidence.
- #9 2026-08-20T02:01:00.000Z `survey_spec_focused_green`; cause_status: `not_applicable`; cause: The new falsey declaration and no-invention probes and the owned Survey/Agent/Report focused suites pass after the minimal seam repair.; resolution: `not_applicable`; lesson: Keep reviewer-directed falsey and no-invention probes at the real workflow and typed consumer boundaries.
- #12 2026-08-20T02:27:00.000Z `central_and_external_acceptance_not_verified`; cause_status: `external`; cause: This package-local remediation has no authority to admit or change the central Report consumer, browser/provider/host acceptance, external Survey oracle evidence, full gate, or release integration.; resolution: `accepted`; lesson: Keep package-local evidence separate from central admission and release acceptance boundaries.

## All waste

- None recorded.

## Root causes and solutions

- `agent-foreign-owner-boundary`: occurrences=1; cause_status: `external`; root cause: The full Agent context-tools suite still contains foreign-owner synthetic fixtures without server-owned model indexes, bindings, workflow receipts, or artifact identities; those fixtures return typed unavailable instead of being repaired in this Survey line.; solution: `accepted`
- `central-and-external-gates-not-verified`: occurrences=1; cause_status: `external`; root cause: This package-local remediation has no authority to admit or change the central Report consumer, browser/provider/host acceptance, external Survey oracle evidence, full gate, or release integration.; solution: `accepted`
- `formal-event-schema-before-append`: occurrences=1; cause_status: `known`; root cause: The first RED event draft omitted the required single evidence digest, so the formal CLI rejected it before append.; solution: `resolved`
- `report-admission-boundary`: occurrences=1; cause_status: `external`; root cause: The broad workflow E2E suite still expects admitted Report HTML, but the protected write-capable Report path has no admitted receipt in this package-local run; Survey projection remains tested separately.; solution: `accepted`
- `survey-spec-focused-green`: occurrences=1; cause_status: `not_applicable`; root cause: The new falsey declaration and no-invention probes and the owned Survey/Agent/Report focused suites pass after the minimal seam repair.; solution: `not_applicable`
- `survey-spec-red-at-real-boundary`: occurrences=1; cause_status: `known`; root cause: Real workflow probes showed falsey survey declarations were swallowed by truthiness/default coercion, while Agent and Report projections synthesized absent survey sections.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `agent-foreign-owner-boundary`: line experience occurrence(s)=1
- `central-and-external-gates-not-verified`: line experience occurrence(s)=1
- `formal-event-schema-before-append`: line experience occurrence(s)=1
- `report-admission-boundary`: line experience occurrence(s)=1
- `survey-spec-focused-green`: line experience occurrence(s)=1
- `survey-spec-red-at-real-boundary`: line experience occurrence(s)=1

## Future guidance

- Keep foreign-owner server evidence prerequisites visible and fail closed; do not widen a package-local Survey repair to synthetic Agent fixtures.
- Keep package-local evidence separate from central admission and release acceptance boundaries.
- Keep protected Report admission and browser acceptance separate from package-local Survey projection evidence.
- Keep reviewer-directed falsey and no-invention probes at the real workflow and typed consumer boundaries.
- Reconcile boundary counts after correcting an accidental non-target change before freezing the handoff numbers.
- Turn each independent Survey review boundary into a real workflow or consumer RED probe before changing the shared typed seam.
- Validate formal event vocabulary and evidence shape before treating a failure record as appended.

## Event index

- #1: `6f5ae263-32c2-4a72-a109-e1fb24794760` | 2026-08-20T01:52:10.807Z | STATE_CHANGE/line_started | incident=`36ad6462-df15-4673-b9fd-074e81c15ba7` | lesson_key=`frozen-context-before-start` | event_sha256=`fb287f0805b63d8b4412609b98df3b89f60eefa99a5f362b242bd81243c3240b`
- #2: `2e4f6a8c-0b1d-4e5f-9a7b-c3d5e6f70819` | 2026-08-20T01:54:00.000Z | ERROR/formal_event_schema_probe | incident=`3f5b7a9c-2e4f-60a1-82b3-c4d5e6f70819` | lesson_key=`formal-event-schema-before-append` | event_sha256=`054acc7438dfce89001829470c66abb3c69d5871b612347b60f5b8264546fae9`
- #3: `0c2d4e6f-8a1b-4c3d-9e5f-60718293a4b5` | 2026-08-20T01:54:00.000Z | FAILURE/falsey_and_no_invention_red | incident=`1d3f5b7a-9c2e-4f60-a182-b3c4d5e6f708` | lesson_key=`survey-spec-red-at-real-boundary` | event_sha256=`2654d72b6e0d47263716e3a5b02c106e8a9d628603c384093a811bbf7170f5e7`
- #4: `d94fd4a2-447f-4af5-a575-8a8b21a6a331` | 2026-08-20T01:56:15.413Z | STATE_CHANGE/context_rescope_required | incident=`a1d3311e-7b98-4b8a-9224-e9d4dd6a44f8` | lesson_key=`context-pack-rescope` | event_sha256=`eacf5255b64684fef4e87941ca70c93bdbed7f9186f3a61b173eaf67c8332182`
- #5: `b7630c2f-d051-451a-a810-df0ac77d67b6` | 2026-08-20T01:56:15.418Z | STATE_CHANGE/context_rescoped | incident=`825c90f6-70bb-4ba0-a70b-c72ce5598ca6` | lesson_key=`context-pack-rescope` | event_sha256=`82dafa41f09650fe58fdeeaf88b55133992292b6a08946db57c60e33d531af7e`
- #6: `4f6a8c0b-1d2e-4f60-a182-b3c4d5e6f709` | 2026-08-20T02:01:00.000Z | GATE/survey_spec_focused_green | incident=`5a7c9e1b-3d5f-6071-82b3-c4d5e6f7091a` | lesson_key=`survey-spec-focused-green` | event_sha256=`aa83aadb80d11d9c1dd47faf3ff3d8bc850f389f2092b1fc4433b446c23aaa2f`
- #7: `6b8d0f1a-3c5e-4a72-b394-d5e6f7091a2b` | 2026-08-20T02:01:00.000Z | GAP/agent_foreign_fixture_boundary | incident=`7c9e1b3d-5f60-71a2-83b4-c5d6e7f8091a` | lesson_key=`agent-foreign-owner-boundary` | event_sha256=`1242e00ba6e7ab4c3122f595802cbf80324e3dd05518b2edc5bebe9423ae8d0e`
- #8: `8d0f1a3c-5e6b-4c84-a5d6-e7f8091a2b3c` | 2026-08-20T02:01:00.000Z | GAP/report_admission_not_verified | incident=`9e1b3d5f-6071-4a82-b3c4-d5e6f7091a2b` | lesson_key=`report-admission-boundary` | event_sha256=`ad99f2be39d38d663c0b5b8112b26926c89fa8dade2400cd31e0e17c041ead47`
- #9: `1a3c5e7f-8091-4b2d-a3c4-d5e6f7091a2b` | 2026-08-20T02:01:00.000Z | GAP/survey_spec_focused_green | incident=`5a7c9e1b-3d5f-6071-82b3-c4d5e6f7091a` | lesson_key=`survey-spec-focused-green` | event_sha256=`b6018dcbbc957b430f2e2e60680ef9be3353bcf5dfd5f0f163fdc4a15069a58f`
- #10: `2b4d6f80-1a3c-5e7f-9b2d-4a6c8e0f1b3d` | 2026-08-20T02:20:00.000Z | REVIEW/agent_fixture_gap_reconciled | incident=`4c6e8a02-5b7d-9f1a-3c5e-7b9d1f3a5c7e` | lesson_key=`agent-foreign-owner-gap-reconciled` | event_sha256=`515441516054cd1fa0c74d2c85c3fa210e0568ac886760cd2762850f917fe0f5`
- #11: `5d7f9b1c-3e6a-8c0f-2b4d-6f8091a3c5e7` | 2026-08-20T02:25:00.000Z | GATE/product_tip_focused_green | incident=`6e8a02b4-5d7f-9b1c-3e6a-8c0f2b4d6f80` | lesson_key=`survey-product-tip-frozen` | event_sha256=`4047b6ce4dca739d79c39823523d327fbb5ab9b33924ffb470b52bb68507f127`
- #12: `7f9b1c3e-6a8c-0f2b-4d6f-8091a3c5e7b9` | 2026-08-20T02:27:00.000Z | GAP/central_and_external_acceptance_not_verified | incident=`8a02b4d6-7f9b-1c3e-6a8c-0f2b4d6f8091` | lesson_key=`central-and-external-gates-not-verified` | event_sha256=`a5ec2a9e36b2705f3802a6b3d85fe6ce2b17b6434d4ec8e9d0bc42e87cd379cc`
- #13: `9b1c3e6a-8c0f-2b4d-6f80-91a3c5e7b9d1` | 2026-08-20T02:28:00.000Z | STATE_CHANGE/remediation_completed | incident=`a02b4d6f-7f9b-1c3e-6a8c-0f2b4d6f8091` | lesson_key=`survey-spec-remediation-completed` | event_sha256=`6a227124ff56fb599647698dbb95d998a170f9356a2a9cb93229be65833ca486`
