import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StatisticalVariablePicker } from "./StatisticalVariablePicker";

const columns = [
  { name: "year", dtype: "int64" },
  { name: "middle", dtype: "int64" },
  { name: "bdsnew", dtype: "int64" },
  { name: "pfl", dtype: "float64" },
  { name: "zmath", dtype: "float64" },
];

describe("StatisticalVariablePicker", () => {
  it("collapses the list and reports the total selected count", () => {
    const onChange = vi.fn();
    render(<StatisticalVariablePicker columns={columns} selectedColumns={["year", "bdsnew"]} onChange={onChange} />);

    expect(screen.getByRole("button", { name: /2 variables selected/i })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "year" })).not.toBeInTheDocument();
  });

  it("searches without changing hidden selections and supports matching bulk actions", () => {
    const onChange = vi.fn();
    render(<StatisticalVariablePicker columns={columns} selectedColumns={columns.map(({ name }) => name)} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: /5 variables selected/i }));
    fireEvent.change(screen.getByRole("searchbox", { name: /search variables/i }), { target: { value: "p" } });
    expect(screen.getByRole("checkbox", { name: "pfl" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "year" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear matching variables" }));
    expect(onChange).toHaveBeenLastCalledWith(["year", "middle", "bdsnew", "zmath"]);
  });

  it("selects all variables matching the search and shows an empty state", () => {
    const onChange = vi.fn();
    render(<StatisticalVariablePicker columns={columns} selectedColumns={[]} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: /0 variables selected/i }));
    fireEvent.change(screen.getByRole("searchbox", { name: /search variables/i }), { target: { value: "math" } });
    fireEvent.click(screen.getByRole("button", { name: "Select all matching variables" }));
    expect(onChange).toHaveBeenLastCalledWith(["zmath"]);

    fireEvent.change(screen.getByRole("searchbox", { name: /search variables/i }), { target: { value: "zzz" } });
    expect(screen.getByText("No variables match")).toBeInTheDocument();
  });
});
