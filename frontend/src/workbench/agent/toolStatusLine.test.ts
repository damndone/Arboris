import { describe, expect, it } from "vitest";

import { toolStatusLine } from "./AgentPanel";

const line = (output: unknown) => toolStatusLine(JSON.stringify({ tool_id: "propose_operation", ok: true, output }));

describe("toolStatusLine", () => {
  it("says a read-only analysis ran without confirmation and counts the tests", () => {
    expect(line({ executed: true, operation: { status: "completed" }, inferential_tests_run_this_session: 3 })).toBe(
      "propose_operation ✓ read-only analysis ran without confirmation (recorded) · 3 tests run this session",
    );
  });

  it("says why a proposal waits for confirmation", () => {
    expect(
      line({ requires_confirmation: true, proposal: { proposal_id: "p1" }, confirmation_reason: "the workflow includes data_change steps" }),
    ).toBe("propose_operation ✓ proposal ready p1 — awaiting confirmation (the workflow includes data_change steps)");
  });

  it("reports a read-only run that could not start", () => {
    expect(line({ executed: false, error: "stale" })).toBe("propose_operation ✗ read-only analysis could not run");
  });
});
