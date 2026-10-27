import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { agentProposalFixture } from "../../apiFixtures";
import type { AgentProposal } from "./agentTypes";

const surface = { confirmationBusyId: null as string | null, confirmProposal: vi.fn(), declineProposal: vi.fn(), reviseProposal: vi.fn(),
  abortTurn: vi.fn() as ReturnType<typeof vi.fn> | undefined, isSubmitting: false, sessionStatus: "idle" };
vi.mock("./AgentSurfaceContext", () => ({ useAgentSurfaceOptional: () => surface }));
vi.mock("./ProposalFields", () => ({ ProposalFields: () => <>
  <input aria-label="Proposal text" />
  <textarea aria-label="Proposal long text" />
  <select aria-label="Proposal selection"><option>First option</option></select>
  <div contentEditable suppressContentEditableWarning role="textbox" aria-label="Proposal rich text">Draft</div>
</> }));

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
  beforeEach(() => {
    surface.confirmationBusyId = null;
    surface.isSubmitting = false;
    surface.sessionStatus = "idle";
    surface.confirmProposal.mockReset().mockResolvedValue(undefined);
    surface.declineProposal.mockReset().mockResolvedValue(true);
    surface.reviseProposal.mockReset().mockResolvedValue(true);
    surface.abortTurn = vi.fn().mockResolvedValue(undefined);
  });

  test("one line says what it will do and its main risk; Run, Decline and Edit act on it", async () => {
    render(<AgentApprovalBar proposals={[proposal("p1")]} projectRoot="/proj" />);
    expect(screen.getByText("Assemble the completed steps into a report", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Report assembly only; it fits nothing new.", { selector: "p" })).toBeInTheDocument();
    expect(screen.queryByText("pending")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm proposal p1" }));
    expect(surface.confirmProposal).toHaveBeenCalledWith("p1");
    await waitFor(() => expect(screen.getByRole("button", { name: "Decline proposal p1" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Decline proposal p1" }));
    expect(surface.declineProposal).toHaveBeenCalledWith("p1");
    await waitFor(() => expect(screen.getByRole("button", { name: "Revise proposal p1" })).not.toBeDisabled());
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

  test("only the focused current card accepts confirm and skip shortcuts", async () => {
    render(<><input aria-label="Outside the proposal" />
      <AgentApprovalBar proposals={[proposal("p1"), proposal("p2")]} projectRoot="/proj" /></>);
    const card = screen.getByRole("article", { name: "Agent proposal p1" });
    expect(card).toHaveAttribute("tabindex", "0");
    expect(screen.getByText(/↵ Confirm.*E Edit.*S Skip.*Esc Stop/)).toBeInTheDocument();
    screen.getByRole("textbox", { name: "Outside the proposal" }).focus();
    fireEvent.keyDown(document, { key: "Enter" });
    fireEvent.keyDown(card, { key: "Enter" });
    expect(surface.confirmProposal).not.toHaveBeenCalled();
    card.focus();
    fireEvent.keyDown(card, { key: "Enter" });
    expect(surface.confirmProposal).toHaveBeenCalledTimes(1);
    expect(surface.confirmProposal).toHaveBeenCalledWith("p1");
    await waitFor(() => expect(screen.getByRole("button", { name: "Decline proposal p1" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Next proposal" }));
    const current = screen.getByRole("article", { name: "Agent proposal p2" });
    current.focus();
    fireEvent.keyDown(current, { key: "S", shiftKey: true });
    expect(surface.declineProposal).toHaveBeenCalledTimes(1);
    expect(surface.declineProposal).toHaveBeenCalledWith("p2");
    await waitFor(() => expect(screen.getByRole("button", { name: "Revise proposal p2" })).not.toBeDisabled());
    expect(surface.confirmProposal).toHaveBeenCalledTimes(1);
  });

  test("E edits and Escape cancels an editor before it can stop or confirm", () => {
    render(<AgentApprovalBar proposals={[proposal("p1")]} projectRoot="/proj" />);
    const card = screen.getByRole("article", { name: "Agent proposal p1" });
    card.focus();
    fireEvent.keyDown(card, { key: "e" });
    expect(screen.getByRole("button", { name: "Save revision p1" })).toBeInTheDocument();
    fireEvent.keyDown(card, { key: "Enter" });
    fireEvent.keyDown(card, { key: "s" });
    expect(surface.confirmProposal).not.toHaveBeenCalled();
    expect(surface.declineProposal).not.toHaveBeenCalled();
    const field = screen.getByRole("textbox", { name: "Proposal text" });
    field.focus();
    fireEvent.keyDown(field, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Save revision p1" })).not.toBeInTheDocument();
    expect(card).toHaveFocus();
    expect(surface.abortTurn).not.toHaveBeenCalled();
    fireEvent.keyDown(card, { key: "Escape" });
    expect(surface.abortTurn).toHaveBeenCalledTimes(1);
  });

  test("shortcuts never hijack buttons, text, selection or editable controls", () => {
    render(<AgentApprovalBar proposals={[proposal("p1")]} projectRoot="/proj" />);
    const decline = screen.getByRole("button", { name: "Decline proposal p1" });
    decline.focus();
    for (const key of ["Enter", "e", "s", "Escape"]) fireEvent.keyDown(decline, { key });
    expect(surface.confirmProposal).not.toHaveBeenCalled();
    expect(surface.declineProposal).not.toHaveBeenCalled();
    expect(surface.abortTurn).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Revise proposal p1" }));
    for (const name of ["Proposal text", "Proposal long text", "Proposal selection", "Proposal rich text"]) {
      const field = screen.getByLabelText(name);
      field.focus();
      for (const key of ["Enter", "e", "s"]) fireEvent.keyDown(field, { key });
    }
    expect(surface.confirmProposal).not.toHaveBeenCalled();
    expect(surface.declineProposal).not.toHaveBeenCalled();
    expect(surface.reviseProposal).not.toHaveBeenCalled();
  });

  test("IME, repeated keydown and modified Enter cannot confirm; in-flight confirmation is invoked once", async () => {
    let resolveConfirmation!: () => void;
    surface.confirmProposal.mockImplementation(() => new Promise<void>((resolve) => { resolveConfirmation = resolve; }));
    render(<AgentApprovalBar proposals={[proposal("p1")]} projectRoot="/proj" />);
    const card = screen.getByRole("article", { name: "Agent proposal p1" });
    card.focus();
    for (const options of [{ isComposing: true }, { keyCode: 229 }, { repeat: true }, { ctrlKey: true }, { altKey: true }, { metaKey: true }, { shiftKey: true }]) {
      fireEvent.keyDown(card, { key: "Enter", ...options });
    }
    expect(surface.confirmProposal).not.toHaveBeenCalled();
    fireEvent.keyDown(card, { key: "Enter" });
    fireEvent.keyDown(card, { key: "Enter" });
    fireEvent.keyDown(card, { key: "Enter", repeat: true });
    fireEvent.keyDown(card, { key: "s" });
    expect(surface.confirmProposal).toHaveBeenCalledTimes(1);
    expect(surface.confirmProposal).toHaveBeenCalledWith("p1");
    expect(surface.declineProposal).not.toHaveBeenCalled();
    fireEvent.keyDown(card, { key: "Escape" });
    expect(surface.abortTurn).toHaveBeenCalledTimes(1);
    await act(async () => { resolveConfirmation(); });
  });

  test.each(["confirmation", "turn", "working"])("a %s in progress blocks decisions and edit shortcuts, while Escape requests stop", async (running) => {
    if (running === "confirmation") surface.confirmationBusyId = "p1";
    if (running === "turn") surface.isSubmitting = true;
    if (running === "working") surface.sessionStatus = "working";
    render(<AgentApprovalBar proposals={[proposal("p1")]} projectRoot="/proj" />);
    const card = screen.getByRole("article", { name: "Agent proposal p1" });
    card.focus();
    for (const key of ["Enter", "e", "s"]) fireEvent.keyDown(card, { key });
    expect(surface.confirmProposal).not.toHaveBeenCalled();
    expect(surface.declineProposal).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Save revision p1" })).not.toBeInTheDocument();
    fireEvent.keyDown(card, { key: "Escape" });
    fireEvent.keyDown(card, { key: "Escape", repeat: true });
    expect(surface.abortTurn).toHaveBeenCalledTimes(1);
    await act(async () => {});
  });

  test("a missing stop method is not advertised or reported as stopped", () => {
    surface.abortTurn = undefined;
    render(<AgentApprovalBar proposals={[proposal("p1")]} projectRoot="/proj" />);
    const card = screen.getByRole("article", { name: "Agent proposal p1" });
    card.focus();
    fireEvent.keyDown(card, { key: "Escape" });
    expect(screen.queryByText(/Esc Stop/)).not.toBeInTheDocument();
    expect(screen.queryByText(/stopped/i)).not.toBeInTheDocument();
    expect(surface.confirmProposal).not.toHaveBeenCalled();
    expect(surface.declineProposal).not.toHaveBeenCalled();
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
