# Retrospective — v1-8-9-p1-survey-formal-closeout-remediation

## Goal

# Workbench v1.8.9 P1 Survey formal closeout remediation objective  ## Objective  Repair only the formal evidence-chain and closeout record for the Survey line. Do not modify product code, tests, the prior Survey line's events, retrospective, Context Pack, manifest, or anchor. The prior line \`v1-8-9-p1-survey-extension\` is historical evidence only; its append-only history is not repairable because a read-only probe found 63 STATE_CHANGE events with 24 state-chain mismatches.  The remediation line starts from the exact product baseline \`319249e6541d202345f2acb63484cf90c7dc3153\` and records a clean, CLI-managed formal chain for closeout. The formal terminal state means that this evidence chain was recorded, verified, and retrospectively generated; it is not a new claim that the product was implemented by this line or that the release is ready.  ## Historical product evidence boundary  An independent review supplied for this closeout accepted the Survey product implementation: focused 105 passed plus 20 targeted probes; Agent/diagnostic tamper 69/24; and the projection seam passed. This line may record those facts as supplied historical evidence, but it must not rerun or alter product tests and must not turn them into release evidence. The only known non-compliance being remediated here is the old formal STATE_CHANGE semantic chain.  ## Formal evidence requirements  - Use only \`scripts/devline_control.py start\`, \`append\`, \`verify\`, and   \`retrospective\` for the new line's formal records. - Record the old line's 24-mismatch result as a formal GAP/diagnostic, with the   old line explicitly retained as historical evidence and left untouched. - Record the supplied independent review and the local formal verification as   bounded evidence; never invent product test results, browser observations,   provider calls, oracle comparisons, full-gate results, or release status. - Every new STATE_CHANGE must continue from the immediately preceding STATE_CHANGE   \`state_to\`; the new line must not repeat the old line's broken semantics.  ## Scope and protected boundaries  This line changes only this objective file and the CLI-generated formal records for this new line. Product source, tests, frontend, release scripts, and every file under the historical line \`.agent/devlines/v1-8-9-p1-survey-extension/\` are protected and must remain unchanged.  Browser acceptance, provider evidence, external Survey oracle comparison, the full gate, release/merge/tag, and any external admitted-consumer acceptance remain \`NOT VERIFIED\`.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/7 (28.6%; 28.6 per 100 events)
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

- None recorded.

## All errors

- None recorded.

## All gaps

- #2 2026-08-19T23:33:00.000Z `legacy_state_chain_noncompliance`; cause_status: `known`; cause: The historical Survey line has 63 STATE_CHANGE events with 24 state-chain mismatches, so its append-only semantic chain cannot be repaired in place without rewriting history.; resolution: `accepted`; lesson: When an append-only state chain is historically inconsistent, preserve it as evidence and create a clean CLI-managed remediation chain.
- #5 2026-08-19T23:33:40.000Z `external_acceptance_not_verified`; cause_status: `external`; cause: This formal remediation line does not execute or inherit browser acceptance, provider evidence, external Survey oracle comparison, the full gate, or release integration acceptance.; resolution: `accepted`; lesson: Keep formal evidence-chain completion separate from browser, provider, oracle, full-gate, and release acceptance.

## All waste

- None recorded.

## Root causes and solutions

- `external-boundaries-not-verified`: occurrences=1; cause_status: `external`; root cause: This formal remediation line does not execute or inherit browser acceptance, provider evidence, external Survey oracle comparison, the full gate, or release integration acceptance.; solution: `accepted`
- `formal-state-chain-remediation`: occurrences=1; cause_status: `known`; root cause: The historical Survey line has 63 STATE_CHANGE events with 24 state-chain mismatches, so its append-only semantic chain cannot be repaired in place without rewriting history.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `external-boundaries-not-verified`: line experience occurrence(s)=1
- `formal-state-chain-remediation`: line experience occurrence(s)=1

## Future guidance

- Keep formal evidence-chain completion separate from browser, provider, oracle, full-gate, and release acceptance.
- Keep independently reviewed product evidence separate from formal closeout and unperformed external acceptance.
- When an append-only state chain is historically inconsistent, preserve it as evidence and create a clean CLI-managed remediation chain.

## Event index

- #1: `dff2dec7-2034-48a3-a365-301abe564906` | 2026-08-19T23:32:06.337Z | STATE_CHANGE/line_started | incident=`bb583974-ff1f-474f-8d98-c726a8074c97` | lesson_key=`frozen-context-before-start` | event_sha256=`53b18b84d767bff9054b591f5d78e41f0d35911aadbd0ee84193115bf48edbf9`
- #2: `11111111-1111-4111-8111-111111111111` | 2026-08-19T23:33:00.000Z | GAP/legacy_state_chain_noncompliance | incident=`22222222-2222-4222-8222-222222222222` | lesson_key=`formal-state-chain-remediation` | event_sha256=`da71ab8801fe3b50e5339e9abc65743049724b1cfb447b42ebe15f733c573107`
- #3: `33333333-3333-4333-8333-333333333333` | 2026-08-19T23:33:10.000Z | REVIEW/independent_product_review_bounded | incident=`44444444-4444-4444-8444-444444444444` | lesson_key=`bounded-product-review-evidence` | event_sha256=`c54b1c89dc8c8dc4c34322a9917e886c577bf759fdb365685006bd88e3a28a21`
- #4: `55555555-5555-4555-8555-555555555555` | 2026-08-19T23:33:20.000Z | STATE_CHANGE/closeout_started | incident=`66666666-6666-4666-8666-666666666666` | lesson_key=`formal-state-chain-remediation` | event_sha256=`aab3a2ec7f1c678d9e8d454c95026d24fee3f660dcce73ed98db1f8d7fee0b74`
- #5: `77777777-7777-4777-8777-777777777777` | 2026-08-19T23:33:40.000Z | GAP/external_acceptance_not_verified | incident=`88888888-8888-4888-8888-888888888888` | lesson_key=`external-boundaries-not-verified` | event_sha256=`fd80daedb206508961bd85195f6d91df790d30e59a25b58c35e44513480b4720`
- #6: `99999999-9999-4999-8999-999999999999` | 2026-08-19T23:33:50.000Z | GATE/formal_closeout_verify_green | incident=`aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`formal-closeout-verification` | event_sha256=`539ef323f576f741aa84f2ba1f338d9585d87192959cfba3048d0b336bcc392a`
- #7: `bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb` | 2026-08-19T23:34:00.000Z | STATE_CHANGE/formal_closeout_completed | incident=`cccccccc-cccc-4ccc-8ccc-cccccccccccc` | lesson_key=`formal-closeout-verification` | event_sha256=`e32ab4be287346f8dedd58bfbea5b23ae24a672bf1c74b540cafbc9f8213c733`
