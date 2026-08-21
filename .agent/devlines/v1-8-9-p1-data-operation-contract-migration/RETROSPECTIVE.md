# Retrospective — v1-8-9-p1-data-operation-contract-migration

## Goal

# Workbench v1.8.9 P1 data-operation contract migration  ## Objective  Migrate the remaining legacy data-operation integration fixtures to the v1.8.9 server-owned contracts without weakening any authority or evidence boundary. Data column-cast and multi-column-cast lifecycle tests must create proposals through the existing server-issued \`ProposalStoreCapabilityV1\` seam. Data profile reload tests must create and confirm the detached, server-owned metadata artifact used by the current profile reader instead of writing the retired legacy registry shape.  The change must preserve preview fingerprint binding, durable operation records, child-artifact lineage, crash reconciliation, metadata revisions, and typed unavailable outcomes. No production path may accept a raw store, caller-owned metadata, or an unconfirmed registry merely to keep old tests green.  ## Scope  Allowed paths are limited to the affected data-operation integration tests, this objective, its work order, and the formal line. Production authority and metadata code are protected unless a RED regression proves a narrowly scoped compatibility defect in the current supported seam.  ## Required evidence  - RED evidence showing the legacy fixtures fail at the new boundary; - GREEN for the data column-cast, multi-column-cast, profile reload and   metadata-child-lineage suites; - compileall and \`git diff --check\`; - formal verification and generated retrospective; - browser, real provider, native \`.sav/.zsav/.dta\`, full host gate, merge,   tag, and release remain separate \`NOT VERIFIED\` gates.

## Final status

STARTED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `2d9d65c2-3725-4458-be84-9ec952ef776b` | 2026-08-21T04:28:28.174Z | STATE_CHANGE/line_started | incident=`03976cad-04f6-40df-ab55-26123bca8321` | lesson_key=`frozen-context-before-start` | event_sha256=`26d2400324c65c4b68bdf0182eb7d7825f311a871d1f36bbe5ca82c64f09f162`
