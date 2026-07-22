# Time Series Diagnostics v1 — Reason-Code Catalogue

## Status

This catalogue defines the closed contract-only C1 namespace. The listed codes
are evidence-bound by the D-record SHA
`5b18d7c2e59b89f54afdb85b9e6fed34dfd8783032d2bb5efc948b3fb19c6d16`; the
catalogue itself does not authorize runtime execution.

| Group | Code | Meaning | Packet placement | Fixture / evidence |
| --- | --- | --- | --- | --- |
| input | `TIME_VALUE_MISSING` | selected time value is missing | Facts component reason | D03 closed namespace; evidence SHA bound in register |
| input | `TIME_PARSE_FAILED` | selected time value is not an accepted form | Facts component reason | D03 closed namespace; runtime parser deferred |
| input | `IRREGULAR_SPACING` | ordered time grid is irregular | Facts component reason | D03 (`raw/irregular-grid.csv`) |
| input | `EXPECTED_TIME_POINT_ABSENT` | declared calendar frequency has a missing point | Facts component reason | D03 closed namespace; calendar parser deferred |
| input | `FREQUENCY_DECLARATION_MISMATCH` | user declaration conflicts with observed grid | Facts component reason | D03 closed namespace; runtime parser deferred |
| component | `TREND_NOT_ASSESSED` | trend was not eligible or available | Facts component reason | D05 normalized-facts tests |
| component | `NO_DECLARED_CANDIDATE_PERIOD` | no user-confirmed seasonal candidate exists | Facts component reason | D03 proposal boundary tests |
| caveat | `RAW_LEVEL_CORRELATION_ONLY` | ACF/PACF are descriptive raw-level facts | Assessment caveat | D04 oracle and Facts packet |
| caveat | `NO_MODEL_ORDER_INFERENCE` | ACF/PACF do not select AR/MA/ARIMA order | Assessment caveat | D04 oracle and Facts packet |
| caveat | `LEVEL_STATIONARITY_ONLY` | null-test evidence concerns levels only | Assessment caveat | D04 oracle and Facts packet |
| caveat | `NO_FORECAST_ELIGIBILITY` | conclusion is not forecast eligibility | Assessment caveat | D04 oracle and Assessment packet |
| caveat | `NO_MODEL_SELECTION` | no model is selected in C1 | Assessment caveat | D04 oracle and Assessment packet |
| caveat | `STRUCTURAL_BREAKS_NOT_ASSESSED` | structural breaks are outside C1 | Assessment caveat | D04 oracle and Facts packet |
| advisory | `CONSIDER_DIFFERENCING` | conditional review of differencing | Assessment advisory | D05 policy and advisory boundary |
| advisory | `REVIEW_TREND_HANDLING` | conditional review of trend handling | Assessment advisory | D05 policy and advisory boundary |
| execution | `ASSESSMENT_COMPLETED` | completed contract-only assessment envelope | outer envelope | D01 completed fixture |
| execution | `HARD_DATA_INPUT` | completed envelope carrying a hard-input conclusion | outer envelope | D01 closed reason set |
| execution | `USER_REJECTED` | user rejected the proposed operation | outer envelope | D01 rejected fixture |
| execution | `EXECUTOR_TIMEOUT` | unexpected executor timeout | outer envelope | D01 failed fixture |
| execution | `EXECUTOR_OOM` | unexpected executor memory exhaustion | outer envelope | D01 closed reason set |
| execution | `TERMINATED_EXECUTOR` | executor was terminated unexpectedly | outer envelope | D01 closed reason set |
| execution | `CORRUPT_PACK_OUTPUT` | Pack output violated its contract | outer envelope | D01 closed reason set |
| execution | `USER_CANCELLED` | user cancelled before completion | outer envelope | D01 cancelled fixture |
| execution | `UNSUPPORTED_DEPENDENCY_MANIFEST` | numeric runtime manifest is unsupported | outer envelope | D07 rejection fixture |

Unknown codes, aliases, and status/code combinations are rejected. C1 does not
coerce or preserve undeclared values for a future consumer.
