import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CompareWithSourceSection } from "./CompareWithSourceSection";

const mockResolved = vi.hoisted(() => ({ current: null as unknown }));
const mockGate = vi.hoisted(() => ({
  current: { ok: false, reason: "missing_rerun_from" } as unknown,
}));

vi.mock("../NodeOperationContextProvider", () => ({
  useResolvedNodeOperationContext: () => mockResolved.current,
}));

vi.mock("../../api/rerunProvenance", () => ({
  getCompareWithSourceGate: () => mockGate.current,
}));

describe("CompareWithSourceSection", () => {
  it("does not render an actionable compare entry without rerun_from", () => {
    mockResolved.current = {
      ok: true,
      context: {},
    };
    mockGate.current = { ok: false, reason: "missing_rerun_from" };

    render(<CompareWithSourceSection />);

    expect(screen.queryByRole("button", { name: /compare with source/i })).toBeNull();
    expect(screen.getByText(/No rerun source recorded/i)).toBeInTheDocument();
  });

  it("renders the compare action when the source gate passes", () => {
    mockResolved.current = {
      ok: true,
      context: {},
    };
    mockGate.current = {
      ok: true,
      source_kind: "node_level_rerun_from",
      rerun_from: {
        owner_run_id: "run_source",
        op_node_id: "model:ols_1",
        node_hash: "hash_source",
        context_fingerprint: "nocv1:source",
        rerun_request_id: "req_1",
      },
    };

    render(<CompareWithSourceSection />);

    expect(screen.getByRole("button", { name: /compare with source/i })).toBeInTheDocument();
  });
});
