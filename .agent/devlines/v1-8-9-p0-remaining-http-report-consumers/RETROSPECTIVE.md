# Retrospective — v1-8-9-p0-remaining-http-report-consumers

## Goal

# Workbench v1.8.9 P0 Remaining HTTP and Report Consumers  ## Objective  Close the remaining HTTP/report consumer tests that still expect unbound \`report.html\`, raw model packets, or legacy \`table_1\`/statistical projections. Use the current typed evidence and unavailable contracts. If a durable typed artifact already exists but the HTTP surface is missing a safe projection, implement that projection through the server-owned boundary; never restore raw-file authority.  ## Scope  - \`tests/test_prediction_models.py\` - \`tests/test_results_service.py\` - \`tests/test_statistical_tests_reachability_v186.py\` - \`tests/test_statistics_api_e2e_v186.py\` - \`backend/workbench/http/runs_routes.py\` (only if a typed projection is   demonstrably supported by the current contract)  ## Acceptance  - Focused tests pass without making raw HTML/model files authoritative. - Statistical and prediction results are either projected from durable typed   evidence with identity/status bindings or explicitly \`UNAVAILABLE\`. - Invalid legacy packets remain fail-closed without leaking raw payloads.

## Final status

COMPLETED

## Metrics

- Failure frequency: 6/9 (66.7%; 66.7 per 100 events)
- Repeat rate: 0/6 (0.0%)
- Recurrence rate: 0/6 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=4)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T09:16:31.894Z `focused_suite_red`; cause_status: `known`; cause: The frozen HTTP and report consumer suite still contains legacy HTML, table, and unbound packet expectations.; resolution: `open`; lesson: Separate legacy consumer expectations from typed evidence and preserve unavailable fail-closed HTTP boundaries.
- #6 2026-08-21T09:25:02.051Z `agent_summary_legacy_statistics_projection`; cause_status: `known`; cause: The migrated focused test still expected inspect_result_summary to expose statistical_evidence, but the current server-owned artifact validator fails closed on the emitted measurement_advisory type and returns AGENT_RESULT_ARTIFACT_INVALID without a legacy packet fallback.; resolution: `open`; lesson: When a typed consumer cannot validate the complete server-owned artifact manifest, assert explicit unavailable output and use the dedicated typed evidence reader rather than reintroducing a legacy nested packet.

## All errors

- #3 2026-08-21T09:16:49.540Z `hash_tool_locale_failure`; cause_status: `external`; cause: The first sha256 probe used a locale-sensitive tool that failed before producing a digest; the portable sha256sum fallback succeeded.; resolution: `accepted`; lesson: Use locale-independent sha256sum for formal evidence digests in this host environment.
- #4 2026-08-21T09:21:22.055Z `test_migration_name_error`; cause_status: `known`; cause: The first reachability migration referenced Path without importing it and used the project root instead of the run root.; resolution: `resolved`; lesson: Keep migrated HTTP assertions anchored to the exact run root and run the file immediately after each test patch.
- #7 2026-08-21T09:25:22.877Z `formal_event_schema_retry`; cause_status: `known`; cause: The first formal append payload omitted schema_version and was rejected before mutating the event stream; the payload was corrected and re-appended through the CLI.; resolution: `resolved`; lesson: Include schema_version in every temporary event payload before invoking the formal append CLI.

## All gaps

- #5 2026-08-21T09:21:22.176Z `artifact_registry_type_vocabulary`; cause_status: `known`; cause: The canonical artifact-listing validator rejects the existing measurement_advisory artifact emitted by a statistics run even though every indexed file and digest is valid.; resolution: `open`; lesson: Do not expand this Report consumer line into artifact vocabulary repair; carry the registry type gap to its owning mainline change.

## All waste

- None recorded.

## Root causes and solutions

- `agent-summary-fail-closed-migration`: occurrences=1; cause_status: `known`; root cause: The migrated focused test still expected inspect_result_summary to expose statistical_evidence, but the current server-owned artifact validator fails closed on the emitted measurement_advisory type and returns AGENT_RESULT_ARTIFACT_INVALID without a legacy packet fallback.; solution: `open`
- `artifact-registry-vocabulary-owner`: occurrences=1; cause_status: `known`; root cause: The canonical artifact-listing validator rejects the existing measurement_advisory artifact emitted by a statistics run even though every indexed file and digest is valid.; solution: `open`
- `focused-test-migration-anchor`: occurrences=1; cause_status: `known`; root cause: The first reachability migration referenced Path without importing it and used the project root instead of the run root.; solution: `resolved`
- `formal-event-schema-before-append`: occurrences=1; cause_status: `known`; root cause: The first formal append payload omitted schema_version and was rejected before mutating the event stream; the payload was corrected and re-appended through the CLI.; solution: `resolved`
- `legacy-http-consumer-contract`: occurrences=1; cause_status: `known`; root cause: The frozen HTTP and report consumer suite still contains legacy HTML, table, and unbound packet expectations.; solution: `open`
- `locale-independent-evidence-digest`: occurrences=1; cause_status: `external`; root cause: The first sha256 probe used a locale-sensitive tool that failed before producing a digest; the portable sha256sum fallback succeeded.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `agent-summary-fail-closed-migration`: line experience occurrence(s)=1
- `artifact-registry-vocabulary-owner`: line experience occurrence(s)=1
- `focused-test-migration-anchor`: line experience occurrence(s)=1
- `formal-event-schema-before-append`: line experience occurrence(s)=1
- `legacy-http-consumer-contract`: line experience occurrence(s)=1
- `locale-independent-evidence-digest`: line experience occurrence(s)=1

