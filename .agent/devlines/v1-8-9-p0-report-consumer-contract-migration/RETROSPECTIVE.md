# Retrospective — v1-8-9-p0-report-consumer-contract-migration

## Goal

# Workbench v1.8.9 P0 Report Consumer Contract Migration  ## Objective  Migrate historical tests that consume an unbound \`reports/report.html\` to the current typed Report evidence contract. An unbound run must remain typed UNAVAILABLE/failed, with no citable facts and no raw HTML authority. Preserve owner-admitted Report tests separately; do not weaken the owner/evidence gate or restore implicit HTML generation.  ## Scope  - \`tests/test_imputation_cache.py\` - \`tests/test_imputation_mice.py\` - \`tests/test_labels_v186.py\` - \`tests/test_legacy_run_compat.py\`  ## Acceptance  - Focused tests pass against the typed Report projection. - Imputation, labels, artifact counts, and model facts remain asserted through   their durable typed artifacts or typed diagnostics. - Legacy HTTP report routes fail closed with the typed unavailable reason when   the host owner capability is absent; no raw HTML is reintroduced. - Compile, diff check, formal verify, and retrospective pass.  ## Non-goals  Do not change production Report authority, owner resolution, evidence transport, or HTML rendering solely to satisfy these historical callers.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/6 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T07:52:57.222Z `scoped_report_consumer_suite_red`; cause_status: `known`; cause: The scoped suite still reads unbound reports/report.html, expects report artifact counts, and requires legacy Report HTTP 200 despite the typed fail-closed contract.; resolution: `open`; lesson: Migrate historical consumers to typed Report diagnostics and durable artifacts.
- #3 2026-08-21T07:57:27.481Z `cache_hit_artifact_index_overassertion`; cause_status: `known`; cause: The first migrated cache assertion required imputed_dataset to be re-registered in the cache-hit child artifact index even though the durable contract preserves the file and imputation_summary while retaining the model artifacts.; resolution: `resolved`; lesson: Assert cache-hit durable files and registered artifacts according to their actual typed ownership.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `cache-hit-artifact-contract`: occurrences=1; cause_status: `known`; root cause: The first migrated cache assertion required imputed_dataset to be re-registered in the cache-hit child artifact index even though the durable contract preserves the file and imputation_summary while retaining the model artifacts.; solution: `resolved`
- `legacy-report-consumer-contract`: occurrences=1; cause_status: `known`; root cause: The scoped suite still reads unbound reports/report.html, expects report artifact counts, and requires legacy Report HTTP 200 despite the typed fail-closed contract.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `cache-hit-artifact-contract`: line experience occurrence(s)=1
- `legacy-report-consumer-contract`: line experience occurrence(s)=1

## Future guidance

- Assert cache-hit durable files and registered artifacts according to their actual typed ownership.
- Migrate historical consumers to typed Report diagnostics and durable artifacts.

## Event index

- #1: `aa6197ae-74fa-4062-90e3-c230be62b094` | 2026-08-21T07:43:16.579Z | STATE_CHANGE/line_started | incident=`729537cb-c8fa-4c75-a421-590437b9a747` | lesson_key=`frozen-context-before-start` | event_sha256=`e9f40f07f0970889f9b5b811946dbb35a5481617cf48a9787a1153c6acb2baa9`
- #2: `a19c8d75-4f61-47ab-9f21-3aefb8f0799c` | 2026-08-21T07:52:57.222Z | FAILURE/scoped_report_consumer_suite_red | incident=`4a8cf631-69a2-4db5-b31e-6d9c7ab3f8d2` | lesson_key=`legacy-report-consumer-contract` | event_sha256=`cdce764f3d8db932f5294717d459cde76e72aa537ba290b37e0cbdc342c7ea57`
- #3: `b20d9e86-5f72-48bc-af32-4befc9a18ad0` | 2026-08-21T07:57:27.481Z | FAILURE/cache_hit_artifact_index_overassertion | incident=`5b9de742-70a3-4ec6-c42f-7e0d1b2c4f93` | lesson_key=`cache-hit-artifact-contract` | event_sha256=`31c1f37a4d84002ef321de46935866a0cb10ce5a23e3573ff971573f0b9b29a6`
- #4: `c31e0f97-6a83-49cd-b043-5cf0d9ab1e74` | 2026-08-21T07:58:56.390Z | GATE/report_focused_tests_passed | incident=`6c0f3187-8b94-4ade-c153-6f1a2b3c4d5e` | lesson_key=`typed-report-consumer-closeout` | event_sha256=`1a01222113c55746553845da0169fa7a7c80361b779295641ebc1a5331d279ec`
- #5: `d42f1a08-7b94-4ade-c154-6f0e1b2c3d5f` | 2026-08-21T07:59:11.950Z | GATE/formal_closeout_checks_passed | incident=`7d1a2b3c-4e5f-6071-8a9b-0c1d2e3f4a5b` | lesson_key=`report-consumer-formal-closeout` | event_sha256=`51eb7de1e1d68e8274f450a935938527ac104f75d145fada4f1fad53c8ecce3f`
- #6: `e53a2b19-8c04-4fde-d165-7a0f2b3c4d6e` | 2026-08-21T07:59:54.193Z | STATE_CHANGE/report_consumer_contract_migration_completed | incident=`8e2b3c4d-5f60-7182-9a0b-1c2d3e4f5a6b` | lesson_key=`report-consumer-line-complete` | event_sha256=`29799d5209dbcab3e383daffe4ef4c5fe5071efd7a54211da77af359f64c2eec`
