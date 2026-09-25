# Retrospective — v1-8-9-p0-report-owner-factory

## Goal

# Workbench v1.8.9 Report Owner Factory Objective  ## Objective  Close the remaining P0 runtime boundary for ordinary model runs: a completed run must publish one server-owned typed evidence packet and Report/Agent/ Notebook must resolve that packet by the exact run identity. Add a host-owned, typed owner factory and a per-run owner catalog. The Workbench process may consume an externally admitted authority and persist evidence, but must never mint authority, accept request-supplied identity, or fall back to raw model result files. Concurrent runs must not replace one another's Report owner.  ## Required outcomes  1. A deployment can install an exact host-owned factory without a generic    callable or in-process authority server. 2. The completed workflow creates a canonical evidence envelope from the    server-produced report payload, admits it into the existing registry/store,    commits it once, and records a run-bound owner and indexed provenance. 3. Report, results, Agent and Notebook consumers resolve the owner by exact    actor/project/session/scope/run/model/confirmation identity. 4. Missing host capability, invalid envelope, foreign run, tampered file, and    concurrent-owner mismatch remain typed unavailable/blocked; no raw fallback. 5. Existing package-local C0 tests remain green and a real external authority    fixture proves ordinary OLS completion through Report evidence.  ## Exact baseline  - baseline SHA: \`afc7649c81eb54ee8adcb89edc6be14fc8378d6f\` - candidate worktree: \`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration\`  ## Boundaries  - affected paths: \`backend/workbench/app.py\`, \`backend/workbench/services/results_service.py\`, \`backend/workbench/services/report_evidence_owner_factory.py\`, \`backend/workbench/engine/stages/report.py\`, \`backend/workbench/orchestrator/__init__.py\`, \`backend/workbench/http/runs_routes.py\`, \`backend/workbench/artifacts.py\`, \`tests/test_v189_report_owner_factory.py\`, \`tests/test_v189_evidence_report_boundary.py\` - allowed paths: same as affected paths - protected paths: \`backend/workbench/agent\`, \`backend/workbench/predictive_research\`, \`frontend/src\` - tests: owner-factory focused tests, report boundary tests, ordinary OLS integration test - known gates: browser/provider/host full gate/release remain NOT VERIFIED

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
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T17:25:12.445Z `stale_catalog_red`; cause_status: `known`; cause: The stale-catalog consumer regression first returned a generic persistence-capability code instead of the required owner-context conflict, showing the stale entry had been filtered before fallback resolution.; resolution: `resolved`; lesson: Treat a run-level owner entry as authoritative before liveness or root filtering so stale entries cannot create a compatibility fallback path.

## All errors

- None recorded.

## All gaps

- #5 2026-08-21T17:26:43.000Z `external_acceptance_boundary`; cause_status: `external`; cause: This package-local line has no deployment-owned production supervisor configuration or real provider endpoint in the candidate worktree, so host startup, browser acceptance, provider acceptance, full release gate, and release publication remain outside the verified boundary.; resolution: `accepted`; lesson: Do not promote package-local P0 tests into product completion until the deployment-owned host and user-visible acceptance boundaries are exercised.

## All waste

- None recorded.

## Root causes and solutions

- `p0-external-acceptance-separation`: occurrences=1; cause_status: `external`; root cause: This package-local line has no deployment-owned production supervisor configuration or real provider endpoint in the candidate worktree, so host startup, browser acceptance, provider acceptance, full release gate, and release publication remain outside the verified boundary.; solution: `accepted`
- `stale-owner-fail-closed`: occurrences=1; cause_status: `known`; root cause: The stale-catalog consumer regression first returned a generic persistence-capability code instead of the required owner-context conflict, showing the stale entry had been filtered before fallback resolution.; solution: `resolved`

## Added tests

- `tests/test_v189_report_owner_factory.py`

## New rules

- `p0-external-acceptance-separation`: line experience occurrence(s)=1
- `stale-owner-fail-closed`: line experience occurrence(s)=1

## Future guidance

- Do not promote package-local P0 tests into product completion until the deployment-owned host and user-visible acceptance boundaries are exercised.
- Keep exact owner identity and run-level catalog authority ahead of compatibility projections and global defaults.
- Treat a run-level owner entry as authoritative before liveness or root filtering so stale entries cannot create a compatibility fallback path.

## Event index

- #1: `11156efc-a9f3-40d5-bb18-ff763098a724` | 2026-08-21T16:59:38.870Z | STATE_CHANGE/line_started | incident=`81b13ce6-6a1e-49b3-a14c-ea06252ddd62` | lesson_key=`frozen-context-before-start` | event_sha256=`2e4446cac72eb8b025a2b33ea42a34eae517141602d70e96f13ef3a15e9c79d3`
- #2: `b1e4d7a2-5c90-4f38-8a16-2d7b9c4e6f01` | 2026-08-21T17:25:12.445Z | FAILURE/stale_catalog_red | incident=`d2a6f9c3-7b14-4e80-9f25-1c6d8a3b5e70` | lesson_key=`stale-owner-fail-closed` | event_sha256=`83a9b91f62eaf15bf7e1c5b120936a1a981902a23c237e2a8927bd5d510a4e89`
- #3: `c2f5e8b3-6d01-4a49-9b27-3e8c0d5f7a12` | 2026-08-21T17:25:39.657Z | REVIEW/owner_catalog_review | incident=`e3b7a0d4-8c25-4f91-a036-2d7e9b4c6f81` | lesson_key=`owner-catalog-authority` | event_sha256=`257cb44797a5cbaf2f3983e854001301f32de6701383de9406084090699891af`
- #4: `d3a6f9c4-7e12-4b50-8c38-4f9d1e6a8b23` | 2026-08-21T17:26:08.828Z | GATE/p0_owner_report_suite | incident=`f4c8b1e5-9d36-4a02-8e47-5c0b2d7f9a14` | lesson_key=`p0-focused-gate-separation` | event_sha256=`5dd7c04406c40b283a5d5db5c7c0512bcbfe6901014c0b88074cf9d98b41ac3b`
- #5: `e4b7a0d5-8f23-4c61-9d49-5a0e2b7f1c35` | 2026-08-21T17:26:43.000Z | GAP/external_acceptance_boundary | incident=`a5c9e2f6-0b34-4d72-8e50-6c1f3a7b9d26` | lesson_key=`p0-external-acceptance-separation` | event_sha256=`10363eefb990a77d99355778a495793aee3a40a0013fc631fd06d19a95109492`
- #6: `f5c8b1e6-0a34-4d72-8e50-6c1f3a7b9d27` | 2026-08-21T17:27:11.970Z | STATE_CHANGE/package_local_completion | incident=`b6d9e2f7-1c45-4a83-9e60-7b2d5f8a0c34` | lesson_key=`p0-package-complete-boundary` | event_sha256=`fcd60d619e6417ae8306a6976b102816d9b46e53c9fcffedefe02d5024a1f655`
