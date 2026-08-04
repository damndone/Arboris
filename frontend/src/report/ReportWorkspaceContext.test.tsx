import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReportWorkspaceProvider, useReportWorkspace } from "./ReportWorkspaceContext";

const mockForest = vi.hoisted(() => ({ current: null as unknown }));

vi.mock("../workbench/ForestContext", () => ({
  useForest: () => mockForest.current,
}));

vi.mock("../workbench/WorkbenchStateProvider", () => ({
  useWorkbenchOptional: () => null,
}));

function WorkspaceProbe() {
  const workspace = useReportWorkspace();
  return (
    <>
      <output data-testid="workspace-current-report">{workspace.current?.id ?? "none"}</output>
      <output data-testid="workspace-source-setters">
        {String("setFacts" in workspace || "setModelResults" in workspace || "setLineage" in workspace)}
      </output>
      <button type="button" onClick={workspace.beginEditing}>Begin prose edit</button>
    </>
  );
}

describe("ReportWorkspaceContext", () => {
  it("shares report lifecycle state while exposing prose actions without source setters", () => {
    mockForest.current = null;

    render(
      <ReportWorkspaceProvider projectRoot="/tmp/report-workspace">
        <WorkspaceProbe />
      </ReportWorkspaceProvider>,
    );

    expect(screen.getByTestId("workspace-current-report")).toHaveTextContent("none");
    expect(screen.getByTestId("workspace-source-setters")).toHaveTextContent("false");
    fireEvent.click(screen.getByRole("button", { name: "Begin prose edit" }));
  });
});
