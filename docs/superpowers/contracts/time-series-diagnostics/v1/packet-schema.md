# Time Series Diagnostics v1 Packet Schema

## Scope

This schema records the D01 outer execution envelope and the D06 packet
identity boundary. It defines contract-only parsing and canonical digest
inputs; it does not authorize a Pack, registry entry, runtime execution, or
feature implementation.

D06 remains **open** and **unsealed**. Fixture IDs, passing fixture evidence,
and evidence SHA values remain pending. A contract-locked shape is not the
same thing as a feature-implemented capability.

## `TimeSeriesDiagnosticFactsPacket`

Facts are the only source packet. The packet has exactly these fields and no
defaults:

| Field | Type | Rule |
| --- | --- | --- |
| `contract` | string | `time_series_diagnostics.facts` |
| `contract_version` | string | `1.0` |
| `packet_id` | non-empty string | identity only; excluded from content digest |
| `producer_version` | non-empty string | included in content digest |
| `policy_version` | non-empty string | included in content digest |
| `run_id` | non-empty string | excluded from content digest |
| `execution_timestamp` | UTC RFC 3339 string | excluded from content digest |
| `input_identity` | JSON object | included in content digest |
| `configuration` | JSON object | included in content digest |
| `numeric_runtime_manifest_digest` | lowercase SHA-256 | included in content digest |
| `facts` | JSON object | included in content digest |
| `facts_content_digest` | lowercase SHA-256 | identity field; excluded from itself |

Unknown and missing fields, malformed digest references, non-finite numbers,
and non-UTC timestamps are rejected. The object is detached and immutable
after parsing; input mappings are never modified.

The content projection is exactly:

```text
contract, contract_version, producer_version, policy_version,
input_identity, configuration, numeric_runtime_manifest_digest, facts
```

`facts_content_digest` is the SHA-256 of the repository canonical JSON v1
encoding of that projection.

## `TimeSeriesDiagnosticAssessmentPacket`

Assessment is a one-way derivation from the Facts content digest. It has
exactly these fields and no defaults:

| Field | Type | Rule |
| --- | --- | --- |
| `contract` | string | `time_series_diagnostics.assessment` |
| `contract_version` | string | `1.0` |
| `packet_id` | non-empty string | excluded from content digest |
| `producer_version` | non-empty string | excluded from content digest |
| `run_id` | non-empty string | excluded from content digest |
| `execution_timestamp` | UTC RFC 3339 string | excluded from content digest |
| `facts_packet_id` | non-empty string | identity only; excluded from content digest |
| `facts_content_digest` | lowercase SHA-256 | included and must match Facts |
| `decision_policy_version` | non-empty string | included in content digest |
| `assessment_scope` | string | `first_slice_diagnostic_evidence` |
| `conclusion` | closed string | `suitable_with_caveats`, `not_suitable`, or `inconclusive` |
| `caveat_codes` | closed string array | sorted by code |
| `caveat_fact_refs` | fact-reference array | sorted by canonical fact path |
| `advisories` | advisory object array | sorted by code then version |
| `assessment_content_digest` | lowercase SHA-256 | excluded from itself |

`assessment_content_digest` is the SHA-256 of the canonical JSON v1 encoding
of exactly `facts_content_digest`, `decision_policy_version`,
`assessment_scope`, `conclusion`, `caveat_codes`, `caveat_fact_refs`, and
`advisories`. Packet IDs, run/timestamp identity, and all digest fields other
than the referenced Facts digest are excluded from this projection.

Fact references use the canonical dotted path form `facts.<segment>...`.
Advisories are packet-owned, `advisory_only`, and must set
`execution_available` to `false`; an embedded advisory has no parent packet
ID. Assessment parsing must be bound to a Facts packet; omitting it is
rejected, and a stale or mutated Facts digest is rejected. The required
semantic signature is:

```python
TimeSeriesDiagnosticAssessmentPacket.from_dict(
    value, *, facts_packet=validated_facts_packet
)
```

## Canonical envelope digest

`envelope_digest(envelope)` hashes the complete envelope object after removing
only its own `envelope_digest` field. A forged or stale self-digest is ignored
for this calculation; changing any other envelope field changes the digest.

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
