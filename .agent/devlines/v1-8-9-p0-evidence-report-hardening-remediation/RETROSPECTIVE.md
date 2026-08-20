# Retrospective — v1-8-9-p0-evidence-report-hardening-remediation

## Goal

# Workbench v1.8.9 P0 Evidence and Report Hardening Remediation  Remediate the independent-reviewer \`NOT COMPLIANT\` findings at baseline \`94a96fb5f4919a38c40662ab28784368897d7162\` in the existing \`workbench-v1.8.9-p0-evidence-report-hardening\` worktree.  Required outcomes:  - \`issue_report_projection\`, \`report_export\`, and \`results_service\` must bind   facts and \`projectionDigest\` to the actual canonical server-owned evidence   envelope. Forged facts, forged projection digests, and synchronized forged   outer index fields must fail closed. The issued wire must be immutable. - Report persistence/writer factories must reject caller raw \`table_rows\`,   arbitrary Mapping fake view models, and foreign \`canonical_run_root\`; the   public \`ServerOwnedReportEvidencePersistenceV1\` constructor must not mint   authority from caller-supplied identity metadata. - \`TableView\` and \`FamilyEvidence\` must not display raw   \`detail.model_results\`, \`detail.post_estimation_results\`, artifact JSON, or   an \`allowLegacyPresentation\` raw fallback. Missing typed evidence renders   only the typed unavailable state. - Formal event verification must reject timestamp/order reversal. The new   line's event stream, terminal state, generated retrospective, and handoff   must agree; temporary files must be removed.  Preserve the real C0 owner boundary, shared Agent/Notebook/Report fact identity/value/status/digest/concurrency assertions, historical reporting assertions, and existing evidence-envelope tests. Do not modify central Agent, Notebook, provider, estimator, or live-host execution code. Browser/provider and full-host release acceptance remain separate gates.

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/12 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=2254995 ms (sample=2; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/4 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #7 2026-08-19T23:55:40.000Z `historical_report_fixture_contract`; cause_status: `known`; cause: The first controlled report/export rerun exposed two historical test-fixture assumptions after the authority hardening: repeated owner-store reuse triggered duplicate persistence identities, and XLSX tests still expected caller raw table_rows to succeed.; resolution: `resolved`; lesson: When tightening an authority boundary, preserve historical assertions that remain valid and convert obsolete caller-owned success expectations into explicit fail-closed tests.

## All errors

- #5 2026-08-19T22:51:20.010Z `sandbox_socket_permission`; cause_status: `external`; cause: The restricted test sandbox denied the fixture authority Unix socket under the test runtime temporary directory.; resolution: `open`; lesson: Environment permission failures must remain separate from implementation pass or fail claims.
- #6 2026-08-19T23:46:50.000Z `focused_test_path_missing`; cause_status: `known`; cause: The frozen Context Pack names tests/test_development_control_events.py, but that repository-relative test file is absent in the remediation worktree.; resolution: `accepted`; lesson: A frozen test command must be checked for repository path existence before claiming the full focused gate.

## All gaps

- #3 2026-08-19T22:43:00.010Z `canonical_report_authority_gap`; cause_status: `known`; cause: The current Report seam validates selected identity fields but still trusts caller-shaped projection wire facts, permits a public C0 persistence constructor, and leaves raw TableView compatibility rendering available.; resolution: `open`; lesson: Keep raw compatibility readers outside the typed Report authority path and require server-owned canonical materialization for every citable fact.

## All waste

- None recorded.

## Root causes and solutions

- `authority-hardening-updates-fixture-contract`: occurrences=1; cause_status: `known`; root cause: The first controlled report/export rerun exposed two historical test-fixture assumptions after the authority hardening: repeated owner-store reuse triggered duplicate persistence identities, and XLSX tests still expected caller raw table_rows to succeed.; solution: `resolved`
- `canonical-report-authority-gap`: occurrences=1; cause_status: `known`; root cause: The current Report seam validates selected identity fields but still trusts caller-shaped projection wire facts, permits a public C0 persistence constructor, and leaves raw TableView compatibility rendering available.; solution: `open`
- `focused-test-path-missing`: occurrences=1; cause_status: `known`; root cause: The frozen Context Pack names tests/test_development_control_events.py, but that repository-relative test file is absent in the remediation worktree.; solution: `accepted`
- `sandbox-socket-permission`: occurrences=1; cause_status: `external`; root cause: The restricted test sandbox denied the fixture authority Unix socket under the test runtime temporary directory.; solution: `open`

## Added tests

- `focused backend substitute; focused frontend; compileall; typecheck; git diff --check`
- `tests/test_reporting_exports.py`
- `tests/test_v189_evidence_report_boundary.py`

## New rules

- `authority-hardening-updates-fixture-contract`: line experience occurrence(s)=1
- `canonical-report-authority-gap`: line experience occurrence(s)=1
- `focused-test-path-missing`: line experience occurrence(s)=1
- `sandbox-socket-permission`: line experience occurrence(s)=1

## Future guidance

- A frozen test command must be checked for repository path existence before claiming the full focused gate.
- Environment permission failures must remain separate from implementation pass or fail claims.
- Independent reviewer probes must cross the canonical envelope, owner, UI, and formal-log boundaries before a Report line can be called compliant.
- Keep raw compatibility readers outside the typed Report authority path and require server-owned canonical materialization for every citable fact.
- Resolve reviewer findings with direct boundary evidence and retain broader integration claims as separate gates.
- When tightening an authority boundary, preserve historical assertions that remain valid and convert obsolete caller-owned success expectations into explicit fail-closed tests.

## Event index

- #1: `a8546b23-9c9c-4f54-be74-63a7cce519b7` | 2026-08-19T22:42:19.334Z | STATE_CHANGE/line_started | incident=`f5774a71-7b79-4c88-9d4e-e54aed693027` | lesson_key=`frozen-context-before-start` | event_sha256=`e29fffc6114b239d6f6951ff81e278a2067bba1228ab6f1093ceb863a8e10562`
- #2: `b8f1f8f7-2bf4-4c1c-9f45-bd844fb9ea11` | 2026-08-19T22:43:00.000Z | REVIEW/reviewer_not_compliant | incident=`0d5c74e2-6a9c-4c98-b3b5-f11bb0cc2842` | lesson_key=`reviewer-not-compliant-boundary` | event_sha256=`d36f30ad38ac2b56f9bdb20a0f49b9b445f3c87692491a15a05c3a760fce4abc`
- #3: `c0d69bf3-8a2c-4e14-ae61-7a3f9e8c52d7` | 2026-08-19T22:43:00.010Z | GAP/canonical_report_authority_gap | incident=`f2e89c10-7d45-4ab6-9c32-1e4f7b8a90d6` | lesson_key=`canonical-report-authority-gap` | event_sha256=`3a833f83299086ba9094a88ee5cbd8a32e0e17c0c80333a38e7183fba03d1e2d`
- #4: `d78d4f4c-2de2-4c8f-9f6f-2e2d83b1a5c1` | 2026-08-19T22:51:20.000Z | GATE/tdd_red | incident=`8f1e94ef-2c5b-4ee8-9f76-0b11d362a6a8` | lesson_key=`tdd-red-boundary` | event_sha256=`5cdbe1c8f206648686cb639614fe18dd8c8ae18ce82a6f4fd18c6729586e064f`
- #5: `c1c65e42-33ac-4ee7-bd0b-70bca9f4ca46` | 2026-08-19T22:51:20.010Z | ERROR/sandbox_socket_permission | incident=`07e3082d-22ef-4f58-b195-31a4e12cf5a0` | lesson_key=`sandbox-socket-permission` | event_sha256=`785d8a8fcc9eee978f2dcba655410b44dcdd414d6359db3743410586134f60ae`
- #6: `b8d1f3a4-2c6e-4f90-8a17-5e3d9c7b1a2f` | 2026-08-19T23:46:50.000Z | ERROR/focused_test_path_missing | incident=`c4e7a1b2-9d3f-4c6e-8a0b-5d7f1e2c9a34` | lesson_key=`focused-test-path-missing` | event_sha256=`8f4834ab925597c616866642ce066ac2f8008984e91ff939ba6ab1b8eb7751df`
- #7: `d4e5f6a7-b8c9-4012-3456-789abcdef012` | 2026-08-19T23:55:40.000Z | FAILURE/historical_report_fixture_contract | incident=`c1d2e3f4-a5b6-4789-0123-abcdef012345` | lesson_key=`authority-hardening-updates-fixture-contract` | event_sha256=`96b056b76e074bba1587f6499dec9a01a8a318c4f40700209a18d6a6b27edce0`
- #8: `e5f6a7b8-c9d0-4123-4567-89abcdef0123` | 2026-08-19T23:56:30.000Z | GATE/remediation_focused_green | incident=`f6a7b8c9-d0e1-4234-5678-9abcdef01234` | lesson_key=`close-package-evidence-boundary` | event_sha256=`ed02cd017fc555c1b2ed35b7da4629bd71439ab0d9ac843fd4c030e026148e3a`
- #9: `f7a8b9c0-d1e2-4345-6789-abcdef012345` | 2026-08-19T23:57:30.000Z | STATE_CHANGE/remediation_line_completed | incident=`a8b9c0d1-e2f3-4456-789a-bcdef0123456` | lesson_key=`close-remediation-at-measured-boundary` | event_sha256=`d75949afc209b0698ff36c62ec9c26f16b11a6870625428dca153092343cbdd8`
- #10: `a9b0c1d2-e3f4-4567-89ab-cdef01234567` | 2026-08-19T23:58:00.000Z | REVIEW/reviewer_findings_resolved | incident=`0d5c74e2-6a9c-4c98-b3b5-f11bb0cc2842` | lesson_key=`reviewer-findings-closed-by-boundary-evidence` | event_sha256=`4c2447169379bad7c095dcfb15edeb0d75f3539f0604346cd67c7c27ecdd3153`
- #11: `b0c1d2e3-f4a5-4678-9abc-def012345678` | 2026-08-19T23:58:10.000Z | GATE/canonical_authority_gap_resolved | incident=`f2e89c10-7d45-4ab6-9c32-1e4f7b8a90d6` | lesson_key=`canonical-report-gap-closed` | event_sha256=`edb6f17ddbc5de11001ed5277bb381eacf4ddc3b1ab64e396ac6cffa1f515cb7`
- #12: `c1d2e3f4-a5b6-4789-0123-456789abcdef` | 2026-08-19T23:58:20.000Z | GATE/tdd_red_resolved | incident=`8f1e94ef-2c5b-4ee8-9f76-0b11d362a6a8` | lesson_key=`red-probe-closed-by-green-rerun` | event_sha256=`34b27e2431f99fc1f426a373ff6edd3f1d3e928ed0900b82ffbb94dbaa0cf6bb`
