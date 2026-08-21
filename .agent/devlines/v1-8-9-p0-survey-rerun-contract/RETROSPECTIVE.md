# Retrospective — v1-8-9-p0-survey-rerun-contract

## Goal

# v1.8.9 P0 — survey rerun contract fixture  Align the Agent survey rerun end-to-end test with the current explicit survey support boundary. The survey variance engine must not silently accept finite-population correction when FPC is unsupported; the test must exercise a supported design and retain a separate assertion for the fail-closed unsupported-FPC path.  Do not expand the survey model family or change estimator behavior in this line. Preserve the existing oracle and typed design evidence assertions for the supported fields.  Acceptance: the supported rerun completes with a survey design result and the unsupported FPC declaration remains explicitly blocked; the scoped Agent reach suite and compile/diff checks pass. Browser, real Provider, external host resolver, and release gates remain explicit known gates.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=363852 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T06:38:35.200Z `survey_rerun_fpc_red`; cause_status: `known`; cause: The Agent rerun success fixture declares survey_fpc_col even though the survey variance engine rejects unsupported finite population correction.; resolution: `open`; lesson: Keep unsupported survey design declarations out of successful execution fixtures and test their fail-closed path separately.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `unsupported-fpc-fixture-red`: occurrences=1; cause_status: `known`; root cause: The Agent rerun success fixture declares survey_fpc_col even though the survey variance engine rejects unsupported finite population correction.; solution: `open`

## Added tests

- `tests/test_agent_v187_capability_reach.py`

## New rules

- `unsupported-fpc-fixture-red`: line experience occurrence(s)=1

## Future guidance

- Keep unsupported survey design declarations out of successful execution fixtures and test their fail-closed path separately.

## Event index

- #1: `200d7292-ff73-4bc1-b8b3-5b259f01fe29` | 2026-08-21T06:31:53.360Z | STATE_CHANGE/line_started | incident=`912a8d47-fbed-44e0-b4f8-3bec7dc44d8e` | lesson_key=`frozen-context-before-start` | event_sha256=`cbe3fe1f4f2d9d90b84699aa3fc32f0f3ab1eac0bf43752a330c00903fc8ec0c`
- #2: `b2c4e6f8-1a3d-4b5c-9e7f-0d2c4a6b8e10` | 2026-08-21T06:38:35.200Z | FAILURE/survey_rerun_fpc_red | incident=`c3d5f7a9-2b4e-4c6d-8f10-1e3a5b7c9d20` | lesson_key=`unsupported-fpc-fixture-red` | event_sha256=`4578011b1d3a929e53b06ab02e934aad5cae18fe1fc07d3ef4bca5401b6084be`
- #3: `d4f6a8b0-3c5e-4f7a-9b1d-2e4c6a8f0b12` | 2026-08-21T06:41:53.779Z | GATE/survey_rerun_contract_green | incident=`e5f7a9b1-4d6c-4e8f-0a2b-3c5d7e9f1a23` | lesson_key=`unsupported-fpc-fixture-red` | event_sha256=`8a56a6e69e5e95a93be0a68ddfa62a9701a8b47f851021b8328da62eef2fcb3b`
- #4: `f6a8c0d2-5e7b-4f9a-1c3d-6e8f0a2b4c56` | 2026-08-21T06:42:23.772Z | STATE_CHANGE/survey_rerun_contract_completed | incident=`a7c9e1f3-6b8d-4a0c-2e5f-7b9d1a3c5e78` | lesson_key=`narrow-line-evidence-before-close` | event_sha256=`4f129a1a512d61ce2f865d366d2bcae431f33efcf09ec72be357da1d287829bf`
- #5: `b8d0f2a4-6c9e-4a1b-3d5f-7e9a0c2b4d68` | 2026-08-21T06:44:39.052Z | REVIEW/survey_rerun_fpc_red_resolved | incident=`c3d5f7a9-2b4e-4c6d-8f10-1e3a5b7c9d20` | lesson_key=`unsupported-fpc-fixture-red` | event_sha256=`3612eb1a2516cd352bbf039a09a44a8542862cef8c19dae78beaf028bb9f835c`
