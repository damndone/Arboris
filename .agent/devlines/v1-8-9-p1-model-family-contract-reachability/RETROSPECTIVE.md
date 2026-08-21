# Retrospective — v1-8-9-p1-model-family-contract-reachability

## Goal

# Workbench v1.8.9 P1 Model Family Contract Reachability  ## Objective  Align model-family result tests with the current typed result/evidence packet contracts and restore any demonstrated production reachability defect. Every supported family must either produce its declared typed packet through the real run/HTTP path or fail with an explicit typed unavailable/degraded reason; no test may accept an unbound legacy result or silently discard a binding.  ## Scope  - \`tests/test_model_families_v186.py\` - \`tests/models/\`  If a production defect is demonstrated, stop and request an explicit formal rescope before editing production files.  ## Acceptance  - Focused model-family tests pass for ordinal, multinomial, survival, and   quantile paths, including packet keys and HTTP reachability. - Result bindings are admitted through the typed contract and do not add   undeclared fields to exact envelopes. - Compile, diff check, formal verify, and retrospective pass.  ## Non-goals  Do not add model families, loosen exact-key validation, or hide provider/model failures behind a generic completed status.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/7 (28.6%; 28.6 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=259989 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T07:52:20.902Z `stale_family_packet_assertion`; cause_status: `known`; cause: Family result assertions passed the persisted envelope with the cross-cutting result binding into exact packet contracts.; resolution: `open`; lesson: Validate the exact family packet after separating its declared cross-cutting result binding.
- #3 2026-08-21T07:52:21.018Z `stale_http_compat_projection`; cause_status: `known`; cause: The HTTP assertion searched the intentionally empty non-authoritative model_results compatibility field instead of the indexed model-result artifact download.; resolution: `open`; lesson: Prove HTTP model reachability through the server-indexed artifact route and keep compatibility projections fail-closed.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `http-typed-artifact-reachability`: occurrences=1; cause_status: `known`; root cause: The HTTP assertion searched the intentionally empty non-authoritative model_results compatibility field instead of the indexed model-result artifact download.; solution: `open`
- `typed-packet-binding-separation`: occurrences=1; cause_status: `known`; root cause: Family result assertions passed the persisted envelope with the cross-cutting result binding into exact packet contracts.; solution: `open`

## Added tests

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_model_families_v186.py tests/models`
- `tests/test_model_families_v186.py`
- `tests/test_model_families_v186.py:472`
- `tests/test_model_families_v186.py:83,142,326`

## New rules

- `http-typed-artifact-reachability`: line experience occurrence(s)=1
- `typed-packet-binding-separation`: line experience occurrence(s)=1

## Future guidance

- Prove HTTP model reachability through the server-indexed artifact route and keep compatibility projections fail-closed.
- Validate the exact family packet after separating its declared cross-cutting result binding.

## Event index

- #1: `a9f581f8-5e1a-4e61-82b3-94e8711338ce` | 2026-08-21T07:43:16.835Z | STATE_CHANGE/line_started | incident=`b33a4ff7-a8de-4d1f-a9b7-51925182c4ea` | lesson_key=`frozen-context-before-start` | event_sha256=`96fc07dd3363117d0e2853b7239e3b54735efd41683dd89941af2df28b0bbe93`
- #2: `90840dd8-3e76-49ae-8eb4-c9424ed4c5ad` | 2026-08-21T07:52:20.902Z | FAILURE/stale_family_packet_assertion | incident=`d7f12e3f-c5e7-44a4-8be3-b97ae6b3eb5a` | lesson_key=`typed-packet-binding-separation` | event_sha256=`a28517057ebfd8483ff5766ef8062a7479894353a249b8c5668a281ec8e911e5`
- #3: `e3c225f8-0282-4f21-8ad4-4071d4e83e6d` | 2026-08-21T07:52:21.018Z | FAILURE/stale_http_compat_projection | incident=`6c9b5a3f-09cf-4af1-9fef-f9a21a7ea6bc` | lesson_key=`http-typed-artifact-reachability` | event_sha256=`275d5ffe1d769d393392c401823705451104765164b8f08e9221b7b831c4d2b7`
- #4: `e175c70f-1456-4aa6-b64c-c4ae49e8acf9` | 2026-08-21T07:56:40.890Z | REVIEW/packet_assertion_migrated | incident=`d7f12e3f-c5e7-44a4-8be3-b97ae6b3eb5a` | lesson_key=`typed-packet-binding-separation` | event_sha256=`82db0cf24962d6dbbf1d5c93e11770ab26a6db0ad8d83c2f2c2b721ade066fc1`
- #5: `e694e4bd-1eac-4cf1-945a-0894408656ec` | 2026-08-21T07:56:41.008Z | REVIEW/http_artifact_path_migrated | incident=`6c9b5a3f-09cf-4af1-9fef-f9a21a7ea6bc` | lesson_key=`http-typed-artifact-reachability` | event_sha256=`c861c7ac0d002d0c9073f353049abb9d0f6063512a7b5607e0555c3542b1660a`
- #6: `ed9b4e9b-83e3-4c9e-a5a1-8501d34812b5` | 2026-08-21T07:56:41.129Z | GATE/scoped_suite_passed | incident=`5e28e6e5-893e-42bb-982d-e3115bfc89e8` | lesson_key=`scoped-model-family-gate` | event_sha256=`c2e71be40b0912b935e31b79653562303b828b5c4372203e890a1f317af66ccd`
- #7: `4de1a7a2-9dd2-4c2e-98b6-229e7a4d4b75` | 2026-08-21T07:56:48.720Z | STATE_CHANGE/line_completed | incident=`b4b116a7-38c0-4e3b-875c-43ac3eb6a125` | lesson_key=`formal-line-closeout` | event_sha256=`9be5c3f90f1f231ee48913387ddec2816575b3ea1b79e050c974d6ccf72ecc2c`
