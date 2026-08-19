# Retrospective — v1-8-9-p0-evidence-report-hardening

## Goal

# Workbench v1.8.9 P0 Evidence and Report Hardening Objective  Close the real consumer-boundary gaps between persisted workflow artifacts, EvidenceEnvelope/EvidenceCommitBinding, and the Report UI.  Required outcomes:  - an indexed post-estimation artifact without a committed canonical evidence   binding cannot create citable Report facts; it must render as   \`UNAVAILABLE\`/\`BLOCKED\` with a typed reason; - the actual ReportView path must receive and render the typed evidence   projection, including status, envelope digest, provenance and bounded facts; - no raw JSON fallback or recursive scalar extraction may bypass evidence   status, digest, or admission checks; - Agent, Notebook, and Report must preserve the same fact identity/value for a   committed envelope; - tests must prove both the accepted committed path and the rejected   uncommitted/tampered path.  This line owns the run/report evidence loading and Report consumer paths plus their tests. It does not modify Agent/Notebook routing, provider execution, model estimators, or release sidecars. Browser/provider/full-host-gate acceptance remains separate.

## Final status

COMPLETED

## Metrics

- Failure frequency: 18/47 (38.3%; 38.3 per 100 events)
- Repeat rate: 0/18 (0.0%)
- Recurrence rate: 0/18 (0.0%)
- MTTR: median=0 ms (sample=13; unresolved=5)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/18 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #3 2026-08-19T17:01:00.000Z `preexisting_host_authority`; cause_status: `external`; cause: The existing post-estimation compatibility run failed before the Report route assertion because the protected Agent workflow host-authority resolver is not configured.; resolution: `accepted`; lesson: Keep Agent host-authority failures separate from the Report consumer gate and use an isolated route probe for this line.
- #4 2026-08-19T17:02:00.000Z `formal_event_validation_retry`; cause_status: `known`; cause: The first TDD red gate event draft used an unsupported preventability value and was rejected by the formal CLI before being corrected and appended.; resolution: `resolved`; lesson: Validate formal event enum values before invoking the append control.
- #5 2026-08-19T17:04:00.000Z `preexisting_api_admission`; cause_status: `external`; cause: The broader API compatibility suite could not materialize its completed-run report artifacts because the host-owned workflow admission receipt is unavailable.; resolution: `accepted`; lesson: Use focused route probes when the broader API fixture depends on an unavailable host admission receipt.
- #12 2026-08-19T17:36:00.000Z `formal_verify_stale_retrospective`; cause_status: `known`; cause: Formal verify observed that the completed retrospective had not yet been regenerated after the new TDD red event was appended.; resolution: `mitigated`; lesson: Regenerate the formal retrospective immediately after appending post-closeout evidence before running final verification.
- #16 2026-08-19T18:00:00.000Z `owner_capability_fixture_mismatch`; cause_status: `known`; cause: After removing the report-local fake persistence ports, the existing canonical indexed tests still supplied a C1 fixture without a C0 owner capability and failed closed at the required content-hash gate.; resolution: `not_applicable`; lesson: Canonical Report probes must exercise the same C0 owner capability as production rather than pass a detached consumer fixture.
- #17 2026-08-19T17:59:30.000Z `content_hash_alias_probe_failure`; cause_status: `known`; cause: The first real C0 owner probe reached production persistence but exposed an inconsistent pair of content-hash aliases: evidence_content_hash remained canonical while content_hash was tampered.; resolution: `resolved`; lesson: All index aliases for an authoritative identity must agree before a persistence capability is called.
- #18 2026-08-19T18:02:00.000Z `route_owner_setup_failure`; cause_status: `known`; cause: The first route-level owner injection probe passed a non-existent persistence root to EvidencePacketStoreV1.admit, which correctly rejected the root before the route could run.; resolution: `resolved`; lesson: Owner-side persistence probes must materialize the admitted root before constructing the immutable store capability.
- #27 2026-08-19T18:55:40.000Z `route_identity_seam_regression`; cause_status: `known`; cause: The first final backend gate started while the route still used the pre-hardening run-only current_report_evidence_persistence call, so the HTTP typed-failure probe raised TypeError before reaching the fail-closed projection.; resolution: `resolved`; lesson: After tightening an owner-capability selector, rerun the real HTTP route probe immediately rather than relying on an earlier in-flight test process.
- #33 2026-08-19T19:30:00.000Z `formal_cli_unknown_command`; cause_status: `known`; cause: The initial formal CLI inspection attempted an unsupported status subcommand while the documented control surface uses verify and refresh-context.; resolution: `resolved`; lesson: Use only the documented devline_control subcommands and record command-surface errors.
- #34 2026-08-19T19:31:00.000Z `formal_append_stage_validation`; cause_status: `known`; cause: The first material event append was rejected because the event used an undocumented verification stage value.; resolution: `resolved`; lesson: Use an existing documented event stage when appending formal evidence.
- #37 2026-08-19T19:42:00.000Z `report_view_model_restore_and_migration`; cause_status: `known`; cause: The first sandboxed git restore could not create the worktree index lock and a locale-dependent mechanical rewrite command exited before changing the test file; both were retried or replaced with the allowed controlled edit path.; resolution: `resolved`; lesson: When a requested test restoration touches protected worktree metadata, use the smallest approved restore and keep the complete regression surface visible before migration.
- #38 2026-08-19T19:43:30.000Z `formal_append_lesson_key_validation`; cause_status: `known`; cause: The formal event append for the migrated test green was rejected because its lesson_key used underscores instead of the normalized identifier grammar.; resolution: `resolved`; lesson: Use normalized hyphenated lesson identifiers for formal event append.
- #40 2026-08-19T19:54:00.000Z `frontend_typecheck_guard_narrowing`; cause_status: `known`; cause: The first frontend typecheck after adding provenance and status monotonicity guards rejected an unknown validationStatus value at the Array.includes boundary.; resolution: `resolved`; lesson: Keep runtime schema guards and TypeScript narrowing aligned when hardening a consumer boundary.
- #41 2026-08-19T19:55:00.000Z `diagnostic_locale_failure`; cause_status: `known`; cause: A diagnostic shasum command emitted a locale initialization panic in the managed shell; the digest was obtained with openssl dgst and no source change was made by the failed command.; resolution: `resolved`; lesson: Use locale-independent repository diagnostics when the managed shell cannot initialize its configured locale.
- #42 2026-08-19T19:55:00.000Z `frontend_typecheck_status_narrowing`; cause_status: `known`; cause: The first narrowing fix still left candidate.status as unknown in the frontend status monotonicity includes check, so the second typecheck remained red while focused Vitest and backend tests were green.; resolution: `resolved`; lesson: Narrow discriminated runtime values once and reuse the narrowed value throughout the consumer contract checks.
- #44 2026-08-19T19:56:30.000Z `formal_append_evidence_validation`; cause_status: `known`; cause: The first formal append attempt for the out-of-scope legacy incompatibility GAP was rejected because evidence.sha256 used the placeholder not_applicable instead of a digest; the event was corrected and appended, and no repository source was changed by the rejected CLI call.; resolution: `resolved`; lesson: Use a real evidence digest for every formal event, including compatibility gaps discovered outside the frozen scope.
- #46 2026-08-19T19:59:30.000Z `formal_append_preventability_validation`; cause_status: `known`; cause: The first final focused-green event append was rejected because preventability used the unsupported not_applicable value; the event was corrected to the accepted unknown value and appended without source changes.; resolution: `resolved`; lesson: Validate formal event enum values against the control CLI before recording final gates.

