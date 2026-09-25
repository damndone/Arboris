# Retrospective — v1-8-9-ui-shell-restoration

## Goal

# v1.8.9 Notebook and Graph Agent UI shell restoration  ## Objective  Restore the mature v1.8.8 Notebook and Graph Agent interaction quality while keeping the v1.8.9 local-first cutover as the only planning, confirmation, execution, and evidence path.  The repaired surfaces must provide a readable conversation/workspace shell, visible planning progress, structured plan preview, clarification and confirmation states, result/evidence presentation, keyboard-capable composition, and reliable Graph Agent tab reachability. They must not render raw JSON as the primary UI or regress to the retired Notebook/Agent execution APIs.  ## Boundaries  - Preserve the existing dirty v1.8.9 candidate and unrelated user work; no reset, checkout, delete, or broad cleanup. - Frontend-only product change unless a browser probe proves a backend defect. - Reuse v1.8.8 presentation patterns and existing CSS/components where safe; do not restore \`NotebookRouteView\`, \`AgentSurfaceProvider\`, legacy session/option execution, or implicit fallback. - \`cutoverApi\` remains the only natural-language compile/confirm/execute transport for both Agent and Notebook. - Server-owned identity, confirmation, evidence references, and fail-closed errors remain authoritative. - Do not add a visual companion, a second planner, a second capability table, or unnecessary folders. - Keep the existing backend, Vite server, and in-app browser tab running throughout acceptance.  ## Required verification  - TDD: focused component tests fail on the regressed shell before production edits and pass after restoration. - Agent tab is reachable from the Graph bottom panel and the compact composer expands it. - Notebook and Agent previews are structured and readable; raw JSON is not the primary presentation. - Both surfaces preserve compile -> preview/clarify -> server confirm -> execute -> evidence behavior through \`cutoverApi\` only. - Frontend typecheck, focused integration tests, retired-route static scan, and \`git diff --check\` pass. - In-app browser acceptance covers Graph Agent and Notebook visible/interactive states on the running local candidate.  ## Known gates  - Browser data/setup errors such as a missing notebook must be represented as recoverable product states, not a blank or disabled shell. - Real external provider quality is outside this UI restoration; deterministic/local cutover behavior is sufficient. - Linux, other macOS hosts, release merge/tag, and deployment are not part of this line.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/14 (21.4%; 21.4 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #3 2026-08-23T17:52:08.680Z `agent_ui_tdd_red`; cause_status: `known`; cause: The restored Agent acceptance tests failed against the minimal cutover shell, including seven UI and safety behaviors plus the clarification recompile field-lock probe.; resolution: `resolved`; lesson: Lock browser-visible shell, authority, scope, retry, and concurrency behavior with failing tests before adapting the safe cutover transport.
- #10 2026-08-23T18:43:47.829Z `cutover_contract_tdd_red`; cause_status: `known`; cause: Adversarial tests were added for malformed clarifications, conflicting executable identity, incomplete evidence, unsafe retry classification, uncertain confirmation, stale responses, and duplicate confirmation.; resolution: `resolved`; lesson: Explicit adversarial contract and concurrency tests are required before a cutover UI can be called safe.

## All errors

- None recorded.

## All gaps

- #2 2026-08-23T17:16:45.275Z `cutover_ui_shell_regression`; cause_status: `known`; cause: The v1.8.9 cutover replaced the mature v1.8.8 Notebook and Agent presentation shells with minimal inline components instead of adapting the existing interaction design to the new compiler boundary.; resolution: `open`; lesson: A security cutover must replace transport and authority seams without discarding the proven presentation shell; browser-visible parity needs its own tests before deleting the old mount.

## All waste

- None recorded.

## Root causes and solutions