## Future guidance

- Classify each red assertion by authority: migrate legacy presentation consumers to typed unavailable contracts, retain existing bounded typed evidence, and defer registry vocabulary repair to its owning mainline.
- Do not expand this Report consumer line into artifact vocabulary repair; carry the registry type gap to its owning mainline change.
- Include schema_version in every temporary event payload before invoking the formal append CLI.
- Keep migrated HTTP assertions anchored to the exact run root and run the file immediately after each test patch.
- Separate legacy consumer expectations from typed evidence and preserve unavailable fail-closed HTTP boundaries.
- Use locale-independent sha256sum for formal evidence digests in this host environment.
- When a typed consumer cannot validate the complete server-owned artifact manifest, assert explicit unavailable output and use the dedicated typed evidence reader rather than reintroducing a legacy nested packet.

## Event index

- #1: `3ab08f4d-bf01-493c-bb41-e93a9f439d4d` | 2026-08-21T09:08:07.529Z | STATE_CHANGE/line_started | incident=`c4f92ca4-1be0-41d6-93f3-66bd4a54bb31` | lesson_key=`frozen-context-before-start` | event_sha256=`f1388081eb6341cab7f51231871fca7e3a9dbee968eff11362520c8fa623a928`
- #2: `6a9c4d7e-2b1f-4c83-9d56-0e7a1b2c3d4f` | 2026-08-21T09:16:31.894Z | FAILURE/focused_suite_red | incident=`7b1e5d9c-3a6f-4d82-9c10-5e7a2b4d6f80` | lesson_key=`legacy-http-consumer-contract` | event_sha256=`5fde6065ba038790a63b1eca34e7d590aafebcb054ff822c3b39d06d2670c0e3`
- #3: `8c2e6a4b-1d9f-4e73-a5b8-0c6d2f1e9a34` | 2026-08-21T09:16:49.540Z | ERROR/hash_tool_locale_failure | incident=`9d3f7b5c-2a1e-4c86-b9d0-6f8a3e5c7b21` | lesson_key=`locale-independent-evidence-digest` | event_sha256=`dc4d0c056fb8f8c6ead712a29220f2a7d348bc99a5d58ac33ba76eae12408ce5`
- #4: `1e7c5a3b-9d2f-4b86-a0c1-6e8f2d4a7b90` | 2026-08-21T09:21:22.055Z | ERROR/test_migration_name_error | incident=`2f8b6d4a-1c9e-47b3-a5d0-6e2f9c7b4a81` | lesson_key=`focused-test-migration-anchor` | event_sha256=`00b56cd6ad6c8a34d4f6cda0848a3243e61125bc15c008105330882076549940`
- #5: `3b9f1d7e-5a2c-4e86-b0d1-7c4a8f2e6b90` | 2026-08-21T09:21:22.176Z | GAP/artifact_registry_type_vocabulary | incident=`4c1e7a9d-3b5f-46a8-b0d2-7e9c4a1f6b83` | lesson_key=`artifact-registry-vocabulary-owner` | event_sha256=`fc1c6e0600f703641a65f1e4040cb6c8dc657d6444c575ee9e54c4f0192d8c19`
- #6: `5d2f8a4c-1b7e-4690-a3c5-9f2e6b8d4a17` | 2026-08-21T09:25:02.051Z | FAILURE/agent_summary_legacy_statistics_projection | incident=`6e3a9c1f-5b7d-42e8-a0c4-1f6b9d3e7a25` | lesson_key=`agent-summary-fail-closed-migration` | event_sha256=`667f00f7b5d5fdc42ca8102e9f277d0f7e4254c5f65c48511b845e41bd9aa737`
- #7: `7c1e5a9d-3b6f-42a8-b0d4-8f2e6c9a1b57` | 2026-08-21T09:25:22.877Z | ERROR/formal_event_schema_retry | incident=`8e4a1c7d-5b9f-4632-a0d6-1f7c3e9b5a28` | lesson_key=`formal-event-schema-before-append` | event_sha256=`c7b28eca4c402294890823825a929b9ab98cf4d0d4b609e108fae86c39b0396d`
- #8: `9f3b7a1c-5d2e-48a6-b0c9-7e4f1d8a2b63` | 2026-08-21T09:27:38.000Z | REVIEW/consumer_contract_classification | incident=`2a6e9c4f-1b7d-45e8-a0c3-9f5b2d7a6e14` | lesson_key=`authority-boundary-consumer-review` | event_sha256=`127a1e1e8e50649b6f90b01c750262bbf6f397110ddf84fed3bd144238e3e876`
- #9: `a6f4c2d8-1b7e-49a0-8c35-2d9f6e4b7a10` | 2026-08-21T09:30:19.043Z | STATE_CHANGE/line_completed | incident=`d8e4b6f2-9a17-4c30-8e5d-1f7a3b9c6d20` | lesson_key=`http-consumer-scoped-green-with-registry-gap` | event_sha256=`e15eb1496d3e117c3c3b5fc05fea2a8f61bfc28cc8f3a3e9e144306f0f1c7e48`
