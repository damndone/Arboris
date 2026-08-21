# Retrospective — v1-8-9-p1-native-statistical-interchange

## Goal

# Workbench v1.8.9 P1 native statistical-file interchange  ## Objective  Complete the real SPSS/Stata interchange boundary for \`.sav\`, \`.zsav\`, and \`.dta\` while preserving the existing fail-closed optional-dependency and metadata-loss contracts. When the admitted native adapter is installed, Workbench must perform a real write/read round trip for all three formats and return exact typed evidence for file identity, value equality, schema/dtype equality, and any metadata that could not be represented. When the adapter is missing, broken, or only superficially importable, every capability, writer, reader, manifest, and Agent/Notebook/Report-facing result remains explicitly \`unavailable\`; no fake success or raw exception is allowed.  Use the existing \`pyreadstat\` adapter seam rather than adding a second reader. Preserve variable labels and value labels where the native format supports them, and report unsupported measurement-level, user-missing, or other fields as a typed metadata-loss manifest. Keep path containment, deterministic cleanup, and real artifact bytes under the existing interchange contract.  ## Required evidence  - RED probes for missing/broken adapter and for native round-trip behavior; - GREEN real \`.sav\`, compressed \`.zsav\`, and \`.dta\` write/read tests when the   admitted dependency is installed; - typed unavailable tests for every native surface when the dependency is   absent or broken; - manifest/catalog coverage, compileall, and \`git diff --check\`; - formal verification and generated retrospective; - browser, provider, full host, merge, tag, and release remain separate gates.

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

- #2 2026-08-21T04:35:07.654Z `native_statistical_interchange_unavailable_red`; cause_status: `known`; cause: The current environment has no admitted pyreadstat adapter, so the native SAV, ZSAV, and DTA capabilities all correctly remain unavailable and no real native round-trip can be verified.; resolution: `open`; lesson: A typed unavailable result proves safety, not native interoperability; close the real adapter dependency and round-trip evidence separately.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `native-interchange-real-adapter-evidence`: occurrences=1; cause_status: `known`; root cause: The current environment has no admitted pyreadstat adapter, so the native SAV, ZSAV, and DTA capabilities all correctly remain unavailable and no real native round-trip can be verified.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `native-interchange-real-adapter-evidence`: line experience occurrence(s)=1

## Future guidance

- A typed unavailable result proves safety, not native interoperability; close the real adapter dependency and round-trip evidence separately.

## Event index

- #1: `27f569da-1ae5-4d43-87ca-c807376be1e2` | 2026-08-21T04:34:35.793Z | STATE_CHANGE/line_started | incident=`c890a9ec-21ce-4b5e-96d3-10a856b218a3` | lesson_key=`frozen-context-before-start` | event_sha256=`8cf48cefae0a257b081c7745be630459b15b243e0f32ea54f330f3350b4f521c`
- #2: `b0c1d2e3-f4a5-4678-9abc-def012345679` | 2026-08-21T04:35:07.654Z | FAILURE/native_statistical_interchange_unavailable_red | incident=`b1c2d3e4-f5a6-4789-ab01-cdef23456790` | lesson_key=`native-interchange-real-adapter-evidence` | event_sha256=`41ec36cc8bad2915a2c6846dfd3e28a81143ec2785e20f8885747f77eccd9e9c`
- #3: `b5c6d7e8-f901-4a2b-8cde-f01234567890` | 2026-08-21T04:48:57.097Z | GATE/native_interchange_focused_green | incident=`c6d7e8f9-0123-4b5c-8def-012345678901` | lesson_key=`native-interchange-fail-closed` | event_sha256=`c5c614827a66b9d2adb21c4d4550ac468da0797e18996136719efdf8855059f2`
- #4: `3456789a-bcde-4f01-8234-56789abcdef0` | 2026-08-21T04:52:12.190Z | STATE_CHANGE/native_interchange_line_completed | incident=`456789ab-cdef-4012-8345-6789abcdef01` | lesson_key=`native-line-completion-boundary` | event_sha256=`c901bf749c41a52207fbe4c0e63eb96b4e846ec4b9b4cc0e5a7f4c28d687a137`
