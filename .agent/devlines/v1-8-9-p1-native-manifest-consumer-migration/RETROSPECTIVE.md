# Retrospective — v1-8-9-p1-native-manifest-consumer-migration

## Goal

# Workbench v1.8.9 P1 native manifest consumer migration  ## Objective  Update the adjacent data-consumer contract test to recognize the live, fail-closed native interchange manifest: \`.sav\`, \`.zsav\`, and \`.dta\` are listed as unavailable only when the admitted pyreadstat capability is absent or broken, and are omitted from \`unavailable\` when real round-trip support is available. Do not weaken the manifest or make environment-sensitive native support appear unavailable.  ## Required evidence  - RED from the stale consumer assertion under an admitted native adapter; - GREEN for the adjacent consumer test and native manifest suite; - formal verification, compileall, and \`git diff --check\`; - browser/provider/full-host/cross-process/release remain separate gates.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/4 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T04:46:35.053Z `native_manifest_consumer_contract_red`; cause_status: `known`; cause: The adjacent data-consumer test still required all native statistical interchange ids to appear as unavailable even when the admitted pyreadstat adapter passes real probes.; resolution: `open`; lesson: Environment-sensitive capabilities must be asserted against the live fail-closed manifest rather than a permanently unavailable fixture assumption.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `live-manifest-contract`: occurrences=1; cause_status: `known`; root cause: The adjacent data-consumer test still required all native statistical interchange ids to appear as unavailable even when the admitted pyreadstat adapter passes real probes.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `live-manifest-contract`: line experience occurrence(s)=1

## Future guidance

- Environment-sensitive capabilities must be asserted against the live fail-closed manifest rather than a permanently unavailable fixture assumption.

## Event index

- #1: `cae2575b-7d6c-4634-a601-c53fc25d74f2` | 2026-08-21T04:46:06.470Z | STATE_CHANGE/line_started | incident=`982bdca0-06e5-4822-98c6-3f6f622458da` | lesson_key=`frozen-context-before-start` | event_sha256=`e55ae2e8c44376579972e0ad2326b346ec9d43d0e2e3157e0a7612280fe6560c`
- #2: `f3a4b5c6-d7e8-490a-8bcd-ef0123456789` | 2026-08-21T04:46:35.053Z | FAILURE/native_manifest_consumer_contract_red | incident=`a4b5c6d7-e8f9-401b-8cde-f01234567890` | lesson_key=`live-manifest-contract` | event_sha256=`8fc64b8667a2665c2ad88d6c5f22c5af52732d20ae2cb3e4fd574490541b7f7e`
- #3: `d7e8f901-2345-4a6b-8cde-f01234567890` | 2026-08-21T04:49:13.301Z | GATE/native_manifest_consumer_focused_green | incident=`e8f90123-4567-4b8c-9def-012345678901` | lesson_key=`live-manifest-contract` | event_sha256=`3f8eec9fd5e0420e2e89d03bd69afc7d2894b726650d7822466d2b4ae7bbf5ad`
- #4: `56789abc-def0-4123-8456-789abcdef012` | 2026-08-21T04:52:12.315Z | STATE_CHANGE/native_manifest_line_completed | incident=`6789abcd-ef01-4234-8567-89abcdef0123` | lesson_key=`manifest-line-completion-boundary` | event_sha256=`0128b74ee5249a6fe0ed6bb2d6def987f1f7d4b8057c16dff468b8e0878a7d5b`
