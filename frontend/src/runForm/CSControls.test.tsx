import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CSControls, type CSValue } from "./CSControls";

const base: CSValue = {
  controlGroup: "never",
  estMethod: "dr",
  basePeriod: "varying",
  anticipation: 0,
  clusterVar: "",
  honestDid: false,
};
const baseValue = base;

describe("CSControls", () => {
  it("renders all four controls", () => {
    render(<CSControls value={base} columns={[]} onChange={() => {}} />);
    expect(screen.getByLabelText("cs-control-group")).toBeInTheDocument();
    expect(screen.getByLabelText("cs-est-method")).toBeInTheDocument();
    expect(screen.getByLabelText("cs-base-period")).toBeInTheDocument();
    expect(screen.getByLabelText("cs-anticipation")).toBeInTheDocument();
  });

  it("renders the cluster-var selector and reports changes", () => {
    const onChange = vi.fn();
    render(<CSControls value={baseValue} columns={["unit", "region", "x1"]} onChange={onChange} />);
    const sel = screen.getByLabelText("cs-cluster-var") as HTMLSelectElement;
    expect(sel).toBeInTheDocument();
    fireEvent.change(sel, { target: { value: "region" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ clusterVar: "region" }));
  });

  // Characterization: clearing a selected cluster var back to the default entity
  // option must emit clusterVar:"" (the entity / no-op sentinel). Guards the
  // unclustered no-op contract at the UI boundary.
  it("renders the honest-DID checkbox and reports toggling it", () => {
    const onChange = vi.fn();
    render(<CSControls value={baseValue} columns={[]} onChange={onChange} />);
    const cb = screen.getByLabelText("cs-honest-did") as HTMLInputElement;
    expect(cb).toBeInTheDocument();
    fireEvent.click(cb);
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ honestDid: true }),
    );
  });

  it("clearing the cluster-var back to entity emits clusterVar:''", () => {
    const onChange = vi.fn();
    render(
      <CSControls
        value={{ ...baseValue, clusterVar: "region" }}
        columns={["unit", "region", "x1"]}
        onChange={onChange}
      />,
    );
    const sel = screen.getByLabelText("cs-cluster-var") as HTMLSelectElement;
    expect(sel.value).toBe("region"); // reflects current selection
    fireEvent.change(sel, { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ clusterVar: "" }));
  });

  it("reflects the current value in each control", () => {
    render(
      <CSControls
        value={{
          controlGroup: "not_yet",
          estMethod: "ipw",
          basePeriod: "universal",
          anticipation: 2,
          clusterVar: "",
          honestDid: false,
        }}
        columns={[]}
        onChange={() => {}}
      />,
    );
    expect((screen.getByLabelText("cs-control-group") as HTMLSelectElement).value).toBe("not_yet");
    expect((screen.getByLabelText("cs-est-method") as HTMLSelectElement).value).toBe("ipw");
    expect((screen.getByLabelText("cs-base-period") as HTMLSelectElement).value).toBe("universal");
    expect((screen.getByLabelText("cs-anticipation") as HTMLInputElement).value).toBe("2");
  });

  it("fires onChange with updated control group", () => {
    const onChange = vi.fn();
    render(<CSControls value={base} columns={[]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("cs-control-group"), {
      target: { value: "not_yet" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ controlGroup: "not_yet" }),
    );
  });

  it("fires onChange with updated estimation method", () => {
    const onChange = vi.fn();
    render(<CSControls value={base} columns={[]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("cs-est-method"), {
      target: { value: "reg" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ estMethod: "reg" }),
    );
  });

  it("fires onChange with updated base period", () => {
    const onChange = vi.fn();
    render(<CSControls value={base} columns={[]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("cs-base-period"), {
      target: { value: "universal" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ basePeriod: "universal" }),
    );
  });

  it("fires onChange with updated anticipation (integer)", () => {
    const onChange = vi.fn();
    render(<CSControls value={base} columns={[]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("cs-anticipation"), {
      target: { value: "3" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ anticipation: 3 }),
    );
  });
});
