# D06 — Packet Identity and Canonical Digests

## Status and evidence

**Status:** locked — contract-only C1

**Evidence:** `5b18d7c2e59b89f54afdb85b9e6fed34dfd8783032d2bb5efc948b3fb19c6d16`.
Canonical Facts/Assessment packet fixtures, digest projections, malformed-packet
tests, stale identity tests, and public helper error tests are committed. This
locks packet identity only and authorizes no runtime capability.

The C1 contract implementation is present for the strict Facts and Assessment
packet types and canonical digest helpers. This is a contract surface only: it
does not create a time-series runtime, registry discovery, HTTP route, Agent
operation, UI feature, or forecast.

## Normative direction

Facts are the only source packet. Assessment is a one-way derivation from the
Facts content digest and owns the conclusion and advisory set. The Facts
projection excludes Facts packet identity fields, run identity, timestamp,
and digest fields. The Assessment projection explicitly includes the
referenced `facts_content_digest`; it excludes `assessment_content_digest`,
packet/run/timestamp identity, and other identity or digest fields. The outer
execution envelope hashes all of its fields except its own `envelope_digest`.

The C1 implementation must use the repository's canonical JSON v1 primitive,
reject non-finite values and unknown fields, and sort closed-set arrays before
projection. Caveat codes sort by code; advisories sort by
`(advisory_code, advisory_version)`; evidence references sort by canonical fact
path. An embedded advisory has no parent packet ID; containment establishes its
parent.

## Required lock evidence

- canonical Facts, Assessment, and envelope projection tests;
- advisory reordering and advisory-content mutation fixtures;
- altered Facts digest and stale identity rejection fixtures;
- malformed/unknown/non-finite packet rejection tests;
- exact policy, fixture, and evidence SHA recorded here and in the register.

## Recorded evidence

- `tests/fixtures/models/time_series_diagnostics/packets/facts-packet.json`
- `tests/fixtures/models/time_series_diagnostics/packets/assessment-packet.json`
- `tests/contracts/test_time_series_diagnostics_canonical_packets.py`
- Evidence manifest: `tests/fixtures/models/time_series_diagnostics/evidence-manifest.json`
