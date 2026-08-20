# Retrospective — v1-8-9-p1-classification-production-remediation-14

## Goal

# Workbench v1.8.9 P1 Classification Production Remediation 14 Objective  Close the independent spec-review blocker from exact tip \`9c968460d168a2e5c6164df1d41b2b4b5ccf2368\` without changing root or any other worktree. Extend the remediation-13 descriptor-based artifact integrity seam to every artifact byte consumer in scope, not only the artifacts-index list.  ## Required behavior  - Create one shared repository/file-integrity seam for the server-owned bounded   relative POSIX path grammar, no-follow descriptor traversal, regular-file   \`fstat\`, same-open-descriptor SHA-256, and same-open-descriptor reads. - Migrate \`runs_routes.py\` artifact download   (\`/runs/{run_id}/artifacts/{artifact_id}\`) to that seam. A generic download   must hash and read the opened object, return bytes from that object, and must   not use path-based \`FileResponse\` after a path check. A classification   download must obtain its typed wrapper only through the safe classification   consumer seam. - Migrate classification artifact and classification receipt reads in   \`predictive_research/consumer_projection.py\` to the same shared seam. The   artifact and receipt bytes must each be read and hashed from their opened   descriptors. - Preserve the existing list validator, artifact type vocabulary, index status   mapping, duplicate/path/type/digest checks, classification server identity,   evidence receipt, split/fold/OOF/holdout/weights/calibration/threshold   contracts, and Agent/Notebook/Report typed projections. - Add real HTTP and direct-consumer probes for valid success, non-race external   symlink rejection, missing/non-regular/digest mismatch behavior, and a   replacement callback that is patched at the live shared helper and asserts   it actually executed. No probe may monkeypatch a removed symbol or use   \`raising=False\` to create an empty callback. - Keep the artifact allowlist unchanged; record producer-vocabulary drift as a   bounded P2 follow-up in the remediation-14 handoff.  ## Formal and verification boundaries  Use the unique formal line \`v1-8-9-p1-classification-production-remediation-14\`, created only through \`scripts/devline_control.py start\`, with exact baseline \`9c968460d168a2e5c6164df1d41b2b4b5ccf2368\`.  Required evidence is TDD RED before production changes, then focused production/HTTP/consumer/TOCTOU tests, classification contract suites, \`compileall\`, \`git diff --check\`, formal verify and retrospective generation. The handoff must include exact implementation and final tips, formal manifest and tail SHA, reproducible commands and observed numbers, the known API artifacts fixture gate if it remains, and formal \`COMPLETED\`/\`unresolved=0\` state. Browser, external provider, central integration/cutover, host full gate, full gate, merge, tag, and release remain \`NOT VERIFIED\`.  ## Scope  - \`backend/workbench/repository/file_integrity.py\` - \`backend/workbench/repository/run_repository.py\` - \`backend/workbench/http/runs_routes.py\` - \`backend/workbench/predictive_research/consumer_projection.py\` - \`tests/test_v189_classification_production.py\` - this objective, plan, and handoff - the new remediation-14 formal line records  Do not modify \`backend/workbench/prediction.py\`, \`backend/workbench/reporting.py\`, \`backend/workbench/http/notebook_routes.py\`, \`backend/workbench/predictive_research/persistence.py\`, the remediation-13 formal records, the repository root, or any other worktree.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/14 (35.7%; 35.7 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=5; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/6 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T02:38:00.000Z `artifact_consumer_toctou_red`; cause_status: `known`; cause: The required RED probes ran before the shared opened-descriptor seam and still observed the path-backed artifact download and classification artifact/receipt reads.; resolution: `open`; lesson: Run live repository, download, and consumer replacement probes before implementation and make every artifact byte read use one no-follow opened descriptor.

## All errors

