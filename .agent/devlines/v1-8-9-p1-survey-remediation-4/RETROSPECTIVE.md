# Retrospective — v1-8-9-p1-survey-remediation-4

## Goal

# Workbench v1.8.9 P1 Survey remediation-4 objective  ## Objective  Repair the independent specification findings against the exact remediation-3 final tip \`945da48f91101aad99548cf273088a97ad19d163\` without changing the Survey statistical engine or any central consumer. The repair must close the low-level Agent/Notebook/Report projection boundaries and preserve the fail-closed typed evidence contract.  ## Required behavior  - P1-A: term keys and coefficient maps are admitted only when their source   values are bounded and valid. Empty terms, overlong terms, invalid nested   coefficient maps, and empty nested structures are omitted. A declared   invalid projection retains only bounded typed   \`projection_status=unavailable\` and \`unavailable_reason\`; it must not   synthesize \`None\`, \`[]\`, \`{}\`, or placeholder cells. - P1-B: every artifact numeric field uses finite, field-specific bounds and   ordering checks. \`p_value\` is in \`[0,1]\`, counts are bounded and   nonnegative, standard errors are positive, confidence intervals are finite   and ordered, and invalid values do not enter Agent, Notebook, Report, or   LLM context. Invalid declared fields fail closed with typed status/reason. - P1-C: P7 nested result projection is depth-bounded and cannot recurse without   a cap. A payload deeper than the cap becomes a bounded typed unavailable or   invalid result; it must not raise a bare \`RecursionError\` or leak nested raw   content. - Add pure and real Agent/Notebook/Report probes for all three findings,   including a deep payload probe and row-count/ordering edge cases. - Preserve Survey engine, ordinary and replicate weights, falsey declarations,   exposure, FPC, Survey Report visibility, Notebook receipt boundaries, and   existing foreign/admitted failure ownership. - Record the prior remediation-3 objective EOF/selector/digest audit and the   prior formal \`open\`/\`accepted\` versus resolved-incident contradictions by   CLI events or bounded audit references. Do not edit remediation-3 or older   events, objectives, Context Packs, manifests, or retrospectives.  ## Scope  Allowed product/test/document paths:  - \`backend/workbench/agent/context_tools.py\` - \`tests/test_agent_context_tools.py\` - \`tests/test_agent_reads_v187_results.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-4-objective.md\` - \`docs/superpowers/plans/2026-08-20-survey-remediation-4.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-4-handoff.md\`  Protected paths:  - \`.agent/devlines/v1-8-9-p1-survey-remediation-3\` - \`.agent/devlines/v1-8-9-p1-survey-remediation-2\` - \`backend/workbench/survey\` - \`backend/workbench/report_view_model.py\` - central integration, browser/provider/host, full-gate, release, merge, tag,   and push machinery  ## Baseline and dependencies  - Exact baseline: \`945da48f91101aad99548cf273088a97ad19d163\` - Previous product tip: \`6a2ebc2d49f998d017da670554141aeabf0270ff\` - Previous handoff:   \`docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-3-handoff.md\` - Dependency: \`v1-8-9-p1-survey-remediation-3\` - Historical documentation audit: the prior objective at the \`9328c3f3...\`   baseline has an EOF blank-line drift in the later tip; record and correct   only through this new exact-tip handoff, never by editing its old formal   evidence.  ## Tests and gates  - Pure P1-A/P1-B/P1-C probes in \`tests/test_agent_context_tools.py\`. - Real Agent/Notebook/Report probes in the two existing Agent test files. - \`tests/test_agent_context_tools.py\` and   \`tests/test_agent_reads_v187_results.py\`. - \`tests/test_report_view_model.py\` and selected   \`tests/test_reporting_exports.py\` projection tests. - Survey GLM/design/composition/limits/visibility/wiring regression suite. - Deep payload probes at and beyond the recursion depth cap. - \`PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests\`   and \`git diff --check\`. - Formal \`scripts/devline_control.py verify\` and \`retrospective\`.  Known gates remain \`NOT VERIFIED\`: foreign-owner/admitted fixture failures, central Notebook/Report cutover, browser acceptance, external provider/oracle evidence, host acceptance, full gate, release readiness, merge/tag/push.

