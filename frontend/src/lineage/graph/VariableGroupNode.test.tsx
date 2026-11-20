import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ReactFlowProvider } from "reactflow";
import { expect, it, vi } from "vitest";
import { VariableGroupNode } from "./VariableGroupNode";

it("keeps all 65 variables in a keyboard-accessible list and opens the last one", () => {
  const names = ["y", "w1", "w2", ...Array.from({ length: 31 }, (_, i) => `d${i}`),
    ...Array.from({ length: 31 }, (_, i) => `z${i}`)];
  const onSelectMember = vi.fn();
  render(
    <ReactFlowProvider>
      <VariableGroupNode data={{
        gid: "group:variables:stage:cleaned",
        label: "Variables (65)",
        members: names.map((title) => ({ id: `var:${title}:cleaned`, title, summary: null })),
        onSelectMember,
      }} />
    </ReactFlowProvider>,
  );

  expect(screen.getByText("Scroll to browse all 65 items")).toBeVisible();
  const list = screen.getByRole("region", { name: "Browse Variables (65)" });
  expect(list).toHaveClass("nowheel", "nopan", "nokey", "nodrag");
  list.focus();
  expect(list).toHaveFocus();
  expect(within(list).getAllByRole("button")).toHaveLength(65);
  fireEvent.click(within(list).getByRole("button", { name: "Open z30" }));
  expect(onSelectMember).toHaveBeenCalledWith("var:z30:cleaned");
});
