# Retrospective — v1-8-9-candidate-acceptance-hardening

## Goal

# Workbench v1.8.9 Candidate Acceptance Hardening Objective  ## Objective  Finish the candidate-bound acceptance boundary without changing product behavior: derive catalog and consumer coverage inside the candidate being evaluated, reject dirty or mutated candidates, keep sidecar evidence outside the candidate, and keep deterministic, provider, browser, and release claims separate.  ## Scope  This line owns only the acceptance QA module, its command-line runner, the focused acceptance tests, and this line's work order. It must not change statistical estimators, Agent/Notebook/Report product behavior, provider authority, or release state.  ## Required behavior  - Candidate SHA, source roots, trusted interpreter, and ignored dependency   policy are checked before any product-path command. - Catalog, coverage, and acceptance matrix are discovered from the candidate   interpreter/PYTHONPATH, never from the evaluator checkout. - A missing projection remains a BLOCKED row; it is not removed from the   denominator. - Deterministic mode never calls a provider. Provider mode never falls back to   deterministic success and remains NOT_VERIFIED without an authorized   adapter. - Candidate source state is checked after commands; generated caches are not   accepted as clean source state. - Sidecar output is write-once and outside the candidate worktree.  ## Verification boundary  Focused acceptance tests, candidate-bound deterministic evaluation, provider non-fallback probe, compileall and diff check only. Browser, external provider, cross-process, full-gate, merge, tag, release and deployment remain separate.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/6 (50.0%; 50.0 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=2; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #2 2026-08-21T03:34:43.931Z `runner_node_preflight_bug`; cause_status: `known`; cause: The first candidate-bound acceptance attempt called is_file on os.stat_result while checking the trusted Node executable, so the runner crashed before the frontend product-path command and before writing a manifest.; resolution: `resolved`; lesson: Acceptance infrastructure needs its own executable preflight tests and must turn infrastructure failures into typed blocked results rather than uncaught tracebacks.
- #3 2026-08-21T03:35:01.970Z `evaluator_catalog_not_candidate_bound`; cause_status: `known`; cause: The first successful deterministic runner invocation derived the catalog and coverage matrix from the evaluator checkout before executing the candidate tests; the evaluator had eight providers and twenty rows while the exact candidate had seven providers and fifteen rows.; resolution: `resolved`; lesson: Candidate-bound evidence must bind not only test commands and SHA but also every denominator and digest source to the candidate being evaluated.
- #4 2026-08-21T03:35:24.415Z `historical_formal_log_append_blocked`; cause_status: `known`; cause: Appending the runner failure to the historical v1-8-9-foundation-integration line was rejected by the formal CLI because that existing events.jsonl contains non-monotonic historical timestamps.; resolution: `accepted`; lesson: A formal event stream must be timestamp-valid before later waves depend on it; preserve an invalid historical stream and start a narrow successor line instead of rewriting evidence.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `candidate-bound-denominator-source`: occurrences=1; cause_status: `known`; root cause: The first successful deterministic runner invocation derived the catalog and coverage matrix from the evaluator checkout before executing the candidate tests; the evaluator had eight providers and twenty rows while the exact candidate had seven providers and fifteen rows.; solution: `resolved`
- `candidate-runner-preflight-failure-is-blocked`: occurrences=1; cause_status: `known`; root cause: The first candidate-bound acceptance attempt called is_file on os.stat_result while checking the trusted Node executable, so the runner crashed before the frontend product-path command and before writing a manifest.; solution: `resolved`
- `invalid-historical-fms-log-requires-successor-line`: occurrences=1; cause_status: `known`; root cause: Appending the runner failure to the historical v1-8-9-foundation-integration line was rejected by the formal CLI because that existing events.jsonl contains non-monotonic historical timestamps.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `candidate-bound-denominator-source`: line experience occurrence(s)=1
- `candidate-runner-preflight-failure-is-blocked`: line experience occurrence(s)=1
- `invalid-historical-fms-log-requires-successor-line`: line experience occurrence(s)=1

## Future guidance

- A formal event stream must be timestamp-valid before later waves depend on it; preserve an invalid historical stream and start a narrow successor line instead of rewriting evidence.
- Acceptance infrastructure needs its own executable preflight tests and must turn infrastructure failures into typed blocked results rather than uncaught tracebacks.
- Candidate-bound evidence must bind not only test commands and SHA but also every denominator and digest source to the candidate being evaluated.

## Event index

- #1: `89d1d7b1-0a94-43ad-932d-f9d830088126` | 2026-08-21T03:34:20.098Z | STATE_CHANGE/line_started | incident=`843139e2-2ec3-47e5-a13b-278634593954` | lesson_key=`frozen-context-before-start` | event_sha256=`213ca520332fae34fefeb11cc91ec3327655fec7285bcf5591786f1e372ff2e1`
- #2: `f0c4de3a-4c1c-4f4c-a6f9-7bbf9f5bb9e1` | 2026-08-21T03:34:43.931Z | ERROR/runner_node_preflight_bug | incident=`f0c4de3a-4c1c-4f4c-a6f9-7bbf9f5bb9e1` | lesson_key=`candidate-runner-preflight-failure-is-blocked` | event_sha256=`d1d32f5f490fd292b260fc3a5f8f31179d2d68c7bb36885164b59de7e87e0d7c`
- #3: `b7a2e5d1-83f2-4e1d-a0e9-94a6a8d913ef` | 2026-08-21T03:35:01.970Z | ERROR/evaluator_catalog_not_candidate_bound | incident=`b7a2e5d1-83f2-4e1d-a0e9-94a6a8d913ef` | lesson_key=`candidate-bound-denominator-source` | event_sha256=`e49aa57ff5cccfb946a08e5355d81a87eb2dbdf3c65a1d361dd57f3b5ad9759d`
- #4: `8b6f3e52-8bb7-49d5-b95a-7dcf6e85d4c1` | 2026-08-21T03:35:24.415Z | ERROR/historical_formal_log_append_blocked | incident=`8b6f3e52-8bb7-49d5-b95a-7dcf6e85d4c1` | lesson_key=`invalid-historical-fms-log-requires-successor-line` | event_sha256=`b75d82420f28e69fd3731155f6f6d8c8e403c6a32b232b84dfc54a54e818afef`
- #5: `c4b8e1f9-2f3e-4a66-9a52-8a2d8db6c4f0` | 2026-08-21T03:36:22.169Z | GATE/candidate_bound_deterministic_acceptance_passed | incident=`c4b8e1f9-2f3e-4a66-9a52-8a2d8db6c4f0` | lesson_key=`candidate-bound-acceptance-denominator` | event_sha256=`77a5e881367c75ebde4d4e5144f744ea662446e417f4d001b7224c99179ecff0`
- #6: `d7e1a93b-1f4a-4c52-bb32-6a4b4e96f8d2` | 2026-08-21T03:36:51.253Z | STATE_CHANGE/line_completed | incident=`d7e1a93b-1f4a-4c52-bb32-6a4b4e96f8d2` | lesson_key=`scoped-acceptance-hardening-closeout` | event_sha256=`90d35a5768640befed2f2d4dfbdf16247570a8395adf94a2a40b1b7b8680d786`
