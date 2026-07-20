# Time Series Diagnostics v1 Packet Schema

## Scope

This schema records only the D01 outer execution envelope. Facts and
Assessment packet schemas, digest projections, and advisory objects remain
unsealed in their respective C1 decision records.

## `OperationExecutionEnvelope`

The envelope has exactly these fields and no defaults:

| Field | Type | Rule |
| --- | --- | --- |
| `operation_status` | closed string enum | One of `rejected`, `completed`, `failed`, `cancelled`. |
| `reason_code` | closed string enum | Must be one of the exact values allowed for its `operation_status` below. |
| `facts_packet_ref` | non-empty string or `null` | Present only for `completed`; otherwise explicitly `null`. |
| `assessment_packet_ref` | non-empty string or `null` | Present only for `completed`; otherwise explicitly `null`. |

The terminal-state invariant is:

```text
completed -> facts_packet_ref present and assessment_packet_ref present
rejected | failed | cancelled -> facts_packet_ref absent and assessment_packet_ref absent
only completed reaches the statistical decision table
hard data-input failure is completed + not_suitable
unexpected timeout, OOM, terminated executor, or corrupt Pack output is failed
```

Here “present” means a non-empty string, and “absent” means the field is
explicitly `null`; missing fields are invalid. A hard input failure’s
`not_suitable` conclusion is found only in the completed Assessment packet.
This outer envelope never itself carries a statistical conclusion.

| `operation_status` | Exact allowed `reason_code` values |
| --- | --- |
| `completed` | `ASSESSMENT_COMPLETED`, `HARD_DATA_INPUT` |
| `rejected` | `USER_REJECTED` |
| `failed` | `EXECUTOR_TIMEOUT`, `EXECUTOR_OOM`, `TERMINATED_EXECUTOR`, `CORRUPT_PACK_OUTPUT` |
| `cancelled` | `USER_CANCELLED` |

Fixture identity belongs to test data and evidence catalogues, not this public
protocol. Known codes are rejected when paired with another terminal status,
just as an unknown code is rejected.

`D01` remains **open**. This schema describes its candidate contract boundary;
it is not evidence that the required fixture-backed lifecycle lock has been
completed.
