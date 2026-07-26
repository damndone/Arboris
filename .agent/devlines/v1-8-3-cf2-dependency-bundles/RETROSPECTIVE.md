# Retrospective — v1-8-3-cf2-dependency-bundles

## Goal

# v1.8.3 CF2 deterministic dependency bundles  Implement the dependency control-plane foundation for Capability Factory: immutable dependency requirements and lock records, networked fetch metadata separated from offline quarantine/assembly, safe wheel/archive inspection, content-addressed bundle candidates, and explicit admission states. Route only dependency acquisition proposals through the existing high-risk Agent policy; do not install packages in the Workbench environment, import or execute fetched code, access user data, mount application routes, or modify AgentCore/model/tool surfaces. Keep bundle validity separate from evidence and scoped admission.  This slice may implement unmounted service contracts and deterministic tests only; it does not claim third-party capability validation, custom execution, native containment acceptance, or Notebook integration.

## Final status

COMPLETED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/3 (0.0%)
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

- `tests/test_capability_dependency_risk.py`
- `tests/test_capability_dependency_service.py`
- `tests/test_capability_dependency_trace.py`

## New rules

- No rule candidate recorded.

## Future guidance

- Never issue a high-risk grant from an unverified in-memory confirmation object.

## Event index

- #1: `12f0244c-0a0e-47a9-96b1-99bbaa6a56e3` | 2026-07-26T13:41:46.265Z | STATE_CHANGE/line_started | incident=`8a959a4e-1a8d-4d70-af5e-b50f8ec2fbdf` | lesson_key=`frozen-context-before-start` | event_sha256=`f0da3f9bed5a0dcb1e3e1c64a145d810bba9a9d72b9b27f1bd7c3a5972b2da7a`
- #2: `7c8b7a07-84f9-4daa-b0f2-079d3bc36a2a` | 2026-07-26T13:53:52.000Z | STATE_CHANGE/cf2_foundation_checkpoint | incident=`4fbadfc4-47cd-4e7a-a9f5-2389c6cd1bc6` | lesson_key=`separate-acquisition-from-execution` | event_sha256=`3d6b5db2f7f5a473e44a0d83aea1eb17bdfb37cb9a16d7859061f1cdf4c9ece2`
- #3: `5a5dbe19-ec43-4b91-bf51-0e728e6f25cc` | 2026-07-26T13:55:33.720Z | GATE/cf2_dependency_gate | incident=`f08c46f0-327c-4e5d-9f6f-5c2f4ce4bb50` | lesson_key=`separate-targeted-from-release-gates` | event_sha256=`526fa83320e366a466c001f8408e4b3baeb5aab6203da21749fbfd22fe9e3860`
- #4: `cf3c7182-14f5-40df-9cce-4cba5a37df0e` | 2026-07-26T14:03:25.602Z | REVIEW/risk_binding_review | incident=`1d5be49a-b9a4-46f7-8c56-0913f3e8fbb0` | lesson_key=`revalidate-durable-confirmation` | event_sha256=`24f8acc7bd126805c1c4a955fb552ae82d24f68fb7f99913a35cea33de19bfbf`
- #5: `81a272aa-e0d8-421f-a82d-6d1049d1cc17` | 2026-07-26T14:03:25.602Z | GATE/proposal_risk_lifecycle_gate | incident=`04ea22b6-46b4-457e-a0fa-dad9f8f590c2` | lesson_key=`separate-authorize-from-execute` | event_sha256=`2845018e6a79e76e6e294e6277538ab30e1bd05330091c7f7e37c5fc6f945aa0`
- #6: `2b4c9e6f-1d7a-4f83-b5e2-0c9a6d8f1472` | 2026-07-26T14:12:16.509Z | GATE/persistent_dependency_store_gate | incident=`ad7c3f29-5e81-4b06-9a2d-7f1c8e4b5063` | lesson_key=`persist-and-verify-content-addressed-metadata` | event_sha256=`43da31ef9ceec14edcc333b4fc1b7204aface91ccafaf9dbf4ebff520b126490`
- #7: `6d1a9f3c-5e72-4b08-a6d4-2c8f7e1b9053` | 2026-07-26T14:13:57.917Z | STATE_CHANGE/cf2_dependency_foundation_completed | incident=`c8f2a7d1-4b6e-49c0-8d3a-5f1e7b2c6049` | lesson_key=`close-cf2-at-offline-control-plane` | event_sha256=`d0d1f52a1354e7cce602edc6a2401e16387a4526a8ff19c325e916f5f1d11b91`
