# Retrospective — v1-8-9-p1-classification-production-remediation-15

## Goal

# Workbench v1.8.9 P1 Classification Production Remediation 15 Objective  Close the independent code-quality review blocker at exact tip \`30f3adb9263cb009ec39174b0ff6597eeb00bf73\` without changing the repository root or any other worktree. Keep remediation-14's descriptor-based integrity seam and make the generic artifact download a bounded, compatible stream.  ## Required behavior  - Keep \`backend/workbench/repository/file_integrity.py\` as the single   server-owned path/open/fstat seam. Generic downloads must hash and stream   from the same safely opened FD; they must not call \`read_bytes_and_sha256\`,   allocate the whole artifact, or use \`b''.join\` for the response body. - Use an explicit \`64 KiB\` maximum stream chunk and an explicit \`512 MiB\`   maximum generic artifact stream size. Reject an indexed artifact larger than   the policy before returning a response with a typed non-success boundary;   do not silently truncate or spill unbounded memory. - Make the stream generator close its FD in \`finally\` on success, normal   client exhaustion, open/hash/read error, and iterator failure. Every emitted   chunk must be bounded. During hashing and streaming, an inode, device, or   size change must fail closed and must not yield further bytes. - Restore the old generic download compatibility surface: MIME \`Content-Type\`,   \`Content-Disposition\`, \`Content-Length\`, \`Accept-Ranges: bytes\`, and explicit   byte-range semantics. Preserve single and multipart range behavior where   the old \`FileResponse\` provided it; malformed or unsatisfiable ranges must   have explicit 400/416 responses rather than silently returning a full file. - Add direct unit/integration probes for intermediate-directory symlinks,   open/read exceptions with FD cleanup, read-time inode/size replacement,   valid large bounded streaming, response headers, and range behavior.   Replacement callbacks must patch live symbols with \`raising=True\` and assert   observed execution. Existing classification consumer, artifacts-index   list, path/type/digest, duplicate, non-regular, symlink, and 500/503   boundaries must remain unchanged.  ## Formal and verification boundaries  Use the unique formal line \`v1-8-9-p1-classification-production-remediation-15\`, created only through \`scripts/devline_control.py start\`, with exact baseline \`30f3adb9263cb009ec39174b0ff6597eeb00bf73\`.  Required evidence is TDD RED before production changes, then focused generic stream/range/cleanup/TOCTOU tests, classification production and contract suites, \`compileall\`, \`git diff --check\`, formal verify, retrospective, and an exact handoff. Known inherited gates remain the API artifacts async fixture failures, the v1.8.6 legacy consumer fixture failure, and the non-canonical artifact-integrity fixture failures. Browser, external provider, central, host, full-gate, merge, tag, and release acceptance remain \`NOT VERIFIED\`.  ## Scope  - \`backend/workbench/repository/file_integrity.py\` - \`backend/workbench/http/runs_routes.py\` - \`tests/test_v189_classification_production.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-15-objective.md\` - \`docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-15.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-15-handoff.md\` - the new remediation-15 formal records  Do not modify \`backend/workbench/predictive_research/consumer_projection.py\`, \`backend/workbench/repository/run_repository.py\`, \`backend/workbench/prediction.py\`, \`backend/workbench/reporting.py\`, \`backend/workbench/http/notebook_routes.py\`, \`backend/workbench/predictive_research/persistence.py\`, remediation-14 or remediation-13 formal records, the repository root, or any other worktree.

## Final status

COMPLETED

## Metrics

