# Retrospective — v181-agent-surface-polish

## Goal

# v1.8.1 Agent Surface Polish and Global Scope Design  ## Objective  Improve the Workbench Agent surface to match the supplied Codex composer reference while preserving the existing typed proposal and fail-closed execution boundaries.  ## Scope  1. Restyle the graph Agent composer as a translucent rounded capsule with a    textarea-first layout, compact action controls, model selector, context    indicator, capability affordance, and circular send control. 2. Make context and capability details hover/focus driven: entering the    control opens the detail surface; leaving both trigger and surface closes    it; keyboard focus remains supported. 3. Render Agent Markdown tables and lightweight inline/block math without    exposing Markdown markers. The renderer must remain dependency-free and    route plain text through the existing cite-chip seam. 4. Clicking graph background clears node selection and switches the Agent to    a project-scoped Main Agent. The Main Agent receives a bounded project    overview containing family/run/head/chain summaries, remains advisory, and    never gains chain mutation tools. Selecting a node continues to use the    chain-scoped Agent.  ## Non-goals and invariants  - No second execution state is introduced; Graph/RunFamily remains the source   of truth. - No provider capacity is guessed. If context capacity is not declared by the   configured provider, the UI says so explicitly. - The Main Agent is read-only and may not confirm, execute, or invent typed   operations. - Project context is bounded to summaries and identifiers; raw datasets and   full artifacts are not sent as global context.  ## Acceptance  - Composer visual regression checks cover the capsule structure, compact   controls, translucent surface, focus/hover behavior, and reduced-motion   safe transitions. - Markdown tests cover GFM-style tables, alignment, inline/block math, Greek   commands, fenced code, and cite-chip text leaves. - Graph tests prove pane click clears selection; Agent surface tests prove   Main role/session creation and bounded project overview; chain selection   remains chain-scoped. - Targeted tests, full frontend tests, TypeScript, diff check, and in-app   browser acceptance all pass.

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 1/12 (8.3%; 8.3 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-07-24T06:46:00.000Z `red_tests`; cause_status: `known`; cause: The requested Agent surface behaviors were not implemented at the baseline.; resolution: `open`; lesson: Write behavior tests before changing the Agent surface implementation.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `test-agent-surface-before-implementation`: occurrences=1; cause_status: `known`; root cause: The requested Agent surface behaviors were not implemented at the baseline.; solution: `open`

## Added tests

- `frontend-targeted-vitest-red`

## New rules

- `test-agent-surface-before-implementation`: line experience occurrence(s)=1

## Future guidance

- Write behavior tests before changing the Agent surface implementation.

## Event index

- #1: `8622d1a7-bf7e-4442-8733-a3e8f39c7286` | 2026-07-24T06:40:10.726Z | STATE_CHANGE/line_started | incident=`4e519083-81de-492c-af85-f99680095f43` | lesson_key=`frozen-context-before-start` | event_sha256=`8bb7bbf59af4dc358d8a3bf2558c5953c24fd4dca65687dab96094bc5720e85a`
- #2: `1c2d6e8f-3d9a-4cb2-9b4d-a3f8b8467d02` | 2026-07-24T06:46:00.000Z | FAILURE/red_tests | incident=`8a9cf1af-142d-42d2-97d3-4b47b7cccb0a` | lesson_key=`test-agent-surface-before-implementation` | event_sha256=`dc1b1d4b11ef82a82547774ff13a36b7195601f511bb2f60d5fd3928d7a3da66`
- #3: `3ed006ad-f091-478f-b02b-c9804922dded` | 2026-07-24T06:49:22.625Z | STATE_CHANGE/context_rescope_required | incident=`4de05914-61bc-4c03-a9d4-1915d1858e86` | lesson_key=`context-pack-rescope` | event_sha256=`a0d8f7764ec6d89109edc2af776788b06d0a6a5e7d652301f05d54bbde4f2e44`
- #4: `8458b1c5-452d-492a-a28b-2971c6be172f` | 2026-07-24T06:49:22.628Z | STATE_CHANGE/context_rescoped | incident=`076a0fe0-8c68-4d65-a351-5f66e852fa01` | lesson_key=`context-pack-rescope` | event_sha256=`fe06f200b54773091757ee2f05d381f861195bc9c24c3578df6573f4a6eff73e`
- #5: `b69cc96e-dc6f-4df5-ae88-6e19d1f0bd56` | 2026-07-24T07:01:30.000Z | GATE/agent_surface_validation_passed | incident=`dd3152e8-1731-4f45-932d-4c1d3a8a7d5d` | lesson_key=`agent-surface-geometry-and-scope-validation` | event_sha256=`671bf141b2af2c4f0cae5d340d378bc65f9427fc5b539acd2d5db3ed0443d2a8`
- #6: `9e6d3274-c7cf-4330-9100-9d44d085f465` | 2026-07-24T08:57:42.259Z | STATE_CHANGE/context_rescope_required | incident=`e2e54faa-329a-4e26-923f-09587aee61b6` | lesson_key=`context-pack-rescope` | event_sha256=`c652a67538fc5012b701747f17ddb60133864d414b20dfd671e6613454526e35`
- #7: `60e31633-4392-4fba-800b-a8baca3bfd23` | 2026-07-24T08:57:42.259Z | STATE_CHANGE/context_rescope_required | incident=`d17f37bc-9f54-4af7-bd90-a98fdc1e7d64` | lesson_key=`context-pack-rescope` | event_sha256=`40ac3ee6a238737cbb0c5c61dd7b77dff437614a01482ebbe8ceec3f0c6fc68a`
- #8: `7ca08cc6-34f0-4dab-a035-13790d138ff9` | 2026-07-24T08:57:42.266Z | STATE_CHANGE/context_rescoped | incident=`9fd03f12-b157-49e1-82ef-b25e37ad22e4` | lesson_key=`context-pack-rescope` | event_sha256=`5521cdd0db36cf5e2450d9023794a0b3d1384730b77cd0a7c25b8f65802cb5de`
- #9: `93494cfc-58e9-4167-9e8c-fde1c60489d7` | 2026-07-24T08:57:46.643Z | STATE_CHANGE/context_rescope_required | incident=`a9df1923-2068-4d9d-9d1f-4803cb8481e2` | lesson_key=`context-pack-rescope` | event_sha256=`6e412f7f596bc7c98b4bbd11e4bf9a735b7e9ca822094fc086de3c1b9fa8f0e5`
- #10: `5788e029-96c0-49c2-9263-3ab1e8721364` | 2026-07-24T08:57:46.649Z | STATE_CHANGE/context_rescoped | incident=`3b191cde-321d-468a-a6e4-6e746f55fc43` | lesson_key=`context-pack-rescope` | event_sha256=`eb6ad1c850995ec9fdb85d5864e133f5197e343c6f2cd05ae1ed12971b906423`
- #11: `b6a41dd9-2799-4e49-a89a-5f6a44fdc5bb` | 2026-07-24T08:45:00.000Z | GATE/full_gate_host_sandbox_blocked | incident=`6daf6906-8a14-45c5-a1e1-d4a4a9b41815` | lesson_key=`host-sandbox-gate-blocked` | event_sha256=`58f21f213e75dcbdcb42552fe098a3cbe35d0203e5fc977a751e2f85124f9d5b`
- #12: `ccf33433-49a6-4b6d-a56a-9f61c59f6de3` | 2026-07-24T08:59:00.000Z | GATE/full_gate_passed | incident=`e991909f-2e9a-48cd-9908-8f5f7548fdf4` | lesson_key=`host-gate-release-pass` | event_sha256=`cd49b4a3e1f19463429eecaa3cb9860a2fb54b5f1608acd5126a31959ea40756`
