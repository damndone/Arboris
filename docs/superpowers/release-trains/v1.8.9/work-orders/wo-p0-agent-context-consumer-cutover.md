# Work order: v1.8.9 P0 Agent context consumer cutover

## Purpose

Migrate the stale direct-file Agent context fixtures to the server-owned
v1.8.9 result-artifact admission contract without changing production code.

## Implementation boundary

The implementer owns only `tests/test_agent_context_tools.py`. Reuse the
existing v1.8.9 binding/admission helpers where possible. Do not duplicate a
second evidence authority in the test file; a fixture helper may write the
minimal server-shaped index and self-digesting result binding needed by the
real reader.

## Acceptance

1. Focused Agent context suite is green with no newly skipped tests.
2. At least one mutation in the suite proves a changed result/index digest is
   unavailable rather than silently consumed.
3. The adjacent C0/Report boundary suite remains green.
4. Formal events, handoff, retrospective, and verification are generated via
   `scripts/devline_control.py`; no commit/merge/tag/release is performed.

