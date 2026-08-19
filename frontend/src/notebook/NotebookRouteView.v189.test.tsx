import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NotebookSurface } from "./NotebookSurface";
import type { NotebookReadyView } from "./contracts";

const readyView: NotebookReadyView = {
  status: "ready",
  notebook: {
    notebook_id: "nb-acceptance",
    run_family_id: "run-family-1",
    narrative: [{ entry_id: "entry-1", kind: "system", text: "Plan is preview-only until confirmation.", occurred_at: "2026-08-19T00:00:00.000Z" }],
    options: [],
    contextSlice: null,
    confirmation: null,
    execution: null,
    result: null,
    executionResults: {},
    materialization: null,
    selection: null,
  },
};

describe("v1.8.9 integrated Notebook acceptance", () => {
  it("shows a bounded planning surface without inventing an executable option", () => {
    render(<NotebookSurface view={readyView} interactionMode="plan" userIntent="Compare the available models" />);

    expect(screen.getByText("Plan is preview-only until confirmation.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirm/i })).toBeNull();
    expect(screen.queryByText(/raw json/i)).toBeNull();
  });
});

