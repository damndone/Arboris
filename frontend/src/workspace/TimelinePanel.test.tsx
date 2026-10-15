import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AgentSurfaceContext } from "../workbench/agent/AgentSurfaceContext";
import { TimelinePanel, timelineSummary, useTimeline } from "./TimelinePanel";

const line = (what: string, summary: string, at: string, extra = {}) => ({ at, who: "ui", what, status: "completed", summary, categories: [], ...extra });

it("reads the ledger newest first, as sentences, with the raw event one click away", () => {
  const value = {
    entries: [
      line("run.submit", "draft=draft_1", "2026-10-13T01:00:00Z"),
      line("model.rerun", "Changed quantiles", "2026-10-13T01:05:00Z", { who: "Agent (read-only, no confirmation)", status: "failed" }),
    ],
    counts: { inferential_tests: 2, models: 1, data_changes: 3 },
    entries_omitted: 4,
  } as never;
  render(<TimelinePanel value={value} error={null} onRefresh={() => {}} />);
  const items = screen.getAllByRole("listitem");
  expect(items[0]).toHaveTextContent("Changed quantiles");
  expect(items[0]).toHaveTextContent("Failed");
  expect(items[0]).toHaveTextContent("Agent");
  expect(items[1]).toHaveTextContent("Ran a new analysis");
  expect(items[1]).toHaveTextContent("You");
  expect(screen.getByText("model.rerun")).not.toBeVisible();
  fireEvent.click(items[0].querySelector("summary")!);
  expect(screen.getByText("model.rerun")).toBeVisible();
  expect(screen.getByText(/4 earlier entries are not shown/)).toBeInTheDocument();
  expect(timelineSummary(value)).toBe("Last: Changed quantiles · 1 model · 2 tests · 3 data changes");
});

it("an error offers a retry", () => {
  const onRefresh = vi.fn();
  render(<TimelinePanel value={null} error="offline" onRefresh={onRefresh} />);
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(onRefresh).toHaveBeenCalled();
});

it("refreshes persisted history after an Agent operation completes", async () => {
  const fetchMock = vi.fn().mockImplementation(() =>
    Promise.resolve(new Response(JSON.stringify({ entries: [], counts: { inferential_tests: 1, models: 1, data_changes: 0 }, entries_omitted: 0 }))),
  );
  vi.stubGlobal("fetch", fetchMock);
  let operation = { record_id: "op-1", status: "running" };
  const hook = renderHook(() => useTimeline("/project", "run-1"), {
    wrapper: ({ children }) => <AgentSurfaceContext.Provider value={{ activeOperation: operation } as never}>{children}</AgentSurfaceContext.Provider>,
  });
  await waitFor(() => expect(hook.result.current.value).not.toBeNull());
  expect(fetchMock).toHaveBeenCalledTimes(1);
  operation = { ...operation, status: "completed" };
  hook.rerender();
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(hook.result.current.value).not.toBeNull();
  hook.rerender();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  vi.unstubAllGlobals();
});
