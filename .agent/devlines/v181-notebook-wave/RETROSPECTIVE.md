# Retrospective — v181-notebook-wave

## Goal

v1.8.1 Notebook wave (Gate 4/5/6) under ADR-PD-001: 3 feature lanes + 1 evaluation lane from a single contract lock.

## Final status

STARTED

## Metrics

- Failure frequency: 4/6 (66.7%; 66.7 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=0 ms (sample=4; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/1)

## All failures

- #4 2026-07-22T23:00:00.000Z `fixture_information_criteria_incoherent`; cause_status: `known`; cause: The canonical ETS fixture carried aic and log_likelihood implying six parameters but a bic implying 5.897; the numbers could not come from one likelihood.; resolution: `resolved`; lesson: Hand-authored numeric fixtures must be checked for internal arithmetic identity between AIC, BIC, log-likelihood and the parameter count before they become a shared lock.
- #5 2026-07-22T24:00:00.000Z `contract_drops_unknown_fields`; cause_status: `known`; cause: NotebookOptionRevision.from_dict read named keys and silently dropped extras while its two sibling packets rejected them; a lane could smuggle an unversioned field and the packet would still validate.; resolution: `resolved`; lesson: Every packet from_dict must reject unknown fields symmetrically; a permissive parser turns a field vanishing on round-trip into an invisible defect.

## All errors

- #6 2026-07-22T23:55:00.000Z `session_limit_interrupted_lanes`; cause_status: `external`; cause: A shared session limit terminated the Lane A and Lane D subagents mid-implementation.; resolution: `resolved`; lesson: On a runner or session interruption, commit the interrupted lane's work in progress immediately so no work is lost and the lane can resume from a clean commit rather than restart.

## All gaps

- #3 2026-07-22T22:00:00.000Z `contract_missing_time_index_semantics`; cause_status: `known`; cause: The ETS 1.0 contract had no time_index_semantics field, so it would have blocked VIXCLS, a trading-day series whose weekend gaps are not missing data.; resolution: `resolved`; lesson: When adding a model that shares data with an existing pack, mirror the existing pack's index and sample vocabulary in the Contract Sprint, or the two models cannot be compared on one series.

## All waste

- #2 2026-07-22T21:00:00.000Z `serial_work_ignored_parallel_protocol`; cause_status: `known`; cause: Gate 1/2/3 were implemented serially in a single worktree without consulting ADR-PD-001, the accepted parallel-development protocol in effect since v1.7.3.; resolution: `mitigated`; lesson: Before starting a version, grep docs/superpowers/specs for accepted ADRs and start each devline from a frozen Context Pack; the discipline surfaces binding constraints the memory index does not.

## Root causes and solutions

- `check-accepted-adrs-before-starting`: occurrences=1; cause_status: `known`; root cause: Gate 1/2/3 were implemented serially in a single worktree without consulting ADR-PD-001, the accepted parallel-development protocol in effect since v1.7.3.; solution: `mitigated`
- `fixture-numbers-must-be-arithmetically-coherent`: occurrences=1; cause_status: `known`; root cause: The canonical ETS fixture carried aic and log_likelihood implying six parameters but a bic implying 5.897; the numbers could not come from one likelihood.; solution: `resolved`
- `mirror-existing-index-vocabulary`: occurrences=1; cause_status: `known`; root cause: The ETS 1.0 contract had no time_index_semantics field, so it would have blocked VIXCLS, a trading-day series whose weekend gaps are not missing data.; solution: `resolved`
- `packet-parsers-reject-unknown-fields`: occurrences=1; cause_status: `known`; root cause: NotebookOptionRevision.from_dict read named keys and silently dropped extras while its two sibling packets rejected them; a lane could smuggle an unversioned field and the packet would still validate.; solution: `resolved`
- `preserve-wip-on-runner-interruption`: occurrences=1; cause_status: `external`; root cause: A shared session limit terminated the Lane A and Lane D subagents mid-implementation.; solution: `resolved`

## Added tests

- `tests/fixtures/contracts/v181/ets_result.json`

## New rules

- `check-accepted-adrs-before-starting`: line experience occurrence(s)=1
- `fixture-numbers-must-be-arithmetically-coherent`: line experience occurrence(s)=1
- `mirror-existing-index-vocabulary`: line experience occurrence(s)=1
- `packet-parsers-reject-unknown-fields`: line experience occurrence(s)=1
- `preserve-wip-on-runner-interruption`: line experience occurrence(s)=1

## Future guidance

- Before starting a version, grep docs/superpowers/specs for accepted ADRs and start each devline from a frozen Context Pack; the discipline surfaces binding constraints the memory index does not.
- Every packet from_dict must reject unknown fields symmetrically; a permissive parser turns a field vanishing on round-trip into an invisible defect.
- Hand-authored numeric fixtures must be checked for internal arithmetic identity between AIC, BIC, log-likelihood and the parameter count before they become a shared lock.
- On a runner or session interruption, commit the interrupted lane's work in progress immediately so no work is lost and the lane can resume from a clean commit rather than restart.
- When adding a model that shares data with an existing pack, mirror the existing pack's index and sample vocabulary in the Contract Sprint, or the two models cannot be compared on one series.

## Event index

- #1: `ea15de88-5096-4a63-99bf-9d25a8cb7f78` | 2026-07-22T23:38:09.913Z | STATE_CHANGE/line_started | incident=`74de4ec2-3586-41ee-9de1-99f1c87dd275` | lesson_key=`frozen-context-before-start` | event_sha256=`e0bb839e430849d504f79919483a2b20e18717a6b3c16897b872e1e0384f3ae7`
- #2: `49d8744c-3653-5f84-84dd-f7d6c64e0532` | 2026-07-22T21:00:00.000Z | WASTE/serial_work_ignored_parallel_protocol | incident=`99fcb157-cd27-56aa-8c3a-32c86a02853e` | lesson_key=`check-accepted-adrs-before-starting` | event_sha256=`7efeb78c905a0fd4b157100e5e6a6bd586c52db7e4fe635437c5405f610d9a87`
- #3: `11cb539d-f90f-5fbe-accc-500d7b6f761a` | 2026-07-22T22:00:00.000Z | GAP/contract_missing_time_index_semantics | incident=`c817b1d5-7a1d-5d1e-82bc-79f224e883e2` | lesson_key=`mirror-existing-index-vocabulary` | event_sha256=`19745b5394d7e2f4e5fbd326d41a7871a6b0f8e93cc32e2cd72003405f699496`
- #4: `b3426cb1-7a71-521c-baa8-e4aa903c0c14` | 2026-07-22T23:00:00.000Z | FAILURE/fixture_information_criteria_incoherent | incident=`1722a8bd-d335-58e7-9a59-72a5c1c52b82` | lesson_key=`fixture-numbers-must-be-arithmetically-coherent` | event_sha256=`6ff9f9100d0de9fa5614e82c8844318f33c2fd2d64e2b56a7f1e3b9f9867956c`
- #5: `811c0ee9-0a81-5cda-857e-f1a987bc0dbb` | 2026-07-22T24:00:00.000Z | FAILURE/contract_drops_unknown_fields | incident=`913272f7-08d5-5871-ad3b-6c9a289dd6b9` | lesson_key=`packet-parsers-reject-unknown-fields` | event_sha256=`2d153cad15cfea4cd8880c70726e6099d9f84c91bf394f099315d43700e310f4`
- #6: `d0ee8b7e-6c3c-5079-952e-3d32513dbbd8` | 2026-07-22T23:55:00.000Z | ERROR/session_limit_interrupted_lanes | incident=`0ebd4926-e4ca-5dae-bc3a-421532ad926f` | lesson_key=`preserve-wip-on-runner-interruption` | event_sha256=`561164d9ebddd2e528cd2238aaab255ffa8b2e1913dcb09f7daf95d60a1a39d1`
