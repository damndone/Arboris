# Retrospective — p3-capability-registration

## Goal

# P3 Capability Registration Objective  At baseline a5efa90, make one workflow capability declaration sufficient to register the capability across the operation registry, proposal/editable schema, workflow vocabulary, notebook planning contracts, node context inspection, route rendering, and unified capability inventory.  Use the live WORKFLOW_STEP_SPEC_CONTRACTS declaration as the only source. Derive the operation tuple and produces/consumes/replayable projections from it, support closed field enums, and project capability_kind plus top_level_exposure_note into CapabilityContract. Keep reachability exemptions separate: the P7 pack seam must have proposed_by=(), composable_as=(operation_id,), reachability_exempt_reason=None.  Use the verified P7 operation ID repeated_measures_anova.repeated_only and fields response_column, subject_column, within_factor_columns, between_factor_column, correction; correction values are greenhouse_geisser, huynh_feldt, and none. Prove injection through tests without a second inventory list.  Do not change P0/P1/P2 behavior, workflow_runtime.py, or orchestrator dispatch. P7 numerical execution remains later work. Required evidence is a real red test followed by green implementation tests, behavior-changing mutation failures with anchored/hash-checked harnesses, focused regression tests, and the backend full suite from the repository root using only the valid R-fixture ignores.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/9 (55.6%; 55.6 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=5; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-08T20:45:00.000Z `tdd_expected_red`; cause_status: `known`; cause: The first P3 test run intentionally referenced the not-yet-implemented pack_step_contract helper.; resolution: `resolved`; lesson: A feature test must go red before its declaration helper is implemented; classify the failure as an expected TDD boundary.

## All errors

- #4 2026-08-08T20:52:00.000Z `formal_event_schema`; cause_status: `known`; cause: A temporary formal event used an unsupported preventability value and was rejected before append.; resolution: `resolved`; lesson: Use the formal event schema's controlled preventability values before submitting a material event.
- #7 2026-08-08T22:04:32.000Z `verification_field_name_guess`; cause_status: `known`; cause: A read-only live-inventory verification command guessed the CapabilityReachabilityGuard field name composed_only instead of querying the runtime annotations.; resolution: `resolved`; lesson: Query live annotations or registry fields before writing verification commands; do not infer field names from concepts.
- #8 2026-08-08T22:05:15.000Z `formal_event_sha_algorithm_error`; cause_status: `known`; cause: The first attempt to append the verification error event supplied a SHA-1 git hash where the formal event schema requires a SHA-256 digest.; resolution: `resolved`; lesson: Use the exact formal event schema and hash algorithm before submitting an event; a rejected append is not evidence until the corrected event is accepted.
- #9 2026-08-08T22:06:27.000Z `sandbox_git_index_permission`; cause_status: `external`; cause: The agent-sandbox staging attempt could not create the worktree index lock under the repository Git metadata directory.; resolution: `resolved`; lesson: Git metadata mutations for a worktree may require the host terminal even when source verification is allowed in the agent sandbox.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `formal-event-schema-values`: occurrences=1; cause_status: `known`; root cause: A temporary formal event used an unsupported preventability value and was rejected before append.; solution: `resolved`
- `query-live-fields-before-verification`: occurrences=1; cause_status: `known`; root cause: A read-only live-inventory verification command guessed the CapabilityReachabilityGuard field name composed_only instead of querying the runtime annotations.; solution: `resolved`
- `stage-worktree-from-host`: occurrences=1; cause_status: `external`; root cause: The agent-sandbox staging attempt could not create the worktree index lock under the repository Git metadata directory.; solution: `resolved`
- `tdd-red-before-implementation`: occurrences=1; cause_status: `known`; root cause: The first P3 test run intentionally referenced the not-yet-implemented pack_step_contract helper.; solution: `resolved`
- `use-formal-event-hash-schema`: occurrences=1; cause_status: `known`; root cause: The first attempt to append the verification error event supplied a SHA-1 git hash where the formal event schema requires a SHA-256 digest.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `formal-event-schema-values`: line experience occurrence(s)=1
- `query-live-fields-before-verification`: line experience occurrence(s)=1
- `stage-worktree-from-host`: line experience occurrence(s)=1
- `tdd-red-before-implementation`: line experience occurrence(s)=1
- `use-formal-event-hash-schema`: line experience occurrence(s)=1

## Future guidance

