# Time Series Diagnostics v1 — Fixture Catalogue

## Status

The catalogue is the contract-only C1 evidence index. Every committed row
below is parsed or asserted by a focused test and bound by evidence SHA
`5b18d7c2e59b89f54afdb85b9e6fed34dfd8783032d2bb5efc948b3fb19c6d16` in the
evidence manifest. Runtime/parser/forecast execution remains outside this
lock.

| Fixture ID | Boundary | Required owner / test | Status |
| --- | --- | --- | --- |
| `exact_regular_no_semantic_frequency` | exact regular grid with no semantic frequency | D03 transport/proposal tests | locked — contract-only (`raw/regular-grid.csv`) |
| `candidate_period_lag_steps` | user-confirmed lag-step period without semantic frequency | D03 proposal tests | locked — contract-only |
| `required_null_outcome_undetermined` | incomplete ADF/KPSS evidence | D02 policy tests | locked — normalized-facts matrix |
| `trend_component_unavailable` | no trend advisory when unavailable | D05 policy tests | locked — normalized-facts matrix |
| `trend_component_ambiguous` | present/undetermined trend evidence | D05 policy tests | locked — normalized-facts matrix |
| `completed_missing_assessment_ref` | completed envelope missing assessment ref | D01 envelope test | locked (`packets/envelope-completed-missing-assessment-ref.json`) |
| `terminal_noncompleted_with_refs` | failed/cancelled envelope carrying refs | D01 envelope test | locked (`packets/envelope-failed-with-refs.json`) |
| `assessment_conclusion_mutated` | changed conclusion changes assessment digest | D06 canonical test | locked — canonical projection |
| `advisory_reordered` | advisory order does not change digest | D06 canonical test | locked — canonical projection |
| `advisory_content_changed` | advisory content changes digest | D06 canonical test | locked — canonical projection |
| `facts_digest_mismatch` | stale Facts digest rejects Assessment | D06 canonical test | locked — Facts binding |
| `unsupported_dependency_manifest` | unsupported runtime manifest is rejected | D07 gate test | locked (`oracle/unsupported-dependency-manifest.json`) |
| `stale_pre_run_confirmation` | stale dataset/row/column identity | D05/D07 negative test | locked (`packets/stale-pre-run-confirmation.json`) |
| `post_run_advisory` | assessment-owned advisory only | D05/D07 negative test | locked (`packets/post-run-advisory.json`) |
| `attempted_execution_of_advisory` | no operation token or execution path | D05/D07 negative test | locked — no token/forecast fields |

Raw CSV fixtures and packet JSON fixtures must remain small, UTF-8, immutable,
and free of provider output. Numerical oracle rows must name an independent
source, tolerance, and supported runtime manifest digest.
