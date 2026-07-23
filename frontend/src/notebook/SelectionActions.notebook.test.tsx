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

  it("passes the selection, verbatim and with its source ref, to each action", () => {
    const spies = handlers();
    render(<SelectionActions selection={selection} {...spies} />);

    fireEvent.click(screen.getByTestId("selection-action-ask"));
    fireEvent.click(screen.getByTestId("selection-action-explain"));
    fireEvent.click(screen.getByTestId("selection-action-follow-up"));
    fireEvent.click(screen.getByTestId("selection-action-note"));
    fireEvent.click(screen.getByTestId("selection-action-defer"));

    for (const spy of Object.values(spies)) {
      expect(spy).toHaveBeenCalledWith(selection);
    }
  });

  it("labels the deferred-option action as a proposal request, not an execution", () => {
    render(<SelectionActions selection={selection} {...handlers()} />);
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
