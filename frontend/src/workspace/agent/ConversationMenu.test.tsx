import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentSurfaceContext, type AgentSurfaceContextValue } from "../../workbench/agent/AgentSurfaceContext";
import { ProjectRootProvider } from "../../workbench/ProjectRootContext";
import * as api from "../../workbench/agent/agentApi";
import { ConversationMenu } from "./ConversationMenu";

vi.mock("../../workbench/agent/agentApi", () => ({
  listAgentConversations: vi.fn(),
  updateAgentConversation: vi.fn(),
  deleteAgentConversation: vi.fn(),
}));

const conversation = (session_id: string, title: string, extra: Record<string, unknown> = {}) => ({
  session_id, role: "chain", title, titled: false, about: "ols_robust", focus: null,
  created_at: "2026-10-14T09:00:00Z", last_active: "2026-10-14T09:30:00Z",
  messages: 4, replies: 2, archived: false, status: "idle", forked_from: null, ...extra,
});

function renderMenu(agent: Partial<AgentSurfaceContextValue>) {
  const value = { messages: [], isSubmitting: false, ...agent } as unknown as AgentSurfaceContextValue;
  return render(
    <ProjectRootProvider projectRoot="/p">
      <AgentSurfaceContext.Provider value={value}>
        <ConversationMenu />
      </AgentSurfaceContext.Provider>
    </ProjectRootProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.listAgentConversations).mockResolvedValue({
    conversations: [conversation("s1", "Is the effect robust?"), conversation("s2", "Forecast GDP", { about: "Project" })],
  });
  vi.mocked(api.updateAgentConversation).mockResolvedValue(conversation("s2", "x"));
  vi.mocked(api.deleteAgentConversation).mockResolvedValue({ session_id: "s1", deleted: true });
});

describe("conversation picker", () => {
  it("shows the current conversation's title, switches and starts new ones", async () => {
    const openConversation = vi.fn();
    const newConversation = vi.fn();
    renderMenu({ sessionId: "s1", openConversation, newConversation });
    const current = await screen.findByRole("button", { name: /Is the effect robust\?/ });
    fireEvent.click(current);
    fireEvent.click(screen.getByRole("button", { name: /^Forecast GDP/ }));
    expect(openConversation).toHaveBeenCalledWith("s2");
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(newConversation).toHaveBeenCalled();
  });

  it("searches, renames and archives", async () => {
    renderMenu({ sessionId: "s1", openConversation: vi.fn(), newConversation: vi.fn() });
    fireEvent.click(await screen.findByRole("button", { name: /Is the effect robust\?/ }));
    fireEvent.change(screen.getByLabelText("Search conversations"), { target: { value: "gdp" } });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Actions for Forecast GDP" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.change(screen.getByLabelText("Conversation title"), { target: { value: "GDP forecast" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.updateAgentConversation).toHaveBeenCalledWith("/p", "s2", { title: "GDP forecast" }));
    fireEvent.click(screen.getByRole("button", { name: "Actions for Forecast GDP" }));
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.updateAgentConversation).toHaveBeenCalledWith("/p", "s2", { archived: true }));
  });

  it("deletes only after confirming, and starts fresh when the current one goes", async () => {
    const newConversation = vi.fn();
    renderMenu({ sessionId: "s1", openConversation: vi.fn(), newConversation });
    fireEvent.click(await screen.findByRole("button", { name: /Is the effect robust\?/ }));
    fireEvent.click(screen.getByRole("button", { name: "Actions for Is the effect robust?" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete…" }));
    expect(api.deleteAgentConversation).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog", { name: "Delete conversation" })).toHaveTextContent("analysis ledger stay");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.deleteAgentConversation).toHaveBeenCalledWith("/p", "s1"));
    await waitFor(() => expect(newConversation).toHaveBeenCalled());
  });

  it("a refusal is shown, not swallowed", async () => {
    vi.mocked(api.deleteAgentConversation).mockRejectedValue(new Error("Other conversations continue from this one. Archive it, or delete those first."));
    renderMenu({ sessionId: "s2", openConversation: vi.fn(), newConversation: vi.fn() });
    fireEvent.click(await screen.findByRole("button", { name: /Forecast GDP/ }));
    fireEvent.click(screen.getByRole("button", { name: "Actions for Is the effect robust?" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete…" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Archive it");
  });
});
