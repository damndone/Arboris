import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentInstructionsPanel } from "./AgentInstructionsPanel";
import * as api from "./agent/agentApi";

vi.mock("./agent/agentApi", () => ({
  getAgentInstructions: vi.fn(),
  saveAgentInstructions: vi.fn(),
  draftAgentInstructions: vi.fn(),
}));

const layer = (kind: "guide" | "personal" | "project", content: string) => ({
  kind, path: `/p/${kind}.md`, exists: Boolean(content), editable: kind !== "guide", content, bytes: content.length,
});
const view = (project: string) => ({
  layers: [layer("guide", "# Arboris analysis guide"), layer("personal", ""), layer("project", project)],
  limit_bytes: 32768,
  templates: { personal: "# Personal instructions", project: "# Project instructions" },
});

beforeEach(() => {
  vi.mocked(api.getAgentInstructions).mockResolvedValue(view("Cluster by firm."));
  vi.mocked(api.saveAgentInstructions).mockImplementation(async (_root, body) => view(body.content));
  vi.mocked(api.draftAgentInstructions).mockResolvedValue({ content: "# Project instructions\n- `wages.csv`" });
});

describe("Agent instructions", () => {
  it("edits and saves the project file; the guide is read-only", async () => {
    render(<AgentInstructionsPanel projectRoot="/p" />);
    const editor = await screen.findByLabelText("This project instructions");
    expect(editor).toHaveValue("Cluster by firm.");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.change(editor, { target: { value: "Cluster by firm and year." } });
    fireEvent.click(save);
    await screen.findByText("Saved. New conversations will read it.");
    expect(api.saveAgentInstructions).toHaveBeenCalledWith("/p", { kind: "project", content: "Cluster by firm and year." });
    fireEvent.click(screen.getByRole("tab", { name: /Built-in guide/ }));
    expect(screen.getByLabelText("Built-in guide instructions")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("asks before a draft replaces what is written", async () => {
    render(<AgentInstructionsPanel projectRoot="/p" />);
    await screen.findByLabelText("This project instructions");
    fireEvent.click(screen.getByRole("button", { name: "Draft from this project" }));
    fireEvent.click(await screen.findByRole("button", { name: "Keep mine" }));
    expect(screen.getByLabelText("This project instructions")).toHaveValue("Cluster by firm.");
    fireEvent.click(screen.getByRole("button", { name: "Draft from this project" }));
    fireEvent.click(await screen.findByRole("button", { name: "Replace" }));
    await waitFor(() => expect(screen.getByLabelText("This project instructions")).toHaveValue("# Project instructions\n- `wages.csv`"));
  });
});