## All gaps

- #43 2026-08-19T19:56:00.000Z `out_of_scope_legacy_report_incompatibility`; cause_status: `known`; cause: An exploratory run of historical tests outside the frozen allowlist produced 14 failures: legacy build_report_view_model assertions expect narrative/exploration recomputation, and reporting/export tests call write-capable artifact helpers without an admitted workflow receipt or read reports/report.html directly.; resolution: `open`; lesson: Separate allowlisted typed Report acceptance from historical writer/engine tests whose raw or admission-free assumptions require a separately authorized migration.

## All waste

- None recorded.

## Root causes and solutions

- `fail-closed-content-hash-aliases`: occurrences=1; cause_status: `known`; root cause: The first real C0 owner probe reached production persistence but exposed an inconsistent pair of content-hash aliases: evidence_content_hash remained canonical while content_hash was tampered.; solution: `resolved`
- `formal-cli-command-surface`: occurrences=1; cause_status: `known`; root cause: The initial formal CLI inspection attempted an unsupported status subcommand while the documented control surface uses verify and refresh-context.; solution: `resolved`
- `formal-event-lesson-key`: occurrences=1; cause_status: `known`; root cause: The formal event append for the migrated test green was rejected because its lesson_key used underscores instead of the normalized identifier grammar.; solution: `resolved`
- `formal-event-stage-validation`: occurrences=1; cause_status: `known`; root cause: The first material event append was rejected because the event used an undocumented verification stage value.; solution: `resolved`
- `formal-gap-evidence-digest`: occurrences=1; cause_status: `known`; root cause: The first formal append attempt for the out-of-scope legacy incompatibility GAP was rejected because evidence.sha256 used the placeholder not_applicable instead of a digest; the event was corrected and appended, and no repository source was changed by the rejected CLI call.; solution: `resolved`
- `formal-gate-enum-validation`: occurrences=1; cause_status: `known`; root cause: The first final focused-green event append was rejected because preventability used the unsupported not_applicable value; the event was corrected to the accepted unknown value and appended without source changes.; solution: `resolved`
- `formal-retrospective-after-append`: occurrences=1; cause_status: `known`; root cause: Formal verify observed that the completed retrospective had not yet been regenerated after the new TDD red event was appended.; solution: `mitigated`
- `legacy-report-incompatibility-boundary`: occurrences=1; cause_status: `known`; root cause: An exploratory run of historical tests outside the frozen allowlist produced 14 failures: legacy build_report_view_model assertions expect narrative/exploration recomputation, and reporting/export tests call write-capable artifact helpers without an admitted workflow receipt or read reports/report.html directly.; solution: `open`
- `locale-independent-diagnostics`: occurrences=1; cause_status: `known`; root cause: A diagnostic shasum command emitted a locale initialization panic in the managed shell; the digest was obtained with openssl dgst and no source change was made by the failed command.; solution: `resolved`
- `owner-store-root-precondition`: occurrences=1; cause_status: `known`; root cause: The first route-level owner injection probe passed a non-existent persistence root to EvidencePacketStoreV1.admit, which correctly rejected the root before the route could run.; solution: `resolved`
- `report-tests-use-c0-owner-capability`: occurrences=1; cause_status: `known`; root cause: After removing the report-local fake persistence ports, the existing canonical indexed tests still supplied a C1 fixture without a C0 owner capability and failed closed at the required content-hash gate.; solution: `not_applicable`
- `restore-complete-report-regression-surface`: occurrences=1; cause_status: `known`; root cause: The first sandboxed git restore could not create the worktree index lock and a locale-dependent mechanical rewrite command exited before changing the test file; both were retried or replaced with the allowed controlled edit path.; solution: `resolved`
- `reuse-narrowed-status`: occurrences=1; cause_status: `known`; root cause: The first narrowing fix still left candidate.status as unknown in the frontend status monotonicity includes check, so the second typecheck remained red while focused Vitest and backend tests were green.; solution: `resolved`
- `route-identity-seam-regression`: occurrences=1; cause_status: `known`; root cause: The first final backend gate started while the route still used the pre-hardening run-only current_report_evidence_persistence call, so the HTTP typed-failure probe raised TypeError before reaching the fail-closed projection.; solution: `resolved`
- `separate-agent-host-authority-failure`: occurrences=1; cause_status: `external`; root cause: The existing post-estimation compatibility run failed before the Report route assertion because the protected Agent workflow host-authority resolver is not configured.; solution: `accepted`
- `separate-api-admission-failure`: occurrences=1; cause_status: `external`; root cause: The broader API compatibility suite could not materialize its completed-run report artifacts because the host-owned workflow admission receipt is unavailable.; solution: `accepted`
- `strict-reader-type-narrowing`: occurrences=1; cause_status: `known`; root cause: The first frontend typecheck after adding provenance and status monotonicity guards rejected an unknown validationStatus value at the Array.includes boundary.; solution: `resolved`
- `validate-formal-event-enums`: occurrences=1; cause_status: `known`; root cause: The first TDD red gate event draft used an unsupported preventability value and was rejected by the formal CLI before being corrected and appended.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `fail-closed-content-hash-aliases`: line experience occurrence(s)=1
- `formal-cli-command-surface`: line experience occurrence(s)=1
- `formal-event-lesson-key`: line experience occurrence(s)=1
- `formal-event-stage-validation`: line experience occurrence(s)=1
- `formal-gap-evidence-digest`: line experience occurrence(s)=1
- `formal-gate-enum-validation`: line experience occurrence(s)=1
- `formal-retrospective-after-append`: line experience occurrence(s)=1
- `legacy-report-incompatibility-boundary`: line experience occurrence(s)=1
- `locale-independent-diagnostics`: line experience occurrence(s)=1
- `owner-store-root-precondition`: line experience occurrence(s)=1
- `report-tests-use-c0-owner-capability`: line experience occurrence(s)=1
- `restore-complete-report-regression-surface`: line experience occurrence(s)=1
- `reuse-narrowed-status`: line experience occurrence(s)=1
- `route-identity-seam-regression`: line experience occurrence(s)=1
- `separate-agent-host-authority-failure`: line experience occurrence(s)=1
- `separate-api-admission-failure`: line experience occurrence(s)=1
- `strict-reader-type-narrowing`: line experience occurrence(s)=1
- `validate-formal-event-enums`: line experience occurrence(s)=1

