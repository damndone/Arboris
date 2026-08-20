# Retrospective — v1-8-9-p1-classification-production-remediation-18

## Goal

# Workbench v1.8.9 P1 classification production remediation-18 objective  - Exact baseline: \`df8f7ce69ddbd66cb8fbab683456d73617e298ca\`. - Formal line: \`v1-8-9-p1-classification-production-remediation-18\`. - Target worktree: \`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p1-classification-production\`. - Scope: close the independent quality-review P2 in the Workbench-owned   generic artifact download Range boundary without changing other security   boundaries, the root checkout, or any other worktree.  ## Required outcome  1. A present but empty \`Range\` header must fail explicitly with the existing    malformed-range \`400\`; it must never silently downgrade to a full \`200\`    response. Other malformed present Range values retain the same explicit    \`400\` boundary. 2. A missing \`Range\` header must continue to return the normal full artifact    download with \`200\`, without \`Content-Range\`. 3. Preserve the Workbench-owned parser, strict range-set grammar, valid    satisfiability filtering, \`If-Range\`, compatibility headers, same-FD    bounded streaming, cleanup, and all existing artifact integrity/security    boundaries. Do not alter unrelated security seams. 4. Add direct parser and live HTTP regressions covering empty/present-invalid    versus missing Range headers, while retaining the existing range and stream    regressions.  ## Allowed paths  - \`backend/workbench/http/runs_routes.py\` - \`tests/test_v189_classification_production.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-18-objective.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-18-handoff.md\` - \`.agent/devlines/v1-8-9-p1-classification-production-remediation-18/**\` (only   through \`scripts/devline_control.py\`).  ## Protected boundaries  - The repository root checkout and every other worktree are out of scope. - No \`reset\`, \`checkout\`, deletion, or overwrite of existing user work. - Existing remediation-17 and earlier formal records, Context Packs,   retrospectives, and handoffs are immutable. - \`backend/workbench/repository/file_integrity.py\`, classification   list/index/consumer seams, central Agent/Notebook/Report consumers, and   unrelated artifact integrity/security boundaries are unchanged.  ## Verification contract  - TDD RED then GREEN for the direct parser and live HTTP Range regressions. - \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q -k 'range or stream or cleanup or mutation or symlink'\`. - Full \`tests/test_v189_classification_production.py\` and relevant   classification contract/production suites. - Direct parser/HTTP probes, \`compileall\`, and \`git diff --check\` against the   exact baseline. - Formal \`verify\` and CLI-generated \`retrospective\`, with \`unresolved=0\`.  ## Known gates  Inherited fixture/environment gates and central Agent/Notebook/Report, browser-visible acceptance, external provider, host/full gate, performance, release, merge, push, and tag verification remain \`NOT VERIFIED\` unless explicitly rerun and evidenced in this line.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/10 (10.0%; 10.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=290000 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/7 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T04:54:21.000Z `empty_range_red`; cause_status: `known`; cause: The artifact route used a truthiness check for the Range value, so a present empty header skipped the strict parser.; resolution: `open`; lesson: Treat Range header presence separately from Range header content before invoking the strict parser.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `range-header-presence`: occurrences=1; cause_status: `known`; root cause: The artifact route used a truthiness check for the Range value, so a present empty header skipped the strict parser.; solution: `open`

## Added tests

- `backend/workbench/http/runs_routes.py`
- `tests/predictive_research/test_classification_contracts_v189.py`
- `tests/test_v189_classification_production.py`

## New rules

- `range-header-presence`: line experience occurrence(s)=1

## Future guidance

- Treat Range header presence separately from Range header content before invoking the strict parser.

## Event index

