import "@testing-library/jest-dom/vitest";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MoreMenu } from "./MoreMenu";
import type { LineageNode } from "./types";

const node: LineageNode = {
  id: "model:ols_1",
  kind: "model",
  display_label: "Primary OLS",
  summary: "OLS",
  created_at: "",
  parent_stage_id: null,
  branch_id: "main",
  trust: "ok",
  trust_reason: null,
  archived: false,
  payload_ref: null,
  decision_points: [],
  annotations: [],
};

describe("MoreMenu", () => {
  it("hides menu by default; opens when toggle clicked", () => {
    render(<MoreMenu node={node} onShowJson={() => {}} />);
    expect(screen.queryByText("Copy node ID")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /more/i }));
    expect(screen.getByText("Copy node ID")).toBeInTheDocument();
  });

  it('calls onShowJson on "View raw JSON"', () => {
    const onShow = vi.fn();
    render(<MoreMenu node={node} onShowJson={onShow} />);
    fireEvent.click(screen.getByRole("button", { name: /more/i }));
    fireEvent.click(screen.getByText("View raw JSON"));
    expect(onShow).toHaveBeenCalled();
  });

  it('copies node id to clipboard on "Copy node ID"', () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<MoreMenu node={node} onShowJson={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /more/i }));
    fireEvent.click(screen.getByText("Copy node ID"));
    expect(writeText).toHaveBeenCalledWith("model:ols_1");
  });

  it('copies node JSON to clipboard on "Copy as JSON"', () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<MoreMenu node={node} onShowJson={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /more/i }));
    fireEvent.click(screen.getByText("Copy as JSON"));
    expect(writeText).toHaveBeenCalled();
    expect(writeText.mock.calls[0][0]).toContain('"id": "model:ols_1"');
  });
});
