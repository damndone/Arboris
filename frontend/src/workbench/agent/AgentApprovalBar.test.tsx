import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { agentProposalFixture } from "../../apiFixtures";
import type { AgentProposal } from "./agentTypes";

const surface = { confirmationBusyId: null as string | null, confirmProposal: vi.fn(), declineProposal: vi.fn(), reviseProposal: vi.fn() };
vi.mock("./AgentSurfaceContext", () => ({ useAgentSurfaceOptional: () => surface }));
vi.mock("./ProposalFields", () => ({ ProposalFields: () => null }));

import { AgentApprovalBar } from "./AgentApprovalBar";
import { receiptsByTurn } from "./AgentProposalReceipt";

function proposal(id: string, overrides: Partial<AgentProposal> = {}): AgentProposal {
  return agentProposalFixture({
    record_type: "revision", proposal_id: id, operation_id: "operation.multi_step", operation_version: "v1", revision: 1,
    session_id: "s", chain_id: "c", command_id: null, target: {}, preconditions: {}, changes: { steps: [] },
    evidence_refs: [], expected_effect: ["A report covering the fits"], risks: ["Report assembly only; it fits nothing new."],
    created_at: "2026-10-22T16:39:00Z", fingerprint: "f", status: "pending",
    readable: ["Assemble the completed steps into a report"], ...overrides,
  });
}

describe("AgentApprovalBar", () => {
  test("one line says what it will do and its main risk; Run, Decline and Edit act on it", () => {
    render(<AgentApprovalBar proposals={[proposal("p1")]} projectRoot="/proj" />);
    expect(screen.getByText("Assemble the completed steps into a report", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Report assembly only; it fits nothing new.", { selector: "p" })).toBeInTheDocument();
    expect(screen.queryByText("pending")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm proposal p1" }));
    expect(surface.confirmProposal).toHaveBeenCalledWith("p1");
    fireEvent.click(screen.getByRole("button", { name: "Decline proposal p1" }));
    expect(surface.declineProposal).toHaveBeenCalledWith("p1");
    fireEvent.click(screen.getByRole("button", { name: "Revise proposal p1" }));
    expect(screen.getByRole("button", { name: "Confirm proposal p1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save revision p1" })).toBeInTheDocument();
  });

  test("several pending proposals are shown one at a time", () => {
    render(<AgentApprovalBar proposals={[proposal("p1"), proposal("p2", { readable: ["Fit the sensitivity model"] })]} projectRoot="/proj" />);
    expect(screen.getByText(/1 of 2/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next proposal" }));
    expect(screen.getByText("Fit the sensitivity model", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm proposal p2" })).toBeInTheDocument();
  });
});

describe("receiptsByTurn", () => {
  test("a decided proposal goes with the turn whose message came last before it", () => {
    const turns = [{ id: "t1", user: { at: "2026-10-22T16:00:00Z" } }, { id: "t2", user: { at: "2026-10-22T16:30:00Z" } }];
    const decided = [proposal("early", { created_at: "2026-10-22T16:10:00Z", status: "confirmed" }),
      proposal("late", { created_at: "2026-10-22T16:40:00Z", status: "declined" })];
    const placed = receiptsByTurn(turns, decided);
    expect(placed.get("t1")?.map((item) => item.proposal_id)).toEqual(["early"]);
    expect(placed.get("t2")?.map((item) => item.proposal_id)).toEqual(["late"]);
    expect(receiptsByTurn([], decided).get("")).toHaveLength(2);
  });
});
