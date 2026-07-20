# Retrospective — v173-c2-native-acceptance

## Goal

# C2 Native Acceptance Objective  ## Objective  Turn the existing C2 policy and fake-adapter test coverage into a bounded, native macOS Seatbelt acceptance path for the exact v1.7.3 Integration candidate. The parent must construct every command, require a fresh canary, write the audit receipt, and remain the only possible source of an evaluator verdict.  ## Boundary  This line adds only a reviewed native C2 adapter, host identity/probe support, trusted canary evidence, and collector integration after its reviewed manifest is bound to one exact candidate SHA. It must keep C1 source-only refusal intact. It must not weaken \`code.execute\`, add raw host-Python fallback, admit caller commands, or make a C2 capability serializable/public.  ## Acceptance  The real local Seatbelt canary proves all seven assertions and records an audit receipt. The exact candidate uses the reviewed collector for bounded, parent-verified evidence. Any failed canary, policy mismatch, unsupported host, or malformed output remains non-passing with no fallback.

## Final status

CLOSED

## Metrics

- Failure frequency: 1/3 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- #2 2026-07-20T09:10:00.000Z `local_runtime_not_c2_trust_identity`; cause_status: `known`; cause: The native Seatbelt backend is root-owned, but the active Workbench virtual environment and package-manager interpreter are user-owned and therefore cannot satisfy the strict C2 immutable-runtime identity policy.; resolution: `open`; lesson: Separate OS-backend availability from immutable evaluator-runtime trust; never promote a local virtual environment to a release C2 identity merely because Seatbelt starts.

## All waste

- None recorded.

## Root causes and solutions

- `c2-runtime-trust-identity`: occurrences=1; cause_status: `known`; root cause: The native Seatbelt backend is root-owned, but the active Workbench virtual environment and package-manager interpreter are user-owned and therefore cannot satisfy the strict C2 immutable-runtime identity policy.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `c2-runtime-trust-identity`: line experience occurrence(s)=1

## Future guidance

- Separate OS-backend availability from immutable evaluator-runtime trust; never promote a local virtual environment to a release C2 identity merely because Seatbelt starts.

## Event index

- #1: `3407189a-dff9-49bc-8d1b-de4fcc16feeb` | 2026-07-20T16:31:18.942Z | STATE_CHANGE/line_started | incident=`6964b792-8b5a-465a-b2cb-408f3b4d1565` | lesson_key=`frozen-context-before-start` | event_sha256=`35d0a3201a07c7bbe210a719b0ef08e0cf0540e47193339a13b90a2db49fff3e`
- #2: `5b0c3db4-3523-49f0-a214-31f63f0a5b9e` | 2026-07-20T09:10:00.000Z | GAP/local_runtime_not_c2_trust_identity | incident=`bf65bb67-3614-48f9-aa70-311bc0d6db68` | lesson_key=`c2-runtime-trust-identity` | event_sha256=`275b3474c344a22e69d1ec39494552a5d73b1347c7ee63e7f08e8c322b3eedb4`
- #3: `8e2ea972-d506-4844-8fc6-a486d7d1ea0f` | 2026-07-20T16:55:33.000Z | STATE_CHANGE/c2_removed_from_local_release_scope | incident=`8dc635a1-0e93-4f13-9590-76a49e68f392` | lesson_key=`future-security-boundary-yagni` | event_sha256=`172b9967fbcd90f7a798d6641344ff4e750eb15de7e6ddb53f9e43dd4fb28d81`
