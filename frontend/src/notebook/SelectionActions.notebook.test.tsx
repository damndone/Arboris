import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SelectionActions } from "./SelectionActions";
import type { NotebookSelection } from "./contracts";

const selection: NotebookSelection = {
  text: "the residual ACF still shows structure at lag 12",
  source_label: "agent message nar_2",
  source_ref: "narrative:nar_2",
};

function handlers() {
  return {
    onAsk: vi.fn(),
    onExplain: vi.fn(),
    onFollowUp: vi.fn(),
    onSaveNote: vi.fn(),
    onDeferAsOption: vi.fn(),
  };
}

describe("SelectionActions — Gate 6 selected-text interaction", () => {
  it("quotes the selection and names where it came from", () => {
    render(<SelectionActions selection={selection} {...handlers()} />);
    expect(screen.getByTestId("selection-quote")).toHaveTextContent(
      "the residual ACF still shows structure at lag 12",
    );
    expect(screen.getByTestId("selection-source")).toHaveTextContent(
      "from agent message nar_2",
    );
  });

  it("offers the three Codex-style primary actions with the typed selection", () => {
    const spies = handlers();
    render(
      <SelectionActions
        selection={selection}
        onAddToTask={spies.onAsk}
        onMoreDetails={spies.onExplain}
        onAskInSideChat={spies.onFollowUp}
        {...spies}
      />,
    );

    fireEvent.click(screen.getByTestId("selection-action-add-to-task"));
    fireEvent.click(screen.getByTestId("selection-action-more-details"));
    fireEvent.click(screen.getByTestId("selection-action-side-chat"));

    expect(spies.onAsk).toHaveBeenCalledWith(selection);
    expect(spies.onExplain).toHaveBeenCalledWith(selection);
    expect(spies.onFollowUp).toHaveBeenCalledWith(selection);
  });

  it("keeps follow-up, note, and deferred-option actions behind More actions", () => {
    const spies = handlers();
    render(<SelectionActions selection={selection} {...spies} />);

    fireEvent.click(screen.getByTestId("selection-action-more"));
    fireEvent.click(screen.getByTestId("selection-action-ask"));
    fireEvent.click(screen.getByTestId("selection-action-note"));
    fireEvent.click(screen.getByTestId("selection-action-defer"));

    expect(spies.onFollowUp).toHaveBeenCalledWith(selection);
    expect(spies.onSaveNote).toHaveBeenCalledWith(selection);
    expect(spies.onDeferAsOption).toHaveBeenCalledWith(selection);
  });

  it("labels the deferred-option action as a proposal request, not an execution", () => {
    render(<SelectionActions selection={selection} {...handlers()} />);
    fireEvent.click(screen.getByTestId("selection-action-more"));
    expect(screen.getByTestId("selection-action-defer")).toHaveTextContent(
      "Save as deferred option",
    );
    expect(screen.getByTestId("notebook-selection-actions")).not.toHaveTextContent("Run");
  });

  it("renders nothing when there is no selection", () => {
    const { container } = render(<SelectionActions selection={null} {...handlers()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