- A feature test must go red before its declaration helper is implemented; classify the failure as an expected TDD boundary.
- Git metadata mutations for a worktree may require the host terminal even when source verification is allowed in the agent sandbox.
- Mutation evidence must demonstrate changed behavior, exact assertion failure, and restoration; a changed file with a green no-op mutation is not proof.
- Query live annotations or registry fields before writing verification commands; do not infer field names from concepts.
- Use the exact formal event schema and hash algorithm before submitting an event; a rejected append is not evidence until the corrected event is accepted.
- Use the formal event schema's controlled preventability values before submitting a material event.

## Event index

- #1: `190247fd-ad37-44a3-9edc-5fa200bfe770` | 2026-08-08T20:31:14.412Z | STATE_CHANGE/line_started | incident=`7a9d4cc6-1249-44df-89b2-bdfd07d409a8` | lesson_key=`frozen-context-before-start` | event_sha256=`98e5a1d7104d116a53a3dcb7545e80187d1a736badaa2f55bf051a0a51cc4961`
- #2: `6a26a00d-4a7a-4a1f-a8f1-46c1b72e5d01` | 2026-08-08T20:45:00.000Z | FAILURE/tdd_expected_red | incident=`bff1dfe4-4cd1-4d53-a24c-0f6db71a2a10` | lesson_key=`tdd-red-before-implementation` | event_sha256=`6c40464cfaa8fce6926ebd13da3e604b10a08e9262c16980a25e8351699be650`
- #3: `b3b8f4f0-3b73-4b9f-88e4-17e78bc3ac02` | 2026-08-08T20:50:00.000Z | REVIEW/mutation_guard_review | incident=`2d50b7c8-1e7f-46f8-a38e-c9afbb7d8f03` | lesson_key=`behavior-changing-mutation-evidence` | event_sha256=`e2f6e46de4411f8e895a20dddd5b468a394b129994ac0963b8a256d4477e3278`
- #4: `d5a67dbd-6d92-49a1-a82d-0fa9f4544104` | 2026-08-08T20:52:00.000Z | ERROR/formal_event_schema | incident=`75275528-e947-4c78-83e8-3b1d519a5cc5` | lesson_key=`formal-event-schema-values` | event_sha256=`0e7bca53cb387e7782834a3d89e5f0ad126c76c9c34ca9102881dee52f723bee`
- #5: `7c02e8f3-a8d0-45c6-a8b0-ff0e7f7c2805` | 2026-08-08T21:10:00.000Z | GATE/backend_full_gate | incident=`f4df5eb5-5d5c-4b42-a47c-7cd8514fa606` | lesson_key=`host-gate-separates-containment` | event_sha256=`5970ac8197dd960631cbbc076de6798f783856e2521b5d1c88d03fd4414f86b1`
- #6: `8fc70f0e-86f3-4dfb-98c4-ff33da3cd207` | 2026-08-08T21:11:06.000Z | STATE_CHANGE/line_completed | incident=`2a3cbf39-3d0b-4d02-83ba-68cee9582ef8` | lesson_key=`close-after-host-gate` | event_sha256=`2852dd8039f6b280cfa0b76ea9c98316f4d546aac20508d29ebc9f70272ac713`
- #7: `e4e521ce-12e0-42c0-88cf-eb3dc7e5f299` | 2026-08-08T22:04:32.000Z | ERROR/verification_field_name_guess | incident=`d19ad2f6-d696-4907-9c79-0610c9a5df7c` | lesson_key=`query-live-fields-before-verification` | event_sha256=`85cc4db08d30fd4468bacd0eb0d3b78186ae230420e8c38f913cb7380ec1df0f`
- #8: `ed41b35b-a238-48db-a283-5aaa43b8239b` | 2026-08-08T22:05:15.000Z | ERROR/formal_event_sha_algorithm_error | incident=`4d771870-7975-4e84-869e-f4733ec08a89` | lesson_key=`use-formal-event-hash-schema` | event_sha256=`2d7bd6ababf42d7b5696ca0b8dc6d5d5ca18aedc6cb9afb13b8b56fe8ee907fc`
- #9: `f8e1436d-b178-4790-8480-027ba978fe7a` | 2026-08-08T22:06:27.000Z | ERROR/sandbox_git_index_permission | incident=`938c8a54-a617-4aa5-a9ce-47c2cf421162` | lesson_key=`stage-worktree-from-host` | event_sha256=`01bbd76ba4339bce6b03c167bd408deafb5946f83b9f25b5cab6af8acf501f3e`