- `agent-cutover-ui-tdd-red`: occurrences=1; cause_status: `known`; root cause: The restored Agent acceptance tests failed against the minimal cutover shell, including seven UI and safety behaviors plus the clarification recompile field-lock probe.; solution: `resolved`
- `cutover-adversarial-tests-before-pass`: occurrences=1; cause_status: `known`; root cause: Adversarial tests were added for malformed clarifications, conflicting executable identity, incomplete evidence, unsafe retry classification, uncertain confirmation, stale responses, and duplicate confirmation.; solution: `resolved`
- `cutover-preserve-ui-shell`: occurrences=1; cause_status: `known`; root cause: The v1.8.9 cutover replaced the mature v1.8.8 Notebook and Agent presentation shells with minimal inline components instead of adapting the existing interaction design to the new compiler boundary.; solution: `open`

## Added tests

- `frontend/src/cutoverApi.test.ts`
- `frontend/src/lineage/graph/NodeActionMenu.test.tsx`
- `frontend/src/workbench/agent/AgentCutoverPanel.test.tsx`

## New rules

- `agent-cutover-ui-tdd-red`: line experience occurrence(s)=1
- `cutover-adversarial-tests-before-pass`: line experience occurrence(s)=1
- `cutover-preserve-ui-shell`: line experience occurrence(s)=1

## Future guidance

- A security cutover must replace transport and authority seams without discarding the proven presentation shell; browser-visible parity needs its own tests before deleting the old mount.
- A visual restoration must be reviewed at the production mount and authority boundary, not only at the component snapshot boundary.
- Explicit adversarial contract and concurrency tests are required before a cutover UI can be called safe.
- Final acceptance needs independent review of both visible behavior and authority invariants after all fixes are present.
- Lock browser-visible shell, authority, scope, retry, and concurrency behavior with failing tests before adapting the safe cutover transport.

## Event index

