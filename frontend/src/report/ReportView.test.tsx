import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeOwnerResolutionSeedFixture } from "../lineage/api/nodeOperationContext";
import { ReportView } from "./ReportView";

const mockForest = vi.hoisted(() => ({ current: null as unknown }));
const mockWb = vi.hoisted(() => ({ current: null as unknown }));
const mockGenerate = vi.hoisted(() => ({
  current: vi.fn() as ReturnType<typeof vi.fn>,
}));

vi.mock("../workbench/ForestContext", () => ({
  useForest: () => mockForest.current,
}));
vi.mock("../workbench/WorkbenchStateProvider", () => ({
  useWorkbenchOptional: () => mockWb.current,
}));
vi.mock("./reportClient", async (importOriginal) => {
  const original = await importOriginal<typeof import("./reportClient")>();
  return {
    ...original,
    generateReport: (...args: unknown[]) => mockGenerate.current(...args),
  };
});

function seedForest() {
  const seed = makeOwnerResolutionSeedFixture();
  const model = seed.forest.nodes.find((n) => n.nodeKey === seed.sharedNodeKey)!;
  model.editableSchema = [
    { key: "covariance", kind: "select", label: "Covariance", value: "HC1" },
  ] as never;
  model.stats = { r_squared: 0.86 } as never;
  return seed;
}

describe("ReportView", () => {
  beforeEach(() => {
    const seed = seedForest();
    mockForest.current = { forest: seed.forest, activeRunId: "run_c", setActiveRunId: vi.fn() };
    mockWb.current = {
      state: {},
      dispatch: { setView: vi.fn(), selectByCanvasClick: vi.fn() },
    };
    mockGenerate.current = vi.fn();
  });

  it("shows the deterministic fact table before any AI call", () => {
    render(<ReportView />);
    expect(screen.getByTestId("report-fact-preview")).toBeInTheDocument();
    expect(screen.getByText("param:covariance")).toBeInTheDocument();
    expect(mockGenerate.current).not.toHaveBeenCalled();
  });

  it("generate renders prose with verified chips and flags unknown ids", async () => {
    mockGenerate.current = vi.fn().mockResolvedValue({
      text: "R² 良好 [[c:c2]],而这个引用不存在 [[c:c99]]。",
      model: "deepseek-v4-flash",
    });
    render(<ReportView />);
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));

    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());
    expect(screen.getByTestId("cite-chip")).toBeInTheDocument();
    expect(screen.getByTestId("cite-chip-unverified")).toBeInTheDocument();
    expect(screen.getByTestId("report-provenance").textContent).toContain(
      "deepseek-v4-flash",
    );
  });

  it("chip click jumps back to the graph and selects the node", async () => {
    mockGenerate.current = vi.fn().mockResolvedValue({ text: "见 [[c:c1]]", model: "m" });
    render(<ReportView />);
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("cite-chip"));
    const wb = mockWb.current as { dispatch: { setView: ReturnType<typeof vi.fn>; selectByCanvasClick: ReturnType<typeof vi.fn> } };
    expect(wb.dispatch.setView).toHaveBeenCalledWith("graph");
    expect(wb.dispatch.selectByCanvasClick).toHaveBeenCalled();
  });

  it("surfaces backend errors honestly", async () => {
    mockGenerate.current = vi.fn().mockRejectedValue(new Error("LLM is not configured"));
    render(<ReportView />);
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert").textContent).toContain("LLM is not configured");
  });

  it("without an active run, asks the user to pick one", () => {
    mockForest.current = null;
    render(<ReportView />);
    expect(screen.getByText(/pick a run/i)).toBeInTheDocument();
  });
});

describe("ReportView curation & history (C-3)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    const seed = seedForest();
    mockForest.current = { forest: seed.forest, activeRunId: "run_c", setActiveRunId: vi.fn() };
    mockWb.current = {
      state: {},
      dispatch: { setView: vi.fn(), selectByCanvasClick: vi.fn() },
    };
    mockGenerate.current = vi.fn().mockResolvedValue({ text: "ok [[c:c1]]", model: "m" });
  });

  it("unticking a fact excludes it from generation and discloses the exclusion", async () => {
    render(<ReportView projectRoot="/tmp/projA" />);
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]); // exclude the first fact

    expect(screen.getByTestId("report-provenance").textContent).toContain(
      "excluded by user",
    );

    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());

    const sent = mockGenerate.current.mock.calls[0][0] as {
      facts: Array<{ id: string }>;
    };
    // one fewer fact was sent than exists in the table
    expect(sent.facts.length).toBe(1);
    // provenance of the generated report keeps the disclosure
    expect(screen.getByTestId("report-provenance").textContent).toContain(
      "facts were excluded",
    );
  });

  it("there is no UI to edit a fact's value (omit-only curation)", () => {
    render(<ReportView projectRoot="/tmp/projA" />);
    const preview = screen.getByTestId("report-fact-preview");
    // checkboxes only — no text inputs anywhere in the fact table
    expect(preview.querySelectorAll("input[type=text], textarea").length).toBe(0);
  });

  it("generated reports persist to history and reopen from it", async () => {
    render(<ReportView projectRoot="/tmp/projA" />);
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-history")).toBeInTheDocument());

    // back to fact table, then reopen the historical report
    fireEvent.click(screen.getByRole("button", { name: /new report/i }));
    expect(screen.getByTestId("report-fact-preview")).toBeInTheDocument();
    const historyLinks = screen
      .getByTestId("report-history")
      .querySelectorAll("button");
    fireEvent.click(historyLinks[0]);
    expect(screen.getByTestId("report-body")).toBeInTheDocument();

    // history survives a remount (localStorage)
    const again = render(<ReportView projectRoot="/tmp/projA" />);
    expect(again.getAllByTestId("report-history").length).toBeGreaterThan(0);
  });

  it("deleting a history record removes it", async () => {
    render(<ReportView projectRoot="/tmp/projB" />);
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-history")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /delete report/i }));
    expect(screen.queryByTestId("report-history")).toBeNull();
  });
});
