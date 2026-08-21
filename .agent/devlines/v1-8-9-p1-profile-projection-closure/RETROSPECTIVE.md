# Retrospective — v1-8-9-p1-profile-projection-closure

## Goal

# Workbench v1.8.9 P1 bounded profile projection closure  ## Objective  Make the direct data-profile route consume the canonical server-built \`DataProfileV1\` shape and project it into the bounded \`data-profile.v1\` consumer shape used by the data editor and downstream Agent/Notebook/Report readers. Preserve fail-closed behavior for malformed, untrusted, or raw payloads. The adapter must retain dataset identity, observed missingness, declared labels/value labels/measurement level/user-missing values, safe samples, and explicit unknown values without exposing paths, rows, or raw artifacts.  ## Required evidence  - RED regression probes showing a confirmed canonical profile currently fails   at the bounded HTTP projection boundary; - GREEN for canonical profile projection, profile reload, and existing bounded   consumer tests; - adversarial coverage for malformed nested columns and raw/path leakage; - compileall, \`git diff --check\`, formal verification, and retrospective; - browser, provider, cross-process, full-host, merge, tag, and release gates   remain separate \`NOT VERIFIED\` evidence.  ## Boundaries  - Do not weaken server-owned metadata authority or accept legacy registry data; - do not expose raw rows, filesystem paths, dataframes, or arbitrary payloads; - keep the public projection stable and composable for Agent/Notebook/Report; - no unrelated model-family or provider changes.

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

- #2 2026-08-21T04:44:21.831Z `canonical_profile_projection_red`; cause_status: `known`; cause: The confirmed server-built DataProfileV1 uses nested columns with observed, declared, and inferred metadata, while the bounded data-profile.v1 route projection only accepted the flat consumer variables shape.; resolution: `open`; lesson: Keep the canonical typed profile and the public bounded consumer shape separate, but implement an explicit fail-closed adapter between them.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `profile-projection-adapter`: occurrences=1; cause_status: `known`; root cause: The confirmed server-built DataProfileV1 uses nested columns with observed, declared, and inferred metadata, while the bounded data-profile.v1 route projection only accepted the flat consumer variables shape.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `profile-projection-adapter`: line experience occurrence(s)=1

## Future guidance

- Keep the canonical typed profile and the public bounded consumer shape separate, but implement an explicit fail-closed adapter between them.

## Event index

- #1: `950e6157-2050-4970-981f-e963d4a16f05` | 2026-08-21T04:43:20.160Z | STATE_CHANGE/line_started | incident=`a0d0d570-c49d-4bb9-9ce9-9f5f9f847329` | lesson_key=`frozen-context-before-start` | event_sha256=`a0134e7fc61bf2b78382cdf5a782f0bb24ea9397f2c916b20ff1f5276dbe3d66`
- #2: `d1e2f3a4-b5c6-4789-8abc-def012345678` | 2026-08-21T04:44:21.831Z | FAILURE/canonical_profile_projection_red | incident=`e2f3a4b5-c6d7-489a-8bcd-ef0123456789` | lesson_key=`profile-projection-adapter` | event_sha256=`00dd1adc32e922be7cea35b1d009b4d7ce699ea3d4e124d389f550b1bdfa2158`
- #3: `f9012345-6789-4abc-8def-012345678901` | 2026-08-21T04:51:25.121Z | GATE/canonical_profile_projection_focused_green | incident=`01234567-89ab-4cde-8f01-234567890abc` | lesson_key=`canonical-profile-adapter` | event_sha256=`816c7aafc91c92ab7e2aef0ef9894e10d9e46261105831f7678f3c300d35c333`
- #4: `12345678-9abc-4def-8012-3456789abcde` | 2026-08-21T04:52:12.062Z | STATE_CHANGE/profile_projection_line_completed | incident=`23456789-abcd-4ef0-8123-456789abcdef` | lesson_key=`profile-line-completion-boundary` | event_sha256=`36ac17e4be2727448bb5798e3ae34e69c825973c4c51e7bc31664077f96ce6fe`
