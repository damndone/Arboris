# Retrospective — v1-8-9-p1-survey-central-source

## Goal

# Workbench v1.8.9 P1 Survey central source objective  ## Objective  Give Survey results the same server-owned source and projection foundation already required for classification. A persisted Survey run, after exact artifact/receipt/identity validation, must yield one opaque source snapshot that can be projected for Agent and Notebook without accepting a path, raw packet, caller registry, or forged capability. The provider contribution must be catalog-visible and model-agnostic across supported Survey OLS/Logit families. Unsupported families remain typed unavailable; this slice must not increase estimator count or change variance semantics.  ## Acceptance  - source snapshot is issued only from an authorized persisted receipt; - Survey identity, evidence status, design metadata, and unavailable reason   survive the adapter without recomputation; - Agent/Notebook adapters use the same source snapshot and reject path/raw   bypasses; - provider declaration is deterministic and coverage-visible; - focused adversarial tests, compileall, diff check, and formal verification   pass.  ## Non-goals  No Survey estimator changes, no Report/HTTP renderer mount, no new model families, no \`.sav/.dta\`, no browser/provider/full-gate/release.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/11 (45.5%; 45.5 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-20T23:05:17.023Z `tdd_red_survey_central_source_absent`; cause_status: `known`; cause: The focused Survey central-source contract test failed because the required server-owned source and consumer modules do not yet exist.; resolution: `accepted`; lesson: Freeze and observe the opaque source boundary before adding consumer adapters.
- #4 2026-08-20T23:11:26.337Z `survey_central_consumer_expanded_red`; cause_status: `known`; cause: Expanded Survey consumer tests exposed a Path subclass rejection, a continuous-outcome Logit fixture, and a diagnostic-file glob rather than the bound model artifact.; resolution: `open`; lesson: Capability boundaries must accept standard Path subclasses while test fixtures must construct the exact model family and indexed artifact they claim to exercise.

## All errors

- #2 2026-08-20T23:04:57.161Z `formal_red_event_payload_incomplete`; cause_status: `known`; cause: The first formal RED event input omitted the required schema_version and event_id fields, so the controlled CLI rejected it before appending any event.; resolution: `resolved`; lesson: Use the formal event schema exactly before treating a TDD result as recorded evidence.
- #7 2026-08-20T23:16:13.536Z `handoff_patch_operation_rejected`; cause_status: `known`; cause: The patch tool rejected a delete-and-add operation targeting the same handoff path; no workspace file changed.; resolution: `resolved`; lesson: Use one update operation when replacing temporary formal-event content with a handoff at the same path.

## All gaps

- #5 2026-08-20T23:14:36.530Z `survey_catalog_coverage_scope_gap`; cause_status: `known`; cause: Adding the required catalog-visible workbench.survey provider changes builtin provider and composable coverage totals, while the corresponding hard-coded coverage expectations are outside the frozen owned paths.; resolution: `open`; lesson: A new required provider must update aggregate coverage expectations through an explicitly authorized central coverage line.

## All waste

- None recorded.

## Root causes and solutions

- `formal-event-schema-before-append`: occurrences=1; cause_status: `known`; root cause: The first formal RED event input omitted the required schema_version and event_id fields, so the controlled CLI rejected it before appending any event.; solution: `resolved`
- `provider-catalog-coverage-scope`: occurrences=1; cause_status: `known`; root cause: Adding the required catalog-visible workbench.survey provider changes builtin provider and composable coverage totals, while the corresponding hard-coded coverage expectations are outside the frozen owned paths.; solution: `open`
- `single-operation-handoff-replacement`: occurrences=1; cause_status: `known`; root cause: The patch tool rejected a delete-and-add operation targeting the same handoff path; no workspace file changed.; solution: `resolved`
- `survey-central-consumer-real-source-fixture`: occurrences=1; cause_status: `known`; root cause: Expanded Survey consumer tests exposed a Path subclass rejection, a continuous-outcome Logit fixture, and a diagnostic-file glob rather than the bound model artifact.; solution: `open`
- `survey-central-source-contract-first`: occurrences=1; cause_status: `known`; root cause: The focused Survey central-source contract test failed because the required server-owned source and consumer modules do not yet exist.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `formal-event-schema-before-append`: line experience occurrence(s)=1
- `provider-catalog-coverage-scope`: line experience occurrence(s)=1
- `single-operation-handoff-replacement`: line experience occurrence(s)=1
- `survey-central-consumer-real-source-fixture`: line experience occurrence(s)=1
- `survey-central-source-contract-first`: line experience occurrence(s)=1

## Future guidance

- A new required provider must update aggregate coverage expectations through an explicitly authorized central coverage line.
- Capability boundaries must accept standard Path subclasses while test fixtures must construct the exact model family and indexed artifact they claim to exercise.
- Freeze and observe the opaque source boundary before adding consumer adapters.
- Use one update operation when replacing temporary formal-event content with a handoff at the same path.
- Use the formal event schema exactly before treating a TDD result as recorded evidence.

