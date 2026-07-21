# D01 — Operation Execution Envelope

## Status and evidence

**Status:** locked — contract-only C1

**Evidence:** `5b18d7c2e59b89f54afdb85b9e6fed34dfd8783032d2bb5efc948b3fb19c6d16`.
The immutable terminal-state and negative-reference fixtures are parsed by the
focused D07 evidence test. This locks the envelope shape only and authorizes no
runtime, confirmation, retry, or executor behavior.

## Normative v1 boundary

```text
completed -> facts_packet_ref present and assessment_packet_ref present
rejected | failed | cancelled -> facts_packet_ref absent and assessment_packet_ref absent
only completed reaches the statistical decision table
hard data-input failure is completed + not_suitable
unexpected timeout, OOM, terminated executor, or corrupt Pack output is failed
```

`rejected`, `completed`, `failed`, and `cancelled` are the complete closed set
of `operation_status` values. `completed` is an execution fact, never a
statistical conclusion. The `not_suitable` conclusion for a hard data-input
failure is held by the referenced completed assessment packet, not by this
outer envelope. The other three terminal states carry no statistical
conclusion and no Facts or Assessment packet reference.

`reason_code` is likewise closed, and it is closed **per terminal status**:

| `operation_status` | Exact allowed `reason_code` values |
| --- | --- |
| `completed` | `ASSESSMENT_COMPLETED`, `HARD_DATA_INPUT` |
| `rejected` | `USER_REJECTED` |
| `failed` | `EXECUTOR_TIMEOUT`, `EXECUTOR_OOM`, `TERMINATED_EXECUTOR`, `CORRUPT_PACK_OUTPUT` |
| `cancelled` | `USER_CANCELLED` |

Fixture identity belongs to test data and evidence catalogues, not the public
protocol. Unknown values or known reasons paired with another terminal state
are rejected rather than preserved for a hypothetical future consumer.

Confirmation idempotence and cancellation lifecycle semantics remain an
existing platform-lifecycle dependency. D01 defines their terminal envelope
shape only; it adds no confirmation token, executor, retry behavior, or
operation route.

## Lock evidence

- `tests/fixtures/models/time_series_diagnostics/packets/envelope-*.json`
- `tests/contracts/test_time_series_diagnostics_evaluation_gates.py`
- Evidence manifest: `tests/fixtures/models/time_series_diagnostics/evidence-manifest.json`

## Exact object shape

```json
{
  "operation_status": "completed",
  "reason_code": "ASSESSMENT_COMPLETED",
  "facts_packet_ref": "facts:immutable-reference",
  "assessment_packet_ref": "assessment:immutable-reference"
}
```

The parser requires exactly these four fields. It applies no defaults, rejects
unknown fields, and accepts a packet reference only when it is a non-empty
string. Non-completed envelopes must explicitly provide both reference fields
as `null`.