- #3 2026-08-20T02:38:01.000Z `red_selector_command_error`; cause_status: `known`; cause: The first RED command used a selector that matched no tests, so pytest exited with code 5 after reporting 93 deselected tests.; resolution: `resolved`; lesson: Validate focused selectors once before relying on their test counts, and record command-selection errors separately from product failures.
- #4 2026-08-20T02:38:02.000Z `safe_read_import_error`; cause_status: `known`; cause: The first GREEN focused run exposed a missing read_json import after the consumer path was migrated to the shared opened-file seam.; resolution: `resolved`; lesson: After extracting a shared file seam, rerun focused consumers and restore only imports needed for the index authority without reintroducing path reads.
- #5 2026-08-20T02:38:03.000Z `formal_status_command_error`; cause_status: `known`; cause: A status subcommand was attempted even though devline_control.py exposes verify, retrospective, and related commands but no status command.; resolution: `resolved`; lesson: Use the documented formal CLI surface and treat unsupported status checks as command errors rather than inventing a new control path.
- #6 2026-08-20T02:38:04.000Z `formal_event_file_error`; cause_status: `known`; cause: One temporary formal event object briefly contained a duplicate JSON key, so the append command rejected it before changing the event chain.; resolution: `resolved`; lesson: Let the formal CLI reject duplicate-key event input and validate temporary JSON before append; never bypass the append-only control path.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `artifact-consumer-toctou-red`: occurrences=1; cause_status: `known`; root cause: The required RED probes ran before the shared opened-descriptor seam and still observed the path-backed artifact download and classification artifact/receipt reads.; solution: `open`
- `formal-cli-command-surface`: occurrences=1; cause_status: `known`; root cause: A status subcommand was attempted even though devline_control.py exposes verify, retrospective, and related commands but no status command.; solution: `resolved`
- `formal-event-json-validation`: occurrences=1; cause_status: `known`; root cause: One temporary formal event object briefly contained a duplicate JSON key, so the append command rejected it before changing the event chain.; solution: `resolved`
- `red-selector-command`: occurrences=1; cause_status: `known`; root cause: The first RED command used a selector that matched no tests, so pytest exited with code 5 after reporting 93 deselected tests.; solution: `resolved`
- `safe-read-import-correction`: occurrences=1; cause_status: `known`; root cause: The first GREEN focused run exposed a missing read_json import after the consumer path was migrated to the shared opened-file seam.; solution: `resolved`

## Added tests

- `tests/predictive_research/test_classification_contracts_v189.py`
- `tests/predictive_research/test_consumer_projection_v186.py`
- `tests/test_api.py`
- `tests/test_v189_artifact_integrity.py`
- `tests/test_v189_classification_production.py`

## New rules

- `artifact-consumer-toctou-red`: line experience occurrence(s)=1
- `formal-cli-command-surface`: line experience occurrence(s)=1
- `formal-event-json-validation`: line experience occurrence(s)=1
- `red-selector-command`: line experience occurrence(s)=1
- `safe-read-import-correction`: line experience occurrence(s)=1

## Future guidance

- After extracting a shared file seam, rerun focused consumers and restore only imports needed for the index authority without reintroducing path reads.
- Let the formal CLI reject duplicate-key event input and validate temporary JSON before append; never bypass the append-only control path.
- Run live repository, download, and consumer replacement probes before implementation and make every artifact byte read use one no-follow opened descriptor.
- Treat artifact-type allowlist drift as a separately evidenced compatibility review rather than copying more constants into a security boundary.
- Use the documented formal CLI surface and treat unsupported status checks as command errors rather than inventing a new control path.
- Validate focused selectors once before relying on their test counts, and record command-selection errors separately from product failures.

## Event index