- Failure frequency: 6/16 (37.5%; 37.5 per 100 events)
- Repeat rate: 3/6 (50.0%)
- Recurrence rate: 1/3 (33.3%)
- MTTR: median=0 ms (sample=6; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/8 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-19T12:00:02.000Z `generic_stream_red`; cause_status: `known`; cause: Before the bounded stream implementation, the generic download route called read_bytes_and_sha256 and returned an in-memory Response; request Range headers were ignored and malformed or unsatisfiable ranges returned 200 full bodies.; resolution: `open`; lesson: Prove whole-file allocation and Range compatibility fail before changing the route, then keep one opened descriptor below hash and stream operations.

## All errors

- #2 2026-08-19T12:00:01.000Z `red_test_setup_error`; cause_status: `known`; cause: The first RED run attempted to remove a non-empty intermediate fixture directory before replacing it with a symlink.; resolution: `resolved`; lesson: Make intermediate-directory symlink probes replace their indexed child before removing the parent, and distinguish setup errors from product failures.
- #4 2026-08-19T12:00:03.000Z `range_exception_import_error`; cause_status: `known`; cause: The first bounded-stream implementation imported Starlette range exception classes from fastapi.responses, which does not export them in this environment.; resolution: `resolved`; lesson: Check the installed framework export boundary after adding compatibility helpers and keep collection failures distinct from runtime product evidence.
- #5 2026-08-19T12:00:04.000Z `cleanup_probe_wrong_symbol`; cause_status: `known`; cause: The first post-implementation cleanup probe still patched the old read_bytes_and_sha256 method, so the new sha256 seam was not exercised and the HTTP response completed 200 instead of reaching the controlled hash failure boundary.; resolution: `resolved`; lesson: When a shared seam changes, patch the live helper actually called by the route and assert the callback executes before interpreting cleanup evidence.
- #6 2026-08-19T12:00:05.000Z `stream_response_shape_regression`; cause_status: `known`; cause: The first full production regression retained remediation-14's direct generic-alias assertion that the route returns a plain Response with an eagerly available body.; resolution: `resolved`; lesson: Update response-shape assertions when replacing whole-body responses with bounded streams, while retaining body and header compatibility checks.
- #7 2026-08-19T12:00:06.000Z `static_scan_shell_error`; cause_status: `known`; cause: The first static scan command used shell quoting that left an unmatched double quote before rg executed.; resolution: `resolved`; lesson: Use shell-safe separate scan expressions for security checks and distinguish command syntax errors from source findings.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `artifact-fd-cleanup`: occurrences=1; cause_status: `known`; root cause: The first post-implementation cleanup probe still patched the old read_bytes_and_sha256 method, so the new sha256 seam was not exercised and the HTTP response completed 200 instead of reaching the controlled hash failure boundary.; solution: `resolved`
- `artifact-range-compatibility`: occurrences=1; cause_status: `known`; root cause: The first bounded-stream implementation imported Starlette range exception classes from fastapi.responses, which does not export them in this environment.; solution: `resolved`
- `artifact-stream-bounded`: occurrences=4; cause_status: `known`; root cause: The first RED run attempted to remove a non-empty intermediate fixture directory before replacing it with a symlink.; solution: `resolved`

## Added tests

- `tests/predictive_research/test_classification_contracts_v189.py; tests/predictive_research/test_classification_protocol_v189.py; tests/predictive_research/test_classification_leakage_v189.py; tests/predictive_research/test_classification_consumers_v189.py`
- `tests/predictive_research/test_consumer_projection_v186.py`
- `tests/test_api.py`
- `tests/test_v189_artifact_integrity.py`
- `tests/test_v189_classification_production.py`

## New rules

- `artifact-fd-cleanup`: line experience occurrence(s)=1
- `artifact-range-compatibility`: line experience occurrence(s)=1
- `artifact-stream-bounded`: line experience occurrence(s)=4

## Future guidance

- Check the installed framework export boundary after adding compatibility helpers and keep collection failures distinct from runtime product evidence.
- Make intermediate-directory symlink probes replace their indexed child before removing the parent, and distinguish setup errors from product failures.
- Prove whole-file allocation and Range compatibility fail before changing the route, then keep one opened descriptor below hash and stream operations.
- Update response-shape assertions when replacing whole-body responses with bounded streams, while retaining body and header compatibility checks.
- Use shell-safe separate scan expressions for security checks and distinguish command syntax errors from source findings.
- When a shared seam changes, patch the live helper actually called by the route and assert the callback executes before interpreting cleanup evidence.

## Event index

- #1: `8e7841fc-6416-4476-a57c-92071b510f09` | 2026-08-20T03:06:01.426Z | STATE_CHANGE/line_started | incident=`1ea7b30a-970c-463d-b38d-74cbe8a0ad0c` | lesson_key=`frozen-context-before-start` | event_sha256=`b1abc92e7450ed5092b967ea20fc1adc6925baf6e8e395befbb76c60af03f094`
- #2: `15a1b2c3-d4e5-4678-9012-3456789abcde` | 2026-08-19T12:00:01.000Z | ERROR/red_test_setup_error | incident=`15a1b2c3-d4e5-4678-9012-3456789abcde` | lesson_key=`artifact-stream-bounded` | event_sha256=`4bb54ed91ddf56d3271cb10b6c178c0ecf0c1430a097a9ea29a36bd4def836ad`
- #3: `16b2c3d4-e5f6-4789-a012-3456789abcde` | 2026-08-19T12:00:02.000Z | FAILURE/generic_stream_red | incident=`16b2c3d4-e5f6-4789-a012-3456789abcde` | lesson_key=`artifact-stream-bounded` | event_sha256=`c599f2bdefc03bb7bd00fde228cfca1ea05a891d1b57b1d616d61ca67c4dbe83`
- #4: `17c3d4e5-f678-4901-abcd-23456789abcd` | 2026-08-19T12:00:03.000Z | ERROR/range_exception_import_error | incident=`17c3d4e5-f678-4901-abcd-23456789abcd` | lesson_key=`artifact-range-compatibility` | event_sha256=`b03b62ce9fad614fa8e3d25264eb6e12b6d99caf9e307f1b99db22d9349eda26`
- #5: `18d4e5f6-7890-4abc-def0-123456789abc` | 2026-08-19T12:00:04.000Z | ERROR/cleanup_probe_wrong_symbol | incident=`18d4e5f6-7890-4abc-def0-123456789abc` | lesson_key=`artifact-fd-cleanup` | event_sha256=`7c9e6a59b42a57e07bfb95301adc8af725a574f3e678ad6ef5dc3041b82924d1`
- #6: `19e5f607-8901-4bcd-ef01-23456789abcd` | 2026-08-19T12:00:05.000Z | ERROR/stream_response_shape_regression | incident=`19e5f607-8901-4bcd-ef01-23456789abcd` | lesson_key=`artifact-stream-bounded` | event_sha256=`432b7f2c4eb2d62c77382bb0c575ec0c883cb274e80721b18311a64fc224ac9b`
- #7: `1ae6f708-9012-4bcd-ef01-23456789abcd` | 2026-08-19T12:00:06.000Z | ERROR/static_scan_shell_error | incident=`1ae6f708-9012-4bcd-ef01-23456789abcd` | lesson_key=`artifact-stream-bounded` | event_sha256=`f5018f18b4fe258b2a170005486a487d96e7bad16c752870befedb686b6f177f`
- #8: `1bf7a809-0123-4cde-f012-3456789abcde` | 2026-08-19T12:00:07.000Z | GATE/bounded_stream_focused_green | incident=`1bf7a809-0123-4cde-f012-3456789abcde` | lesson_key=`artifact-stream-bounded` | event_sha256=`5a09643f1c0add67ce431dbcae0c6718851cc708da6e415dd87c6524a02bd1bd`
- #9: `1c08b91a-1234-4def-0123-456789abcdef` | 2026-08-19T12:00:08.000Z | GATE/classification_production_green | incident=`1c08b91a-1234-4def-0123-456789abcdef` | lesson_key=`artifact-stream-bounded` | event_sha256=`032312c3804aebac35637c36aaf1e9294c4751548938419cebeb3408ec4fdbbe`
- #10: `1d19ca2b-2345-4efa-1234-56789abcdef0` | 2026-08-19T12:00:09.000Z | GATE/classification_contracts_green | incident=`1d19ca2b-2345-4efa-1234-56789abcdef0` | lesson_key=`artifact-stream-bounded` | event_sha256=`e7b732af59f7ef996e55d175e092f6c834bbb15696c4b17db1bf15ef12296aeb`
- #11: `1e2ad3bc-3456-4fab-2345-6789abcdef01` | 2026-08-19T12:00:10.000Z | GATE/api_artifacts_known_gate | incident=`1e2ad3bc-3456-4fab-2345-6789abcdef01` | lesson_key=`api-artifacts-known-gate` | event_sha256=`cb668a437784c17e50544139ab203407ad376ee47bf857ebac91623af5e68e3e`
- #12: `1f3be4cd-4567-4abc-3456-789abcdef012` | 2026-08-19T12:00:11.000Z | GATE/legacy_consumer_known_gate | incident=`1f3be4cd-4567-4abc-3456-789abcdef012` | lesson_key=`legacy-consumer-known-gate` | event_sha256=`7dc3ec867506874ff4c3aa565166cc017b522ebfdf8809efd741b9be8594ae70`
- #13: `20a4f5de-5678-4bcd-4567-89abcdef0123` | 2026-08-19T12:00:12.000Z | GATE/artifact_integrity_fixture_known_gate | incident=`20a4f5de-5678-4bcd-4567-89abcdef0123` | lesson_key=`artifact-integrity-fixture-gate` | event_sha256=`08543026e2da2b0e89247bc4c4435cbe24e4b7f58da73522847bf9b3771e62ce`
- #14: `21b5c6ef-6789-4cde-5678-9abcdef01234` | 2026-08-19T12:00:13.000Z | GATE/static_integrity_green | incident=`21b5c6ef-6789-4cde-5678-9abcdef01234` | lesson_key=`artifact-stream-bounded` | event_sha256=`9a45986a927ee7d471fd3659c2445326fd8e83ced285dfee94988cec42837226`
- #15: `22c6d7f8-7890-4abc-6789-abcdef012345` | 2026-08-19T12:00:14.000Z | STATE_CHANGE/remediation_15_completed | incident=`22c6d7f8-7890-4abc-6789-abcdef012345` | lesson_key=`remediation-15-formal-closeout` | event_sha256=`5c23eec2c81325500fc69cda213eb8d633b24483ab345cb39a9f4c3148a5e1da`
- #16: `23d7e8f9-8901-4abc-7890-abcdef012345` | 2026-08-19T12:00:15.000Z | GATE/generic_stream_red_resolved | incident=`16b2c3d4-e5f6-4789-a012-3456789abcde` | lesson_key=`artifact-stream-bounded` | event_sha256=`da872a8e5cc83feb344b6c62eff612ce79bee138bfb21797f1753143007577da`
