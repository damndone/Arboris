# Retrospective — wo-a-agent

## Goal

Preserve the reviewed LMM Agent persistence boundary while integration resolves its single trusted admission capability.

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 1/6 (16.7%; 16.7 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #6 2026-07-20T01:16:00.000Z `durability_retry_boundary`; cause_status: `known`; cause: Equal-existing retry paths accepted a file without re-proving leaf and parent durability after a transient parent fsync failure.; resolution: `resolved`; lesson: Every equal-existing persistence retry must reopen without following links, fsync leaf and parent, then re-read canonical bytes.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `filesystem-persistence-capability-bypass`: occurrences=1; cause_status: `known`; root cause: Equal-existing retry paths accepted a file without re-proving leaf and parent durability after a transient parent fsync failure.; solution: `resolved`

## Added tests

- `tests/models/linear_mixed_effects/test_pinned_persistence.py`
- `tests/test_pinned_run_directory.py`

## New rules

- `filesystem-persistence-capability-bypass`: line experience occurrence(s)=1

## Future guidance

- Every equal-existing persistence retry must reopen without following links, fsync leaf and parent, then re-read canonical bytes.
- Keep persistence authority inside a verified capability boundary.

## Event index

- #1: `bed341f8-0a8b-427f-af5c-c054c8d6bc32` | 2026-07-19T23:45:18.819Z | STATE_CHANGE/line_started | incident=`736a4acb-28ee-4e8d-ae25-d0814181ace8` | lesson_key=`frozen-context-before-start` | event_sha256=`79b0ed68a9ff5a10c9159b08835115608f0c5d925b46d196c234adaa60bd4ce8`
- #2: `10000000-0000-4000-8000-000000000001` | 2026-07-19T19:00:00.000Z | REVIEW/persistence_capability_boundary_review | incident=`20000000-0000-4000-8000-000000000001` | lesson_key=`filesystem-persistence-capability-bypass` | event_sha256=`3e0047a4909059534745b1afe9b884651e4d7e5604116502130389e2bc2184b8`
- #3: `f1789fa9-9dea-4ec8-89cb-c3fc659cfdff` | 2026-07-20T00:45:16.538Z | STATE_CHANGE/context_rescope_required | incident=`44fb598b-ad13-42b7-bdbd-63a153fe6a89` | lesson_key=`context-pack-rescope` | event_sha256=`d01cdf563b4c15d9084fbd6874920d56ce3893c51983cb257fc0b9c9a82eca20`
- #4: `e51fae07-fb09-4b7a-805c-97feadcf5a5c` | 2026-07-20T00:45:16.542Z | STATE_CHANGE/context_rescoped | incident=`179d89b3-3e34-47fe-a35a-c77886a147fb` | lesson_key=`context-pack-rescope` | event_sha256=`ea2b7af2b751f4535e4b1448cc6270ce17c8f3e315d65fa801430b74db651199`
- #5: `3d8c5409-c437-4e96-baf7-1e2610d22319` | 2026-07-20T00:46:33.000Z | STATE_CHANGE/sealed_admission_state_machine_implemented | incident=`e8be1c61-99a7-4b4e-8933-b10f904fb625` | lesson_key=`filesystem-persistence-capability-bypass` | event_sha256=`350e08b227c4728b879ebe93ab1d47c233784ce4d329aae68809a7ee18c7d2a6`
- #6: `d45aa448-e4e8-4679-b917-41d7ab6abda4` | 2026-07-20T01:16:00.000Z | FAILURE/durability_retry_boundary | incident=`ecddd91b-24d9-4e4e-ae8a-40a27f19ce14` | lesson_key=`filesystem-persistence-capability-bypass` | event_sha256=`0e063435e9dd1ba14efe41b5141c20ce9073ccdda137a8915435e3213382698f`