## Final status

COMPLETED

## Metrics

- Failure frequency: 4/21 (19.0%; 19.0 per 100 events)
- Repeat rate: 0/4 (0.0%)
- Recurrence rate: 0/4 (0.0%)
- MTTR: median=4659000 ms (sample=4; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/10 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #5 2026-08-20T04:05:00.000Z `p1_projection_red`; cause_status: `known`; cause: The four remediation-4 RED probes fail against the baseline: invalid or empty coefficient terms cross low-level projections, artifact numeric fields accept out-of-range values and reversed intervals, and depth-1100 P7 nesting raises a bare RecursionError.; resolution: `open`; lesson: Keep adversarial projection probes red until every optional value is source-present, typed, bounded, and structurally safe.

## All errors

- None recorded.

## All gaps

- #3 2026-08-20T04:00:01.000Z `prior_objective_eof_selector_digest_audit`; cause_status: `known`; cause: The prior remediation-3 objective has a double-line-feed EOF; its content digest is unchanged between product tip 6a2ebc2d and final tip 945da48f. The prior handoff names the product tip and its own Context Pack digest but not the later formal final tip.; resolution: `accepted`; lesson: A handoff must distinguish implementation tip, formal final tip, Context Pack manifest, and handoff digest before closeout.
- #4 2026-08-20T04:00:02.000Z `prior_formal_resolution_contradiction_audit`; cause_status: `known`; cause: The protected remediation-3 event stream contains six incidents whose original FAILURE/GAP resolution is open or accepted while a later same-incident GATE records resolved. This line records the contradiction as historical audit evidence and leaves the prior stream untouched.; resolution: `accepted`; lesson: Resolve formal contradictions in a new append-only audit line rather than rewriting a terminal historical stream.
- #11 2026-08-20T05:20:02.000Z `foreign_context_suite_not_verified`; cause_status: `not_applicable`; cause: The full Agent context suite retains admitted server-owned artifact, diagnostic fixture, figure evidence, and lifecycle failures outside this line's owned P1 projection boundary.; resolution: `not_applicable`; lesson: Keep admitted foreign fixture failures separate from package-local projection ownership and release claims.

## All waste

- None recorded.

## Root causes and solutions

- `append-only-formal-contradiction-audit`: occurrences=1; cause_status: `known`; root cause: The protected remediation-3 event stream contains six incidents whose original FAILURE/GAP resolution is open or accepted while a later same-incident GATE records resolved. This line records the contradiction as historical audit evidence and leaves the prior stream untouched.; solution: `accepted`
- `exact-tip-selector-digest-audit`: occurrences=1; cause_status: `known`; root cause: The prior remediation-3 objective has a double-line-feed EOF; its content digest is unchanged between product tip 6a2ebc2d and final tip 945da48f. The prior handoff names the product tip and its own Context Pack digest but not the later formal final tip.; solution: `accepted`
- `foreign-owner-suite-boundary`: occurrences=1; cause_status: `not_applicable`; root cause: The full Agent context suite retains admitted server-owned artifact, diagnostic fixture, figure evidence, and lifecycle failures outside this line's owned P1 projection boundary.; solution: `not_applicable`
- `remediation-4-red-before-fix`: occurrences=1; cause_status: `known`; root cause: The four remediation-4 RED probes fail against the baseline: invalid or empty coefficient terms cross low-level projections, artifact numeric fields accept out-of-range values and reversed intervals, and depth-1100 P7 nesting raises a bare RecursionError.; solution: `open`

## Added tests

- `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-4-handoff.md`
- `remediation-4-owned-regression-command-set`
- `tests/test_agent_context_tools.py focused remediation-4 projection selector`
- `tests/test_agent_context_tools.py full suite`
- `tests/test_agent_context_tools.py full suite and remediation-4 handoff`
- `tests/test_agent_context_tools.py::remediation-4-red-probes`

## New rules

- `append-only-formal-contradiction-audit`: line experience occurrence(s)=1
- `exact-tip-selector-digest-audit`: line experience occurrence(s)=1
- `foreign-owner-suite-boundary`: line experience occurrence(s)=1
- `remediation-4-red-before-fix`: line experience occurrence(s)=1

## Future guidance

- A handoff must distinguish implementation tip, formal final tip, Context Pack manifest, and handoff digest before closeout.
- Keep admitted foreign fixture failures separate from package-local projection ownership and release claims.
- Keep adversarial projection probes red until every optional value is source-present, typed, bounded, and structurally safe.
- Resolve formal contradictions in a new append-only audit line rather than rewriting a terminal historical stream.
- Review every optional projection key for source presence, typed bounds, and structural depth before accepting a closed allowlist.

## Event index

- #1: `f2e3e8fb-5ba2-47a8-8063-f13c56182c0a` | 2026-08-20T04:00:11.749Z | STATE_CHANGE/line_started | incident=`4b028672-96c8-41c4-ab6b-9c6424625c5d` | lesson_key=`frozen-context-before-start` | event_sha256=`3e20feec0c3dcd95896ba757bc343358f1f507f2e08f203e525bd00ed9a883e8`
- #2: `a1111111-2222-4333-8444-555555555555` | 2026-08-20T04:00:00.000Z | REVIEW/independent_spec_not_compliant | incident=`b1111111-2222-4333-8444-555555555555` | lesson_key=`remediation-4-spec-review-boundaries` | event_sha256=`189e22545ee7fac31b29e30de295359cd3c304f8dbcfcb24b56d643b5f7df985`
- #3: `c1111111-2222-4333-8444-555555555555` | 2026-08-20T04:00:01.000Z | GAP/prior_objective_eof_selector_digest_audit | incident=`d1111111-2222-4333-8444-555555555555` | lesson_key=`exact-tip-selector-digest-audit` | event_sha256=`41fad37fd93e379bfa29ad98f392233cb66122f10673b26033ce90afc309d705`
- #4: `e1111111-2222-4333-8444-555555555555` | 2026-08-20T04:00:02.000Z | GAP/prior_formal_resolution_contradiction_audit | incident=`f1111111-2222-4333-8444-555555555555` | lesson_key=`append-only-formal-contradiction-audit` | event_sha256=`7708b694aa782ecce8c3ba585adfafea39db3c1739e248e9ae7af47bd60d98b1`
- #5: `a2222222-3333-4444-8555-666666666666` | 2026-08-20T04:05:00.000Z | FAILURE/p1_projection_red | incident=`a2222222-3333-4444-8555-666666666666` | lesson_key=`remediation-4-red-before-fix` | event_sha256=`03315c7133576fed1ee0e148ed1d00f8f72cd88552a5bd4557618fe9d0ed2811`
- #6: `b2222222-3333-4444-8555-666666666666` | 2026-08-20T04:05:01.000Z | STATE_CHANGE/red_probes_observed | incident=`c2222222-3333-4444-8555-666666666666` | lesson_key=`remediation-4-red-state-continuity` | event_sha256=`a034435532ba55c1ba7b35c892283bb90b7609e963bccd97fcda0e2022e3a191`
- #7: `11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:10:00.000Z | GATE/focused_projection_green | incident=`22222222-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`focused-projection-green` | event_sha256=`7a4babd34ba12177f298445114bfc353eb34786f06e4b1fe20072727c3c96145`
- #8: `33333333-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:10:01.000Z | STATE_CHANGE/focused_projection_green_state | incident=`44444444-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`remediation-4-green-state` | event_sha256=`7232afe569ac720e0b8f8a5e2332016f28498c74a527fa0428c7a2f124bc0acd`
- #9: `55555555-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:00.000Z | GATE/owned_regression_green | incident=`66666666-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`owned-regression-green` | event_sha256=`e8c1d473db4a874b01657f5127ed38370d8ba4c24d20a1d44f7b3d844ebb1fa6`
- #10: `77777777-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:01.000Z | STATE_CHANGE/owned_regression_green_state | incident=`88888888-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`regression-green-state` | event_sha256=`49a0b36f6b6febafbeff1a10f13342d2b0439ef54d6c66371055d5eba43f9bb4`
- #11: `99999999-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:02.000Z | GAP/foreign_context_suite_not_verified | incident=`aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`foreign-owner-suite-boundary` | event_sha256=`9ebae2218c5139568f6de7b11573010b0bc8c2d5b48936eb98691d553ed16a13`
- #12: `bbbbbbbb-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:03.000Z | STATE_CHANGE/owned_regression_green_state | incident=`cccccccc-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`regression-green-state` | event_sha256=`e4e7dfb35ad0fccc9d214fdf3b2ec3b38d6f598708e97b9649932d1ed79c8532`
- #13: `dddddddd-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:04.000Z | GATE/foreign_owner_boundary_recorded | incident=`aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`foreign-owner-suite-boundary` | event_sha256=`4ef44695f6bba91da23825be8a7e14891f7cf3146bd83f45e090de8966a22e3f`
- #14: `eeeeeeee-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:05.000Z | GATE/p1_projection_red_resolved | incident=`a2222222-3333-4444-8555-666666666666` | lesson_key=`p1-projection-red-resolved` | event_sha256=`8f52eac647db092085e14a4ee2e31193e962dd5ba9cec11418208d4b7ac8c311`
- #15: `ffffffff-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:06.000Z | GATE/central_release_boundary_recorded | incident=`12121212-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`central-release-boundary` | event_sha256=`daaae5f014665cef4147da85b573546bbd2119beefc0187f38714bbb59328d96`
- #16: `13131313-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:07.000Z | GATE/p1_projection_red_resolved | incident=`a2222222-3333-4444-8555-666666666666` | lesson_key=`p1-projection-red-resolved` | event_sha256=`3a03254bdf41711bdfffe4e47f5de4fd050ca393564ffccc5c1c3cb3db6edfae`
- #17: `15151515-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:08.000Z | STATE_CHANGE/formal_handoff_closed | incident=`16161616-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`exact-tip-handoff-closeout` | event_sha256=`ddd9b0f3490a7a5f3451ee6e11140b4a7c9410ff9e8cd3adc965ed50c488e8a9`
- #18: `17171717-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:09.000Z | GATE/p1_projection_red_resolution_confirmed | incident=`a2222222-3333-4444-8555-666666666666` | lesson_key=`p1-projection-red-resolved` | event_sha256=`741e92ff66990358d8828e399c81cb46c6a617bc2f5af47e1497bf44ba7c652f`
- #19: `18181818-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:10.000Z | GATE/prior_objective_audit_resolved | incident=`d1111111-2222-4333-8444-555555555555` | lesson_key=`exact-tip-selector-digest-audit` | event_sha256=`b5cc99f5937837a8d9d7451b098571086a3d201ec494240dcbff0a93f9074ce5`
- #20: `19191919-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:11.000Z | GATE/prior_contradiction_audit_resolved | incident=`f1111111-2222-4333-8444-555555555555` | lesson_key=`append-only-formal-contradiction-audit` | event_sha256=`6359d2268652b9c7ee1a5de45ddc44855d829e00efe7bab1a38ac25b2b9f9c26`
- #21: `20202020-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | 2026-08-20T05:20:12.000Z | GATE/foreign_context_boundary_resolved | incident=`aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | lesson_key=`foreign-owner-suite-boundary` | event_sha256=`8bbcb74e84d96e2e9d2fc1d433a363dcafdb2c14c2d616534a0f2b396eae6c1f`
