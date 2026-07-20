# D06 — Packet Identity and Canonical Digests

## Status and evidence

**Status:** open

**Evidence:** unsealed. Canonical packet fixtures, digest projections,
malformed-packet tests, stale identity tests, and evidence SHA are still
required. This record does not authorize a runtime capability.

The C1 contract implementation is now present for the strict Facts and
Assessment packet types and canonical digest helpers. This is a contract
surface only: it does not create a time-series runtime, registry discovery,
HTTP route, Agent operation, UI feature, fixture catalogue, or oracle. The
implementation and focused tests do not seal this decision record; fixture
identity and evidence SHA remain pending.

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
