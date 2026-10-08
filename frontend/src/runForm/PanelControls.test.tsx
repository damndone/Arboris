import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { PanelControls } from "./PanelControls";
import type { Capabilities } from "../capabilities/types";
import { capabilitiesFixture } from "../apiFixtures";

const caps: Capabilities = capabilitiesFixture({
  covariance_options: [{ key: "robust", label: "Robust (default)" },
                       { key: "clustered", label: "Clustered" }],
});

describe("PanelControls", () => {
  it("offers column choices and reports entity selection", () => {
    const onEntity = vi.fn();
    render(<PanelControls capabilities={caps} columns={["firm", "yr", "profit"]}
      entity="" time="" covariance="" onEntity={onEntity} onTime={vi.fn()} onCovariance={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/entity/i), { target: { value: "firm" } });
    expect(onEntity).toHaveBeenCalledWith("firm");
  });

  it("reports time selection", () => {
    const onTime = vi.fn();
    render(<PanelControls capabilities={caps} columns={["firm", "yr"]}
      entity="" time="" covariance="" onEntity={vi.fn()} onTime={onTime} onCovariance={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/time/i), { target: { value: "yr" } });
    expect(onTime).toHaveBeenCalledWith("yr");
  });

  it("renders covariance options from the manifest", () => {
    render(<PanelControls capabilities={caps} columns={["firm"]} entity="" time="" covariance=""
      onEntity={vi.fn()} onTime={vi.fn()} onCovariance={vi.fn()} />);
    expect(screen.getByText("Clustered")).toBeInTheDocument();
  });

  it("omits covariance control when manifest has none", () => {
    const noCov: Capabilities = capabilitiesFixture();
    render(<PanelControls capabilities={noCov} columns={["firm"]} entity="" time="" covariance=""
      onEntity={vi.fn()} onTime={vi.fn()} onCovariance={vi.fn()} />);
    expect(screen.queryByText(/covariance/i)).toBeNull();
  });
});