## Event index

- #1: `19ab0e21-c16b-4688-a6f0-8736216187af` | 2026-08-20T22:58:47.604Z | STATE_CHANGE/line_started | incident=`16527a75-01fc-4fc6-a09c-2a805af2586a` | lesson_key=`frozen-context-before-start` | event_sha256=`74342048ea9b0abac1e7dafac163251bf99e6207361d6d621fa662772003113b`
- #2: `ab6ab176-23d5-437f-bc6e-91f9614d8b15` | 2026-08-20T23:04:57.161Z | ERROR/formal_red_event_payload_incomplete | incident=`7a545b0c-b8ed-4b6b-992e-2696d5da54b6` | lesson_key=`formal-event-schema-before-append` | event_sha256=`32802d6e310116cb6369cd34568f0d8c5a1a3523379da4c627415a68e1e874fd`
- #3: `205bde7a-e9cc-4ceb-a3e2-3d5a60f9b77a` | 2026-08-20T23:05:17.023Z | FAILURE/tdd_red_survey_central_source_absent | incident=`49e13fea-1d3c-4d39-8947-28e99fd7f939` | lesson_key=`survey-central-source-contract-first` | event_sha256=`3e4f8ada58fa65b3218785e388b6d8c9a6b3b47ff5ebd3c04da4277d8691313a`
- #4: `4f9d13a4-9323-4ded-942d-9455d47b44e1` | 2026-08-20T23:11:26.337Z | FAILURE/survey_central_consumer_expanded_red | incident=`1455fd0d-11f5-4fa3-ad8b-0134f8b1c383` | lesson_key=`survey-central-consumer-real-source-fixture` | event_sha256=`d31a38fdaafccc90a932e9674d50ca14da5fd8d2a16435a2377c37111d47ee89`
- #5: `b9323c8f-bc00-49e0-8416-e5e54ea9b8a6` | 2026-08-20T23:14:36.530Z | GAP/survey_catalog_coverage_scope_gap | incident=`80fd451c-a742-4a57-8d0c-b73b1c013221` | lesson_key=`provider-catalog-coverage-scope` | event_sha256=`9cabde55c1eb9dfcb4c3bec700aa9f4932b0eb7f303a747ad99d7460bb7fa577`
- #6: `278f1cd2-e610-4894-bb8f-ef5c6889dbb7` | 2026-08-20T23:15:19.693Z | GATE/survey_central_source_focused_gate | incident=`1455fd0d-11f5-4fa3-ad8b-0134f8b1c383` | lesson_key=`survey-central-source-focused-gate` | event_sha256=`a02ca23c11f1b42d6587cd3a4cbac90dc54271209999840c932540390359e02d`
- #7: `328c9c11-6f50-44d9-bf83-73ee08f0c765` | 2026-08-20T23:16:13.536Z | ERROR/handoff_patch_operation_rejected | incident=`ae4e99f9-5120-4fbd-9d85-133cfe180c25` | lesson_key=`single-operation-handoff-replacement` | event_sha256=`7f3f456851153a9d2a3cab5c6857ca1aa93c80ef5fa5df5dc9b132fbc6596a20`
- #8: `0ab73173-30d3-470e-9bb8-0b50fb4a96ae` | 2026-08-20T23:18:22.953Z | STATE_CHANGE/context_rescope_required | incident=`57bad264-ddc6-4e48-98ce-e3dfc4a06325` | lesson_key=`context-pack-rescope` | event_sha256=`4f430b5de372d1499d967d9ca570e01ee8cffd7f6dbaff36836ccb16aeeb1aa8`
- #9: `e412620e-056d-4d9a-b1c7-87fdc0e60c16` | 2026-08-20T23:18:22.961Z | STATE_CHANGE/context_rescoped | incident=`e74d4173-2a4f-4eb1-8253-e62dfb8446c6` | lesson_key=`context-pack-rescope` | event_sha256=`e65b165406cd6a1e6bc99fa8d42a1b79db8f8a12c9713f5d6ba043c2b524d150`
- #10: `c2f7a94d-5e13-4b68-9a20-7d6c1f3e8b52` | 2026-08-20T23:20:16.408Z | GATE/survey_central_source_catalog_green | incident=`9e4b7c1a-6d2f-48a0-b5c3-7f1e9d2a6b84` | lesson_key=`catalog-denominator-explicit-rescope` | event_sha256=`cb7fc7152baff2836dc53971c7bf0e1f419e86b8c73d88f8dd68b095487b179a`
- #11: `f8a3c6d1-4e72-49b0-9c5a-7d2e1f6b8a34` | 2026-08-20T23:20:42.240Z | STATE_CHANGE/line_completed | incident=`2c7f9a4e-6b13-48d0-5e2a-1f8c6d3b7a95` | lesson_key=`bounded-survey-source-closeout` | event_sha256=`170cd6ae015d061edb0748a0dd38fefa1b9da38e014f22de0a3b5a08b04b9db6`
