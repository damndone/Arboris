import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DIDControls, type DIDRoleValue } from "./DIDControls";

const base: DIDRoleValue = { mode: "cohort", entity: "", time: "", cohort: "",
  treat: "", post: "", status: "" };

describe("DIDControls", () => {
  it("shows entity/time/cohort selectors in cohort mode", () => {
    render(<DIDControls columns={["id", "year", "first_treat", "y"]} value={base}
      onChange={() => {}} />);
    expect(screen.getByLabelText("did-entity")).toBeInTheDocument();
    expect(screen.getByLabelText("did-time")).toBeInTheDocument();
    expect(screen.getByLabelText("did-cohort")).toBeInTheDocument();
  });

  it("switches to two_by_two mode via onChange", () => {
    const onChange = vi.fn();
    render(<DIDControls columns={["id", "year", "treat", "post"]} value={base}
      onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("did-mode"), { target: { value: "two_by_two" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ mode: "two_by_two" }));
  });

  it("shows treat/post selectors when mode is two_by_two", () => {
    render(<DIDControls columns={["id", "year", "treat", "post"]}
      value={{ ...base, mode: "two_by_two" }} onChange={() => {}} />);
    expect(screen.getByLabelText("did-treat")).toBeInTheDocument();
    expect(screen.getByLabelText("did-post")).toBeInTheDocument();
    // entity/time are still needed by the backend panel index in two_by_two mode
    expect(screen.getByLabelText("did-entity")).toBeInTheDocument();
    expect(screen.getByLabelText("did-time")).toBeInTheDocument();
  });

  it("shows status selector when mode is status", () => {
    render(<DIDControls columns={["id", "year", "d_it"]}
      value={{ ...base, mode: "status" }} onChange={() => {}} />);
    expect(screen.getByLabelText("did-status")).toBeInTheDocument();
  });

  it("hides treat/post selectors in cohort mode", () => {
    render(<DIDControls columns={["id", "year", "first_treat"]} value={base}
      onChange={() => {}} />);
    expect(screen.queryByLabelText("did-treat")).toBeNull();
    expect(screen.queryByLabelText("did-post")).toBeNull();
    expect(screen.queryByLabelText("did-status")).toBeNull();
  });
});