- #1: `f42ac587-b743-41cc-99fa-a208cd04cf07` | 2026-08-23T17:11:07.389Z | STATE_CHANGE/line_started | incident=`116a2a55-5801-4c1e-bc02-6dc73c4e4b1c` | lesson_key=`frozen-context-before-start` | event_sha256=`cf2aa7f3c3c62a308c67cf9685e608741924d31de7b25af0c633151740d3db54`
- #2: `4351fc37-f659-47f3-896c-bd5d31ca19db` | 2026-08-23T17:16:45.275Z | GAP/cutover_ui_shell_regression | incident=`cf2249f5-01f7-4ade-8b53-40e883776853` | lesson_key=`cutover-preserve-ui-shell` | event_sha256=`dd9e506282f3498c2a491675be7beb701a020c63ee885e17f1e20c7349f73127`
- #3: `4b70e519-eac0-4d9d-bdb5-256e159d3812` | 2026-08-23T17:52:08.680Z | FAILURE/agent_ui_tdd_red | incident=`5d13a4b4-a174-44ed-a15c-0b1953c458f7` | lesson_key=`agent-cutover-ui-tdd-red` | event_sha256=`aa824c173bbd07a660d486ec992bfc75eb26784daee8f5a66b5e30a088b9c015`
- #4: `4bf8b880-55e0-4a7b-8c5f-bcd1b33a1d73` | 2026-08-23T17:52:24.563Z | GATE/agent_ui_focused_green | incident=`5d13a4b4-a174-44ed-a15c-0b1953c458f7` | lesson_key=`agent-cutover-ui-focused-green` | event_sha256=`29345316b4b53dfc5f2d2f7a7c8da9c172c592b88b71526bfc05ce47813abb60`
- #5: `bf2cdcbc-c6a5-4c41-91ed-82e7065bd4ec` | 2026-08-23T17:59:07.350Z | STATE_CHANGE/context_rescope_required | incident=`6de6ba45-9394-46e6-9d39-2bc3b830fc60` | lesson_key=`context-pack-rescope` | event_sha256=`dde470e663b97c1663defe47527f10fb7be00c1572eb446e4425535ade94871c`
- #6: `a3fe37f1-890e-40ad-8c48-a453981de50e` | 2026-08-23T17:59:07.356Z | STATE_CHANGE/context_rescoped | incident=`5cad3db4-d76d-47d0-bb22-3fb15955a33a` | lesson_key=`context-pack-rescope` | event_sha256=`f3e33aedb7a2a958dd022140c9b467a0ac194f66639918400642e79f271d377d`
- #7: `1846e46e-24b7-40a0-a08b-1d3977444139` | 2026-08-23T18:26:34.386Z | STATE_CHANGE/context_rescope_required | incident=`4c68c469-9a1a-4dba-af3b-b0778f127160` | lesson_key=`context-pack-rescope` | event_sha256=`b0f610a7d729d18cf8412becfd6adaa288de92217b45fb075116ba2b31a3b3de`
- #8: `2d7e3d5d-9d9e-45f9-bbba-548ecedc5e5d` | 2026-08-23T18:26:34.393Z | STATE_CHANGE/context_rescoped | incident=`07c0ff70-fcb4-40d9-ac64-b18bc9d25256` | lesson_key=`context-pack-rescope` | event_sha256=`11e06ce192fcdfbffe627e9d0d066ba6ad52148f803285ad2369a926f805a10f`
- #9: `30a0f328-adba-493b-b302-66953cd7f4aa` | 2026-08-23T18:43:47.685Z | REVIEW/independent_review_changes_required | incident=`f2fa8856-43f6-4af7-ae0d-726f508a457f` | lesson_key=`review-production-mount-and-authority` | event_sha256=`294bfe5a5f5ec86d99d2e60e257687d6dbe867b06044cc446bf08f7694df7eea`
- #10: `fcbd4783-5004-40e8-94c8-4c3ff925d731` | 2026-08-23T18:43:47.829Z | FAILURE/cutover_contract_tdd_red | incident=`f2fa8856-43f6-4af7-ae0d-726f508a457f` | lesson_key=`cutover-adversarial-tests-before-pass` | event_sha256=`e7bc03ccc0ebaa2d5c7ca668ef86d608795d033bf503681e02030048e9f9554e`
- #11: `6b97a8f5-333d-4728-9b85-ac8e1f925a8d` | 2026-08-23T18:43:47.959Z | REVIEW/independent_review_pass | incident=`f2fa8856-43f6-4af7-ae0d-726f508a457f` | lesson_key=`independent-ui-and-authority-review` | event_sha256=`0849cbcd0244afc46948eb268a63147cdbe43bf5a878305345d6d01ca250e91a`
- #12: `ddacbb59-3adc-461e-ace2-021b6b67c53e` | 2026-08-23T18:43:48.082Z | GATE/browser_ui_acceptance | incident=`cf2249f5-01f7-4ade-8b53-40e883776853` | lesson_key=`browser-accept-ui-with-live-backend` | event_sha256=`f9b7f81f6626c1b86ecce643bc44c04a6d04f84e4d99ffad4c4bd6f217102763`
- #13: `0bee9ffb-ce30-48b1-9e15-93805d0f7392` | 2026-08-23T18:43:48.207Z | GATE/ui_shell_full_gate | incident=`cf2249f5-01f7-4ade-8b53-40e883776853` | lesson_key=`ui-shell-full-regression-gate` | event_sha256=`89b5bbbdf1b0a9da20db200271ff91f162a976818a61992b1a2d60fcd3836f3c`
- #14: `bcc3e30d-9349-4bda-83e7-354c7a4aa8b3` | 2026-08-23T18:43:48.338Z | STATE_CHANGE/line_completed | incident=`cf2249f5-01f7-4ade-8b53-40e883776853` | lesson_key=`preserve-shell-replace-transport` | event_sha256=`486743bb40fbc0c7b0ad1e40a40a47cd1cb053181bf2a91ea53d61e93b118c3f`
