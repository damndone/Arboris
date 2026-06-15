import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CSControls, type CSValue } from "./CSControls";

const cols = ["id", "year", "first_treat", "y", "region"];

const base: CSValue = {
  controlGroup: "never",
  estMethod: "dr",
  basePeriod: "varying",
  anticipation: 0,
  clusterVar: "",
};

describe("CSControls", () => {
  it("renders all five controls", () => {
    render(<CSControls columns={cols} value={base} onChange={() => {}} />);
    expect(screen.getByLabelText("cs-control-group")).toBeInTheDocument();
    expect(screen.getByLabelText("cs-est-method")).toBeInTheDocument();
    expect(screen.getByLabelText("cs-base-period")).toBeInTheDocument();
    expect(screen.getByLabelText("cs-anticipation")).toBeInTheDocument();
    expect(screen.getByLabelText("cs-cluster-var")).toBeInTheDocument();
  });

  it("reflects the current value in each control", () => {
    render(
      <CSControls
        columns={cols}
        value={{
          controlGroup: "not_yet",
          estMethod: "ipw",
          basePeriod: "universal",
          anticipation: 2,
          clusterVar: "region",
        }}
        onChange={() => {}}
      />,
    );
    expect((screen.getByLabelText("cs-control-group") as HTMLSelectElement).value).toBe("not_yet");
    expect((screen.getByLabelText("cs-est-method") as HTMLSelectElement).value).toBe("ipw");
    expect((screen.getByLabelText("cs-base-period") as HTMLSelectElement).value).toBe("universal");
    expect((screen.getByLabelText("cs-anticipation") as HTMLInputElement).value).toBe("2");
    expect((screen.getByLabelText("cs-cluster-var") as HTMLSelectElement).value).toBe("region");
  });

  it("fires onChange with updated control group", () => {
    const onChange = vi.fn();
    render(<CSControls columns={cols} value={base} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("cs-control-group"), {
      target: { value: "not_yet" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ controlGroup: "not_yet" }),
    );
  });

  it("fires onChange with updated estimation method", () => {
    const onChange = vi.fn();
    render(<CSControls columns={cols} value={base} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("cs-est-method"), {
      target: { value: "reg" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ estMethod: "reg" }),
    );
  });

  it("fires onChange with updated base period", () => {
    const onChange = vi.fn();
    render(<CSControls columns={cols} value={base} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("cs-base-period"), {
      target: { value: "universal" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ basePeriod: "universal" }),
    );
  });

  it("fires onChange with updated anticipation (integer)", () => {
    const onChange = vi.fn();
    render(<CSControls columns={cols} value={base} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("cs-anticipation"), {
      target: { value: "3" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ anticipation: 3 }),
    );
  });

  it("fires onChange with updated cluster var", () => {
    const onChange = vi.fn();
    render(<CSControls columns={cols} value={base} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("cs-cluster-var"), {
      target: { value: "region" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ clusterVar: "region" }),
    );
  });
});