## Future guidance

- After tightening an owner-capability selector, rerun the real HTTP route probe immediately rather than relying on an earlier in-flight test process.
- All index aliases for an authoritative identity must agree before a persistence capability is called.
- Canonical Report probes must exercise the same C0 owner capability as production rather than pass a detached consumer fixture.
- Keep Agent host-authority failures separate from the Report consumer gate and use an isolated route probe for this line.
- Keep runtime schema guards and TypeScript narrowing aligned when hardening a consumer boundary.
- Narrow discriminated runtime values once and reuse the narrowed value throughout the consumer contract checks.
- Owner-side persistence probes must materialize the admitted root before constructing the immutable store capability.
- Regenerate the formal retrospective immediately after appending post-closeout evidence before running final verification.
- Separate allowlisted typed Report acceptance from historical writer/engine tests whose raw or admission-free assumptions require a separately authorized migration.
- Use a real evidence digest for every formal event, including compatibility gaps discovered outside the frozen scope.
- Use an existing documented event stage when appending formal evidence.
- Use focused route probes when the broader API fixture depends on an unavailable host admission receipt.
- Use locale-independent repository diagnostics when the managed shell cannot initialize its configured locale.
- Use normalized hyphenated lesson identifiers for formal event append.
- Use only the documented devline_control subcommands and record command-surface errors.
- Validate formal event enum values against the control CLI before recording final gates.
- Validate formal event enum values before invoking the append control.
- When a requested test restoration touches protected worktree metadata, use the smallest approved restore and keep the complete regression surface visible before migration.

