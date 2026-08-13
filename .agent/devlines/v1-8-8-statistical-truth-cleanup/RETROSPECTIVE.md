# Retrospective — v1-8-8-statistical-truth-cleanup

## Goal

# v1.8.8 statistical truth and integration cleanup  ## Objective  Make the final v1.8.8 tree describe and expose exactly what it executes. Correct the Matching and Hurdle inference semantics, remove unused QA compatibility and duplicate workflow validation, and replace stale status claims with one current handoff. Preserve fail-closed execution, declaration-derived capability wiring, and the separation between automated execution and browser acceptance.  ## Design  ### Matching  - Replace the misleading \`distance_policy="logit"\` request field with   \`matching_geometry_policy="standardized_covariate_euclidean_v1"\`. - Add \`support_distance_policy="absolute_logit_difference"\` for propensity   overlap evidence and the secondary deterministic tie-breaker. - Replace \`common_support_policy="trim"\` with   \`common_support_policy="reject_disjoint_no_trim_v1"\`. - Publish the same policies in the typed proposal and result, including   \`trim_applied=false\`. Do not retain aliases for the incorrect development-only   contract. - Freeze an independently generated R oracle for the declared geometry and   propensity-support evidence.  ### Hurdle inference  - Label the positive-count coefficient inference with   \`standard_error_method="bfgs_inverse_hessian_approximation"\` and   \`p_value_status="approximate"\`. - Preserve the label in the bounded result, Agent-visible workflow evidence, and   Report evidence. The label is data, not prose inferred by an LLM. - Add a frozen independent R direct-formula oracle for Hurdle estimates and   inverse-Hessian inference. Tests must compare the committed implementation to   that oracle and continue to reject non-convergence.  ### Workflow capability seam  - One operation-owned path validates the request once, executes once, and   validates the result once. It returns both the normalized request and the   execution so runtime persistence does not repeat validation. - Remove the \`validate_request\`, \`execute\`, and \`validate_result\` constructor   parameters that are currently ignored and overwritten by \`adapter_key\`. - Keep the live declaration derivation and generic orchestrator dispatch intact.  ### QA ledger and reachability records  - Delete \`LegacyLedgerMigration\`, the \`migrate\` CLI, and migration-only tests.   A ledger without current write-once control remains rejected; Git history is   the only reference for the deleted development compatibility path. - Keep the complete P2 snapshot \`(129, 9, 123, 127, 2, 0)\` in the P2 inventory   guard only. P5 retains the historical 18 IDs and verifies their live wiring   plus zero current gaps without pinning the six global counts again.  ### Status truth  - Add a prominent historical/superseded banner to the roadmap and P7 adoption   design without rewriting their historical body. - Add one final handoff naming current reachability, P7 automated execution,   browser acceptance, local-only witness scope, known statistical limitations,   and the exact remaining gate state. - Resolve or supersede obsolete open formal events only by appending through   \`scripts/devline_control.py\`; regenerate retrospectives through the CLI.  ## Explicit non-scope  - No World ID or concrete remote witness provider. - No claim of human identity or Anti-Agent proof. - No 64-operation manual browser repetition. - No broad conversion of every family branch in \`p7_pack_adapters.py\` to handler   maps. Those branches are pack-internal maintenance debt, not orchestrator   dispatch leakage, and a release-wide refactor would add risk without fixing a   current truth or safety defect. - No push, PR, merge, tag, or release.  ## Acceptance  - New assertions are proven live with behavior-changing mutations. - Matching proposal, contract, runtime, result, and independent oracle agree. - Hurdle approximate inference labels survive into Agent and Report evidence and   match the frozen independent oracle within declared tolerances. - Workflow validators are each called exactly once per execution. - No legacy migration command or implementation remains; uncontrolled ledgers   still fail closed. - One authoritative P2 snapshot reports \`129 / 9 / 123 / 127 / 2 / 0\`. - Focused backend/frontend tests, formal verification, \`git diff --check\`, and   the host full gate pass on the final source commit.

## Final status

COMPLETED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- A changed file or green test is not mutation evidence; prove the selected fixture changes behavior and record failed mutation design separately from product failures.

## Event index

- #1: `8a498c1e-77c0-4866-9dfb-9c3a36acd114` | 2026-08-13T09:15:40.172Z | STATE_CHANGE/line_started | incident=`730f3109-caad-4629-bd7a-33f234848ba1` | lesson_key=`frozen-context-before-start` | event_sha256=`baf860ebe70ceb7267e64327072c3fbf7c5244cc691120ec80c489f3380b22fa`
- #2: `46c86a25-6190-4223-8079-5cc7c1c85efb` | 2026-08-13T09:30:00.660Z | STATE_CHANGE/context_rescope_required | incident=`d8628a09-a270-4821-920b-4dd6d937d51e` | lesson_key=`context-pack-rescope` | event_sha256=`72846f6e722950d1865fa4c9fcf9ceb285845022c673ca6009a7a9dd0ce8e913`
- #3: `6bf62c7f-5394-42bf-b4cf-cd1426c0db19` | 2026-08-13T09:30:00.666Z | STATE_CHANGE/context_rescoped | incident=`16ffffdc-0150-4c34-8c5a-be6aeff300b6` | lesson_key=`context-pack-rescope` | event_sha256=`4231ee30bd4c1f881470df3261f571d50a5b8c583cb098abd8e8c20ca2904107`
- #4: `b0d5e6f7-1829-4abc-def0-123456789abc` | 2026-08-13T09:48:00.000Z | REVIEW/statistical_truth_mutation_review | incident=`c1e6f708-293a-4bcd-ef01-23456789abcd` | lesson_key=`behavior-changing-mutation-evidence` | event_sha256=`da15f4bb68de5d8ba35a1fd88c989a773546cd8681d6fe8c115b2b56f656d848`
- #5: `d3e4f5a6-b718-49ca-8d2e-3f4051627384` | 2026-08-13T10:11:22.000Z | GATE/p7_current_source_batch_execution | incident=`e4f5a6b7-c829-4adb-9e3f-405162738495` | lesson_key=`p7-exact-source-batch-evidence` | event_sha256=`9abf69f0b4c11209bae16b74cf0238c7672f5e13e08d2fbb5a10097134e3da85`
- #6: `f5a6b7c8-d930-4bec-af40-5162738495a6` | 2026-08-13T10:11:23.000Z | GATE/host_full_gate_passed | incident=`a6b7c8d9-e041-4cfd-b051-62738495a6b7` | lesson_key=`host-full-gate-on-final-source` | event_sha256=`0e07e16f12bb13f595040e205d1db27d423440c5e9f61c6a06627695392919b9`
- #7: `c8d9e0f1-a263-4e1f-d273-8495a6b7c8d9` | 2026-08-13T10:11:25.000Z | STATE_CHANGE/statistical_truth_cleanup_completed | incident=`d9e0f1a2-b374-4f20-e384-95a6b7c8d9e0` | lesson_key=`statistical-truth-end-to-end-closeout` | event_sha256=`12067ef219eb0a4daa3e2858c067672c5dbeab04fbadf460c2d9b2e1212f102f`
