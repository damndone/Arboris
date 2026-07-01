import { render, screen } from "@testing-library/react";
import { it, expect, vi } from "vitest";
import { RunHistoryPanel } from "./runHistory";

it("shows a friendly empty state when the project does not exist", () => {
  render(<RunHistoryPanel runs={null} onSelect={vi.fn()} projectMissing />);
  const msg = screen.getByTestId("history-project-missing");
  expect(msg).toHaveTextContent(/project/i);
  // does NOT render the raw loading / error state
  expect(screen.queryByText("Loading runs…")).toBeNull();
});

it("still shows loading when runs are null and project exists", () => {
  render(<RunHistoryPanel runs={null} onSelect={vi.fn()} />);
  expect(screen.getByText("Loading runs…")).toBeInTheDocument();
});

it("shows the empty-project hint when the project exists but has no runs", () => {
  render(<RunHistoryPanel runs={[]} onSelect={vi.fn()} />);
  expect(screen.getByText("No runs in this project yet.")).toBeInTheDocument();
});
