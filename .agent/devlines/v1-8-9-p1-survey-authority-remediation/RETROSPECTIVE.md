# Retrospective — v1-8-9-p1-survey-authority-remediation

## Goal

# Workbench v1.8.9 P1 Survey authority remediation  ## Objective  Close the independent review findings in the Survey central-source boundary. The consumer-facing API must not be able to mint a Survey run capability or a receipt/source snapshot from caller-shaped paths, metadata, digests, or raw packets. Issuance must require the server-owned internal issuer and a real, persisted, hash-checked run artifact manifest. Unsupported Survey families must remain typed unavailable while preserving the persisted evidence status, reason, and safe design metadata for diagnosis.  ## Success criteria  1. Direct calls to the internal capability/receipt factories without the    server issuer fail closed. 2. A directory with a \`runs/<id>\` shape but no verified server artifact    manifest cannot mint a run capability. 3. A forged receipt metadata object cannot produce a validated Agent/Notebook    projection. 4. Supported OLS/Logit Agent and Notebook projections remain green through the    existing central service. 5. Unsupported model families return typed unavailable while retaining the    persisted status/reason and bounded Survey design metadata. 6. No estimator, variance-engine, Report, HTTP, frontend, provider, or release    behavior is changed.  ## Required verification  Run the existing Survey central-source suite plus the new authority probes, catalog/coverage regression, selected compileall, \`git diff --check\`, formal verification, and retrospective. Browser/provider/full/release remain separate gates.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/6 (16.7%; 16.7 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T23:31:44.899Z `survey_authority_review_red`; cause_status: `known`; cause: The review-directed authority and unsupported-family probes fail against the current Survey central-source implementation before remediation.; resolution: `open`; lesson: Run direct authority and metadata-preservation probes before accepting a focused consumer green result.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `survey-authority-probe-before-close`: occurrences=1; cause_status: `known`; root cause: The review-directed authority and unsupported-family probes fail against the current Survey central-source implementation before remediation.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `survey-authority-probe-before-close`: line experience occurrence(s)=1

## Future guidance

- Re-review after each security-boundary fix and include malformed persisted shapes in the evidence contract.
- Run direct authority and metadata-preservation probes before accepting a focused consumer green result.
- Validate persisted discriminator types before mapping them to supported model families.

## Event index

- #1: `90a9b4c7-2d98-418a-858b-34bae52d30b8` | 2026-08-20T23:30:07.644Z | STATE_CHANGE/line_started | incident=`114f24be-e611-473e-92d9-628c80ddce17` | lesson_key=`frozen-context-before-start` | event_sha256=`6ccf807578b51b5ca3cbd2c901f6e5a0e8ec6a99e28cc7c721336e212317a946`
- #2: `7c4e1a9b-5d32-46f8-0a7b-2e9d6c3f1a85` | 2026-08-20T23:31:44.899Z | FAILURE/survey_authority_review_red | incident=`4f8a2c7e-1b63-49d0-5e7a-3c9f6b2d8a14` | lesson_key=`survey-authority-probe-before-close` | event_sha256=`6c469288b90b612ac62599ce5c0eeee8de4bdc523f22655cdd21de10ce814f1b`
- #3: `a6d2f8c1-4e97-5b30-9a7c-2d1f8e6b4c53` | 2026-08-20T23:38:21.960Z | REVIEW/survey_malformed_model_family_boundary | incident=`3f7a1c9e-5b24-4d80-6c2e-8a9f1b5d7c43` | lesson_key=`survey-model-family-type-gate` | event_sha256=`3d65be3db94f7cf9197f37e4aea713f83e619f491aa44477ba33ca4eaf74ad45`
- #4: `d4a8f1c6-7e23-49b0-5d9a-2c6f8e1b3a74` | 2026-08-20T23:42:20.538Z | REVIEW/survey_authority_quality_review_resolved | incident=`8c2e6a1f-4b97-5d30-9a7e-1f6c3b8d2a54` | lesson_key=`survey-authority-re-review-green` | event_sha256=`7e5304b2a554b1f1813a5fcbbf175f65e386d2db63f17218c9e7f2d2e2ad8d3b`
- #5: `e7c1a9d4-5b26-48f0-2a6e-9d3c7b1f8a54` | 2026-08-20T23:42:39.685Z | GATE/survey_authority_remediation_focused_green | incident=`1a6f3c8e-9b24-4d70-5c2e-7f8a1b6d3e95` | lesson_key=`survey-authority-focused-gate` | event_sha256=`26cb46f8d6d17a37ef8e0d3edf6bb7ecef3098360841dd9c34967c7007b3dc82`
- #6: `f2a7c9e4-6b13-48d0-5c2e-1f8a7d3b9e64` | 2026-08-20T23:42:58.556Z | STATE_CHANGE/line_completed | incident=`5c8e1a7d-3b94-6f20-9a2e-7d1c4b8f6e53` | lesson_key=`survey-authority-remediation-closeout` | event_sha256=`64b1b2e1c0f85669a299c8640eb0448ea132ce45a62e28ccee02c41b0527c84d`