- #1: `29aadd55-a48d-46dc-9b21-ed393034b4ec` | 2026-08-20T02:21:36.142Z | STATE_CHANGE/line_started | incident=`b71a5f65-76c3-4eb0-8001-03f92e9236cd` | lesson_key=`frozen-context-before-start` | event_sha256=`01f2a5a589a312954a332cb14cfe59b585e5f375b690323065acdbce6c9f8ee7`
- #2: `0e7f1a2b-3c4d-456e-8f90-1a2b3c4d5e60` | 2026-08-20T02:38:00.000Z | FAILURE/artifact_consumer_toctou_red | incident=`1a2b3c4d-5e6f-4789-a012-3456789abcde` | lesson_key=`artifact-consumer-toctou-red` | event_sha256=`0600facf9739b3d696c0e529ecb5e0e10d622b3614e4aba24b6248db51dad687`
- #3: `2b3c4d5e-6f70-489a-b123-456789abcdef` | 2026-08-20T02:38:01.000Z | ERROR/red_selector_command_error | incident=`2b3c4d5e-6f70-489a-b123-456789abcdef` | lesson_key=`red-selector-command` | event_sha256=`99e113c6a8ed301a1aa1c836a2ef4304648d129647814a13ff6182edee6d236f`
- #4: `3c4d5e6f-7081-49ab-c234-56789abcdef0` | 2026-08-20T02:38:02.000Z | ERROR/safe_read_import_error | incident=`3c4d5e6f-7081-49ab-c234-56789abcdef0` | lesson_key=`safe-read-import-correction` | event_sha256=`fb25979edd6088b8578f83217b8dbfbbcd9421ee89ce8100d480afc2771e2dc8`
- #5: `4d5e6f70-8192-4abc-d345-6789abcdef01` | 2026-08-20T02:38:03.000Z | ERROR/formal_status_command_error | incident=`4d5e6f70-8192-4abc-d345-6789abcdef01` | lesson_key=`formal-cli-command-surface` | event_sha256=`e149d4834ab2499c15875aeee720a58138fb86cc3c1e6437a78cda90a9740f81`
- #6: `5e6f7081-92a3-4bcd-e456-789abcdef012` | 2026-08-20T02:38:04.000Z | ERROR/formal_event_file_error | incident=`5e6f7081-92a3-4bcd-e456-789abcdef012` | lesson_key=`formal-event-json-validation` | event_sha256=`8b456682216fdb591439800b0ec8c1968b340d6750def688dd91e90d86aae10b`
- #7: `6f708192-a3b4-4cde-f567-89abcdef0123` | 2026-08-20T02:39:00.000Z | GATE/artifact_consumer_toctou_green | incident=`1a2b3c4d-5e6f-4789-a012-3456789abcde` | lesson_key=`artifact-consumer-toctou-red` | event_sha256=`e026e39dbb40fdc52e63349cb5482ee84fdb6e48c4b56da41f2e6f282d951083`
- #8: `708192a3-b4c5-4def-6789-abcdef012345` | 2026-08-20T02:39:01.000Z | GATE/classification_contracts_green | incident=`708192a3-b4c5-4def-6789-abcdef012345` | lesson_key=`classification-contract-focused-green` | event_sha256=`7fe94bb811cfc9ec9bb8c370004a085b862c75d9757241660c08e6aaa20fcc91`
- #9: `8192a3b4-c5d6-4efa-7890-bcdef0123456` | 2026-08-20T02:39:02.000Z | GATE/api_artifacts_known_gate | incident=`8192a3b4-c5d6-4efa-7890-bcdef0123456` | lesson_key=`api-artifacts-known-gate` | event_sha256=`02606f2df6ad08cd56c50ba0e4c6f1562aa1a3a06a1b72faa45d9e957103c0f3`
- #10: `92a3b4c5-d6e7-4f01-8901-cdef01234567` | 2026-08-20T02:39:03.000Z | GATE/legacy_consumer_known_gate | incident=`92a3b4c5-d6e7-4f01-8901-cdef01234567` | lesson_key=`legacy-consumer-known-gate` | event_sha256=`25140a73a28736456ad02730827bc56135bf62ec6f17b6ddc7c6f79f9598211d`
- #11: `a3b4c5d6-e7f8-4012-9012-def012345678` | 2026-08-20T02:39:04.000Z | GATE/artifact_integrity_fixture_known_gate | incident=`a3b4c5d6-e7f8-4012-9012-def012345678` | lesson_key=`artifact-integrity-fixture-gate` | event_sha256=`6b84fc9a581359629ce041a31be1a0278d7ba5656b2449fb493bb1d43bc0dc35`
- #12: `b4c5d6e7-f809-4123-a123-ef0123456789` | 2026-08-20T02:39:05.000Z | GATE/static_compile_diff_green | incident=`b4c5d6e7-f809-4123-a123-ef0123456789` | lesson_key=`static-integrity-green` | event_sha256=`c8651ef590d6b2d8d910f926fadb66e8c7fe8544f523503becda3a3c1692bb1e`
- #13: `c5d6e7f8-091a-4234-b234-f0123456789a` | 2026-08-20T02:39:06.000Z | REVIEW/artifact_allowlist_drift_followup | incident=`c5d6e7f8-091a-4234-b234-f0123456789a` | lesson_key=`artifact-allowlist-drift-followup` | event_sha256=`189704af7d53f0114a54bb46cc782afd7f3c6289f447ea5d5be87094beb5922f`
- #14: `d6e7f809-1a2b-4345-c345-0123456789ab` | 2026-08-20T02:39:07.000Z | STATE_CHANGE/remediation_14_completed | incident=`d6e7f809-1a2b-4345-c345-0123456789ab` | lesson_key=`remediation-14-formal-closeout` | event_sha256=`96bfb821f107b88fd1826d8826f07477c45e260b803b26656ff54ef2e19555c7`
