# Retrospective — v1-8-9-p1-native-interchange-packaging

## Goal

# Workbench v1.8.9 P1 native statistical interchange packaging objective  Make the already implemented \`.sav\`, \`.zsav\`, and \`.dta\` adapters reproducible in a clean installation. The supported optional dependency must be declared by the package, the user-facing install instructions must name the extra, and the existing fail-closed \`UNAVAILABLE\` behavior must remain intact when the extra is not installed or its runtime probe is broken.  This is packaging and documentation only. It must not broaden the native format parser, bypass the typed capability probe, or change the Agent/Notebook/ Report authority boundary.  Required evidence:  - a red test or equivalent proof that the package metadata does not currently   declare the native adapter; - the native extra is declared in \`pyproject.toml\`; - README installation guidance names the extra and the supported formats; - native interchange and manifest tests remain green with \`pyreadstat\`   available; - absent/broken optional dependency tests remain typed \`UNAVAILABLE\`; - \`git diff --check\` and formal verification.  Browser, real provider, supervisor, cross-process, full repository, merge, tag, and release gates remain outside this line.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/4 (25.0%; 25.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=54851 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T05:08:38.918Z `native_extra_metadata_red`; cause_status: `known`; cause: The new package metadata assertion failed because the project has no native optional dependency extra.; resolution: `open`; lesson: Package optional dependencies must be tested from project metadata before implementation claims are accepted.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `native-extra-metadata-gap`: occurrences=1; cause_status: `known`; root cause: The new package metadata assertion failed because the project has no native optional dependency extra.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `native-extra-metadata-gap`: line experience occurrence(s)=1

## Future guidance

- Package optional dependencies must be tested from project metadata before implementation claims are accepted.

## Event index

- #1: `f3011888-10ec-427f-b193-ba8d1bb7d3b0` | 2026-08-21T05:05:41.630Z | STATE_CHANGE/line_started | incident=`0bbfa192-696a-47a7-b601-4553b4562b22` | lesson_key=`frozen-context-before-start` | event_sha256=`fbfd36102cd46218047fbe1a453bfd48073987cee6b7b3f9a3f570668d7c1bbf`
- #2: `7d2c1f4a-6b8e-4c90-9a1d-3e5f7b2c8d14` | 2026-08-21T05:08:38.918Z | FAILURE/native_extra_metadata_red | incident=`1a9f4e72-3c6d-4b81-8e25-7f0a2d6c9b34` | lesson_key=`native-extra-metadata-gap` | event_sha256=`5c80980e799f57089ceaca2764e3eba08c6c48dc04ba91b9b6abc1c0a66dc6cd`
- #3: `8e3f2a61-7c94-4b08-a5d2-1f6e9c3b7a20` | 2026-08-21T05:09:33.769Z | GATE/native_interchange_packaging_green | incident=`1a9f4e72-3c6d-4b81-8e25-7f0a2d6c9b34` | lesson_key=`native-extra-packaging-gate` | event_sha256=`049f60112452c1cd6e34416fa81d708f84c486f33fbeb8b2dfcc9b265c425637`
- #4: `9f4b2d73-1c68-4a90-b5e7-2d8f6c3a1049` | 2026-08-21T05:10:05.002Z | STATE_CHANGE/native_interchange_packaging_completed | incident=`b6e1a3d8-5c97-4f20-8a64-1d3e7b9c2f50` | lesson_key=`scoped-line-closeout` | event_sha256=`c11837dccdeab352b5e551d705605e6a06b86c00b9e19d21ffdc71a88569c1fd`
