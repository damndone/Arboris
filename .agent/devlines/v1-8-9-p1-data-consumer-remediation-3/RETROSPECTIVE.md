# Retrospective — v1-8-9-p1-data-consumer-remediation-3

## Goal

# Objective: Workbench v1.8.9 P1 Data Consumer Remediation 3  ## Exact baseline  This fresh implementation line starts from the exact target worktree product tip \`779c150e63ac0eba3c24e24aaef673d19f47d426\`. Prior formal lines, their Context Packs, events, retrospectives, handoffs, and commits are historical evidence only and must not be edited.  ## Required remediation  Close the two independently reviewed P1 defects in the package-local Data Consumer pyreadstat boundary:  - If a pyreadstat writer creates the explicitly requested target and then   raises \`RuntimeError\`, \`write_interchange_frame\` must return typed   \`unavailable\` with \`path=None\` and remove only that target created by this   call. A pre-existing user file must never be removed. \`round_trip_frame\` must   apply the same ownership-safe cleanup and leave no partial artifact. - \`_pyreadstat_module\` admission must exercise every native writer mode used at   runtime: bounded real probes for SAV, ZSAV (\`compress=True\`), and DTA using a   minimal frame and private temporary files. Any missing/import-broken/probe-   broken adapter remains typed \`unavailable\` and the real-adapter test remains   skipped when \`pyreadstat\` is not installed.  Do not broaden exception handling to hide unrelated system failures; all adapter runtime errors at the public native surfaces must become the existing typed \`InterchangeUnavailableError\` / typed unavailable result boundary.  ## TDD and evidence requirements  Add real fake-adapter regressions first for partial writer cleanup and ZSAV probe coverage, observe the baseline failures, record the RED evidence through the formal event stream, then implement the smallest fail-closed fix. Preserve SAV/DTA/pyarrow/csv/xlsx behavior and metadata/ingestion contracts.  ## Scope and boundaries  Only package-local Data Consumer interchange implementation/tests, this objective, the final handoff, and formal development-line files are in scope. Do not modify central Agent/Notebook/Report/cutover code, providers, dependencies, other worktrees, or prior formal lines. Do not install dependencies, sign/broadcast anything, or claim browser/provider/central/ host/full-gate/merge/tag/release acceptance.  ## Verification and known gates  Run focused and impacted backend tests, impacted frontend tests and typecheck, backend \`compileall\`, and \`git diff --check\`; run direct fake-adapter probes and retain the real-adapter test skip fact. Run formal \`verify\`, append the required GATE and state events, and regenerate the retrospective through the CLI. Browser, provider, central, host, full, merge, tag, and release remain \`NOT VERIFIED\`.

## Final status

STARTED

## Metrics

- Failure frequency: 2/4 (50.0%; 50.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: N/A (sample=0; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T05:25:00.000Z `native_partial_writer_cleanup_red`; cause_status: `known`; cause: The fake pyreadstat writer created the requested target before raising RuntimeError; the baseline returned typed unavailable but left the partial file and did not distinguish user-owned pre-existing targets.; resolution: `open`; lesson: Adapter failure cleanup must remove only a target newly created by the current call and preserve pre-existing user files.
- #3 2026-08-20T05:25:01.000Z `zsav_admission_probe_red`; cause_status: `known`; cause: The fake pyreadstat adapter probe recorded SAV and DTA only; the baseline never exercised write_sav with compress=True, so capability admission could claim ZSAV support without testing the runtime mode.; resolution: `open`; lesson: Capability probes must cover every native runtime mode, including ZSAV compression, before manifest admission.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `native-mode-probe-parity`: occurrences=1; cause_status: `known`; root cause: The fake pyreadstat adapter probe recorded SAV and DTA only; the baseline never exercised write_sav with compress=True, so capability admission could claim ZSAV support without testing the runtime mode.; solution: `open`
- `owned-target-cleanup`: occurrences=1; cause_status: `known`; root cause: The fake pyreadstat writer created the requested target before raising RuntimeError; the baseline returned typed unavailable but left the partial file and did not distinguish user-owned pre-existing targets.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `native-mode-probe-parity`: line experience occurrence(s)=1
- `owned-target-cleanup`: line experience occurrence(s)=1

## Future guidance

- Adapter failure cleanup must remove only a target newly created by the current call and preserve pre-existing user files.
- Capability probes must cover every native runtime mode, including ZSAV compression, before manifest admission.

## Event index

- #1: `4264adf8-ce74-4bd4-880d-b444c1472de2` | 2026-08-20T05:21:15.855Z | STATE_CHANGE/line_started | incident=`2a294d49-1360-4ed1-a601-78c5611b58d7` | lesson_key=`frozen-context-before-start` | event_sha256=`1b4942ed1b87985098e15a1de39e1aabaf3e36acd0f86417404c3ac095c6d0dc`
- #2: `4d5f7a91-2c3e-4b6d-8f10-9a2c4e6b8d10` | 2026-08-20T05:25:00.000Z | FAILURE/native_partial_writer_cleanup_red | incident=`5e7a9c1b-3d4f-6a8b-0c2e-4f6a8b0c2e4f` | lesson_key=`owned-target-cleanup` | event_sha256=`7082471d3048523b668d44febb6934ba004480d6a97dcf865988ab5d04a23293`
- #3: `6f8a0c2e-4b6d-8f10-9a2c-4e6b8d0f2a4c` | 2026-08-20T05:25:01.000Z | FAILURE/zsav_admission_probe_red | incident=`7a9c1e3f-5b7d-9f1a-3c5e-7a9c1e3f5b7d` | lesson_key=`native-mode-probe-parity` | event_sha256=`d2d408e22b70bfd924fa0c009ae2c037159c9fe7c67de11c1a070a99b76403ed`
- #4: `8b0d2f4a-6c8e-0a2c-4e6f-8a0c2e4f6a8c` | 2026-08-20T05:30:00.000Z | GATE/data_consumer_remediation_3_package_local_green | incident=`9c1e3f5b-7d9f-1b3d-5f7a-9c1e3f5b7d9f` | lesson_key=`package-local-evidence-boundary` | event_sha256=`4027e3220254a081672d542430a905005b613d609c8441c382a8544b36834fb1`
