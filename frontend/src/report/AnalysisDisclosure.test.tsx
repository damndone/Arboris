import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalysisDisclosure, type AnalysisDisclosureValue } from "./AnalysisDisclosure";

function value(settings: AnalysisDisclosureValue["settings"]): AnalysisDisclosureValue {
  return {
    run_id: "r1",
    counts: { inferential_tests: 3, descriptive_analyses: 1, models: 2, data_changes: 1, metadata_changes: 0, run_deletions: 1, failed_actions: 0 },
    inferential_tests_by: { agent_without_confirmation: 2, user: 1 },
    changes: [
      { at: "2026-09-26T10:00:00.000+00:00", who: "User", status: "completed", what: "data.subset", categories: ["data_change"], summary: "age < 60" },
    ],
    entries: [
      { at: "2026-09-26T09:00:00.000+00:00", who: "Agent (read-only, no confirmation)", status: "completed", what: "test.t_tests", categories: ["inferential"], summary: "" },
    ],
    entries_omitted: 0,
    settings,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("AnalysisDisclosure", () => {
  it("shows every test and data change, and lets the user turn the export section off", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(value({ include_in_exports: true, detail: "summary" }))))
      .mockResolvedValueOnce(new Response(JSON.stringify({ include_in_exports: false, detail: "summary" })))
      .mockResolvedValueOnce(new Response(JSON.stringify(value({ include_in_exports: false, detail: "summary" }))));
    vi.stubGlobal("fetch", fetchMock);
    render(<AnalysisDisclosure projectRoot="/p" runId="r1" />);

    const counts = await screen.findByTestId("analysis-disclosure-counts");
    expect(counts.textContent).toContain("3 inferential tests");
    expect(counts.textContent).toContain("Agent without confirmation 2");
    expect(counts.textContent).toContain("1 run deleted");
    expect(within(screen.getByTestId("analysis-disclosure")).getByText(/age < 60/)).toBeTruthy();

    fireEvent.click(screen.getByLabelText("Include in exported reports"));
    await waitFor(() => expect(screen.getByText(/Exports omit this section/)).toBeTruthy());
    const [url, init] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/projects/report-disclosure");
    expect(JSON.parse(String(init.body))).toEqual({ include_in_exports: false, detail: "summary" });
  });
});

it("shows evidence-based pre-specified and exploratory sections without hiding failures", async () => {
  const fixed={record_id:"record-primary",run_id:"r1",step_id:"primary",operation_id:"test.t_tests",question_id:"question",specification_status:"pre_specified",verification:"verified",reason:"fixed_before_related_results",status:"completed",at:null,specification_event_id:"frozen-proof"};
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify({
    ...value({include_in_exports:true,detail:"summary"}),research_specifications:{pre_specified:[fixed],
      exploratory:[{...fixed,record_id:"record-exploratory",step_id:"alternative",specification_status:"exploratory",
        verification:"unverified",reason:"no_pre_execution_evidence",status:"failed",specification_event_id:null}]},
  }))));
  render(<AnalysisDisclosure projectRoot="/p" runId="r1" />);
  await screen.findByRole("heading",{name:"Pre-specified analyses"});
  expect(screen.getByRole("heading",{name:"Exploratory analyses"})).toBeTruthy();
  expect(screen.getByText(/frozen-proof/)).toBeTruthy();
  expect(screen.getByText(/record-exploratory/)).toBeTruthy();
  expect(screen.getByText(/no_pre_execution_evidence/)).toBeTruthy();
  expect(screen.getByText(/failed/)).toBeTruthy();
});
