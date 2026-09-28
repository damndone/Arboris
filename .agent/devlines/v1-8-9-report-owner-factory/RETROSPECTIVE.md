# Retrospective — v1-8-9-report-owner-factory

## Goal

# Workbench v1.8.9 Report Owner Factory Objective  ## Objective  Close the remaining P0 runtime boundary for ordinary model runs: a completed run must publish one server-owned typed evidence packet and Report/Agent/ Notebook must resolve that packet by the exact run identity. Add a host-owned, typed owner factory and a per-run owner catalog. The Workbench process may consume an externally admitted authority and persist evidence, but must never mint authority, accept request-supplied identity, or fall back to raw model result files. Concurrent runs must not replace one another's Report owner.  ## Required outcomes  1. A deployment can install an exact host-owned factory without a generic    callable or in-process authority server. 2. The completed workflow creates a canonical evidence envelope from the    server-produced report payload, admits it into the existing registry/store,    commits it once, and records a run-bound owner and indexed provenance. 3. Report, results, Agent and Notebook consumers resolve the owner by exact    actor/project/session/scope/run/model/confirmation identity. 4. Missing host capability, invalid envelope, foreign run, tampered file, and    concurrent-owner mismatch remain typed unavailable/blocked; no raw fallback. 5. Existing package-local C0 tests remain green and a real external authority    fixture proves ordinary OLS completion through Report evidence.  ## Exact baseline  - baseline SHA: \`afc7649c81eb54ee8adcb89edc6be14fc8378d6f\` - candidate worktree: \`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration\`  ## Boundaries  - affected paths: \`backend/workbench/app.py\`, \`backend/workbench/services/results_service.py\`, \`backend/workbench/services/report_evidence_owner_factory.py\`, \`backend/workbench/engine/stages/report.py\`, \`backend/workbench/orchestrator/__init__.py\`, \`backend/workbench/http/runs_routes.py\`, \`backend/workbench/artifacts.py\`, \`tests/test_v189_report_owner_factory.py\`, \`tests/test_v189_evidence_report_boundary.py\` - allowed paths: same as affected paths - protected paths: \`backend/workbench/agent\`, \`backend/workbench/predictive_research\`, \`frontend/src\` - tests: owner-factory focused tests, report boundary tests, ordinary OLS integration test - known gates: browser/provider/host full gate/release remain NOT VERIFIED

## Final status

STARTED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
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

- No guidance recorded.

## Event index

- #1: `a8d6d52b-6560-4020-9feb-93ac8be10dc0` | 2026-08-21T11:54:06.247Z | STATE_CHANGE/line_started | incident=`e4d10bab-0ca6-4af6-9603-68e19a61da4c` | lesson_key=`frozen-context-before-start` | event_sha256=`7ae736924c29eae544da6f6c6014249045b88c9971dc9a3db9445fdcea9b57ee`