## Event index

- #1: `4d4470c0-5786-414e-bfa6-9ed9c056a9fe` | 2026-08-19T16:34:43.586Z | STATE_CHANGE/line_started | incident=`ad4126bd-d9c4-4939-9b43-f3c6c602b59b` | lesson_key=`frozen-context-before-start` | event_sha256=`54b27b5ba090210619b4dea7929898a22befe6d604842036a6fe60b10cd8dc0e`
- #2: `55d848f3-0ad1-4b28-8d3d-5e2be9e2915b` | 2026-08-19T16:52:00.000Z | GATE/tdd_red | incident=`9cd71950-19d3-4c36-93b3-0bde0c690d77` | lesson_key=`tdd-red-before-implementation` | event_sha256=`29dfa363d880bcbb42494351e2f7089f20aab358ec77f56c849874d1a069e83f`
- #3: `2f6e0f16-5eef-4e38-b5f4-2a3fcdad57bf` | 2026-08-19T17:01:00.000Z | ERROR/preexisting_host_authority | incident=`7ee2d830-5d8f-4ee4-87e1-4071e118c99f` | lesson_key=`separate-agent-host-authority-failure` | event_sha256=`ab706e1a59ec8ece6620bbfa617b0541fa867274aa228166e66e69f6b6f3f6e2`
- #4: `8e7c7d9e-8e20-4f74-b3a0-e1542e0e53a8` | 2026-08-19T17:02:00.000Z | ERROR/formal_event_validation_retry | incident=`c9458024-0c33-45ef-b6dc-0d27eefdd950` | lesson_key=`validate-formal-event-enums` | event_sha256=`c80e7538c063a898a129ba89420f4c7cf425267e6e8cfe132c710e397778f063`
- #5: `e4b00c49-19b3-4d24-aed7-5ce86ab7a613` | 2026-08-19T17:04:00.000Z | ERROR/preexisting_api_admission | incident=`6ecfce9d-0e70-4b95-90d9-9a2e65b82f20` | lesson_key=`separate-api-admission-failure` | event_sha256=`f42126c3dadf6ce8e6017a4a47b390990eb5a103799a262393a25ded51f819ff`
- #6: `c745b744-c195-45d7-bd43-6d66b20a8b19` | 2026-08-19T17:06:00.000Z | GATE/report_boundary_backend | incident=`e9c6cc2d-fc2f-4dba-9e23-d8f09d0e7bc3` | lesson_key=`backend-report-boundary-green` | event_sha256=`66d81f70ea968a3bbd2f8f6f18a7029857eeb81d64f531288fb0c0adc4b72d8c`
- #7: `6f3a4e68-660f-45da-b5ef-5aa9ec0e0f2a` | 2026-08-19T17:06:10.000Z | GATE/report_boundary_frontend | incident=`e0a994ef-6bb1-48d1-a61a-3f6fc25388df` | lesson_key=`frontend-report-boundary-green` | event_sha256=`3fc0e291acd313fe02100598ce45349a61ebef0916d2421764135adef46ef03f`
- #8: `f6d4cbd7-5ff4-4cc2-b7bf-9e1cf8de373a` | 2026-08-19T17:06:20.000Z | GATE/frontend_typecheck | incident=`4b5d45c6-480e-4c98-9825-3a7c22414a1c` | lesson_key=`frontend-typecheck-separate-browser` | event_sha256=`d61e6c5404936ebfbfeaba54860c271ab4f16fa545fbd2609b175b1792f3bece`
- #9: `d84e986a-2d3d-4011-a5e9-37dbd85ee968` | 2026-08-19T17:08:00.000Z | STATE_CHANGE/implementation_verified | incident=`d67651d8-b1e8-4135-ad5b-a43124b964c6` | lesson_key=`report-boundary-implementation-verified` | event_sha256=`87a348d11f05722166c7ff674115081126e88075e6fcfd9089df3d9c7307fdcf`
- #10: `9d8be3e7-82e6-44dc-8cf0-bbf1b6bc7b12` | 2026-08-19T17:12:00.000Z | STATE_CHANGE/line_completed | incident=`46d65aed-6cba-40d0-93da-4e753caef2b7` | lesson_key=`close-with-evidence-and-deferred-gates` | event_sha256=`b9fe97935143dd24c615fad0f946f9e608401b7a93993805d7a852caab424d80`
- #11: `c3c7b4ba-1a37-4ba6-a568-6c6d67b2e2c9` | 2026-08-19T17:30:08.000Z | GATE/tdd_red | incident=`2dd1c02a-e83e-4dd3-835c-a9ec17c43f6a` | lesson_key=`tdd-red-foreign-artifact-bundle` | event_sha256=`a8e5eb84e81b7fdf47bcf27d901bcf5424ab4219765ed27a5c0f39117c638d9b`
- #12: `c7b69c57-a1e0-4ee0-a601-c4a3dfc4c5f4` | 2026-08-19T17:36:00.000Z | ERROR/formal_verify_stale_retrospective | incident=`0c97b43b-86e9-4a9a-82b2-68d3b11df4da` | lesson_key=`formal-retrospective-after-append` | event_sha256=`c09c56d62f65d64ed731449652eb4c457a15d39584255d984cf6f6a6a97cf009`
- #13: `8e7a3bd2-c8d4-4b7f-b0a3-56f322f7561e` | 2026-08-19T17:50:00.000Z | GATE/tdd_red_authoritative_registry | incident=`1f5bf047-75a4-42ce-ab8d-5f91ed03d7f2` | lesson_key=`authoritative-registry-before-report-facts` | event_sha256=`ea9fdb2a9334985a5e860ee66df7ac30ac5c0a506b10039eb68731e8b888c728`
- #14: `45230fe7-f434-478a-af6d-ed1d0cb9ad4c` | 2026-08-19T17:41:20.480Z | STATE_CHANGE/context_rescope_required | incident=`13f54121-3a6b-4039-bf3d-e8646ebe4c5d` | lesson_key=`context-pack-rescope` | event_sha256=`3e8242cc2b8f7d8e7aa596bfe345b64dbe9128ecd7f64c5a306db1ed1b8fd143`
- #15: `c73021b4-0a97-4476-b18e-299d6600f3df` | 2026-08-19T17:41:20.487Z | STATE_CHANGE/context_rescoped | incident=`14d066e1-f44e-4902-92fb-033094c8073c` | lesson_key=`context-pack-rescope` | event_sha256=`ed9ad34b3971ab2c41f29ec72c1f787c5f515840ce9476dd00f0670797f0c94f`
- #16: `b9d7ac7e-5d62-4e92-83d7-7fc42c4905ac` | 2026-08-19T18:00:00.000Z | ERROR/owner_capability_fixture_mismatch | incident=`0c3bfe33-a476-4c4f-a39e-1572cf7012ee` | lesson_key=`report-tests-use-c0-owner-capability` | event_sha256=`32eb2b612196caad21fbe69821cc4e902b058d77bb816974213f9bd35207acd3`
- #17: `5c82c04f-fdb3-4bce-94c5-6de59fcaa2d1` | 2026-08-19T17:59:30.000Z | ERROR/content_hash_alias_probe_failure | incident=`c587f731-51e3-4d6e-9c8a-bdbfcd2c037a` | lesson_key=`fail-closed-content-hash-aliases` | event_sha256=`c2a51190282a4f00f3255d88b9227d9226980a486006b8ee6ef5ac2ba2836d2f`
- #18: `0f710e97-640e-49d4-92d4-9aa86c4a7379` | 2026-08-19T18:02:00.000Z | ERROR/route_owner_setup_failure | incident=`0a2a54c3-1e2f-4cab-85ac-af2b6a10d7b2` | lesson_key=`owner-store-root-precondition` | event_sha256=`54beec6da81924e37fc022fec8d7043f485f0d2133400601be57f8f1d9b47cbf`
- #19: `2a8f947d-4db1-488d-8aca-6d5c045a3aa6` | 2026-08-19T18:03:45.000Z | GATE/report_authoritative_registry_green | incident=`a0b5db92-7d1a-4d46-a72d-4efac6f2905b` | lesson_key=`authoritative-report-persistence-green` | event_sha256=`3adf7c2e0e19db10754b8fd966369e407c67ef6c7f129b39e2df5a363be01653`
- #20: `f82d9d4b-4e7d-4c3c-bb0d-e82bc73fdc38` | 2026-08-19T18:03:50.000Z | GATE/report_boundary_frontend_final | incident=`2ea3fe37-ecc6-4013-b65e-e49db6c4ea4e` | lesson_key=`frontend-typed-evidence-green` | event_sha256=`487551aecfc8e615bd3eaa31fb0d5f009f8ea3853dc2115296af3599aff38488`
- #21: `5f1c9fe5-07a8-46f8-88e1-33b66e65782c` | 2026-08-19T18:03:55.000Z | GATE/report_static_gates_final | incident=`a60a2bee-d397-4a08-a6ab-7bcb62e83a63` | lesson_key=`report-static-gates-green` | event_sha256=`0615d4e8e1d166f8732d323e82fea552d382d9bbad26b1984c23d234a4047714`
- #22: `cb3e2f1c-5276-42a2-aa55-77f8f8c1fda1` | 2026-08-19T18:05:52.000Z | GATE/formal_verify_final | incident=`acb56290-b579-4f57-82af-2de8199473e8` | lesson_key=`formal-final-verify-green` | event_sha256=`e767e527562367ee3d726d2f3f13889363e68284e5240dd6c4bce8afcbbfb031`
- #23: `2152c23e-b109-4aac-8fc0-6b5119be2002` | 2026-08-19T18:38:54.000Z | GATE/tdd_red_second_round | incident=`e5325584-5d79-4070-adb6-efd6202c7c51` | lesson_key=`tdd-red-second-round-evidence-report` | event_sha256=`33c2273068a0f8c7de12693f54cbc4c99e62eecccac2ff3c3534e1432d6edd08`
- #24: `fc14466e-aae6-48fd-8e0e-32d52d590cfd` | 2026-08-19T18:43:48.650Z | STATE_CHANGE/context_rescope_required | incident=`d693e33a-d2a0-48e6-8b87-60bb80277d17` | lesson_key=`context-pack-rescope` | event_sha256=`a0299f84b6fb91ef57f58198046b86a7bbef32c892e8aa6dca13cef45cd6a83e`
- #25: `fd7ab24b-81b5-4909-9049-b85810aafa33` | 2026-08-19T18:43:48.661Z | STATE_CHANGE/context_rescoped | incident=`1ada45b0-c38f-4330-b339-136c123a4662` | lesson_key=`context-pack-rescope` | event_sha256=`cef394e5218abe047d76f412682a142db3244d6ee7cca89abb2dceef57cf1804`
- #26: `11bc3b06-7558-41ef-a43f-3702968353c8` | 2026-08-19T18:52:45.000Z | GATE/report_hardening_green | incident=`4d8437f9-3d44-4ca4-9a96-da959b82784b` | lesson_key=`report-hardening-green` | event_sha256=`5f9c60f8d72f84acb10335504108d5e9480f851483dff782e39f92dd329e5fda`
- #27: `6c2f3c56-6ca2-4e0b-bf93-1c4dcf7b7225` | 2026-08-19T18:55:40.000Z | ERROR/route_identity_seam_regression | incident=`0b43c5aa-c86a-4fd5-b0cb-792c7c05e9b1` | lesson_key=`route-identity-seam-regression` | event_sha256=`10b1535f235681be1e473f3cb71ecb095d6dfef9c623fb4a58f1c0b72419808d`
- #28: `fae7c979-5a4c-46b6-9223-ff952220d685` | 2026-08-19T18:56:11.000Z | GATE/report_static_gates_green | incident=`86b93edd-2903-4fe5-8b9f-68b87b35e616` | lesson_key=`scoped-gates-separate` | event_sha256=`1ec34ac0854f74b5c01687f2c7abbe7508d443b234cac293ad77fe788da880d2`
- #29: `e3dfcb11-7722-45c0-8840-4bf70c54254f` | 2026-08-19T18:56:19.000Z | GATE/report_hardening_final_gate | incident=`ba6fd4c8-104c-4b5a-bd72-5f49010763b7` | lesson_key=`report-hardening-final-gate` | event_sha256=`852270c84cacfd9d8335a161da5157cc5773524714874c4c4bfbe4922afda4dc`
- #30: `824db8c5-dade-486b-9562-c893cab40c02` | 2026-08-19T18:56:40.000Z | STATE_CHANGE/report_hardening_completed | incident=`e91149e7-0f40-41f1-8660-d992dbc3bc55` | lesson_key=`report-hardening-complete` | event_sha256=`91bacf390c4ead5ff25fd459dc07a86e313cb60b4b238064d004de0d0bd1ecc2`
- #31: `c8df8935-f44c-411a-9b9c-72de9480bdc8` | 2026-08-19T19:22:14.015Z | STATE_CHANGE/context_rescope_required | incident=`f82a384c-9fe4-40ae-badc-0183ab7172a1` | lesson_key=`context-pack-rescope` | event_sha256=`dda1805263bfca6fd6f7e8d15cb199d540a4e8a45da3d37d34744752d9499710`
- #32: `9197a6c3-5dcb-4ea6-a39a-369b42a7cf40` | 2026-08-19T19:22:14.028Z | STATE_CHANGE/context_rescoped | incident=`049bb495-4859-423a-bc1f-14f7b9a4316b` | lesson_key=`context-pack-rescope` | event_sha256=`0e440bf2cb033dfdbb9b4313b4ea9f1c3d21f32280ba4ce75e46adff7441e073`
- #33: `c01b0b8e-4a55-4e3b-a126-8cb1d68fd56a` | 2026-08-19T19:30:00.000Z | ERROR/formal_cli_unknown_command | incident=`e6e80195-ff68-4f18-90b4-3889a53dcfd6` | lesson_key=`formal-cli-command-surface` | event_sha256=`3aa91c12fb41ae90d19a893954e102fd974b2923edb33de552d090c5f26996b5`
- #34: `a6d9972c-15f3-4e02-9ac5-0bb2dc5ba77d` | 2026-08-19T19:31:00.000Z | ERROR/formal_append_stage_validation | incident=`27a6c64a-f1e3-44f0-af33-2e99f114c1fa` | lesson_key=`formal-event-stage-validation` | event_sha256=`90973c309f0c1d5c1c7b5a54e66fb9da0f1d5dcd31d85ab230e17d967db44c94`
- #35: `fd32f952-7a57-4c45-a3f1-45fa8e7a60af` | 2026-08-19T19:32:00.000Z | GATE/tdd_red_review_report_boundary | incident=`f4f6f9a6-936c-4aec-8cb7-8b36640fbc7a` | lesson_key=`tdd-red-review-report-boundary` | event_sha256=`c42c05187a706c0d3cd05d0cf3e9cb1d80fe3aec455899abd74a412ce238cbe7`
- #36: `8b99dff4-e31f-4edc-b2ef-e1fe87aeff84` | 2026-08-19T19:34:00.000Z | GATE/tdd_red_real_http_report_boundary | incident=`2ff97fa7-8229-4b06-957c-25a4fd2ca1a6` | lesson_key=`tdd-red-real-http-report-boundary` | event_sha256=`ac0b79a77d7bee2e966dcc963d67c06898c5c7daf060f1154781c03a2f711f35`
- #37: `59b7b8d1-9a1f-420b-a697-53002fe4d6e7` | 2026-08-19T19:42:00.000Z | ERROR/report_view_model_restore_and_migration | incident=`8aa927e3-5b89-49c4-87cd-27bf06cae532` | lesson_key=`restore-complete-report-regression-surface` | event_sha256=`5c40746802d205f93e2afa9db14bd62073fdfd8e0c2bde407e985091cb9ca3a4`
- #38: `baf33ccb-6b75-4c92-aaf6-fb3bc5f01157` | 2026-08-19T19:43:30.000Z | ERROR/formal_append_lesson_key_validation | incident=`b4c6867f-dc07-4b5c-86f4-e441299eed50` | lesson_key=`formal-event-lesson-key` | event_sha256=`b26e1b5492c5096bf8e01ffa274c5d99131ca7f4ccc0f1b917c2957c8665ab1f`
- #39: `9c30fa83-5fd5-472e-a1c0-30260a14b123` | 2026-08-19T19:43:45.000Z | GATE/typed_report_view_model_regression_green | incident=`f01c5e5d-ff48-4d76-bc93-48c2e0681e71` | lesson_key=`typed-report-view-model-regression` | event_sha256=`dbd65f7c30e39dd9d1ad7c76c06ebef68df45c044aa44bf279856ca2ddd874cf`
- #40: `c7b2a29e-2a35-4e4a-9f54-7ea0eafc09b4` | 2026-08-19T19:54:00.000Z | ERROR/frontend_typecheck_guard_narrowing | incident=`0d24b1c1-bb2b-4f14-a6d5-b8cb0b0f76d5` | lesson_key=`strict-reader-type-narrowing` | event_sha256=`94756f760cef722ebb1a5e71fa5999626c10c1768dbfe5d55c58e127740ca706`
- #41: `49f15c1e-3ee1-4a28-9d75-8ee99e86403c` | 2026-08-19T19:55:00.000Z | ERROR/diagnostic_locale_failure | incident=`1e083b80-2b3e-4e54-af01-7be8980cd497` | lesson_key=`locale-independent-diagnostics` | event_sha256=`74761c57c3aa6f6b1fa6244ba4942e43354572059c253d134f397e5c2129cce4`
- #42: `a260f74d-3ff6-4cb2-997b-9b06c5df8c30` | 2026-08-19T19:55:00.000Z | ERROR/frontend_typecheck_status_narrowing | incident=`f1c59ef7-5c4f-4a41-9d52-6bcb37e28cd4` | lesson_key=`reuse-narrowed-status` | event_sha256=`70c7f1dfc8b051f135d7f00aae2352a28b67a77a8961dda472778bb576e2a6dd`
- #43: `ab8c854e-1ce7-456e-8ae9-0c12c8735ce3` | 2026-08-19T19:56:00.000Z | GAP/out_of_scope_legacy_report_incompatibility | incident=`f0b614e8-a70b-4ddc-a32c-14c7a756f7d8` | lesson_key=`legacy-report-incompatibility-boundary` | event_sha256=`89d8a36c3c21df2457f2f294c7b54555e90b6170ded437696b0d0f8b0231c3e9`
- #44: `a8ded2c5-01a9-416f-9bf3-dae81048b1ca` | 2026-08-19T19:56:30.000Z | ERROR/formal_append_evidence_validation | incident=`1af1c36b-2c12-4e8a-9d39-b6778acb9d43` | lesson_key=`formal-gap-evidence-digest` | event_sha256=`862a8823937a2891d21fc3bba6c19277b963597217286c563fcaaa1a797edfb9`
- #45: `b4e4ec41-5605-4c87-83ad-44d8444a5e11` | 2026-08-19T19:59:00.000Z | GATE/focused_report_hardening_green | incident=`4ab8948c-e2f5-48ae-af25-524103f2cae3` | lesson_key=`focused-report-hardening-green` | event_sha256=`809e99f9fda86decc3f557abd8bac11a6e3c8c39a7bb53cba48783e53a763894`
- #46: `fc5f7c21-6b8f-47e2-89cb-633903a26ff5` | 2026-08-19T19:59:30.000Z | ERROR/formal_append_preventability_validation | incident=`54156f8a-dc0a-4197-ae6f-3227c5cb021c` | lesson_key=`formal-gate-enum-validation` | event_sha256=`ca91957c80eff7a14db7e2f91029640e5991f5b9d9af03f1bb6018a14cf2e2d9`
- #47: `d9df0255-4638-47f0-bd54-0d0a5c7d8ce5` | 2026-08-19T20:02:00.000Z | STATE_CHANGE/report_hardening_completed_after_review | incident=`0e25a455-01dd-4457-aad3-bc56d7bb0805` | lesson_key=`report-hardening-complete-after-review` | event_sha256=`26f2e68ce02151cbc3ec3410dac291721a7dc47c7695af2c4da360758df91950`
