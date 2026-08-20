# Retrospective — v1-8-9-p1-data-consumer-remediation-2

## Goal

# Objective: Workbench v1.8.9 P1 Data Consumer Remediation 2  ## Exact baseline  This fresh implementation line starts from the target worktree product tip \`74e92d89d889726d0d6955e5faeae6b4367898d5\`. Prior formal lines, their Context Packs, events, retrospectives, handoffs, and commits are historical evidence only and must not be edited.  ## Required remediation  Close the independently reviewed P1 in the package-local Data Consumer interchange boundary:  - \`_pyreadstat_module()\` must admit an adapter only after a bounded real   write/read probe over a minimal in-memory-safe frame and a safe temporary   file; callable attributes alone are insufficient. - A missing, import-broken, or runtime-broken pyreadstat adapter must be   represented as typed \`unavailable\` with a stable \`optional_dependency\`   reason at capability, manifest/admission, writer, reader, and round-trip   surfaces; no bare adapter exception may escape. - Preserve the existing pyarrow and other Data Consumer behavior, including   the existing typed unavailable behavior and normal round-trip contracts.  ## TDD and evidence requirements  Write RED tests first for a callable pyreadstat adapter whose write/read operations raise \`RuntimeError\`, covering capability, manifest/admission, writer, reader, and round-trip surfaces. Add a bounded real-adapter probe test using only a minimal frame and a safe temporary file; it must not read user data. Record the RED failure through the formal event stream, then implement the smallest fail-closed fix and retain the GREEN evidence.  ## Scope and boundaries  Only package-local Data Consumer implementation, its focused tests, this objective, the final handoff, and formal development-line files are in scope. Do not modify root, other worktrees, central Agent/Notebook/Report/cutover code, providers, frontend product code, dependencies, or prior formal lines. Do not install dependencies, sign/broadcast anything, or claim browser, provider, central, host, full-gate, merge, tag, or release acceptance.  ## Verification and known gates  Run the backend focused and impacted Data Consumer tests, impacted frontend tests and typecheck, backend \`compileall\`, and \`git diff --check\`. Run direct adversarial probes for absent, available, and broken pyreadstat states. Run formal verify and CLI-generated retrospective before closeout. Browser, provider, central, host, full, merge, tag, and release remain \`NOT VERIFIED\` unless separately evidenced.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/7 (28.6%; 28.6 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #4 2026-08-20T05:01:09.000Z `runtime_broken_pyreadstat_adapter_red`; cause_status: `known`; cause: The RED probe supplied callable pyreadstat read and write functions that raise RuntimeError; the baseline capability and manifest surfaces still admitted the adapter before writer and reader execution.; resolution: `open`; lesson: Optional adapter capability must be admitted only after a bounded real operation probe and must fail closed across capability, manifest, writer, reader, and round-trip surfaces.

## All errors

- #5 2026-08-20T05:05:23.000Z `frontend_focus_path_error`; cause_status: `known`; cause: The first Vitest invocation was run from the frontend directory with repository-prefixed test paths, so the runner found no test files.; resolution: `resolved`; lesson: Run frontend focused paths relative to the declared frontend working directory and treat no-test-file output as a command error.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `bounded-adapter-probe`: occurrences=1; cause_status: `known`; root cause: The RED probe supplied callable pyreadstat read and write functions that raise RuntimeError; the baseline capability and manifest surfaces still admitted the adapter before writer and reader execution.; solution: `open`
- `frontend-focused-command-path`: occurrences=1; cause_status: `known`; root cause: The first Vitest invocation was run from the frontend directory with repository-prefixed test paths, so the runner found no test files.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `bounded-adapter-probe`: line experience occurrence(s)=1
- `frontend-focused-command-path`: line experience occurrence(s)=1

## Future guidance

- Optional adapter capability must be admitted only after a bounded real operation probe and must fail closed across capability, manifest, writer, reader, and round-trip surfaces.
- Run frontend focused paths relative to the declared frontend working directory and treat no-test-file output as a command error.

## Event index

- #1: `830a5093-2d9c-4c01-88d7-44337bc5f4d7` | 2026-08-20T04:57:58.532Z | STATE_CHANGE/line_started | incident=`fa8df746-94cb-4cf2-b950-c502061dd328` | lesson_key=`frozen-context-before-start` | event_sha256=`3603f9f8407422bc7468a87e5d0410f8070ce55e7a0cfcaa670b1040e6f31b5a`
- #2: `f62008c5-8797-4531-82b0-81481ecc18ba` | 2026-08-20T04:58:52.823Z | STATE_CHANGE/context_rescope_required | incident=`caeada96-2165-4009-8268-199b10496136` | lesson_key=`context-pack-rescope` | event_sha256=`d1da5c348a3a8f6b369bb04054dc94a4300916c44f80b16b56ce3dcb177d470d`
- #3: `a14d775f-1f6e-4cc0-8a9a-ddd90274e171` | 2026-08-20T04:58:52.826Z | STATE_CHANGE/context_rescoped | incident=`48c779b6-f191-4669-8cec-dc6ddff5414b` | lesson_key=`context-pack-rescope` | event_sha256=`710e3e7db3a147f63e01ab288af9c1d28053ba324c886e9c2fffbbc51647ddf2`
- #4: `7e1c2a4b-5d6f-4789-8a0b-1c2d3e4f5a6b` | 2026-08-20T05:01:09.000Z | FAILURE/runtime_broken_pyreadstat_adapter_red | incident=`8f2a4c6e-1b3d-4f50-9a7c-2e5d0b8f1a63` | lesson_key=`bounded-adapter-probe` | event_sha256=`61d191a18dc799781c2d4ce77c28a15a230b11abaeed06293b82bb3f1b4ea687`
- #5: `9a3c5e7f-1b2d-4e60-8a9c-3d5f7b1e2a64` | 2026-08-20T05:05:23.000Z | ERROR/frontend_focus_path_error | incident=`ab4d6f8a-2c5e-4f70-9b1d-3e6a8c0f2b54` | lesson_key=`frontend-focused-command-path` | event_sha256=`52013412634680e52a8a4754bdb6afbe7ac03f42904dff596e7a4cd34d86450d`
- #6: `b6d8f0a2-4c7e-491b-8d3f-5a1c9e2b7d64` | 2026-08-20T05:06:34.000Z | GATE/remediation_2_package_local_green | incident=`c7e9a1b3-5d8f-4a20-9c6e-1b7d3f5a8e02` | lesson_key=`data-consumer-remediation-2-green` | event_sha256=`7690d9dd827b527fdbf546a707e252ae58f7001a131d601d16f4c87e9ef95257`
- #7: `d8f0a2c4-6e1b-493d-8f5a-7c2e0b4d9a16` | 2026-08-20T05:07:32.000Z | STATE_CHANGE/line_completed | incident=`e9a1c3f5-7b2d-4e60-8a9c-1d3f5b7e2a64` | lesson_key=`close-at-owned-evidence-boundary` | event_sha256=`7f154633043a7cc9588670ed846a0ff0a0ccd457b6b94c6d07f36a87bc0a8246`
