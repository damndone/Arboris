import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { AgentSurfaceContext, type AgentSurfaceContextValue } from "../workbench/agent/AgentSurfaceContext";
import { WorkspaceCommandsContext } from "./workspaceCommands";
import { SelectionMenu } from "./SelectionMenu";
import { appendToPrompt, nodeQuestion, quoteSelection, selectionQuestion } from "./agent/askAgent";

function Harness({ showAgent }: { showAgent: () => void }) {
  const [prompt, setPrompt] = useState("draft in progress");
  const agent = { prompt, setPrompt } as unknown as AgentSurfaceContextValue;
  return (
    <AgentSurfaceContext.Provider value={agent}>
      <WorkspaceCommandsContext.Provider value={{ analyze: () => {}, showAgent }}>
        <div data-testid="workspace-shell">
          <table aria-label="Result">
            <thead><tr><th>Term</th><th>SE</th></tr></thead>
            <tbody><tr><td>education</td><td data-testid="se">74.0</td></tr></tbody>
          </table>
          <textarea aria-label="Notes" defaultValue="typed" />
          <output data-testid="prompt">{prompt}</output>
        </div>
        <SelectionMenu />
      </WorkspaceCommandsContext.Provider>
    </AgentSurfaceContext.Provider>
  );
}

function select(element: Element) {
  const range = document.createRange();
  range.selectNodeContents(element);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
}

describe("right-click on selected text", () => {
  it("asks the Agent with the row and its column names, after the unsent draft", () => {
    const showAgent = vi.fn();
    render(<Harness showAgent={showAgent} />);
    const cell = screen.getByTestId("se");
    select(cell);
    act(() => { fireEvent.contextMenu(cell); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Ask Agent about this" }));
    const prompt = screen.getByTestId("prompt").textContent!;
    expect(prompt.startsWith("draft in progress\n\nExplain this: \"74.0\"")).toBe(true);
    expect(prompt).toContain("Shown with: Term: education | SE: 74.0");
    expect(prompt).toContain("Where: Result");
    expect(showAgent).toHaveBeenCalled();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("quotes the selection into the message", () => {
    render(<Harness showAgent={() => {}} />);
    const cell = screen.getByTestId("se");
    select(cell);
    act(() => { fireEvent.contextMenu(cell); });
    fireEvent.click(screen.getByRole("menuitem", { name: "Add to Agent message" }));
    expect(screen.getByTestId("prompt").textContent).toBe("draft in progress\n\n> 74.0\n\n");
  });

  it("leaves the browser menu alone without a selection or inside a text field", () => {
    render(<Harness showAgent={() => {}} />);
    window.getSelection()!.removeAllRanges();
    const plain = fireEvent.contextMenu(screen.getByTestId("se"));
    expect(plain).toBe(true);
    const field = screen.getByLabelText("Notes");
    select(field);
    expect(fireEvent.contextMenu(field)).toBe(true);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("ask Agent wording", () => {
  it("appends rather than replaces, and names what is asked about", () => {
    expect(appendToPrompt("", "q")).toBe("q");
    expect(appendToPrompt("mine  ", "q")).toBe("mine\n\nq");
    expect(nodeQuestion("ols_robust", "model")).toBe('About the model "ols_robust": what does it show, how was it produced, and what should I check next?');
    expect(selectionQuestion("74.0", "74.0", "")).not.toContain("Shown with");
    expect(quoteSelection("a\nb")).toBe("> a\n> b\n\n");
  });
});
