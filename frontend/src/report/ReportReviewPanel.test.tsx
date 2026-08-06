import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportReviewPanel } from "./ReportReviewPanel";

const mockWorkspace = vi.hoisted(() => ({ current: null as unknown }));

vi.mock("./ReportWorkspaceContext", () => ({
  useReportWorkspace: () => mockWorkspace.current,
}));

function emptyWorkspace() {
  return {
    current: null,
    editing: false,
    editorText: "",
    revisionInstruction: "",
    currentIsStale: false,
    currentQualityStatus: null,
    reportLoadError: null,
    reportExportAllowed: false,
    reportFigures: [],
    currentFactsById: new Map(),
    currentContextLines: [],
    currentContextDetails: [],
    currentContextUsedTokens: 1,
    generating: false,
    onEditorTextChange: vi.fn(),
    onRevisionInstructionChange: vi.fn(),
    beginEditing: vi.fn(),
    cancelEditing: vi.fn(),
    resetEditor: vi.fn(),
    saveRevision: vi.fn(),
    handleRevise: vi.fn(),
    jumpToNode: vi.fn(),
  };
}

describe("ReportReviewPanel", () => {
  beforeEach(() => {
    mockWorkspace.current = emptyWorkspace();
  });

  it("shows an honest empty state when there is no current report", () => {
    render(<ReportReviewPanel />);

    expect(screen.getByTestId("report-review-panel")).toBeInTheDocument();
    expect(screen.getByText("No report yet")).toBeInTheDocument();
    expect(screen.queryByTestId("report-body")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Report revision instruction" })).not.toBeInTheDocument();
  });

  it("renders the current report with compact window controls and no second composer", () => {
    const workspace = {
      ...emptyWorkspace(),
      projectRoot: "/tmp/report-review",
      current: {
        id: "report-1",
        generatedAt: "2026-08-04T10:00:00Z",
        model: "model-a",
        instruction: "Explain the result",
        text: "# Current report\n\n[[c:c1]]\n\n[[fig:figure-1]]",
        generatedText: "# Current report",
        scope: { run_id: "run-1", node_count: 1, node_keys: ["node-1"] },
        context_fingerprints: ["report-evidence-v1:abc"],
        facts: [{
          id: "c1",
          node_key: "node-1",
          node_label: "Model",
          field: "estimate:x",
          label: "Estimate x",
          value: 1.25,
        }],
        excluded_fact_ids: [],
        figures: [{
          artifact_id: "figure-1",
          chart_type: "Coefficient plot",
          path: "figures/figure-1.png",
          source: null,
        }],
        excluded_figure_ids: [],
        validation_status: "needs_revision" as const,
        report_quality: { status: "needs_revision" as const, violations: ["Add limitations"] },
      },
      reportFigures: [{
        artifact_id: "figure-1",
        chart_type: "Coefficient plot",
        path: "figures/figure-1.png",
        source: null,
      }],
      currentFactsById: new Map([[
        "c1",
        {
          id: "c1",
          node_key: "node-1",
          node_label: "Model",
          field: "estimate:x",
          label: "Estimate x",
          value: 1.25,
        },
      ]]),
      currentIsStale: true,
      currentQualityStatus: "needs_revision" as const,
    };
    mockWorkspace.current = workspace;

    render(<ReportReviewPanel />);

    expect(screen.getByTestId("report-body")).toHaveTextContent("Current report");
    expect(screen.getByTestId("report-figure-figure-1")).toHaveAttribute(
      "src",
      expect.stringContaining("figure-1"),
    );
    expect(screen.getByTestId("report-review-quality")).toHaveTextContent("needs_revision");
    expect(screen.getByTestId("report-review-stale")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Report revision instruction" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Float report review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pin report review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Collapse report review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Collapse report review" })).toHaveAttribute(
      "data-icon",
      "collapse-right",
    );
    expect(screen.getByTestId("report-review-provenance-summary")).toHaveTextContent(
      "Evidence inventory: 1 facts",
    );
  });

  it("does not mislabel a report loading failure as an empty run", () => {
    mockWorkspace.current = {
      ...emptyWorkspace(),
      reportLoadError: "network unavailable",
    };

    render(<ReportReviewPanel />);

    expect(screen.getByTestId("report-review-load-error")).toHaveTextContent("Report failed to load");
    expect(screen.getByTestId("report-review-load-error")).toHaveTextContent("network unavailable");
    expect(screen.queryByText("No report yet")).not.toBeInTheDocument();
  });

  it("uses a pin glyph for the locked floating state and disables dragging", () => {
    mockWorkspace.current = emptyWorkspace();

    render(
      <ReportReviewPanel
        floating
        pinned
        collapsed
        onUnpin={vi.fn()}
        onExpand={vi.fn()}
        onDragPointerDown={vi.fn()}
        onDragKeyDown={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Unpin report review" })).toHaveAttribute(
      "data-icon",
      "pin",
    );
    expect(screen.getByRole("button", { name: "Drag report review" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByRole("button", { name: "Expand report review" })).toHaveAttribute(
      "data-icon",
      "collapse-left",
    );
  });
});
