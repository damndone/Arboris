import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentRowsTable, shownRows } from "./AgentRowsTable";
import type { AgentMessage } from "./agentTypes";

function toolMessage(name: string, payload: unknown): AgentMessage {
  return { entry_id: "e1", role: "tool", name, content: JSON.stringify(payload) } as AgentMessage;
}

const payload = {
  tool_call_id: "c1",
  tool_id: "show_dataset_rows",
  ok: true,
  output: {
    run_id: "r1", node_id: "stage:raw", columns: ["wage", "educ"], total_rows: 60, offset: 0,
    row_numbers: [1, 2], rows: [{ wage: 18.7310004, educ: 12 }, { wage: null, educ: 16 }],
    egress_summary: "Rows 1-2 of 60",
  },
};

describe("AgentRowsTable", () => {
  it("renders the rows a show_dataset_rows call put on screen", () => {
    const shown = shownRows(toolMessage("show_dataset_rows", payload));
    expect(shown).not.toBeNull();
    render(<AgentRowsTable shown={shown!} />);
    const block = screen.getByTestId("agent-shown-rows");
    expect(within(block).getByText(/rows 1–2 of 60/)).toBeTruthy();
    expect(within(block).getByText("18.731")).toBeTruthy();
    expect(within(block).getAllByRole("row")).toHaveLength(3);
  });

  it("ignores other tools and failed calls", () => {
    expect(shownRows(toolMessage("inspect_data_schema", payload))).toBeNull();
    expect(shownRows(toolMessage("show_dataset_rows", { ...payload, ok: false }))).toBeNull();
    expect(shownRows({ ...toolMessage("show_dataset_rows", payload), content: "not json" })).toBeNull();
  });
});