- #1: `9f7fede5-9719-43cb-806a-7da873a2ce34` | 2026-08-20T04:53:28.993Z | STATE_CHANGE/line_started | incident=`58425454-a4cc-4b04-a197-34fe082f4868` | lesson_key=`frozen-context-before-start` | event_sha256=`f61d4e24bd6553e6d31b9a4f0cb895ff7dbb62d821960a8759d3c9b10f66be2d`
- #2: `f4d8bc3a-3b0c-4b7e-9d5f-7a5eb08ec0a4` | 2026-08-20T04:54:21.000Z | FAILURE/empty_range_red | incident=`0e3b4f21-b4d3-4f96-8b4c-5e3f0b4b8f25` | lesson_key=`range-header-presence` | event_sha256=`0e62ae55f9f46e2f508dda1bde5d99145cde8ce5e5eb68c6fc42b3e42bacb447`
- #3: `8d03b8f0-5a73-46ce-8ae2-e49638bca7c0` | 2026-08-20T04:55:21.000Z | GATE/focused_range_green | incident=`be5d72d6-09f7-48a3-9a5f-f1b43bda6b5b` | lesson_key=`range-header-presence` | event_sha256=`590aaca500eb2433e8a78cd6d524b297bcd7f3c3d168837e602d0e902336c9be`
- #4: `24c2a9fb-8e6e-4a7e-a0dc-36bb4d114a2b` | 2026-08-20T04:56:45.000Z | GATE/production_suite_green | incident=`bf6ea875-5b4f-4b85-a866-4a1aafafc1f7` | lesson_key=`classification-production-suite` | event_sha256=`4ed5750f4ff20886e7632119dfe6eab80bf646b8eb5af81b2926b1cdf5473f82`
- #5: `f8b30aa1-f9ba-45fe-a7ad-9a5c8db0b6dd` | 2026-08-20T04:56:45.000Z | GATE/classification_contracts_green | incident=`d2c72fd7-efb1-4a17-9d17-f9c67bd1c5d7` | lesson_key=`classification-contract-boundary` | event_sha256=`eafb25e0fb1f15e703af94555dba0744831240e9df003937d78062adcb384001`
- #6: `1feea0f4-7b1b-42b1-8ee4-3e1e0dc85f44` | 2026-08-20T04:56:45.000Z | GATE/compileall_green | incident=`68d4eef9-3e46-4a9d-a6e2-3d4a283cdfa2` | lesson_key=`classification-static-integrity` | event_sha256=`0dcfa0a94c49efa98bbcfa80034cf09d2512a24195c8bee3c56c75eca6bb3328`
- #7: `c37e7e01-0f9a-467b-9e94-96f0b49d34f3` | 2026-08-20T04:56:45.000Z | GATE/diff_check_green | incident=`d90173ef-e8c1-4444-8dfd-ae0a0ee55f7a` | lesson_key=`classification-static-integrity` | event_sha256=`3cad02fc2e625ff8bc811acb70be03e27c5f1f3eb403f67cf86078a851c46ca0`
- #8: `a1b4823e-7e73-4a70-bcb4-2cb9a0917c36` | 2026-08-20T04:58:02.000Z | STATE_CHANGE/remediation_18_completed | incident=`d4d3e46e-5ea8-432b-8b8f-9bc4f03d66ba` | lesson_key=`remediation-18-formal-closeout` | event_sha256=`6fdcb8bdf89274ad37bfaa7b84f8c3f28783febf72cf2a8972877e5485f07a65`
- #9: `c52ebeb8-4d2e-4ae3-97db-c4e8153ee6d4` | 2026-08-20T04:59:11.000Z | GATE/empty_range_red_resolved | incident=`0e3b4f21-b4d3-4f96-8b4c-5e3f0b4b8f25` | lesson_key=`range-header-presence` | event_sha256=`d70c8a1f99be13082777daf195f95e31c46a15796b088f30a658b54ddd72e54b`
- #10: `0b12e8d5-c8bd-4a34-948e-6e8dc4c6f5d1` | 2026-08-20T05:04:28.000Z | GATE/final_tip_green | incident=`f5c0a1ed-8fdd-4fe0-88a9-32d97df2a5d4` | lesson_key=`remediation-18-final-tip` | event_sha256=`e62f5aef500359e8c88abf04aa52b1fec83132cad86e62393ae4ae474e6efad4`
